# 日志按天落盘（箱子·存储层）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把流程日志与运行日志从「一个文件混着所有天」改成「一天一个文件」，让「箱子」有对应的落盘形态。

**Architecture:** 两个日志模块各自按**写入时刻**的日期选文件。整理日志不用动——它本来就是一天一个文件。跑一次性的迁移脚本把现有两个文件拆进新结构。Web 层拿到统一的「列有哪些天 / 读某一天」接口。

**Tech Stack:** Python 3.11、pytest、ruff、conda 环境 `kn_base`

**前置背景（设计理由）：** 见 [`docs/superpowers/specs/2026-09-17-log-boxes-design.md`](../specs/2026-09-17-log-boxes-design.md) 第三节。

**不在本计划范围内：** UI（页签、箱子按钮、巡检页、「还需调整」带要求重跑）——那是第二份计划 `2026-09-17-log-boxes-ui.md`，本计划做完它才有依赖可依。

---

## 文件结构

| 文件 | 职责 | 本计划动它什么 |
|---|---|---|
| `src/kb/core/flow.py` | 流程日志的读写（只管流程日志这一种） | 落点改成按天；新增 `list_days`/`read_day`/`latest_run_rows`/`prune`；删掉 `read_flow` 与大小轮转 |
| `src/kb/logging_setup.py` | 运行日志的落点 | 换掉 `RotatingFileHandler`，新增按天 handler 与 `prune` |
| `src/kb/web/data.py` | Web 层的数据聚合 | 新增 `journal_days`/`read_journal`/`runtime_days`/`read_runtime`/`box_label`；删掉 `read_journals`/`tail_log` |
| `scripts/migrate_logs.py` | **新增**，一次性迁移 | 拆分旧文件 |
| `tests/core/test_flow.py` | | 改写 5 个、新增 6 个 |
| `tests/test_logging_setup.py` | **新增** | 按天 handler |
| `tests/web/test_data.py` | | 新增按天接口与 `box_label` |
| `tests/test_migrate_logs.py` | **新增** | 迁移脚本 |
| `src/kb/api/http.py` | 服务启动时清理过期日志 | 加两行 `prune` |
| `docs/01_架构.md` | 第十节日志 | 补按天落盘与保留策略 |

**测试总数基线：400 个。** 本计划删掉 3 个用例（`read_flow` 那条链的三个）、改写 5 个，其余以实跑为准。

**命令速查（本机 `conda run` 会报内部错误，勿用）：**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -v
```

---

## Task 1: 流程日志按天落盘

**这是整件事的地基。** 不改它，后面的「箱子」没有落盘形态可依。

**Files:**
- Modify: `src/kb/core/flow.py`
- Modify: `tests/core/test_flow.py`

- [ ] **Step 1: 改写测试**

`tests/core/test_flow.py` 里 `read_flow` 相关的四个用例要换掉。把文件开头到 `test_set_run_tags_subsequent_entries` 结束之间的部分整段替换：

```python
"""流程日志：自然语言，一条一个动作（Q89）。存服务侧，不进 vault。"""

from datetime import datetime

import pytest

from kb.core import flow
from kb.core.flow import (
    STEPS,
    emit,
    latest_run_rows,
    list_days,
    read_day,
    set_run,
)


@pytest.fixture(autouse=True)
def _reset():
    """每个测试前后都把模块状态清干净——它是模块级的，会串。"""
    flow.configure(None)
    set_run("")
    yield
    flow.configure(None)
    set_run("")


def _boom(*_args, **_kwargs):
    raise OSError("磁盘满了")


def _at(text: str) -> datetime:
    """把 `2026-09-17 14:32` 变成一个 datetime。"""
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


def test_emit_writes_into_todays_file(tmp_path):
    """落点按**写入时刻**的日期分文件。"""
    flow.configure(tmp_path)
    emit("投递", "你在网页上投递了一条草稿", now=_at("2026-09-17 14:32"))

    assert (tmp_path / "logs" / "flow" / "2026-09-17.jsonl").is_file()
    rows = read_day(tmp_path, "2026-09-17")
    assert len(rows) == 1
    assert rows[0]["step"] == "投递"
    assert rows[0]["text"] == "你在网页上投递了一条草稿"
    assert rows[0]["at"].startswith("2026-09-17 14:32")


def test_emit_splits_across_days(tmp_path):
    """跨天写进两个文件——这是「箱子」的落盘形态。"""
    flow.configure(tmp_path)
    emit("投递", "昨天的", now=_at("2026-09-16 23:59"))
    emit("投递", "今天的", now=_at("2026-09-17 00:01"))

    assert list_days(tmp_path) == ["2026-09-17", "2026-09-16"]
    assert [r["text"] for r in read_day(tmp_path, "2026-09-16")] == ["昨天的"]
    assert [r["text"] for r in read_day(tmp_path, "2026-09-17")] == ["今天的"]


