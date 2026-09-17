"""巡检的状态：上次什么时候跑的、报告读没读。"""

from datetime import datetime, timedelta

from kb.core.sweep_state import (
    SWEEP_INTERVAL,
    due,
    load_state,
    mark_read,
    save_report,
)


def test_missing_state_means_due(tmp_path):
    """从没跑过 —— 该跑。"""
    assert due(tmp_path) is True


def test_recent_sweep_not_due(tmp_path):
    save_report(tmp_path, {"summary": "x"}, when=datetime(2026, 9, 17, 10, 0))
    assert due(tmp_path, now=datetime(2026, 9, 20, 10, 0)) is False


def test_old_sweep_is_due(tmp_path):
    save_report(tmp_path, {"summary": "x"}, when=datetime(2026, 9, 1, 10, 0))
    assert due(tmp_path, now=datetime(2026, 9, 17, 10, 0)) is True


def test_boundary_is_six_days(tmp_path):
    """刚好 6 天不算超——超过才跑。"""
    base = datetime(2026, 9, 1, 10, 0)
    save_report(tmp_path, {"summary": "x"}, when=base)
    assert due(tmp_path, now=base + timedelta(days=6)) is False
    assert due(tmp_path, now=base + timedelta(days=7)) is True
    assert SWEEP_INTERVAL.days == 6


def test_report_starts_unread(tmp_path):
    save_report(tmp_path, {"summary": "合并了 2 组标签"})
    state = load_state(tmp_path)
    assert state["report"]["summary"] == "合并了 2 组标签"
    assert state["report"]["read"] is False


def test_mark_read(tmp_path):
    save_report(tmp_path, {"summary": "x"})
    mark_read(tmp_path)
    assert load_state(tmp_path)["report"]["read"] is True


def test_state_file_lives_under_data(tmp_path):
    save_report(tmp_path, {"summary": "x"})
    assert (tmp_path / "state.json").is_file()


def test_corrupt_state_treated_as_never_run(tmp_path):
    """文件坏了当作没跑过——宁可多跑一次，也不要永远不跑。"""
    (tmp_path / "state.json").write_text("{ 坏掉的", encoding="utf-8")
    assert due(tmp_path) is True
    assert load_state(tmp_path) == {}
