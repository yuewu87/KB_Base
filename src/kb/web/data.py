"""Web UI 的数据聚合。

把 vault 里的文件与服务侧的日志变成页面能直接渲染的结构。

**这里只做「读 + 整形」，不做判断**——判断逻辑全在 `core/`。本模块是薄的。

不引入 markdown 渲染库：整理日志的结构是我们自己写的（`## 时刻 整理 N 条草稿`
+ `- 条目`），一个几十行的解析器就够，比拖一个依赖进来划算。
"""

from __future__ import annotations

from pathlib import Path

from kb.config import PROJECT_ROOT
from kb.core.vault import INDEX, JOURNAL_DIR

# 投递脚手架：**给人读**，帮他把话说清（`templates/笔记/` 那份是给机器读的 schema）
PUSH_TEMPLATES_DIR = PROJECT_ROOT / "templates" / "投递"

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


def group_flow(rows: list[dict], steps: list[str] | None = None) -> list[dict]:
    """按 run 分组，**新的在前**。

    传了 `steps` 就把六个步骤分成三类：

    - `reached` —— 有记录的
    - `skipped` —— 没记录，但**它后面有记录**（流程越过了它）
    - `todo`    —— 没记录，且后面也没有（流程停在前头了）

    **`skipped` 和 `todo` 要分开。** 比如「审核」常常没记录——那是没触发
    （没新建分类所以不跑），不是卡住了。画成一样会让人以为出了问题。
    """
    groups: dict[str, dict] = {}
    for row in rows:
        run = row.get("run") or "（未分组）"
        g = groups.setdefault(
            run, {"run": run, "rows": [], "reached": set(), "at": ""}
        )
        g["rows"].append(row)
        g["reached"].add(row.get("step", ""))
        g["at"] = g["at"] or row.get("at", "")

    out = list(groups.values())
    if steps:
        for g in out:
            seen = [i for i, s in enumerate(steps) if s in g["reached"]]
            last = max(seen) if seen else -1
            g["skipped"] = {s for i, s in enumerate(steps) if i < last and s not in g["reached"]}
            g["todo"] = {s for i, s in enumerate(steps) if i > last}
    return list(reversed(out))


def load_push_templates() -> dict[str, str]:
    """随手记的脚手架，返回 `{名字: 正文}`。

    **每次现读不缓存**——模板是用户可以随手改、随手加的（Q26），
    缓存会让改动不生效。目录不存在时返回空字典：模板没了不该让页面挂掉。
    """
    if not PUSH_TEMPLATES_DIR.is_dir():
        return {}
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(PUSH_TEMPLATES_DIR.glob("*.md"))
    }


def tail_log(path: Path, lines: int) -> str:
    """日志文件的最后 N 行。文件不存在返回空串。"""
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])
