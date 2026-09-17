"""按天文件——三个日志落点共用的那一层。"""

from datetime import datetime

import pytest

from kb.core import daybox


@pytest.mark.parametrize("good", ["2026-09-17", "2026-01-01", "1999-12-31"])
def test_is_day_accepts_real_dates(good):
    assert daybox.is_day(good)


@pytest.mark.parametrize(
    "bad",
    ["模板", "backup", "", "2026-9-17", "20260917", "../x", "2026-09-17.jsonl"],
)
def test_is_day_rejects_everything_else(bad):
    """不认形状的一律不是一天——**这正是路径穿越与拆包崩溃的闸门**。"""
    assert not daybox.is_day(bad)


def test_day_file_rejects_bad_day(tmp_path):
    """`day` 可能是 `?d=` 传上来的——直接拼路径就是任意文件读。"""
    assert daybox.day_file(tmp_path, "../../secret", ".jsonl") is None
    assert daybox.day_file(tmp_path, "模板", ".md") is None


def test_day_file_joins(tmp_path):
    assert daybox.day_file(tmp_path, "2026-09-17", ".log") == tmp_path / "2026-09-17.log"


def test_list_days_newest_first(tmp_path):
    for day in ("2026-09-15", "2026-09-17", "2026-09-16"):
        (tmp_path / f"{day}.jsonl").write_text("x", encoding="utf-8")
    assert daybox.list_days(tmp_path, ".jsonl") == [
        "2026-09-17", "2026-09-16", "2026-09-15",
    ]


def test_list_days_ignores_other_names(tmp_path):
    """`backup.jsonl` 按字符串排序会排到 `2026-...` **前面**（`'b' > '2'`），
    于是被当成「最新一天」——这正是不筛形状的后果。"""
    (tmp_path / "2026-09-17.jsonl").write_text("x", encoding="utf-8")
    (tmp_path / "backup.jsonl").write_text("x", encoding="utf-8")
    (tmp_path / "模板.md").write_text("x", encoding="utf-8")

    assert daybox.list_days(tmp_path, ".jsonl") == ["2026-09-17"]


def test_list_days_missing_dir(tmp_path):
    assert daybox.list_days(tmp_path / "不存在", ".jsonl") == []


def test_prune_removes_old_days_only(tmp_path):
    for day in ("2026-06-01", "2026-09-16", "2026-09-17"):
        (tmp_path / f"{day}.jsonl").write_text("x", encoding="utf-8")
    (tmp_path / "backup.jsonl").write_text("x", encoding="utf-8")

    removed = daybox.prune(tmp_path, ".jsonl", keep_days=90, now=datetime(2026, 9, 17, 12))

    assert removed == 1
    assert (tmp_path / "backup.jsonl").is_file()          # 不认识的不动
    assert daybox.list_days(tmp_path, ".jsonl") == ["2026-09-17", "2026-09-16"]


def test_prune_missing_dir(tmp_path):
    """目录不存在返回 0，不抛。"""
    assert daybox.prune(tmp_path / "不存在", ".jsonl", keep_days=90) == 0
