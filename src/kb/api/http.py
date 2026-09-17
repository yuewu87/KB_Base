"""HTTP 接口层——薄层，只做协议转换，不含判断逻辑（Q33）。

所有写入都经过这里：CLI 和 MCP 都调这个服务，不直接碰文件。
于是写入天然串行化，不会出现两份逻辑打架（Q29）。

直接运行即启动服务：

    python -m kb.api.http --port 51723
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from kb.api import runtime
from kb.config import DATA_DIR, Config, load_config
from kb.core import flow, organize
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
    text, draft_id = push_draft(
        cfg, content, source=source, revise_target=revise_target
    )
    if not draft_id:
        return text

    results = organize.organize_selected(
        cfg.vault_path,
        [p for p in [find_draft(cfg.vault_path, draft_id)] if p],
        llm,
    )
    if not results:
        return text

    r = results[0]
    if r.kind.value == "failed":
        return f"{text}\n整理没成：{r.error}"
    if r.kind.value == "pending":
        return f"{text}\n归不了类，先搁在待归类：{r.detail}"
    return f"{text}\n已归到 {r.detail}"


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
    try:
        uvicorn.run(create_app(cfg), host="127.0.0.1", port=port, log_level="info")
    finally:
        runtime.clear_service_info()


if __name__ == "__main__":
    main()