def test_emit_is_noop_when_not_configured(tmp_path):
    """没配落点就不记——不抛、也不往别处写。"""
    emit("投递", "x", now=_at("2026-09-17 14:32"))
    assert list_days(tmp_path) == []


def test_emit_never_raises_on_write_failure(tmp_path, monkeypatch):
    """写日志失败不该让正事挂掉——日志是附属品。"""
    flow.configure(tmp_path)
    monkeypatch.setattr(flow.Path, "open", _boom)

    emit("投递", "x", now=_at("2026-09-17 14:32"))          # 不抛


def test_set_run_tags_subsequent_entries(tmp_path):
    flow.configure(tmp_path)
    set_run("20260917-1400")
    emit("投递", "a", now=_at("2026-09-17 14:32"))
    assert read_day(tmp_path, "2026-09-17")[0]["run"] == "20260917-1400"


def test_list_days_missing_dir(tmp_path):
    """目录不存在时返回空列表，不抛。"""
    assert list_days(tmp_path) == []


def test_list_days_newest_first(tmp_path):
    """新的在前——箱子列表倒序显示。"""
    flow.configure(tmp_path)
    for day in ("2026-09-15", "2026-09-17", "2026-09-16"):
        emit("投递", "x", now=_at(f"{day} 10:00"))
    assert list_days(tmp_path) == ["2026-09-17", "2026-09-16", "2026-09-15"]


def test_read_day_unknown_returns_empty(tmp_path):
    """指向没有日志的一天 → 空列表，不抛。手动改 URL 不该看到错误。"""
    flow.configure(tmp_path)
    emit("投递", "x", now=_at("2026-09-17 10:00"))
    assert read_day(tmp_path, "2026-09-01") == []


def test_read_day_skips_broken_lines(tmp_path):
    """半行（进程被杀）跳过，别让整页挂掉。"""
    flow.configure(tmp_path)
    emit("投递", "好的", now=_at("2026-09-17 10:00"))
    path = tmp_path / "logs" / "flow" / "2026-09-17.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"step": "规划", "tex')      # 截断的半行

    rows = read_day(tmp_path, "2026-09-17")
    assert [r["text"] for r in rows] == ["好的"]


def test_latest_run_rows_picks_the_last_run(tmp_path):
    """「报告/流程图」页签要的是**最近一次**，与箱子无关。"""
    flow.configure(tmp_path)
    set_run("run-A")
    emit("投递", "A 的第一步", now=_at("2026-09-17 10:00"))
    emit("规划", "A 的第二步", now=_at("2026-09-17 10:00"))
    set_run("run-B")
    emit("投递", "B 的第一步", now=_at("2026-09-17 11:00"))

    assert [r["text"] for r in latest_run_rows(tmp_path)] == ["B 的第一步"]


def test_latest_run_rows_spans_midnight(tmp_path):
    """最近一次 run 跨了午夜也要收齐——它是一件事，不该被日期切开。"""
    flow.configure(tmp_path)
    set_run("run-X")
    emit("投递", "23:59 投的", now=_at("2026-09-16 23:59"))
    emit("规划", "00:01 规划的", now=_at("2026-09-17 00:01"))

    assert [r["text"] for r in latest_run_rows(tmp_path)] == [
        "23:59 投的",
        "00:01 规划的",
    ]


def test_latest_run_rows_empty_when_no_logs(tmp_path):
    assert latest_run_rows(tmp_path) == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_flow.py -v
```

**Expected:** 收集期就报错——`ImportError: cannot import name 'latest_run_rows' from 'kb.core.flow'`

- [ ] **Step 3: 改实现**

`src/kb/core/flow.py` 整份替换：

```python
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
from datetime import datetime
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

    **只碰服务侧**——vault 里的整理日志是知识，永不自动删（见设计第三节）。
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
```

同时把 `from datetime import datetime` 改成 `from datetime import datetime, timedelta`。

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_flow.py -v
```

**Expected:** 全 PASS

- [ ] **Step 5: 跑全量测试，看看谁还在用 `read_flow`**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
```

**Expected:** `tests/core/test_flow.py` 全绿；**`tests/web/test_data.py` 与 `tests/web/test_router.py` 会有失败**——它们还在调 `read_flow`。这没关系，Task 3 会改。**先记下失败清单，别现在改**：本 Task 只碰 `flow.py`，混进别的文件会让 diff 说不清。

- [ ] **Step 6: 提交**

```bash
git add src/kb/core/flow.py tests/core/test_flow.py
git commit -m "refactor: 流程日志按天落盘，去掉大小轮转"
```

---

## Task 2: 运行日志按天落盘

**Files:**
- Modify: `src/kb/logging_setup.py`
- Create: `tests/test_logging_setup.py`

- [ ] **Step 1: 写失败的测试**

新建 `tests/test_logging_setup.py`：

```python
"""运行日志按天落盘。"""

