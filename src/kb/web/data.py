"""Web UI 的数据聚合。

把 vault 里的文件与服务侧的日志变成页面能直接渲染的结构。

**这里只做「读 + 整形」，不做判断**——判断逻辑全在 `core/`。本模块是薄的。

不引入 markdown 渲染库：整理日志的结构是我们自己写的（`## 时刻 整理 N 条草稿`
+ `- 条目`），一个几十行的解析器就够，比拖一个依赖进来划算。
"""

from __future__ import annotations

from pathlib import Path

from kb.core.vault import INDEX, JOURNAL_DIR

# 每个整理日志小节：`## <标题>` 后面跟若干 `- <条目>`
Entry = str
Section = tuple[str, list[Entry]]
Journal = tuple[str, list[Section]]


def parse_journal(text: str) -> list[Section]:
    """把一篇整理日志拆成 [(小节标题, [条目, ...]), ...]。

    frontmatter 与一级标题（`# 整理日志 2026-09-16`）都丢掉——它们是文件
    结构，不是内容；页面上日期显示在卡片外面。
    """
    sections: list[Section] = []
    title: str | None = None
    items: list[Entry] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if title is not None:
                sections.append((title, items))
            title = stripped[3:].strip()
            items = []
        elif stripped.startswith("- ") and title is not None:
            items.append(stripped[2:].strip())

    if title is not None:
        sections.append((title, items))
    return sections


def read_journals(vault_root: Path) -> list[Journal]:
    """按日期倒序返回全部整理日志：[(日期, 各小节)]。"""
    directory = vault_root / INDEX / JOURNAL_DIR
    if not directory.is_dir():
        return []

    out: list[Journal] = []
    for path in sorted(directory.glob("*.md"), reverse=True):
        text = path.read_text(encoding="utf-8")
        sections = parse_journal(text)
        if sections:
            out.append((path.stem, sections))
    return out


def tail_log(path: Path, lines: int) -> str:
    """日志文件的最后 N 行。文件不存在返回空串。"""
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])
