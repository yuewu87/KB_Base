"""Web UI 路由。布局见 `docs/02_需求.md` 第五节。

**薄层**——只做「取数据 + 渲染」，判断逻辑全在 `core/`。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kb.config import Config
from kb.core.search import search_notes
from kb.core.vault import list_domains, read_note
from kb.logging_setup import LOG_FILE
from kb.web.data import read_journals, tail_log

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 运行日志页一次显示多少行
LOG_TAIL_LINES = 300


def build_router(cfg: Config) -> APIRouter:
    router = APIRouter()

    def _ctx(name: str, **extra) -> dict:
        return {"active": name, "vault": str(cfg.vault_path), **extra}

    def _hit(path: Path) -> dict:
        meta, _ = read_note(path)
        tags = meta.get("主题") or []
        if isinstance(tags, str):
            tags = [tags]
        return {
            "path": path.relative_to(cfg.vault_path).as_posix(),
            "title": path.stem,
            "tags": tags,
        }

    @router.get("/", response_class=HTMLResponse)
    def chat(request: Request, q: str = ""):
        """对话式检索。当前是「输入关键词 → 列命中」，还没做成对话。"""
        hits = [_hit(p) for p in search_notes(cfg.vault_path, q)] if q.strip() else []
        return templates.TemplateResponse(
            request, "chat.html", _ctx("chat", q=q, hits=hits)
        )

    @router.get("/journal", response_class=HTMLResponse)
    def journal(request: Request):
        return templates.TemplateResponse(
            request, "journal.html", _ctx("journal", days=read_journals(cfg.vault_path))
        )

    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request):
        """流程日志的字段清单还没定（见 03_问题记录.md 待解决 #2），先不接。"""
        return templates.TemplateResponse(request, "flow.html", _ctx("flow"))

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
