"""流程日志：自然语言，一条一个动作（Q89）。存服务侧，不进 vault。"""

import pytest

from kb.core import flow
from kb.core.flow import STEPS, emit, read_flow, set_run


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


def test_emit_writes_jsonl(tmp_path):
    flow.configure(tmp_path)
    emit("投递", "你在网页上投递了一条草稿")

    rows = read_flow(tmp_path)
    assert len(rows) == 1
    assert rows[0]["step"] == "投递"
    assert rows[0]["text"] == "你在网页上投递了一条草稿"
    assert rows[0]["at"]


def test_emit_is_noop_when_not_configured(tmp_path):
    """没配落点就不记——不抛、也不往别处写。"""
    emit("投递", "x")
    assert read_flow(tmp_path) == []


def test_emit_never_raises_on_write_failure(tmp_path, monkeypatch):
    """写日志失败不该让正事挂掉——日志是附属品。"""
    flow.configure(tmp_path)
    monkeypatch.setattr(flow.Path, "open", _boom)

    emit("投递", "x")          # 不抛


def test_set_run_tags_subsequent_entries(tmp_path):
    flow.configure(tmp_path)
    set_run("20260917-1400")
    emit("投递", "a")
    assert read_flow(tmp_path)[0]["run"] == "20260917-1400"


def test_read_flow_missing_file(tmp_path):
    assert read_flow(tmp_path) == []


def test_read_flow_skips_broken_lines(tmp_path):
    """半行（进程被杀）跳过，别让整页挂掉。"""
    flow.configure(tmp_path)
    emit("投递", "好的")
    path = tmp_path / "logs" / "flow.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"step": "规划", "tex')      # 截断的半行

    rows = read_flow(tmp_path)
    assert [r["text"] for r in rows] == ["好的"]


def test_emit_rotates_when_large(tmp_path, monkeypatch):
    """超过上限就轮转一份，别让单文件无限长。"""
    monkeypatch.setattr(flow, "MAX_BYTES", 10)
    flow.configure(tmp_path)
    emit("投递", "第一条够长了")
    emit("投递", "第二条")

    assert (tmp_path / "logs" / "flow.jsonl.1").is_file()
    assert [r["text"] for r in read_flow(tmp_path)] == ["第二条"]


def test_steps_are_the_pipeline_order():
    """链上的顺序就是流水线的顺序——页面的流程图照它画。"""
    assert STEPS == ["投递", "规划", "校验", "审核", "落盘", "提交"]


def test_new_run_id_has_random_suffix():
    """只用秒的话，同一秒内的两次投递会共用同一个 run——
    页面把它们并成一条流程链。实测挤过 41 条记录。"""
    from kb.core.flow import new_run_id

    a, b = new_run_id(), new_run_id()
    assert a != b                     # 同一秒内也不该撞
    assert len(a) == len(b) == 20     # YYYYMMDD(8) + -(1) + HHMMSS(6) + -(1) + xxxx(4)
    assert a[:15] == b[:15]           # 前 15 位是时间，应当一样


def test_run_does_not_leak_across_threads(tmp_path):
    """并发请求各记各的 run。

    FastAPI 的同步端点跑在**线程池**里，两个并发请求是真并行的。run 若是
    模块全局，会被后一个请求覆盖，前一个后续记的流程就挂到别人名下——
    实测两个并发投递，12 条记录被拆成 10/2，串得一塌糊涂。
    """
    import threading
    import time

    flow.configure(tmp_path)

    seen: dict[str, str] = {}

    def worker(name: str) -> None:
        set_run(name)
        time.sleep(0.02)          # 给另一个线程机会去改（全局实现下就会串）
        seen[name] = flow.current_run()

    threads = [
        threading.Thread(target=worker, args=(f"run-{i}",)) for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert seen == {"run-0": "run-0", "run-1": "run-1"}


def test_concurrent_emit_loses_nothing(tmp_path):
    """并发写同一文件不能丢行——实测两个线程同时写只落到一条。"""
    import threading

    flow.configure(tmp_path)

    def worker(i: int) -> None:
        emit("投递", f"第 {i} 条")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(read_flow(tmp_path)) == 20
