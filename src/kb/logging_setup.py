"""运行日志（Q51）。

`KN_Base/logs/kb.log`，标准 Python logging，按大小轮转，默认 INFO、可配 DEBUG。

**运行日志绝不能进 vault**——一旦进去就成了笔记，会被检索、被 RAG 切片、
被 AI 当作知识。技术日志是噪音，属于垃圾进垃圾出。

它与**整理日志**的分界是「是不是知识」：整理日志进 vault（`_索引/整理日志/`），
运行日志留在服务侧。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from kb.config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "kb.log"

MAX_BYTES = 1_000_000
BACKUP_COUNT = 5

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: str | None = None) -> Path:
    """配置根 logger，返回日志文件路径。

    幂等——重复调用不会叠加 handler（服务重启、测试里多次调用都会碰到）。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level or os.environ.get("KB_LOG_LEVEL", "INFO"))

    for handler in root.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler) and Path(
            handler.baseFilename
        ) == LOG_FILE:
            return LOG_FILE

    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    return LOG_FILE
