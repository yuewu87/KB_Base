"""运行日志（Q51）。

`data/logs/kb/YYYY-MM-DD.log`，标准 Python logging，默认 INFO、可配 DEBUG。
**按天分文件**——这是「箱子」的落盘形态。

**运行日志绝不能进 vault**——一旦进去就成了笔记，会被检索、被 RAG 切片、
被 AI 当作知识。技术日志是噪音，属于垃圾进垃圾出。

它与**整理日志**的分界是「是不是知识」：整理日志进 vault（`_索引/整理日志/`），
运行日志留在服务侧。

## 为什么不用 `TimedRotatingFileHandler`

标准库那个**靠文件的 mtime 判断该不该轮转**——服务重启跨天时，它看到的是
昨天创建的文件，于是把**今天的内容写进昨天的文件**，箱子就不纯了。
这里按**写入时刻**选文件，跟流程日志一个判断方式。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from kb.config import PROJECT_ROOT
from kb.core import daybox

LOG_DIR = PROJECT_ROOT / "data" / "logs" / "kb"

# 按天文件保留多久（天）。服务启动时清理更早的。
KEEP_DAYS = 90

_SUFFIX = ".log"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def day_path(directory: Path, day: str) -> Path | None:
    """某一天的运行日志文件。`day` 形状不对返回 `None`。

    `day` 可能是 `?d=` 传上来的——**校验在这里**，直接拼路径就是一次任意文件读。
    """
    return daybox.day_file(directory, day, _SUFFIX)


def list_days(directory: Path) -> list[str]:
    """有日志的日期，**倒序**。目录不存在返回空列表。"""
    return daybox.list_days(directory, _SUFFIX)


def prune(directory: Path, keep_days: int = KEEP_DAYS, now: datetime | None = None) -> int:
    """删掉超过 `keep_days` 的按天文件，返回删了几个。"""
    return daybox.prune(directory, _SUFFIX, keep_days, now)


class DailyFileHandler(logging.Handler):
    """按天写 `YYYY-MM-DD.log`。

    **句柄按日期缓存**——同一天里不能每条日志都开关一次文件。
    `emit` 收一个 `now` 只为测试留口子（仓库里 `flow.emit` 也是这个写法）：
    现取时间就没法测跨天。
    """

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory
        self._day: str | None = None
        self._stream = None

    def emit(self, record: logging.LogRecord, now: datetime | None = None) -> None:
        try:
            now = now or datetime.now()
            day = f"{now:{daybox.DAY_FMT}}"
            if day != self._day:
                self._swap(day)
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            # 磁盘满、没权限、路径没了，或者 formatter 自己抛了——
            # **只吞掉，不能往上抛**：日志是附属品，不该拖垮服务。
            # stdlib 里 `Handler.emit` 的一贯做法就是吞掉一切走 handleError。
            self.handleError(record)

    def _swap(self, day: str) -> None:
        self._close()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._stream = (self.directory / f"{day}{_SUFFIX}").open("a", encoding="utf-8")
        self._day = day

    def _close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
        self._stream = None
        self._day = None

    def close(self) -> None:
        self._close()
        super().close()


def setup_logging(level: str | None = None) -> Path:
    """配置根 logger，返回**今天**的日志文件路径。

    幂等——重复调用不会叠加 handler（服务重启、测试里多次调用都会碰到）。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level or os.environ.get("KB_LOG_LEVEL", "INFO"))

    for handler in root.handlers:
        if isinstance(handler, DailyFileHandler) and handler.directory == LOG_DIR:
            return LOG_DIR / f"{datetime.now():{daybox.DAY_FMT}}{_SUFFIX}"

    handler = DailyFileHandler(LOG_DIR)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    return LOG_DIR / f"{datetime.now():{daybox.DAY_FMT}}{_SUFFIX}"
