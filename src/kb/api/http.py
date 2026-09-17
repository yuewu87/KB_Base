"""HTTP 接口层——薄层，只做协议转换，不含判断逻辑（Q33）。

所有写入都经过这里：CLI 和 MCP 都调这个服务，不直接碰文件。
于是写入天然串行化，不会出现两份逻辑打架（Q29）。

直接运行即启动服务：

    python -m kb.api.http --port 51723
"""

from __future__ import annotations

import argparse
import logging
import threading
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from kb.api import runtime
from kb.config import DATA_DIR, Config, load_config
from kb.core import flow, organize, sweep, sweep_state
from kb.core.chat import handle
from kb.core.chat_store import list_chats, load_chat
from kb.core.models import Draft, OrganizeResult
from kb.core.search import search_notes
from kb.core.vault import (
    PENDING,
    find_draft,
    list_drafts,
    new_draft_id,
    read_draft,
    read_note,
    write_draft,
)
from kb.llm.base import LLM
from kb.llm.providers.openai_compat import OpenAICompatLLM
from kb.logging_setup import setup_logging

# 草稿 id 只有 4 位随机十六进制（65536 种），撞号时重试而不是覆盖
PUSH_ATTEMPTS = 10


class PushRequest(BaseModel):
    content: str
    project: str | None = None
    source: str | None = None
    revise_target: str | None = None


class OrganizeRequest(BaseModel):
    draft_id: str | None = None


class ChatRequest(BaseModel):
    message: str
    chat_id: str | None = None


def build_llm(cfg: Config) -> LLM:
    return OpenAICompatLLM(
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
    )


def _result_payload(result: OrganizeResult) -> dict:
    return {
        "draft_id": result.draft_id,
        "kind": result.kind.value,
        "detail": result.detail,
        "error": result.error,
    }


def push_draft(
    cfg: Config,
    content: str,
    *,
    project: str | None = None,
    source: str | None = None,
    revise_target: str | None = None,
) -> tuple[str, str]:
    """落一条草稿，返回 `(给人看的文本, 草稿 id)`。

    **公开**（不带下划线）：`web/router.py` 也调它——投递只能有一份实现。
    HTTP 端点、对话层、Web 表单三条路都走这里。

    `/push` 端点与对话层共用这一份——否则「投递」会有两份实现。

    失败时 id 是空串，文本说明原因：对话可以直接把它说给用户听，
    端点则把它翻成 500。
    """
    created_at = f"{datetime.now():%Y-%m-%d %H:%M}"

    # write_draft 遇 id 冲突会抛 FileExistsError——这是刻意的，
    # 静默覆盖即数据丢失。这里重试换一个 id。
    for _ in range(PUSH_ATTEMPTS):
        draft = Draft(
            id=new_draft_id(),
            body=content.strip() + "\n",
            source=source,
            project=project,
            created_at=created_at,
            revise_target=revise_target,
        )
        try:
            write_draft(cfg.vault_path, draft)
        except FileExistsError:
            continue
        logging.getLogger("kb.push").info(
            "收到草稿 id=%s 来源=%s 项目=%s%s",
            draft.id,
            source or "未说明",
            project or "无",
            f" 修改目标={revise_target}" if revise_target else "",
        )
        # 措辞要中性：这条路同时被 `/push`（CLI 与各会话 agent 走的）和
        # Web 表单调——写死「你在网页上投递」会让 `kb push` 也记成网页
        flow.emit("投递", f"收到一条草稿（来源：{source or '未说明'}），编号 {draft.id}")
        return f"已记下，编号 {draft.id}。", draft.id

    return f"连续 {PUSH_ATTEMPTS} 次撞上已存在的草稿 id，没记成。", ""


def push_and_organize(
    cfg: Config,
    content: str,
    llm: LLM,
    *,
    source: str | None = None,
    revise_target: str | None = None,
) -> str:
    """投一条草稿，**立刻整理**，返回给人看的结果。

    Web 这条路不等（Q88）——人写完就想看到结果，留着等没有意义。
    会话层那条（`kb push` + 事后 `kb organize`）仍保留缓冲：
    agent 干活时投的东西要攒着，由会话 AI 判断时机（Q62）。
    """
    # 先开一个 run——这样这次「投递」和紧接着的整理是同一个 run，
    # 工作日志页上它们才会画进同一条流程链。
    run = flow.new_run_id()
    flow.set_run(run)

    text, draft_id = push_draft(
        cfg, content, source=source, revise_target=revise_target
    )
    if not draft_id:
        return text

    results = organize.organize_selected(
        cfg.vault_path,
        [p for p in [find_draft(cfg.vault_path, draft_id)] if p],
        llm,
        run_id=run,
    )
    if not results:
        return text

    r = results[0]
    if r.kind.value == "failed":
        return f"{text}\n整理没成：{r.error}"
    if r.kind.value == "pending":
        return f"{text}\n归不了类，先搁在待归类：{r.detail}"
    return f"{text}\n已归到 {r.detail}"


