"""Web UI 路由。布局见 `docs/02_需求.md` 第五节。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kb.config import Config

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def build_router(cfg: Config) -> APIRouter:
    router = APIRouter()

    def _ctx(name: str, **extra) -> dict:
        return {"active": name, "vault": str(cfg.vault_path), **extra}

    @router.get("/", response_class=HTMLResponse)
    def chat(request: Request):
        return templates.TemplateResponse(request, "chat.html", _ctx("chat"))

    @router.get("/journal", response_class=HTMLResponse)
    def journal(request: Request):
        return templates.TemplateResponse(request, "journal.html", _ctx("journal"))

    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request):
        return templates.TemplateResponse(request, "flow.html", _ctx("flow"))

    @router.get("/runtime", response_class=HTMLResponse)
    def runtime_page(request: Request):
        return templates.TemplateResponse(request, "runtime.html", _ctx("runtime"))

    return router
