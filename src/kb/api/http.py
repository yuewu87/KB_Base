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

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from kb.api import runtime
from kb.config import Config, load_config
from kb.core import organize
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


def create_app(cfg: Config | None = None, llm: LLM | None = None) -> FastAPI:
    cfg = cfg or load_config()
    cache: dict[str, LLM | None] = {"llm": llm}

    def get_llm() -> LLM:
        if cache["llm"] is None:
            cache["llm"] = build_llm(cfg)
        return cache["llm"]

    app = FastAPI(title="KN_Base 知识库服务")

    from fastapi.staticfiles import StaticFiles

    from kb.web.router import STATIC_DIR, build_router

    app.include_router(build_router(cfg))
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

        created_at = f"{datetime.now():%Y-%m-%d %H:%M}"

        # write_draft 遇 id 冲突会抛 FileExistsError——这是刻意的，
        # 静默覆盖即数据丢失。这里重试换一个 id。
        for _ in range(PUSH_ATTEMPTS):
            draft = Draft(
                id=new_draft_id(),
                body=body + "\n",
                source=req.source,
                project=req.project,
                created_at=created_at,
                revise_target=req.revise_target,
            )
            try:
                write_draft(cfg.vault_path, draft)
            except FileExistsError:
                continue
            logging.getLogger("kb.push").info(
                "收到草稿 id=%s 来源=%s 项目=%s%s",
                draft.id,
                req.source or "未说明",
                req.project or "无",
                f" 修改目标={req.revise_target}" if req.revise_target else "",
            )
            return {"id": draft.id}

        raise HTTPException(
            status_code=500,
            detail=f"连续 {PUSH_ATTEMPTS} 次撞上已存在的草稿 id",
        )

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