def _commit_sweep(vault_root: Path, touched: list[Path], plan: sweep.SweepPlan) -> bool:
    """一次巡检 = 一个 commit，message 用 `plan.summary`（Q46 同样适用）。

    **禁用 `git add -A`**——那会把用户正在编辑、尚未提交的笔记一起裹进
    这次「AI 收拾」的 commit 里，历史就骗人了。只 add `apply_plan` 报上来的
    那份清单。

    清单里**旧路径和新路径都有**（`apply_plan` 特意那么返回的）：
    旧路径让 git 看见「删除」、新路径让 git 看见「新增」，两边都 staged
    才会被识别成一次 rename。**只 add 新路径的话，移动过的文件会漏提交。**

    git 的两个调用沿用 `organize` 里的那份实现——**编码与 `-c` 参数这些
    平台坑只该有一处**，复制一份迟早会改漏。
    """
    rels: list[str] = []
    for path in touched:
        try:
            rels.append(path.relative_to(vault_root).as_posix())
        except ValueError:
            continue

    rels = organize.stageable(vault_root, rels)
    if not rels:
        return False

    message = plan.summary or "巡检：收拾标签与目录"
    organize.git_run(vault_root, "add", "--", *rels)
    proc = organize.git_run(
        vault_root,
        "-c", f"user.name={organize.SERVICE_AUTHOR_NAME}",
        "-c", f"user.email={organize.SERVICE_AUTHOR_EMAIL}",
        "commit", "-m", message,
    )
    if proc.returncode == 0:
        flow.emit("提交", f"提交了一个 commit：「{message.splitlines()[0]}」")
    return proc.returncode == 0


def run_sweep(
    vault_root: Path,
    data_dir: Path,
    llm: LLM,
    requirement: str | None = None,
) -> dict:
    """跑一次巡检：规划 → 校验 → 落盘 → commit → 存报告。

    **它走的是和整理草稿同一条链**，只是输入换成了整个库的标签与目录。

    `requirement` 非空时是「还需调整」带上来的用户意见（Q96）——巡检**带着
    它重跑一次**，不是撤销上次的改动。重跑会产生**新的一个 commit**，
    上一个留着（与 Q46「一次整理 = 一个 commit」一致）。
    """
    # **一开始就开自己的 run**，别等到真的有事要做才开。
    # ContextVar 是 per-thread 的，而 uvicorn 的线程池会复用线程——
    # 不在入口处重置，这次的流程记录会落进上一个请求的 run 里
    # （空计划那条提前返回的路径原先就没有 set_run，实测撞上过）。
    flow.set_run(flow.new_run_id())

    plan = sweep.make_plan(vault_root, llm, requirement)
    sweep.validate(plan, vault_root)

    if plan.is_empty:
        flow.emit("规划", f"巡检发现：{plan.summary or '没什么要收拾的'}")
        report = {"summary": plan.summary or "没什么要收拾的", "tag_merges": [], "dir_merges": []}
        sweep_state.save_report(data_dir, report)
        return report

    flow.emit("规划", f"巡检发现：{plan.summary or '有可以合并的'}")
    flow.emit("校验", "校验通过")
    touched = sweep.apply_plan(plan, vault_root)
    if touched:
        flow.emit("落盘", f"动了 {len(touched)} 个文件")
    _commit_sweep(vault_root, touched, plan)

    report = {
        "summary": plan.summary,
        "tag_merges": [{"from": a, "to": b} for a, b in plan.tag_merges],
        "dir_merges": [{"from": a, "to": b} for a, b in plan.dir_merges],
        "touched": [p.relative_to(vault_root).as_posix() for p in touched],
    }
    sweep_state.save_report(data_dir, report)
    return report


