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


def test_read_day_rejects_path_traversal(tmp_path):
    """`day` 可能是 `?d=` 传上来的——直接拼路径就是一次任意文件读。"""
    flow.configure(tmp_path)
    outside = tmp_path.parent / "秘密.jsonl"
    outside.write_text('{"text": "库外的东西"}\n', encoding="utf-8")
    try:
        assert read_day(tmp_path, "../秘密") == []
        assert read_day(tmp_path, "../../x") == []
    finally:
        outside.unlink()


def test_list_days_ignores_non_date_names(tmp_path):
    """`backup.jsonl` 按字符串排序会排到 `2026-...` 前面（`'b' > '2'`），
    被当成最新一天。"""
    flow.configure(tmp_path)
    emit("投递", "a", now=_at("2026-09-17 10:00"))
    (tmp_path / "logs" / "flow" / "backup.jsonl").write_text("x", encoding="utf-8")

    assert list_days(tmp_path) == ["2026-09-17"]


def test_latest_run_rows_skips_a_corrupt_newest_day(tmp_path):
    """最新一天全是坏行时不能整个返回空——前一天明明有完整记录。"""
    flow.configure(tmp_path)
    set_run("run-A")
    emit("投递", "前一天的", now=_at("2026-09-16 10:00"))

    corrupt = tmp_path / "logs" / "flow" / "2026-09-17.jsonl"
    corrupt.write_text('{"text": "断在这\n', encoding="utf-8")

    assert [r["text"] for r in latest_run_rows(tmp_path)] == ["前一天的"]


def test_latest_run_rows_returns_empty_when_nothing_anywhere(tmp_path):
    flow.configure(tmp_path)
    assert latest_run_rows(tmp_path) == []


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
    today = f"{datetime.now():%Y-%m-%d}"

    def worker(i: int) -> None:
        emit("投递", f"第 {i} 条")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(read_day(tmp_path, today)) == 20
