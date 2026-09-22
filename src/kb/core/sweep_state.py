"""巡检的状态：上次什么时候跑的、报告读没读。

存在 `data/state.json`（服务侧，**不进 git**——`data/` 整棵已排除）。

**为什么不用日志推**：流程日志是流水，要算「上次巡检」得倒着找；这里就两个
字段，单独放一个文件最省事。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from kb.core.vault import atomic_write

# 把「读 → 改 → 写」串起来的一把锁。
#
# **`atomic_write` 防的是读到半截 JSON，防不了丢更新。** 后台巡检线程和 Web
# 请求会同时碰这个文件：一个写 `last_sweep`、一个标「已读」，而**被挡住那条
# 路也写**——`/sweep/run` 拿不到 `Busy` 时要落一份「这次巡检没跑成」的报告，
# 而走到那一步的前提**就是**别人正持锁、正对着同一个文件做同样的读-改-写。
# 没有这把锁的话，请求线程读到旧快照、后台线程这时写进一份**真**报告，
# 请求线程再把旧快照盖回去：那份合并清单只剩 commit message 里有，页面上
# 再也看不到。
#
# 粒度是「整个进程一把」——这几个函数都只碰一个几十字节的文件，不值得更细。
_LOCK = threading.Lock()

# 距上次超过这个间隔就该跑。**默认值**——真值来自配置（`KB_SWEEP_INTERVAL`），
# 由调用方传进来。用户原话是「一次（6 天），超过才跑」，但 6 这个数是拍的。
SWEEP_INTERVAL_DAYS = 6

_FILE = "state.json"
_FMT = "%Y-%m-%d %H:%M:%S"


def state_path(data_dir: Path) -> Path:
    return data_dir / _FILE


def load_state(data_dir: Path) -> dict:
    """读状态。文件不存在或坏掉都返回 `{}`——**宁可多跑一次，也别永远不跑**。"""
    path = state_path(data_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data_dir: Path, state: dict) -> None:
    """原子写。

    **不是为了防崩溃，是为了防并发。** 后台的巡检线程和 Web 请求会同时
    碰这个文件（一个写 `last_sweep`，一个标「已读」）。直接覆写的话，
    读的一方可能拿到半截 JSON——而 `load_state` 会把解析失败吞成 `{}`，
    于是 `due()` 判 True，**白跑一次巡检**（一次 LLM 调用 + 可能移文件）。

    `vault.atomic_write` 现成的，先写临时文件再改名。
    """
    atomic_write(
        state_path(data_dir), json.dumps(state, ensure_ascii=False, indent=2)
    )


def due(
    data_dir: Path,
    now: datetime | None = None,
    interval_days: int = SWEEP_INTERVAL_DAYS,
) -> bool:
    """距上次巡检是否已超过 `interval_days`。从没跑过 → True。"""
    last = load_state(data_dir).get("last_sweep")
    if not last:
        return True
    try:
        last_at = datetime.strptime(last, _FMT)
    except ValueError:
        return True
    return (now or datetime.now()) - last_at > timedelta(days=interval_days)


def save_report(data_dir: Path, report: dict, when: datetime | None = None) -> None:
    """记下「跑过了」并留一份**未读**报告。**读-改-写走 `_LOCK`。**"""
    when = when or datetime.now()
    with _LOCK:
        state = load_state(data_dir)
        state["last_sweep"] = f"{when:{_FMT}}"
        state["report"] = {**report, "at": f"{when:{_FMT}}", "read": False}
        _write(data_dir, state)


def mark_run(data_dir: Path, when: datetime | None = None) -> None:
    """只占坑：把「上次巡检」推到现在，**不留报告**。

    后台巡检一开始就要占坑（否则服务重启会重复跑），但那一刻还没有报告可写。
    早先用 `save_report(data_dir, {"summary": "巡检正在跑…"})` 占坑——那条也是
    `read: false`，侧栏会把它当**正式报告**显示，还带两个回复按钮；进程中途
    被杀的话它会一直留着。
    """
    when = when or datetime.now()
    with _LOCK:
        state = load_state(data_dir)
        state["last_sweep"] = f"{when:{_FMT}}"
        _write(data_dir, state)


def mark_read(data_dir: Path) -> None:
    with _LOCK:
        state = load_state(data_dir)
        if "report" in state:
            state["report"]["read"] = True
            _write(data_dir, state)