def _sweep_in_background(vault_root: Path, data_dir: Path, llm: LLM) -> None:
    """后台跑巡检。**绝不抛异常**——后台线程里抛了没人接。

    `llm` 由 `main()` 用现成的 `cfg` 建好传进来，**这里不重新 `load_config()`**：
    `load_dotenv` 写的是进程级 `os.environ`，同一进程内只该调用一次
    （见 `config.load_config` 的 docstring），而 `main()` 已经调过了。
    """
    # 先占坑：万一跑挂了也不会每次重启都重跑。
    # 用 mark_run 而不是 save_report——后者会留一份 read: false 的报告，
    # 侧栏会把它当正式报告显示（还带两个回复按钮）。
    sweep_state.mark_run(data_dir)
    try:
        run_sweep(vault_root, data_dir, llm)
    except Exception:      # noqa: BLE001
        logging.getLogger("kb.sweep").exception("巡检失败")
        sweep_state.save_report(data_dir, {"summary": "这次巡检没跑成，看运行日志"})


def create_app(
    cfg: Config | None = None,
    llm: LLM | None = None,
    data_dir: Path | None = None,
) -> FastAPI:
    cfg = cfg or load_config()
    # 会话历史**不能进仓库**（public）——落点只有 data/ 是安全的，
    # 夹具可以传临时目录来隔离。
    data_dir = data_dir or DATA_DIR
    # 流程日志的落点跟着它走——测试注入临时目录时也跟着隔离
    flow.configure(data_dir)
    cache: dict[str, LLM | None] = {"llm": llm}

    def get_llm() -> LLM:
        if cache["llm"] is None:
            cache["llm"] = build_llm(cfg)
        return cache["llm"]

    def _chat_organize_fn(kind: str, content: str, target: str | None) -> str:
        """对话层能调的动作——**只有服务已有的能力**，不新增判断。

        Web 对话页也用它（`build_router` 收的就是这个闭包），
        两个入口的动作清单才是同一份。
        """
        if kind == "push":
            return push_and_organize(cfg, content, get_llm(), source="Web")
        if kind == "revise":
            return push_and_organize(
                cfg, content, get_llm(), source="Web", revise_target=target
            )
        if kind == "organize":
            results = organize.organize_selected(
                cfg.vault_path, list_drafts(cfg.vault_path), get_llm()
            )
            ok = sum(1 for r in results if not r.error)
            return f"整理了 {len(results)} 条，成功 {ok} 条。"
        return f"未知动作：{kind}"

    app = FastAPI(title="KN_Base 知识库服务")

    from fastapi.staticfiles import StaticFiles

    from kb.web.router import STATIC_DIR, build_router

    app.include_router(build_router(cfg, data_dir, _chat_organize_fn, get_llm))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/push")
    def push(req: PushRequest) -> dict:
        """投递一条草稿。异步——立刻返回，不做整理（Q55）。"""
        body = req.content.strip()
        if not body:
            raise HTTPException(status_code=400, detail="正文不能为空")

        # 同上：入口处重置 run，否则会继承这个线程上一次请求的
        flow.set_run(flow.new_run_id())
        _, draft_id = push_draft(
            cfg,
            body,
            project=req.project,
            source=req.source,
            revise_target=req.revise_target,
        )
        if not draft_id:
            raise HTTPException(
                status_code=500,
                detail=f"连续 {PUSH_ATTEMPTS} 次撞上已存在的草稿 id",
            )
        return {"id": draft_id}

    @app.get("/inbox")
    def inbox() -> dict:
        items = []
        for path in list_drafts(cfg.vault_path):
            draft = read_draft(path)
            first_line = draft.body.strip().splitlines()
            items.append(
                {
                    "id": draft.id,
                    "project": draft.project,
                    "source": draft.source,
                    "created_at": draft.created_at,
                    "preview": first_line[0][:80] if first_line else "",
                    "pending": path.parent.name == PENDING,
                }
            )
        return {"count": len(items), "items": items}

    @app.get("/search")
    def search(q: str = "") -> dict:
        hits = search_notes(cfg.vault_path, q)
        items = []
        for path in hits:
            meta, _ = read_note(path)
            items.append({
                "path": path.relative_to(cfg.vault_path).as_posix(),
                "title": path.stem,
                "tags": meta.get("主题") or [],
            })
        return {"count": len(items), "items": items}

    @app.post("/organize")
    def run_organize(req: OrganizeRequest) -> dict:
        """整理草稿。不传 draft_id 就整理全部（Q38）。"""
        if req.draft_id:
            path = find_draft(cfg.vault_path, req.draft_id)
            if path is None:
                raise HTTPException(
                    status_code=404, detail=f"找不到草稿 {req.draft_id}"
                )
            paths = [path]
        else:
            paths = list_drafts(cfg.vault_path)

        # run 与「开始整理」那句都由 `organize_selected` 自己记
        # （入口有三个，在端点里记会漏掉另两条）
        log = logging.getLogger("kb.organize")
        log.info("开始整理 %d 条草稿", len(paths))
        results = organize.organize_selected(cfg.vault_path, paths, get_llm())
        for r in results:
            if r.error:
                log.warning("草稿 %s → %s：%s", r.draft_id, r.kind.value, r.error)
            else:
                log.info("草稿 %s → %s：%s", r.draft_id, r.kind.value, r.detail)
        log.info("整理结束：%d 条", len(results))
        return {
            "count": len(results),
            "results": [_result_payload(r) for r in results],
        }

    @app.post("/chat")
    def chat_endpoint(req: ChatRequest) -> dict:
        """一轮对话。会话历史落服务侧，不入库（Q83）。"""
        if req.chat_id and load_chat(data_dir, req.chat_id) is None:
            raise HTTPException(status_code=404, detail=f"找不到会话 {req.chat_id}")
        chat_id, reply = handle(
            data_dir,
            cfg.vault_path,
            req.chat_id,
            req.message,
            get_llm(),
            organize_fn=_chat_organize_fn,
        )
        return {"chat_id": chat_id, "reply": reply}

    @app.get("/chats")
    def chats() -> dict:
        items = list_chats(data_dir)
        return {"count": len(items), "items": items}

    @app.get("/sweep")
    def sweep_latest() -> dict:
        """最近一次巡检的报告，以及「读没读」。没跑过就是空的。"""
        state = sweep_state.load_state(data_dir)
        return {
            "report": state.get("report"),
            "last_sweep": state.get("last_sweep"),
        }

    @app.post("/sweep")
    def sweep_now() -> dict:
        """手动跑一次巡检（`kb sweep` 与网页「巡检一次」走这里）。

        **同步跑**——巡检是低频动作，等一会儿可以接受；跑完直接拿报告。
        """
        try:
            return run_sweep(cfg.vault_path, data_dir, get_llm())
        except sweep.SweepError as exc:
            # 模型输出坏了、计划不合规——原因要说给人听，CLI 是拿它调试的
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # 这里**不**放 `/sweep/reply`。它是网页那个表单在用（`web/router.py`
    # 里的 Form 版），而 `include_router` 先于 app 级路由注册——
    # 同一个路径注册两次，**先注册的那个赢**，放这儿也是收不到请求的死代码。
    # 将来别的入口（比如 qqbot）要调，那时会有明确的形状需求，再加不迟。

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="KN_Base 知识库服务")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config()
    port = args.port or cfg.port or runtime.find_free_port()

    log_path = setup_logging()
    logging.getLogger(__name__).info(
        "服务启动 port=%s vault=%s 日志=%s", port, cfg.vault_path, log_path
    )

    runtime.write_service_info(port)

    # 先把 app 建出来（`create_app` 里会把流程日志的落点配好），再放后台巡检——
    # 否则巡检抢在前面记流程，「规划」「提交」那几行会因为没有落点而丢掉。
    app = create_app(cfg)

    # 距上次巡检超过 6 天就跑一次——**后台线程**，不挡启动。
    #
    # **放这里而不是 `create_app` 里**：只有走到 `main()` 才是「服务真起来了」。
    # 测试和嵌入用法都直接调 `create_app`，要是那里也算启动，后台巡检会去用
    # 夹具注入的假模型（把 `FakeLLM` 的应答队列吃掉，实测让对话那条用例变红），
    # 还会拿默认的 `data/` 当落点写状态（跑一次 pytest 就写进一份假报告，
    # 顺带把 `last_sweep` 顶掉——真服务 6 天内都不会再自动跑）。
    # 服务进程只有这一条入口（`runtime.spawn_service` 也是 `-m kb.api.http`）。
    if sweep_state.due(DATA_DIR):
        threading.Thread(
            target=_sweep_in_background,
            args=(cfg.vault_path, DATA_DIR, build_llm(cfg)),
            daemon=True,
        ).start()

    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    finally:
        runtime.clear_service_info()


if __name__ == "__main__":
    main()
