"""检索（Q25）。**标签是主力，全文是补充。**

不引入向量库——库规模是几十到几百篇，全文匹配足够。真到了需要 RAG
的规模再说。失效的笔记**默认不出现在结果里**（Q60），
`include_superseded=True` 时把历史也要回来。
"""
from __future__ import annotations

from pathlib import Path

from kb.core.vault import is_superseded, list_notes, read_note

MAX_HITS = 20


def _matches(path: Path, meta: dict, body: str, query: str) -> bool:
    q = query.lower()
    if q in path.stem.lower():
        return True
    tags = meta.get("主题") or []
    if isinstance(tags, str):
        tags = [tags]
    if any(q in str(t).lower() for t in tags):
        return True
    return q in body.lower()


def search_notes(
    vault_root: Path, query: str, *, include_superseded: bool = False
) -> list[Path]:
    """按关键词搜笔记。返回命中的笔记路径，最多 `MAX_HITS` 条。"""
    if not query.strip():
        return []
    hits: list[Path] = []
    for path in list_notes(vault_root):
        meta, body = read_note(path)
        if not include_superseded and is_superseded(meta):
            continue
        if _matches(path, meta, body, query):
            hits.append(path)
            if len(hits) >= MAX_HITS:
                break
    return hits