import logging
from datetime import datetime

from kb.logging_setup import DailyFileHandler, day_path, list_days, prune


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="kb.test", level=logging.INFO, pathname=__file__,
        lineno=1, msg=msg, args=(), exc_info=None,
    )


def _handler(tmp_path) -> DailyFileHandler:
    h = DailyFileHandler(tmp_path)
    h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    return h


def _write(handler: DailyFileHandler, msg: str, at: str) -> None:
    """写一条，时间可控。"""
    handler.emit(_record(msg), now=datetime.strptime(at, "%Y-%m-%d %H:%M"))


def test_writes_into_todays_file(tmp_path):
    h = _handler(tmp_path)
    _write(h, "收到草稿", "2026-09-17 14:32")

    assert (tmp_path / "2026-09-17.log").is_file()
    assert "收到草稿" in (tmp_path / "2026-09-17.log").read_text(encoding="utf-8")


def test_splits_across_days(tmp_path):
    h = _handler(tmp_path)
    _write(h, "昨天的", "2026-09-16 23:59")
    _write(h, "今天的", "2026-09-17 00:01")

    assert list_days(tmp_path) == ["2026-09-17", "2026-09-16"]
    assert "昨天的" in (tmp_path / "2026-09-16.log").read_text(encoding="utf-8")
    assert "今天的" in (tmp_path / "2026-09-17.log").read_text(encoding="utf-8")


def test_same_day_reuses_the_handle(tmp_path):
    """同一天里不能每条日志都开关一次文件——句柄要缓存。"""
    h = _handler(tmp_path)
    _write(h, "第一条", "2026-09-17 10:00")
    first = h._stream
    _write(h, "第二条", "2026-09-17 11:00")

    assert h._stream is first
    assert "第二条" in (tmp_path / "2026-09-17.log").read_text(encoding="utf-8")


def test_switches_handle_on_new_day(tmp_path):
    h = _handler(tmp_path)
    _write(h, "昨天", "2026-09-16 10:00")
    first = h._stream
    _write(h, "今天", "2026-09-17 10:00")

    assert h._stream is not first


def test_close_releases_the_handle(tmp_path):
    h = _handler(tmp_path)
    _write(h, "一条", "2026-09-17 10:00")
    h.close()
    assert h._stream is None


def test_write_failure_is_swallowed(tmp_path, monkeypatch):
    """写失败不能抛——日志是附属品，不该拖垮服务。"""
    h = _handler(tmp_path)
    monkeypatch.setattr(
        "pathlib.Path.open",
        lambda *a, **k: (_ for _ in ()).throw(OSError("磁盘满了")),
    )
    _write(h, "写不进去", "2026-09-17 10:00")          # 不抛


def test_day_path(tmp_path):
    assert day_path(tmp_path, "2026-09-17") == tmp_path / "2026-09-17.log"


def test_prune_removes_old_files(tmp_path):
    for day in ("2026-06-01", "2026-09-16", "2026-09-17"):
        (tmp_path / f"{day}.log").write_text("x", encoding="utf-8")

    removed = prune(tmp_path, keep_days=90, now=datetime(2026, 9, 17, 12, 0))

    assert removed == 1
    assert list_days(tmp_path) == ["2026-09-17", "2026-09-16"]


def test_prune_missing_dir(tmp_path):
    """目录不存在时返回 0，不抛。"""
    assert prune(tmp_path / "不存在", keep_days=90) == 0


def test_setup_logging_is_idempotent(tmp_path, monkeypatch):
    """重复调用不叠加 handler——服务重启、测试里多次调用都会碰到。"""
    monkeypatch.setattr("kb.logging_setup.LOG_DIR", tmp_path)
    root = logging.getLogger()

    from kb.logging_setup import setup_logging

    setup_logging()
    setup_logging()

    assert sum(isinstance(h, DailyFileHandler) for h in root.handlers) == 1
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_logging_setup.py -v
```

**Expected:** 收集期 `ImportError: cannot import name 'DailyFileHandler' from 'kb.logging_setup'`

- [ ] **Step 3: 改实现**

`src/kb/logging_setup.py` 整份替换：

```python
"""运行日志（Q51）。

`data/logs/kb/YYYY-MM-DD.log`，标准 Python logging，默认 INFO、可配 DEBUG。
**按天分文件**——这是「箱子」的落盘形态，见设计文档第三节。

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
from datetime import datetime, timedelta
from pathlib import Path

from kb.config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "data" / "logs" / "kb"

# 按天文件保留多久（天）。服务启动时清理更早的。
KEEP_DAYS = 90

_DAY_FMT = "%Y-%m-%d"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def day_path(directory: Path, day: str) -> Path:
    return directory / f"{day}.log"


def list_days(directory: Path) -> list[str]:
    """有日志的日期，**倒序**。目录不存在返回空列表。"""
    if not directory.is_dir():
        return []
    return sorted((p.stem for p in directory.glob("*.log")), reverse=True)


def prune(directory: Path, keep_days: int = KEEP_DAYS, now: datetime | None = None) -> int:
    """删掉超过 `keep_days` 的按天文件，返回删了几个。"""
    now = now or datetime.now()
    cutoff = (now - timedelta(days=keep_days)).strftime(_DAY_FMT)
    removed = 0
    if not directory.is_dir():
        return 0
    for p in directory.glob("*.log"):
        if p.stem < cutoff:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


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
            day = f"{now:{_DAY_FMT}}"
            if day != self._day:
                self._swap(day)
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except OSError:
            # 磁盘满、没权限、路径没了——**只吞掉，不能往上抛**：
            # 日志是附属品，不该拖垮服务。
            self.handleError(record)

    def _swap(self, day: str) -> None:
        self._close()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._stream = day_path(self.directory, day).open("a", encoding="utf-8")
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
            return day_path(LOG_DIR, f"{datetime.now():{_DAY_FMT}}")

    handler = DailyFileHandler(LOG_DIR)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    return day_path(LOG_DIR, f"{datetime.now():{_DAY_FMT}}")
```

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_logging_setup.py -v
```

**Expected:** 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/kb/logging_setup.py tests/test_logging_setup.py
git commit -m "refactor: 运行日志按天落盘，不用 TimedRotatingFileHandler"
```

---

## Task 3: Web 数据层的按天接口

**Files:**
- Modify: `src/kb/web/data.py`
- Modify: `tests/web/test_data.py`

- [ ] **Step 1: 改测试**

`tests/web/test_data.py` 里 `read_journals` / `tail_log` 相关的用例要换掉。先看现状：

```bash
grep -n "read_journals\|tail_log" tests/web/test_data.py
```

把命中的用例删掉，换成下面这组（追加到文件末尾即可）：

```python
from kb.web.data import (
    box_label,
    journal_days,
    read_journal,
    read_runtime,
    runtime_days,
)


def test_journal_days_newest_first(tmp_path):
    d = tmp_path / "_索引" / "整理日志"
    d.mkdir(parents=True)
    for day in ("2026-09-15", "2026-09-17", "2026-09-16"):
        (d / f"{day}.md").write_text("## 10:00 整理 1 条草稿\n\n- 新建：[[x]]\n",
                                     encoding="utf-8")
    assert journal_days(tmp_path) == ["2026-09-17", "2026-09-16", "2026-09-15"]


def test_journal_days_missing_dir(tmp_path):
    assert journal_days(tmp_path) == []


def test_journal_days_skips_empty_files(tmp_path):
    """只有 frontmatter、一个小节都没有的日志不算一天——别列出个空箱子。"""
    d = tmp_path / "_索引" / "整理日志"
    d.mkdir(parents=True)
    (d / "2026-09-15.md").write_text(
        "---\n更新: '2026-09-15'\n---\n\n# 整理日志 2026-09-15\n", encoding="utf-8"
    )
    (d / "2026-09-16.md").write_text(
        "## 10:00 整理 1 条草稿\n\n- 新建：[[x]]\n", encoding="utf-8"
    )
    assert journal_days(tmp_path) == ["2026-09-16"]


def test_read_journal_one_day(tmp_path):
    d = tmp_path / "_索引" / "整理日志"
    d.mkdir(parents=True)
    (d / "2026-09-16.md").write_text(
        "## 23:20 整理 1 条草稿\n\n- 新建：[[A]]\n", encoding="utf-8"
    )
    (d / "2026-09-17.md").write_text(
        "## 09:27 整理 2 条草稿\n\n- 新建：[[B]]\n- 待归类：说不清\n", encoding="utf-8"
    )

    sections = read_journal(tmp_path, "2026-09-17")
    assert sections == [("09:27 整理 2 条草稿", ["新建：[[B]]", "待归类：说不清"])]


def test_read_journal_unknown_day(tmp_path):
    """指向没有日志的一天 → 空列表，不抛。"""
    assert read_journal(tmp_path, "2026-01-01") == []


def test_runtime_days_and_read(tmp_path):
    d = tmp_path / "kb"
    d.mkdir(parents=True)
    (d / "2026-09-16.log").write_text("昨天的\n", encoding="utf-8")
    (d / "2026-09-17.log").write_text("第一行\n第二行\n", encoding="utf-8")

    assert runtime_days(d) == ["2026-09-17", "2026-09-16"]
    assert read_runtime(d, "2026-09-17") == "第一行\n第二行"


def test_read_runtime_unknown_day(tmp_path):
    assert read_runtime(tmp_path, "2026-01-01") == ""


def test_box_label():
    """箱子名只是界面叫法——`2026-09-17` → `26_9_17箱子`。"""
    assert box_label("2026-09-17") == "26_9_17箱子"
    assert box_label("2026-10-01") == "26_10_1箱子"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web/test_data.py -v
```

**Expected:** 收集期 `ImportError: cannot import name 'box_label'`

- [ ] **Step 3: 改实现**

`src/kb/web/data.py` 里 `read_journals`（第 52-64 行）与 `tail_log`（第 113-118 行）整段替换成：

```python
def read_journal(vault_root: Path, day: str) -> list[Section]:
    """读某一天的整理日志。没有这一天返回空列表（不抛）。"""
    path = vault_root / INDEX / JOURNAL_DIR / f"{day}.md"
    if not path.is_file():
        return []
    return parse_journal(path.read_text(encoding="utf-8"))


def journal_days(vault_root: Path) -> list[str]:
    """有内容的整理日志日期，**倒序**。

    **空的不算一天**——只写了 frontmatter、一个小节都没有的文件不该在
    箱子列表里占一格（那会是个点进去什么都没有的空箱子）。
    """
    directory = vault_root / INDEX / JOURNAL_DIR
    if not directory.is_dir():
        return []

    out: list[str] = []
    for path in sorted(directory.glob("*.md"), reverse=True):
        if parse_journal(path.read_text(encoding="utf-8")):
            out.append(path.stem)
    return out


def runtime_days(directory: Path) -> list[str]:
    """有运行日志的日期，**倒序**。目录不存在返回空列表。"""
    if not directory.is_dir():
        return []
    return sorted((p.stem for p in directory.glob("*.log")), reverse=True)


def read_runtime(directory: Path, day: str) -> str:
    """读某一天的运行日志。没有这一天返回空串（不抛）。"""
    path = directory / f"{day}.log"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def box_label(day: str) -> str:
    """`2026-09-17` → `26_9_17箱子`。

    **只是界面上的叫法**——落盘的文件名还是各自的 `2026-09-17.*`
    （整理日志是 vault 里的笔记，文件名跟标题一致是现有约定）。
    """
    year, month, day_of_month = day.split("-")
    return f"{year[2:]}_{int(month)}_{int(day_of_month)}箱子"
```

同时在文件头加 `from datetime import datetime` 之外不需要的新 import——`Path` 已有。

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web/test_data.py -v
```

**Expected:** 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/kb/web/data.py tests/web/test_data.py
git commit -m "refactor: Web 数据层改成按天读，删掉 read_journals/tail_log"
```

---

## Task 4: 一次性迁移脚本

**Files:**
- Create: `scripts/migrate_logs.py`
- Create: `tests/test_migrate_logs.py`

- [ ] **Step 1: 写失败的测试**

新建 `tests/test_migrate_logs.py`：

```python
"""旧日志文件 → 按天目录。跑完即弃的一次性迁移。"""

import json

from scripts.migrate_logs import migrate_flow, migrate_runtime


def test_migrate_flow_moves_whole_file(tmp_path):
    """flow.jsonl 里全是同一天 → 整份搬过去。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    rows = [
        {"at": "2026-09-17 10:00:00", "run": "r1", "step": "投递", "text": "a"},
        {"at": "2026-09-17 10:01:00", "run": "r1", "step": "规划", "text": "b"},
    ]
    (logs / "flow.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )

    migrate_flow(logs)

    assert not (logs / "flow.jsonl").exists()
    out = logs / "flow" / "2026-09-17.jsonl"
    assert out.is_file()
    assert [json.loads(x)["text"] for x in out.read_text(encoding="utf-8").splitlines()] == ["a", "b"]


def test_migrate_flow_splits_across_days(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    rows = [
        {"at": "2026-09-16 23:59:00", "run": "r1", "step": "投递", "text": "昨天的"},
        {"at": "2026-09-17 00:01:00", "run": "r1", "step": "规划", "text": "今天的"},
    ]
    (logs / "flow.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )

    migrate_flow(logs)

    assert (logs / "flow" / "2026-09-16.jsonl").is_file()
    assert (logs / "flow" / "2026-09-17.jsonl").is_file()


def test_migrate_flow_noop_when_absent(tmp_path):
    """旧文件不在 → 什么都不做，不抛。"""
    migrate_flow(tmp_path)


def test_migrate_flow_skips_broken_lines(tmp_path):
    """坏行跳过，别让整份迁移挂掉。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    good = {"at": "2026-09-17 10:00:00", "run": "r", "step": "投递", "text": "好的"}
    (logs / "flow.jsonl").write_text(
        json.dumps(good, ensure_ascii=False) + "\n" + '{"at": "2026-09-1\n',
        encoding="utf-8",
    )

    migrate_flow(logs)

    out = logs / "flow" / "2026-09-17.jsonl"
    assert [json.loads(x)["text"] for x in out.read_text(encoding="utf-8").splitlines()] == ["好的"]


def test_migrate_runtime_splits_by_line_timestamp(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "kb.log").write_text(
        "2026-09-16 23:59:59,000 INFO    kb.push: 昨天的\n"
        "2026-09-17 00:00:01,000 INFO    kb.push: 今天的\n"
        "没有时间戳的半行\n",
        encoding="utf-8",
    )

    migrate_runtime(logs)

    assert not (logs / "kb.log").exists()
    assert (logs / "kb" / "2026-09-16.log").read_text(encoding="utf-8").strip().endswith("昨天的")
    today = (logs / "kb" / "2026-09-17.log").read_text(encoding="utf-8")
    assert "今天的" in today
    assert "没有时间戳的半行" in today          # 认不出日期的归到**最后一行所在的那天**


def test_migrate_runtime_noop_when_absent(tmp_path):
    migrate_runtime(tmp_path)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_migrate_logs.py -v
```

**Expected:** 收集期 `ModuleNotFoundError: No module named 'scripts.migrate_logs'`

- [ ] **Step 3: 写实现**

新建 `scripts/migrate_logs.py`：

```python
"""把旧的单文件日志拆进按天目录。**跑完即弃的一次性脚本。**

旧格式（`logs/flow.jsonl`、`logs/kb.log`）只会出现这一次，所以不留常驻逻辑。

用法：

    python scripts/migrate_logs.py            # 默认 data/logs
    python scripts/migrate_logs.py <目录>

迁完会打印每个文件落到了哪，**确认对得上再删旧的**——脚本自己会删，但
先 dry-run 看一眼更稳：

    python scripts/migrate_logs.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_DAY_FMT = "%Y-%m-%d"
# 运行日志行首形如 `2026-09-17 10:00:00,123`
_STAMP_LEN = 10


def migrate_flow(logs: Path, dry_run: bool = False) -> dict[str, int]:
    """`flow.jsonl` → `flow/YYYY-MM-DD.jsonl`（按记录里的 `at` 分）。

    返回 `{日期: 条数}`。
    """
    old = logs / "flow.jsonl"
    if not old.is_file():
        return {}

    buckets: dict[str, list[str]] = {}
    for line in old.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            day = str(row["at"])[:_STAMP_LEN]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue          # 坏行走掉，别让整份迁移挂掉
        buckets.setdefault(day, []).append(line)

    out_dir = logs / "flow"
    for day, lines in buckets.items():
        target = out_dir / f"{day}.jsonl"
        print(f"  flow: {len(lines):>5} 条 → {target}")
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")

    if not dry_run:
        old.unlink()
    return {day: len(lines) for day, lines in buckets.items()}


def migrate_runtime(logs: Path, dry_run: bool = False) -> dict[str, int]:
    """`kb.log` → `kb/YYYY-MM-DD.log`（按**行首时间戳**分）。

    **认不出日期的行归到「上一行所在的那天」**——运行日志是多行一条的
    （traceback 的后续行就没有时间戳），按行独立判断会把它们拆散。
    """
    old = logs / "kb.log"
    if not old.is_file():
        return {}

    buckets: dict[str, list[str]] = {}
    current: str | None = None
    for line in old.read_text(encoding="utf-8", errors="replace").splitlines():
        stamp = line[:_STAMP_LEN]
        if len(stamp) == _STAMP_LEN and stamp[4] == "-" and stamp[7] == "-":
            current = stamp
        if current is not None:
            buckets.setdefault(current, []).append(line)
        # 第一行就没有时间戳 → 没有可以归的日子，丢掉（它是残缺的）

    out_dir = logs / "kb"
    for day, lines in buckets.items():
        target = out_dir / f"{day}.log"
        print(f"  kb:   {len(lines):>5} 行 → {target}")
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")

    if not dry_run:
        old.unlink()
    return {day: len(lines) for day, lines in buckets.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="拆分旧的单文件日志")
    parser.add_argument("logs", nargs="?", default=None, help="日志目录，默认 data/logs")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不动文件")
    args = parser.parse_args()

    if args.logs:
        logs = Path(args.logs)
    else:
        from kb.config import PROJECT_ROOT
        logs = PROJECT_ROOT / "data" / "logs"

    if not logs.is_dir():
        print(f"目录不存在：{logs}")
        return

    print(f"在 {logs} 里找旧文件：")
    flow = migrate_flow(logs, args.dry_run)
    runtime = migrate_runtime(logs, args.dry_run)
    if not flow and not runtime:
        print("  没找到 flow.jsonl 或 kb.log —— 可能已经迁过了。")
    elif args.dry_run:
        print("（dry-run：什么都没动）")


if __name__ == "__main__":
    main()
```

> **注意 `_STAMP_LEN` 那个判断。** 用「第 5、8 位是 `-`」认时间戳，而不是
> 正则匹配整个日期——运行日志里时间戳后跟的是毫秒和级别，格式会变，但
> 前 10 位的位置是稳的。

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_migrate_logs.py -v
```

**Expected:** 全 PASS

- [ ] **Step 5: 对真实数据 dry-run 一次**

```bash
"D:/Conda_base/envs/kn_base/python.exe" scripts/migrate_logs.py --dry-run
```

**Expected:** 打印 `flow: 640 条 → ...\flow\2026-09-17.jsonl` 与 `kb: 65 行 → ...` 两行以上，**不修改任何文件**。核对条数与本文档第三节表格里的一致（flow 640 条、kb 65 行）。

- [ ] **Step 6: 真迁**

```bash
"D:/Conda_base/envs/kn_base/python.exe" scripts/migrate_logs.py
ls "data/logs/flow" "data/logs/kb"
```

**Expected:** `data/logs/flow/2026-09-17.jsonl`、`data/logs/kb/2026-09-16.log`、`data/logs/kb/2026-09-17.log` 三个文件在；旧的 `flow.jsonl` 与 `kb.log` 已消失。

- [ ] **Step 7: 提交**

```bash
git add scripts/migrate_logs.py tests/test_migrate_logs.py
git commit -m "feat: 旧日志拆分脚本（跑完即弃）"
```

> **`data/` 不入库**，所以 Step 6 产生的东西不会进 commit——这是对的。

---

## Task 5: 服务启动时清理过期日志

**Files:**
- Modify: `src/kb/api/http.py:448-480`（`main()` 里，`create_app` 之后）
- Modify: `src/kb/web/router.py`（导入改成新的数据接口）
- Modify: `tests/web/test_router.py`（跟着改）

- [ ] **Step 1: 改路由的导入与三个日志页**

`src/kb/web/router.py`：

第 26 行 `from kb.core.flow import STEPS, read_flow` 改成：

```python
from kb.core.flow import STEPS, latest_run_rows
```

第 29-30 行改成：

```python
from kb.logging_setup import LOG_DIR
from kb.web.data import (
    group_flow,
    journal_days,
    load_push_templates,
    read_journal,
    read_runtime,
    runtime_days,
)
```

`/journal` 端点（第 105-109 行）替换：

```python
    @router.get("/journal", response_class=HTMLResponse)
    def journal(request: Request, d: str = ""):
        days = journal_days(cfg.vault_path)
        day = d if d in days else (days[0] if days else "")
        return templates.TemplateResponse(
            request,
            "journal.html",
            _ctx(
                "journal",
                days=days,
                day=day,
                sections=read_journal(cfg.vault_path, day) if day else [],
                latest=latest_run_rows(data_dir),
            ),
        )
```

`/flow` 端点（第 111-125 行）替换：

```python
    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request, d: str = ""):
        days = flow_days(data_dir)
        day = d if d in days else (days[0] if days else "")
        return templates.TemplateResponse(
            request,
            "flow.html",
            _ctx(
                "flow",
                days=days,
                day=day,
                groups=group_flow(read_flow_day(data_dir, day), steps=STEPS),
                steps=STEPS,
                latest=latest_run_rows(data_dir),
            ),
        )
```

`/runtime` 端点（第 168-179 行）替换：

```python
    @router.get("/runtime", response_class=HTMLResponse)
    def runtime_page(request: Request, d: str = ""):
        days = runtime_days(LOG_DIR)
        day = d if d in days else (days[0] if days else "")
        return templates.TemplateResponse(
            request,
            "runtime.html",
            _ctx(
                "runtime",
                log_dir=str(LOG_DIR),
                days=days,
                day=day,
                log_text=read_runtime(LOG_DIR, day) if day else "",
            ),
        )
```

在 imports 里补上 `flow_days` / `read_flow_day` —— 它们来自 `kb.core.flow`：

```python
from kb.core.flow import STEPS, latest_run_rows, list_days as flow_days, read_day as read_flow_day
```

- [ ] **Step 2: 跑测试，看哪些挂了**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web -v
```

**Expected:** 会有失败——模板还引用着旧变量（`days` 的形状从 `[(日期, 小节)]` 变成了 `[日期]`）。**Task 6/7 会改模板，本 Task 先只保证路由层不报 ImportError。**

- [ ] **Step 3: 改 `main()`，启动时清理**

`src/kb/api/http.py` 的 `main()` 里，`app = create_app(cfg)` 那行**之前**插入：

```python
    # 清理过期的按天日志（流程 90 天、运行 90 天）。
    # **放启动时**：它是一次目录扫描，不该压在请求路径上。
    # vault 里的整理日志是知识，**永不自动删**——这里只碰 data/logs/。
    removed = flow.prune(DATA_DIR) + logging_setup.prune(LOG_DIR)
    if removed:
        logging.getLogger(__name__).info("清理了 %d 个过期日志文件", removed)
```

并把 `from kb.logging_setup import setup_logging` 改成：

```python
from kb.logging_setup import LOG_DIR, setup_logging
```

以及 `from kb.core import flow, organize, sweep, sweep_state` 保持不变（`flow` 已在）。

- [ ] **Step 4: 跑全量测试**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
```

**Expected:** 只剩模板相关的失败（Task 6/7 处理）。**`tests/api/` 与 `tests/core/` 应当全绿。**

- [ ] **Step 5: 提交**

```bash
git add src/kb/api/http.py src/kb/web/router.py
git commit -m "feat: 服务启动时清理过期日志；路由改按天取数"
```

---

## Task 6: 文档同步

**Files:**
- Modify: `docs/01_架构.md`（第十节日志、第十一节接口）

- [ ] **Step 1: 改第十节**

`docs/01_架构.md` 第十节「日志」，把「按天聚合」那句下的三行列表替换：

```markdown
- **整理日志**：`_索引/整理日志/YYYY-MM-DD.md`，**按天聚合**，每次整理往当天那篇追加一节。**失败也记**——只记成功的话，回头看会不知道当时为什么有东西卡在收件箱
- **流程日志**：`data/logs/flow/YYYY-MM-DD.jsonl`，**按天分文件**，记每一个流转
- **运行日志**：`data/logs/kb/YYYY-MM-DD.log`，标准 Python logging，**按天分文件**
```

并在节末补一段：

```markdown
**三个日志的落盘形态都是「一天一个文件」**——这就是 Web UI 上「箱子」的本体。
日期取**写入时刻**，不是记录里的字段；写入与落点必须是同一个判断，否则
跨午夜那一秒会写串。

**服务侧日志保留 90 天**（`flow.KEEP_DAYS` / `logging_setup.KEEP_DAYS`），
服务启动时清理更早的。**vault 里的整理日志永不自动删**——它是知识。

**运行日志不用 `TimedRotatingFileHandler`**：标准库那个靠文件的 mtime 判断
该不该轮转，服务重启跨天时会把昨天的内容写进今天的文件。自己写的
`DailyFileHandler` 按写入时刻选文件，跟流程日志一个判断方式。
```

- [ ] **Step 2: 改第十一节**

`docs/01_架构.md` 第十一节「接口与工程」，在接口表下面补一行说明本计划动了哪些路径（三个日志页的 `?d=` 参数与 `/sweep` 页是下一份计划的事，这里只提存储）：

```markdown
> **2026-09-17：日志落点改成按天。** `data/logs/flow.jsonl` → `data/logs/flow/YYYY-MM-DD.jsonl`；
> `data/logs/kb.log` → `data/logs/kb/YYYY-MM-DD.log`。旧文件已由
> `scripts/migrate_logs.py` 拆过去。
```

- [ ] **Step 3: 跑风格检查**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**Expected:** `All checks passed!`

- [ ] **Step 4: 提交**

```bash
git add docs/01_架构.md
git commit -m "docs: 日志落点改成按天"
```

---

## Self-Review

**1. 规格覆盖：** 设计文档第三节（数据落盘）的每一条都对应到任务了——流程日志按天（Task 1）、运行日志按天（Task 2）、数据层按天接口（Task 3）、一次性迁移（Task 4）、保留策略与启动清理（Task 5）、文档同步（Task 6）。设计第四节之后是 UI，属第二份计划。

**2. 占位符扫描：** 无 TBD / TODO / 「类似 Task N」/ 无代码的代码步骤。

**3. 类型一致性：**
- `flow.emit(step, text, now=None)` —— `now` 是关键字参数，调用处不传
- `flow.list_days(data_dir) -> list[str]` / `flow.read_day(data_dir, day) -> list[dict]`
- `logging_setup.DailyFileHandler(directory)` / `.emit(record, now=None)`
- `data.journal_days(vault_root) -> list[str]` / `data.read_journal(vault_root, day) -> list[Section]`
- `data.runtime_days(directory) -> list[str]` / `data.read_runtime(directory, day) -> str`
- `data.box_label(day) -> str`
- 路由里 `flow_days = flow.list_days`、`read_flow_day = flow.read_day`（别名，避免和现有 `flow` 端点函数名撞）

**4. 已知的中间态：** Task 5 结束时模板还是旧的，`tests/web` 会有失败。**这是刻意的**——模板改造要动变量形状，跟路由一起改会让 diff 说不清。Task 5 的提交点是「路由层能起来」，模板在第二份计划里换。

**5. 一处待确认：** 运行日志页现在显示 `log_path`（单个文件路径），改成目录后模板变量是 `log_dir`。第二份计划改模板时要跟上。

---

## 收尾

跑完 Task 6 后：

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**`tests/core/`、`tests/api/`、`tests/web/test_data.py` 必须全绿。** `tests/web/test_router.py` 里跟日志页渲染有关的用例会红——那是第二份计划的活。**下一步是另一份计划：`2026-09-17-log-boxes-ui.md`。**
