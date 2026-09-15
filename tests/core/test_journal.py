from datetime import datetime

from kb.core.journal import append_results, format_entry, journal_dir, journal_path
from kb.core.models import OrganizeResult, ResultKind
from kb.core.vault import INDEX, read_note

WHEN = datetime(2026, 9, 15, 14, 32)


def _result(kind, detail, error=None):
    return OrganizeResult(
        draft_id="20260915-a3f2", kind=kind, detail=detail, error=error
    )


def test_journal_dir_is_under_index(tmp_path):
    assert journal_dir(tmp_path) == tmp_path / INDEX / "整理日志"


def test_journal_path_is_daily(tmp_path):
    assert journal_path(tmp_path, WHEN) == (
        tmp_path / INDEX / "整理日志" / "2026-09-15.md"
    )


def test_empty_results_write_nothing(tmp_path):
    """没干活就不该在日志里留空节。"""
    assert append_results(tmp_path, [], WHEN) is None
    assert not (tmp_path / INDEX).exists()


def test_creates_daily_page_with_frontmatter(tmp_path):
    path = append_results(tmp_path, [_result(ResultKind.CREATED, "并发写锁")], WHEN)
    meta, body = read_note(path)
    assert meta["类型"] == "日志"
    assert "# 整理日志 2026-09-15" in body


def test_entry_carries_time_and_count(tmp_path):
    path = append_results(
        tmp_path,
        [
            _result(ResultKind.CREATED, "并发写锁"),
            _result(ResultKind.FOLDED, "XXX-踩坑"),
        ],
        WHEN,
    )
    _, body = read_note(path)
    assert "## 14:32 整理 2 条草稿" in body


def test_appends_second_run_to_same_day_file(tmp_path):
    """Q50：按天聚合——同一天第二次整理追加，不另建文件。"""
    append_results(tmp_path, [_result(ResultKind.CREATED, "第一条")], WHEN)
    path = append_results(
        tmp_path, [_result(ResultKind.CREATED, "第二条")], WHEN.replace(hour=16)
    )

    files = list((tmp_path / INDEX / "整理日志").glob("*.md"))
    assert len(files) == 1

    _, body = read_note(path)
    assert "第一条" in body and "第二条" in body
    assert "## 14:32" in body and "## 16:32" in body


def test_different_days_go_to_different_files(tmp_path):
    append_results(tmp_path, [_result(ResultKind.CREATED, "周一")], WHEN)
    append_results(
        tmp_path, [_result(ResultKind.CREATED, "周二")], WHEN.replace(day=16)
    )
    names = sorted(p.name for p in (tmp_path / INDEX / "整理日志").glob("*.md"))
    assert names == ["2026-09-15.md", "2026-09-16.md"]


def test_first_run_keeps_title_of_second_run(tmp_path):
    """追加不能把原标题挤掉——用户可能改过它。"""
    append_results(tmp_path, [_result(ResultKind.CREATED, "甲")], WHEN)
    path = append_results(
        tmp_path, [_result(ResultKind.CREATED, "乙")], WHEN.replace(hour=15)
    )
    _, body = read_note(path)
    assert body.count("# 整理日志 2026-09-15") == 1


def test_failures_are_recorded(tmp_path):
    """Q50：失败也记——只记成功的话，回头看不知道当时为什么卡住。"""
    path = append_results(
        tmp_path,
        [_result(ResultKind.FAILED, "格式不合规", error="JSONDecodeError")],
        WHEN,
    )
    _, body = read_note(path)
    assert "失败" in body
    assert "JSONDecodeError" in body


def test_pending_is_recorded(tmp_path):
    path = append_results(
        tmp_path, [_result(ResultKind.PENDING, "无法判断主题")], WHEN
    )
    _, body = read_note(path)
    assert "待归类" in body


def test_update_field_is_set(tmp_path):
    path = append_results(tmp_path, [_result(ResultKind.CREATED, "x")], WHEN)
    meta, _ = read_note(path)
    assert meta["更新"] == "2026-09-15"


def test_format_entry_labels_by_kind():
    assert format_entry(_result(ResultKind.CREATED, "甲")).startswith("- 新建：")
    assert format_entry(_result(ResultKind.FOLDED, "乙")).startswith("- 合并：")
    assert format_entry(_result(ResultKind.PENDING, "丙")).startswith("- 待归类：")
    assert format_entry(_result(ResultKind.FAILED, "丁")).startswith("- 失败：")


def test_format_entry_omits_empty_error():
    """error 为 None 时不该渲染出空括号。"""
    assert format_entry(_result(ResultKind.CREATED, "甲")) == "- 新建：甲"
