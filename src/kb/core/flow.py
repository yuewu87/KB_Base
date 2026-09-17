"""流程日志——「从投递到落库，中间发生了什么」（Q89）。

**用自然语言写，一条就是一个动作。** 不是结构化字段：
读它的人想知道「模型决定放进 计算机/git」，不想看 `target_path=...`。

**按天分文件**（`data/logs/flow/YYYY-MM-DD.jsonl`）——这是「箱子」的落盘形态。
日期取**写入时刻**，不是记录里的字段：写入与落点必须是同一个判断，
否则跨午夜那一秒会写串。也**没有大小轮转**了——按天切本身就是长度上限。

**存服务侧（`data/logs/`），绝不进 vault**——它是过程记录不是知识
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

import contextvars
import json
import random
import threading
from datetime import datetime, timedelta
from pathlib import Path

# 链上的顺序就是流水线的顺序——工作日志页的流程图照它画
STEPS = ["投递", "规划", "校验", "审核", "落盘", "提交"]

# 按天文件保留多久（天）。服务启动时清理更早的。
KEEP_DAYS = 90

_SUBDIR = "flow"
_DAY_FMT = "%Y-%m-%d"

# 落点是启动时定一次、之后不变——模块全局没问题。
_data_dir: Path | None = None

# **当前 run 必须用 ContextVar，不能用模块全局。**
#
# FastAPI 的同步端点跑在**线程池**里，两个并发请求是真并行的。模块全局的
# run 会被后一个请求覆盖，前一个请求后续记的流程就挂到别人的 run 上了——
# 实测两个并发投递，12 条记录被拆成 10/2，串得一塌糊涂。
#
# ContextVar 是 per-thread 的，各请求各记各的。
_run: contextvars.ContextVar[str] = contextvars.ContextVar("flow_run", default="")

# 并发写同一文件会丢行——实测两个线程同时 emit，只落到一条。
# 日志丢一条不算大事，但既然看见了就加锁，三行的事。
_write_lock = threading.Lock()


def new_run_id(now: datetime | None = None) -> str:
    """`YYYYMMDD-HHMMSS-` + 4 位随机十六进制。

    **随机后缀不是装饰**：只用秒的话，同一秒内的两次投递会共用同一个 run，
    页面把它们并成一条流程链——实测一条 run 里挤过 41 条记录。
    """
    now = now or datetime.now()
    return f"{now:%Y%m%d-%H%M%S}-{random.randrange(16 ** 4):04x}"


def configure(data_dir: Path | None) -> None:
    """指定落点。服务启动时调一次；测试传临时目录；传 `None` 关掉。"""
    global _data_dir
    _data_dir = data_dir


def set_run(run_id: str) -> None:
    """标记「这一批整理」的开始。之后记的流程都挂在这个 id 下。

    写进 ContextVar（per-thread），并发请求各记各的。
    """
    _run.set(run_id)


def current_run() -> str:
    """当前线程的 run id。并发时各线程拿到各自的。"""
    return _run.get()


def day_dir(data_dir: Path) -> Path:
    return data_dir / "logs" / _SUBDIR


def day_path(data_dir: Path, day: str) -> Path:
    return day_dir(data_dir) / f"{day}.jsonl"


def emit(step: str, text: str, now: datetime | None = None) -> None:
    """记一条流程。`step` 取 `STEPS` 里的一个。

    `now` 只为测试留口子（仓库里 `new_run_id` / `save_report` 都是这个写法）：
    现取时间就没法测跨天。

    **没配落点、或写失败，都直接返回**——日志是附属品，不该拖垮正事。
    """
    if _data_dir is None:
        return
    now = now or datetime.now()
    row = {
        "at": f"{now:%Y-%m-%d %H:%M:%S}",
        "run": _run.get(),
        "step": step,
        "text": text,
    }
    path = day_path(_data_dir, f"{now:{_DAY_FMT}}")
    try:
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass          # 满了、没权限、路径没了——都不该让整理失败


def _parse(path: Path) -> list[dict]:
    """读一个 jsonl 文件。文件不存在返回空列表；坏行跳过。"""
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
    return rows


def list_days(data_dir: Path) -> list[str]:
    """有流程记录的日期，**倒序**（新的在前）。目录不存在返回空列表。"""
    directory = day_dir(data_dir)
    if not directory.is_dir():
        return []
    return sorted((p.stem for p in directory.glob("*.jsonl")), reverse=True)


def read_day(data_dir: Path, day: str) -> list[dict]:
    """读某一天的记录，**按写入顺序**。没有这一天返回空列表（不抛）。"""
    return _parse(day_path(data_dir, day))


def latest_run_rows(data_dir: Path) -> list[dict]:
    """**最近一次 run** 的记录——「报告 / 流程图」页签要的，与箱子无关。

    run 可能跨午夜（23:59 投、00:01 规划），所以**倒着扫**：从最新的那天
    往回找，直到收齐那个 run 的全部记录。
    """
    days = list_days(data_dir)
    if not days:
        return []

    rows = read_day(data_dir, days[0])
    if not rows:
        return []
    run = rows[-1].get("run")

    out = [r for r in rows if r.get("run") == run]
    # 往前一天找有没有同 run 的（跨午夜那条）
    for day in days[1:]:
        earlier = [r for r in read_day(data_dir, day) if r.get("run") == run]
        if not earlier:
            break
        out = earlier + out
    return out


def prune(data_dir: Path, keep_days: int = KEEP_DAYS, now: datetime | None = None) -> int:
    """删掉超过 `keep_days` 的按天文件，返回删了几个。

    **只碰服务侧**——vault 里的整理日志是知识，永不自动删。
    """
    now = now or datetime.now()
    cutoff = (now - timedelta(days=keep_days)).strftime(_DAY_FMT)
    removed = 0
    for p in day_dir(data_dir).glob("*.jsonl"):
        if p.stem < cutoff:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed
