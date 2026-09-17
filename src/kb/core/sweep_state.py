"""巡检的状态：上次什么时候跑的、报告读没读。

存在 `data/state.json`（服务侧，**不进 git**——`data/` 整棵已排除）。

**为什么不用日志推**：流程日志是流水，要算「上次巡检」得倒着找；这里就两个
字段，单独放一个文件最省事。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from kb.core.vault import atomic_write

# 距上次超过这个间隔就该跑。用户定的是「一次（6 天），超过才跑」。
SWEEP_INTERVAL = timedelta(days=6)

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


def due(data_dir: Path, now: datetime | None = None) -> bool:
    """距上次巡检是否已超过 `SWEEP_INTERVAL`。从没跑过 → True。"""
    last = load_state(data_dir).get("last_sweep")
    if not last:
        return True
    try:
        last_at = datetime.strptime(last, _FMT)
    except ValueError:
        return True
    return (now or datetime.now()) - last_at > SWEEP_INTERVAL


def save_report(data_dir: Path, report: dict, when: datetime | None = None) -> None:
    """记下「跑过了」并留一份**未读**报告。"""
    when = when or datetime.now()
    state = load_state(data_dir)
    state["last_sweep"] = f"{when:{_FMT}}"
    state["report"] = {**report, "at": f"{when:{_FMT}}", "read": False}
    _write(data_dir, state)


def mark_read(data_dir: Path) -> None:
    state = load_state(data_dir)
    if "report" in state:
        state["report"]["read"] = True
        _write(data_dir, state)
