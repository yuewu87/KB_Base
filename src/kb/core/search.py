"""检索（Q25）。**标签是主力，全文是补充。**

不引入向量库——库规模是几十到几百篇，全文匹配足够。真到了需要 RAG
的规模再说。失效的笔记**默认不出现在结果里**（Q60），
`include_superseded=True` 时把历史也要回来。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kb.core.vault import is_superseded, list_notes, note_title, read_note

MAX_HITS = 20
K_TOPIC = "主题"


@dataclass(frozen=True)
class Hit:
    """一篇命中的笔记，**连同它的正文**。

    以前这里返回的是 `Path`，三处调用方各自再把文件读一遍拼标题标签——
    读出来的东西里**没有正文**，于是「检索」拿回来的是个读不出内容的索引记录：
    会话层只能说「要我把调出来读给你听吗」，而它并没有第二个动作可以调（Q103）。

    正文是**已读进来**的（要拿它做全文匹配），顺手带回去，一次读没有额外代价。
    """

    path: Path
    title: str
    tags: list[str] = field(default_factory=list)
    body: str = ""


def _tags_of(meta: dict) -> list[str]:
    tags = meta.get(K_TOPIC) or []
    return [str(t) for t in tags] if isinstance(tags, list) else [str(tags)]


def _matches(path: Path, meta: dict, body: str, query: str) -> bool:
    q = query.lower()
    if q in path.stem.lower():
        return True
    if any(q in t.lower() for t in _tags_of(meta)):
        return True
    return q in body.lower()


def search_notes(
    vault_root: Path, query: str, *, include_superseded: bool = False
) -> list[Hit]:
    """按关键词搜笔记。返回命中的笔记（带正文），最多 `MAX_HITS` 条。"""
    if not query.strip():
        return []
    hits: list[Hit] = []
    for path in list_notes(vault_root):
        meta, body = read_note(path)
        if not include_superseded and is_superseded(meta):
            continue
        if _matches(path, meta, body, query):
            hits.append(
                Hit(
                    path=path,
                    title=note_title(path, body),
                    tags=_tags_of(meta),
                    body=body,
                )
            )
            if len(hits) >= MAX_HITS:
                break
    return hits
