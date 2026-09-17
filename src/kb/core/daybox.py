"""按天文件——三个日志落点共用的那一层（Q93）。

「箱子」的落盘形态是「一天一个文件」。三个日志（整理/流程/运行）目录不同、
后缀不同，但**三件事完全一样**：日期怎么校验、目录里有哪些天、哪些天该清掉。
抄三遍迟早改漏一处，所以收在这里。

**日期格式认死 `YYYY-MM-DD`。** 不认形状的名字一律当「不是一天」——
目录里放个 `模板.md` 或 `backup.jsonl` 不该被当成箱子，更不该让
`box_label()` 拆包崩掉（实测过）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

# 只认 `YYYY-MM-DD`。这些名字会从 `?d=` 传上来，也会用来拼路径
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DAY_FMT = "%Y-%m-%d"


def is_day(name: str) -> bool:
    """这个名字是不是一个日期。"""
    return bool(DAY_RE.fullmatch(name))


def day_file(directory: Path, day: str, suffix: str) -> Path | None:
    """某一天的按天文件路径。`day` 形状不对返回 `None`。

    **校验在这里，不在调用方**——`day` 可能是 `?d=` 传上来的，
    直接拼路径就是一次任意文件读。
    """
    if not is_day(day):
        return None
    return directory / f"{day}{suffix}"


def list_days(directory: Path, suffix: str) -> list[str]:
    """目录里有哪些天，**倒序**。目录不存在返回空列表。

    只收日期形状的名字——模板、备份之流不算箱子。
    """
    if not directory.is_dir():
        return []
    return sorted(
        (p.stem for p in directory.glob(f"*{suffix}") if is_day(p.stem)),
        reverse=True,
    )


def prune(
    directory: Path, suffix: str, keep_days: int, now: datetime | None = None
) -> int:
    """删掉超过 `keep_days` 的按天文件，返回删了几个。

    **只删日期形状的**——不认识的留着：宁可占地方，也别误删别人的文件。
    """
    now = now or datetime.now()
    cutoff = (now - timedelta(days=keep_days)).strftime(DAY_FMT)
    removed = 0
    for p in directory.glob(f"*{suffix}"):
        if is_day(p.stem) and p.stem < cutoff:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed
