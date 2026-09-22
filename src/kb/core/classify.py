"""查重预筛——Q36 两段式的第一段。

只做便宜的候选召回，**不下结论**。「完全重复 / 相关 / 全新」由 LLM 判定。
这样 LLM 只需要看 5-10 篇候选，而不是全库。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kb.core.models import K_TOPIC
from kb.core.vault import list_notes, note_title, read_note

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


def note_title_tags_body(path: Path) -> tuple[str, list[str], str]:
    """标题、主题标签、正文。

    **读一次就够**——`find_candidates` 三样都要，而 `read_note` 本来就把正文
    读出来了，多返回一份是白捡的。
    """
    meta, body = read_note(path)
    title = note_title(path, body)
    tags = meta.get(K_TOPIC) or []
    if isinstance(tags, str):
        tags = [tags]
    return title, list(tags), body


def note_title_and_tags(path: Path) -> tuple[str, list[str]]:
    """只要标题与标签时用这个（`note_title_tags_body` 的薄壳）。"""
    title, tags, _ = note_title_tags_body(path)
    return title, tags


def find_candidates(
    vault_root: Path, text: str, limit: int = DEFAULT_LIMIT
) -> list[Candidate]:
    """按相似度取前 `limit` 篇候选笔记。

    全库扫描，但只算字符串相似度——**不调 LLM**，所以便宜。阶段二会把这里换成
    向量召回，判定层不用动（Q36）。
    """
    # **比的是正文对正文。** 原先拿「草稿正文」对「标题 + 标签」——两侧长度
    # 差一个量级，Jaccard 的并集被正文撑满，分数全挤在 0.04–0.11，
    # **排序不带信息**：2026-09-18 实测，拿一篇笔记自己的正文去查，只有
    # 14/49 排第一（20 篇第二、11 篇第三），排前面的大多不相关。
    # 好在 recall@8 是 49/49——**真要的那篇总在清单里，只是被噪声裹着**。
    # 正文对正文两侧同量级，分数才分得开。（不是「换成向量」那条路——那是
    # 阶段二的事，Q36；这一步纯代码、不涨 token。）
    scored: list[Candidate] = []
    for path in list_notes(vault_root):
        title, tags, body = note_title_tags_body(path)
        scored.append(
            Candidate(
                path=path,
                title=title,
                tags=tags,
                # 正文为空（只剩标题的空笔记）时退回标题——否则那条恒得 0 分，
                # 排序里永远垫底，而它可能正是要 fold 进去的那一篇。
                score=similarity(text, body or title),
            )
        )
    scored.sort(key=lambda c: (-c.score, str(c.path)))
    return scored[:limit]
