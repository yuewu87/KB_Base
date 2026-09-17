"""Web UI 路由。布局见 `docs/02_需求.md` 第五节。

**薄层**——只做「取数据 + 渲染」，判断逻辑全在 `core/`。

**对话不在这里实现**（Q84）：跑一轮对话的是 `core.chat.handle`，能做的动作
由服务侧的闭包给。Web 只是调用方——两份实现迟早会分叉。

会话历史的落点（`data_dir`）同样由 `create_app` 传进来：Web 层自己拼路径
迟早会拼成仓库根的 `chats/`，那条路径没被 gitignore 覆盖（见 `chat_store`）。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from kb.api.http import push_and_organize, run_sweep
from kb.config import Config
from kb.core import sweep, sweep_state
from kb.core.chat import handle
from kb.core.chat_store import list_chats, load_chat
from kb.core.flow import STEPS, latest_run_rows
from kb.core.flow import list_days as flow_days
from kb.core.flow import read_day as read_flow_day
from kb.llm.base import LLM
from kb.logging_setup import LOG_DIR
from kb.web.data import (
    box_label,
    group_flow,
    journal_days,
    load_push_templates,
    read_journal,
    read_runtime,
    runtime_days,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 模板里现算箱子名——三个页面都要用，注册成全局比每个端点传一次干净
templates.env.globals["box_label"] = box_label


def build_router(
    cfg: Config,
    data_dir: Path,
    organize_fn: Callable[[str, str, str | None], str],
    get_llm: Callable[[], LLM],
) -> APIRouter:
    """`data_dir`、`organize_fn`、`get_llm` 都由 `create_app` 传进来。

    三者都是**服务侧的东西**：会话历史落哪、对话能调哪些动作、模型是谁。
    Web 层自己知道这三件事，就意味着多出第二份实现——
    尤其是 `get_llm`：自己 `build_llm(cfg)` 会绕过注入的模型（测试里就是假模型）。
    """
    router = APIRouter()

    def _ctx(name: str, **extra) -> dict:
        return {"active": name, "vault": str(cfg.vault_path), **extra}

    def _pick_day(d: str, days: list[str]) -> str:
        """选哪一天：`d` 在列表里就用它，否则落到**最新一天**。

        **非法 `d` 不 404**——手改 URL 或书签过期不该看到错误页，
        当「没有这一天」处理即可。
        """
        return d if d in days else (days[0] if days else "")

    @router.get("/", response_class=HTMLResponse)
    def chat_page(request: Request, cid: str = ""):
        """对话页。不带 `cid` 就落到最近一次会话。"""
        chats = list_chats(data_dir)
        if not cid and chats:
            cid = chats[0]["id"]
        current = load_chat(data_dir, cid) if cid else None
        return templates.TemplateResponse(
            request,
            "chat.html",
            _ctx("chat", chats=chats, current=current, cid=cid),
        )

    # 表单 POST 落在 `/` 上，**不能也叫 `/chat`**——那条路径已经被服务端的
    # JSON 端点占了（`api/http.py`）。同一个路径注册两次，先注册的那个
    # 会把另一个的请求全吃掉（表单进 JSON 端点 = 422，反之亦然）。
    @router.post("/")
    def chat_post(message: str = Form(...), cid: str = Form("")):
        chat_id, _ = handle(
            data_dir,
            cfg.vault_path,
            cid or None,
            message,
            get_llm(),
            organize_fn=organize_fn,
        )
        return RedirectResponse(f"/?cid={chat_id}", status_code=303)

    @router.get("/new", response_class=HTMLResponse)
    def new_note(request: Request, t: str = ""):
        """模板随手记（Q85）。模板只是脚手架，**不逼人先做分类判断**（Q86）。"""
        templates_ = load_push_templates()
        chosen = templates_.get(t, "")
        return templates.TemplateResponse(
            request,
            "new.html",
            _ctx("new", templates=list(templates_), chosen=t, body=chosen),
        )

    @router.post("/new")
    def new_note_post(content: str = Form(...)):
        """只填正文（Q87）——`source` 记成 Web，项目留空，其余归整理。"""
        if not content.strip():
            raise HTTPException(status_code=400, detail="正文不能为空")
        push_and_organize(cfg, content, get_llm(), source="Web")
        return RedirectResponse("/journal", status_code=303)

    @router.get("/journal", response_class=HTMLResponse)
    def journal(request: Request, d: str = ""):
        days = journal_days(cfg.vault_path)
        day = _pick_day(d, days)
        return templates.TemplateResponse(
            request,
            "journal.html",
            _ctx(
                "journal",
                days=days,
                day=day,
                sections=read_journal(cfg.vault_path, day) if day else [],
                latest=latest_run_rows(data_dir),
            ),
        )

    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request, d: str = ""):
        days = flow_days(data_dir)
        day = _pick_day(d, days)
        return templates.TemplateResponse(
            request,
            "flow.html",
            _ctx(
                "flow",
                days=days,
                day=day,
                groups=group_flow(read_flow_day(data_dir, day), steps=STEPS),
                steps=STEPS,
                latest=latest_run_rows(data_dir),
            ),
        )

    def _run_sweep_or_report() -> RedirectResponse:
        """跑一次巡检，失败就落一份没读的报告——**人在这儿等着，不能甩 500**。

        写成报告的语义和后台那条失败路径一致（`_sweep_in_background` 也这么落），
        巡检页上看得见原因。
        """
        try:
            run_sweep(cfg.vault_path, data_dir, get_llm())
        except sweep.SweepError as exc:
            sweep_state.save_report(
                data_dir,
                {
                    "summary": f"这次巡检没跑成：{exc}",
                    "tag_merges": [],
                    "dir_merges": [],
                },
            )
        return RedirectResponse("/sweep", status_code=303)

    @router.post("/sweep/reply")
    def sweep_reply():
        """报告下面那个按钮。

        **「我知道了」= 把报告标成已读。** 它就只做这件事——是不再高亮的提醒，
        不是审批，也不触发任何动作。

        （原来这里还有个「还需调整」，点了会带着用户写的话把巡检重跑一遍。
        2026-09-17 删了：巡检只会合并、且刻意不看笔记正文，所以「拆开某个分类」
        这类调整在结构上无法表达——后端能力与用户预期对不上，不留半截。）
        """
        sweep_state.mark_read(data_dir)
        return RedirectResponse("/sweep", status_code=303)

    @router.post("/sweep/run")
    def sweep_run():
        """手动跑一次巡检，**不受 6 天限制**——是你主动要跑的。

        跑完 `run_sweep` 自己会写 `last_sweep`（Task 1 的 `save_report`），
        所以自动那条也跟着顺延，这里不用额外记。

        **同步跑**，和 `/new` 一个路子：点完等它跑完，页面转到巡检页看报告。
        巡检比单条投递慢（全库过一遍 + 一次 LLM），但它是低频动作。
        """
        return _run_sweep_or_report()

    @router.get("/sweep", response_class=HTMLResponse)
    def sweep_page(request: Request):
        """巡检页——报告与「我知道了」的家（Q93）。

        **报告读过了也显示**，只是不再高亮：这一页就是它的家。原来那条
        「没读才冒出来」的逻辑是侧栏时代的（那块侧栏已经搬走了）。
        """
        state = sweep_state.load_state(data_dir)
        return templates.TemplateResponse(
            request,
            "sweep.html",
            _ctx(
                "sweep",
                report=state.get("report"),
                last_sweep=state.get("last_sweep"),
            ),
        )

    @router.get("/runtime", response_class=HTMLResponse)
    def runtime_page(request: Request, d: str = ""):
        days = runtime_days(LOG_DIR)
        day = _pick_day(d, days)
        return templates.TemplateResponse(
            request,
            "runtime.html",
            _ctx(
                "runtime",
                log_dir=str(LOG_DIR),
                days=days,
                day=day,
                log_text=read_runtime(LOG_DIR, day) if day else "",
            ),
        )

    return router
