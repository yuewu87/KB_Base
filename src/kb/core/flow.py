"""流程日志——「从投递到落库，中间发生了什么」（Q89）。

**用自然语言写，一条就是一个动作。** 不是结构化字段：
读它的人想知道「模型决定放进 计算机/git」，不想看 `target_path=...`。

**存服务侧（`data/logs/flow.jsonl`），绝不进 vault**——它是过程记录不是知识
（Q80 的分界）。进去会被检索、被当知识。

## 为什么不用 logging

一开始它挂在 `kb.flow` logger 上（独立 handler）。执行时证明行不通，两个问题：

1. **写路径在 handler 创建时就绑死了**——`monkeypatch` 改模块变量对写入毫无
   影响，测试没法注入落点。
2. `setup_logging()` 只在 `main()` 里调，`create_app` 不调——**pytest 进程里
   根本没有 handler**，`emit` 往哪儿都没写。

改成显式 `configure(data_dir)`：落点是个可设的模块变量，**写入时现读**。
不调 `configure` 就不记——服务在生产里配，测试里配临时目录。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# 链上的顺序就是流水线的顺序——工作日志页的流程图照它画
STEPS = ["投递", "规划", "校验", "审核", "落盘", "提交"]

MAX_BYTES = 1_000_000
_FILE = "flow.jsonl"

# 模块级状态：单进程、整理是同步的，够用。
# **并发整理时会串**（一批的 run 被另一批改掉）——知道有这个边界。
_data_dir: Path | None = None
_run: str = ""


def configure(data_dir: Path | None) -> None:
    """指定落点。服务启动时调一次；测试传临时目录；传 `None` 关掉。"""
    global _data_dir
    _data_dir = data_dir


def set_run(run_id: str) -> None:
    """标记「这一批整理」的开始。之后记的流程都挂在这个 id 下。"""
    global _run
    _run = run_id


def flow_path(data_dir: Path) -> Path:
    return data_dir / "logs" / _FILE


def emit(step: str, text: str) -> None:
    """记一条流程。`step` 取 `STEPS` 里的一个。

    **没配落点、或写失败，都直接返回**——日志是附属品，不该拖垮正事。
    """
    if _data_dir is None:
        return
    row = {
        "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "run": _run,
        "step": step,
        "text": text,
    }
    path = flow_path(_data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > MAX_BYTES:
            path.replace(path.with_name(_FILE + ".1"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass          # 满了、没权限、路径没了——都不该让整理失败


def read_flow(data_dir: Path, limit: int = 500) -> list[dict]:
    """读最近的流程记录，**按写入顺序**。文件不存在返回空列表。"""
    path = flow_path(data_dir)
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # 半行（进程被杀）——跳过，别让整页挂掉
    return rows[-limit:]
