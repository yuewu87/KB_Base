"""Web UI 的数据聚合：把文件变成页面能直接渲染的结构。"""

from kb.web.data import group_flow, parse_journal, read_journals, tail_log

JOURNAL = """---
更新: '2026-09-16'
类型: 日志
---

# 整理日志 2026-09-16

## 23:20 整理 6 条草稿

- 新建：[[a]]（计算机/a.md）
- 新建：[[b]]（计算机/b.md）

## 23:21 整理 1 条草稿

- 合并：[[c]]（计算机/c.md）
"""


def test_parse_journal_splits_into_sections():
    got = parse_journal(JOURNAL)
    assert len(got) == 2
    assert got[0][0] == "23:20 整理 6 条草稿"
    assert got[0][1] == ["新建：[[a]]（计算机/a.md）", "新建：[[b]]（计算机/b.md）"]
    assert got[1][0] == "23:21 整理 1 条草稿"
    assert got[1][1] == ["合并：[[c]]（计算机/c.md）"]


def test_parse_journal_ignores_frontmatter_and_title():
    got = parse_journal(JOURNAL)
    assert all("更新" not in title for title, _ in got)
    assert all("整理日志 2026" not in title for title, _ in got)


def test_parse_journal_empty():
    assert parse_journal("") == []


def test_read_journals_newest_first(tmp_path):
    d = tmp_path / "_索引" / "整理日志"
    d.mkdir(parents=True)
    (d / "2026-09-15.md").write_text(
        "## 10:00 整理 1 条草稿\n\n- 新建：[[旧]]\n", encoding="utf-8"
    )
    (d / "2026-09-16.md").write_text(
        "## 10:00 整理 1 条草稿\n\n- 新建：[[新]]\n", encoding="utf-8"
    )
    got = read_journals(tmp_path)
    assert [date for date, _ in got] == ["2026-09-16", "2026-09-15"]
    assert got[0][1][0][1] == ["新建：[[新]]"]


def test_read_journals_empty_when_absent(tmp_path):
    assert read_journals(tmp_path) == []


def test_tail_log_returns_last_lines(tmp_path):
    p = tmp_path / "kb.log"
    p.write_text("\n".join(f"line{i}" for i in range(10)), encoding="utf-8")
    assert tail_log(p, 3) == "line7\nline8\nline9"


def test_tail_log_missing_file_is_empty(tmp_path):
    assert tail_log(tmp_path / "没有.log", 10) == ""


def test_tail_log_fewer_lines_than_asked(tmp_path):
    p = tmp_path / "kb.log"
    p.write_text("只有一行", encoding="utf-8")
    assert tail_log(p, 10) == "只有一行"


def test_group_flow_by_run():
    rows = [
        {"run": "a", "step": "投递", "text": "投了", "at": "t1"},
        {"run": "a", "step": "规划", "text": "规划了", "at": "t2"},
        {"run": "b", "step": "投递", "text": "又投了", "at": "t3"},
    ]
    got = group_flow(rows)
    assert [g["run"] for g in got] == ["b", "a"]        # 新的在前
    assert [r["step"] for r in got[1]["rows"]] == ["投递", "规划"]


def test_group_flow_marks_reached_steps():
    rows = [
        {"run": "a", "step": "投递", "text": "x", "at": "t"},
        {"run": "a", "step": "落盘", "text": "y", "at": "t"},
    ]
    got = group_flow(rows)
    assert got[0]["reached"] == {"投递", "落盘"}


def test_group_flow_splits_three_states():
    """走过 / 跳过 / 没走到，是三回事。

    中间没出现的步骤，要看**它后面有没有记录**：
    后面有 → 流程越过了它，是「跳过」（比如审核没触发）
    后面没有 → 流程停在那里了，是「没走到」
    """
    rows = [
        {"run": "a", "step": "投递", "text": "t", "at": "t"},
        {"run": "a", "step": "规划", "text": "t", "at": "t"},
        {"run": "a", "step": "落盘", "text": "t", "at": "t"},
    ]
    g = group_flow(rows, steps=["投递", "规划", "校验", "审核", "落盘", "提交"])[0]
    assert g["reached"] == {"投递", "规划", "落盘"}
    assert g["skipped"] == {"校验", "审核"}      # 越过了
    assert g["todo"] == {"提交"}                 # 停在落盘之后


def test_group_flow_last_record_failure_leaves_rest_todo():
    """流程停在「规划」——后面全是没走到，不是跳过。"""
    rows = [
        {"run": "a", "step": "投递", "text": "t", "at": "t"},
        {"run": "a", "step": "规划", "text": "t", "at": "t"},
    ]
    g = group_flow(rows, steps=["投递", "规划", "校验", "审核", "落盘", "提交"])[0]
    assert g["skipped"] == set()
    assert g["todo"] == {"校验", "审核", "落盘", "提交"}


def test_group_flow_without_steps_keeps_old_shape():
    """不传 steps 时不算三态——向后兼容，老的调用点不炸。"""
    rows = [{"run": "a", "step": "投递", "text": "t", "at": "t"}]
    g = group_flow(rows)[0]
    assert g["reached"] == {"投递"}
