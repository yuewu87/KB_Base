"""查重预筛——Q36 两段式的第一段。

只做便宜的候选召回，**不下结论**。「完全重复 / 相关 / 全新」由 LLM 判定。
这样 LLM 只需要看 5-10 篇候选，而不是全库。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kb.core.models import K_TOPIC
from kb.core.vault import KNOWLEDGE, list_notes, read_note

DEFAULT_LIMIT = 8


@dataclass(frozen=True)
class Candidate:
    """一篇可能相关的已有笔记。"""

    path: Path
    title: str
    tags: list[str]
    score: float


def bigrams(text: str) -> set[str]:
    """字符 2-gram。

    中文没有空格可分词，字符 2-gram 是不引第三方库、且够用的近似。
    """
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def similarity(a: str, b: str) -> float:
    """Jaccard 相似度，取值 0.0 ~ 1.0。任一侧为空则返回 0.0。"""
    ga, gb = bigrams(a), bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def first_heading(body: str) -> str:
    """取正文第一个 `# ` 标题；没有就用首个非空行。

    笔记的「一句话结论」就写在第一个标题里，这是喂给 LLM 判定查重的主信号。
    """
    for line in body.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()
    for line in body.splitlines():
        if line.strip():
            return line.strip()
    return ""


def note_title_and_tags(path: Path) -> tuple[str, list[str]]:
    meta, body = read_note(path)
    title = first_heading(body) or path.stem
    tags = meta.get(K_TOPIC) or []
    if isinstance(tags, str):
        tags = [tags]
    return title, list(tags)


def find_candidates(
    vault_root: Path, text: str, limit: int = DEFAULT_LIMIT
) -> list[Candidate]:
    """按相似度取前 `limit` 篇候选笔记。

    全库扫描，但只算字符串相似度——**不调 LLM**，所以便宜。阶段二会把这里换成
    向量召回，判定层不用动（Q36）。
    """
    scored: list[Candidate] = []
    for path in list_notes(vault_root):
        title, tags = note_title_and_tags(path)
        haystack = " ".join([title, *tags])
        scored.append(
            Candidate(
                path=path,
                title=title,
                tags=tags,
                score=similarity(text, haystack),
            )
        )
    scored.sort(key=lambda c: (-c.score, str(c.path)))
    return scored[:limit]


def knowledge_topics(vault_root: Path) -> list[str]:
    """`20_知识/` 下已有的主题目录名。

    服务的主题必须落在这些既有主题里——**新主题要用户决定**
    （Q11：AI 不得自行发明分类）。
    """
    root = vault_root / KNOWLEDGE
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
