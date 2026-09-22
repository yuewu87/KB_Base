"""Web UI 的数据聚合。

把 vault 里的文件与服务侧的日志变成页面能直接渲染的结构。

**这里只做「读 + 整形」，不做判断**——判断逻辑全在 `core/`。本模块是薄的。

不引入 markdown 渲染库：整理日志的结构是我们自己写的（`## 时刻 整理 N 条草稿`
+ `- 条目`），一个几十行的解析器就够，比拖一个依赖进来划算。
"""

from __future__ import annotations

from pathlib import Path

from kb.config import PROJECT_ROOT
from kb.core import daybox
from kb.core.flow import STEPS, latest_run_rows
from kb.core.vault import INDEX, JOURNAL_DIR

# 投递脚手架：**给人读**，帮他把话说清（`templates/笔记/` 那份是给机器读的 schema）
PUSH_TEMPLATES_DIR = PROJECT_ROOT / "templates" / "投递"

# 每个整理日志小节：`## <标题>` 后面跟若干 `- <条目>`
Entry = str
Section = tuple[str, list[Entry]]


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


def read_journal(vault_root: Path, day: str) -> list[Section]:
    """读某一天的整理日志。没有这一天（或 `day` 形状不对）返回空列表。"""
    if not daybox.is_day(day):
        return []          # day 来自 ?d=，不校验就是一次任意文件读
    path = vault_root / INDEX / JOURNAL_DIR / f"{day}.md"
    if not path.is_file():
        return []
    return parse_journal(path.read_text(encoding="utf-8"))


def journal_days(vault_root: Path) -> list[str]:
    """有内容的整理日志日期，**倒序**。

    **空的不算一天**——只写了 frontmatter、一个小节都没有的文件不该在
    箱子列表里占一格（那会是个点进去什么都没有的空箱子）。
    **非日期名字也不算**——`模板.md` 是模板不是箱子。
    """
    directory = vault_root / INDEX / JOURNAL_DIR
    if not directory.is_dir():
        return []

    out: list[str] = []
    for path in sorted(directory.glob("*.md"), reverse=True):
        if daybox.is_day(path.stem) and parse_journal(path.read_text(encoding="utf-8")):
            out.append(path.stem)
    return out


def runtime_days(directory: Path) -> list[str]:
    """有运行日志的日期，**倒序**。目录不存在返回空列表。"""
    return daybox.list_days(directory, ".log")


def read_runtime(directory: Path, day: str) -> str:
    """读某一天的运行日志。没有这一天（或 `day` 形状不对）返回空串。

    末尾换行去掉——本模块出的是**页面能直接渲染的东西**，页面上是终端样式
    （`<pre>`），带着行尾换行会多空一行；它替换掉的 `tail_log` 也是拼行返回、
    本来就不带尾巴。
    """
    path = daybox.day_file(directory, day, ".log")
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").rstrip("\n")


def box_label(day: str) -> str:
    """`2026-09-17` → `26_9_17箱子`。

    **只是界面上的叫法**——落盘的文件名还是各自的 `2026-09-17.*`
    （整理日志是 vault 里的笔记，文件名跟标题一致是现有约定）。
    """
    year, month, day_of_month = day.split("-")
    return f"{year[2:]}_{int(month)}_{int(day_of_month)}箱子"


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


def latest_flow(data_dir: Path) -> dict | None:
    """最近一次 run，**已经分成 reached / skipped / todo 三类**。没有就 `None`。

    「流程图」那一栏原先自己在模板里算 `reached`，然后**没记录的一律画成
    「还没走到」**——`group_flow` 明明把 `skipped` 与 `todo` 分开了
    （它的 docstring 写着「比如『审核』常常没记录——那是没触发，不是卡住了。
    画成一样会让人以为出了问题」），`style.css` 里 `.chain-step.skipped`
    也早就备着色，**可模板从来没发过这个类**。
    """
    groups = group_flow(latest_run_rows(data_dir), steps=STEPS)
    return groups[0] if groups else None


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
