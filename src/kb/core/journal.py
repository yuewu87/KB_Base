"""工作日志（Q50）。

按天聚合：`40_索引/整理日志/YYYY-MM-DD.md`，每次整理往当天那篇追加一节。

**报告与工作日志同源**——本模块只负责渲染成 markdown，文本报告由 api 层从同一批
OrganizeResult 渲染。不写两套逻辑，否则会出现报告说「新建 3 篇」而日志写 4 篇。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from kb.core.models import K_TYPE, K_UPDATED, NoteType, OrganizeResult, ResultKind
from kb.core.vault import INDEX, JOURNAL_DIR, read_note, write_note

_LABEL: dict[ResultKind, str] = {
    ResultKind.CREATED: "新建",
    ResultKind.FOLDED: "合并",
    ResultKind.PENDING: "待归类",
    ResultKind.FAILED: "失败",
}


def journal_dir(vault_root: Path) -> Path:
    return vault_root / INDEX / JOURNAL_DIR


def journal_path(vault_root: Path, when: datetime) -> Path:
    return journal_dir(vault_root) / f"{when:%Y-%m-%d}.md"


def format_entry(result: OrganizeResult) -> str:
    """渲染一条结果。失败时把原因也带上——不然日志里看不出为什么卡住。"""
    line = f"- {_LABEL[result.kind]}：{result.detail}"
    if result.error:
        line += f"（{result.error}）"
    return line


def append_results(
    vault_root: Path,
    results: list[OrganizeResult],
    when: datetime | None = None,
) -> Path | None:
    """把一次整理的结果追加进当天的工作日志。

    `results` 为空时**不写文件**并返回 None——没干活就不该在日志里留空节。
    """
    if not results:
        return None

    when = when or datetime.now()
    path = journal_path(vault_root, when)

    if path.exists():
        meta, body = read_note(path)
    else:
        meta = {K_TYPE: NoteType.JOURNAL.value}
        body = f"# 整理日志 {when:%Y-%m-%d}\n"

    meta[K_TYPE] = NoteType.JOURNAL.value
    meta[K_UPDATED] = f"{when:%Y-%m-%d}"

    section = "\n".join(
        [f"## {when:%H:%M} 整理 {len(results)} 条草稿", ""]
        + [format_entry(r) for r in results]
    )
    body = body.rstrip("\n") + "\n\n" + section + "\n"

    write_note(path, meta, body)
    return path
