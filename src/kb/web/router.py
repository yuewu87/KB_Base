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

from kb.api.http import push_and_organize
from kb.config import Config
from kb.core.chat import handle
from kb.core.chat_store import list_chats, load_chat
from kb.core.flow import STEPS, read_flow
from kb.core.vault import list_domains
from kb.llm.base import LLM
from kb.logging_setup import LOG_FILE
from kb.web.data import group_flow, load_push_templates, read_journals, tail_log

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 运行日志页一次显示多少行
LOG_TAIL_LINES = 300


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
    def journal(request: Request):
        return templates.TemplateResponse(
            request, "journal.html", _ctx("journal", days=read_journals(cfg.vault_path))
        )

    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request):
        groups = group_flow(read_flow(data_dir), steps=STEPS)
        return templates.TemplateResponse(
            request, "flow.html", _ctx("flow", groups=groups, steps=STEPS)
        )

    @router.get("/runtime", response_class=HTMLResponse)
    def runtime_page(request: Request):
        return templates.TemplateResponse(
            request,
            "runtime.html",
            _ctx(
                "runtime",
                log_path=str(LOG_FILE),
                log_text=tail_log(LOG_FILE, LOG_TAIL_LINES),
                domains=list_domains(cfg.vault_path),
            ),
        )

    return router
