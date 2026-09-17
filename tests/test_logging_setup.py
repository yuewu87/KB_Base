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
