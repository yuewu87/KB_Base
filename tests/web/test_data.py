"""Web UI 的数据聚合：把文件变成页面能直接渲染的结构。"""

from kb.web.data import (
    box_label,
    group_flow,
    journal_days,
    parse_journal,
    read_journal,
    read_runtime,
    runtime_days,
)

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


def test_journal_days_ignores_non_date_files(tmp_path):
    """`模板.md` 是模板不是箱子——放进去不该让 `box_label` 拆包崩掉。"""
    d = tmp_path / "_索引" / "整理日志"
    d.mkdir(parents=True)
    (d / "2026-09-17.md").write_text("## 10:00 整理 1 条草稿\n\n- 新建：[[x]]\n",
                                     encoding="utf-8")
    (d / "模板.md").write_text("## 这是模板\n\n- 占位\n", encoding="utf-8")

    assert journal_days(tmp_path) == ["2026-09-17"]


def test_read_journal_rejects_path_traversal(tmp_path):
    """`day` 来自 `?d=`，不校验就是一次任意文件读。"""
    outside = tmp_path / "库外.md"
    outside.write_text("## 不该读到\n\n- x\n", encoding="utf-8")
    root = tmp_path / "vault"
    root.mkdir()

    assert read_journal(root, "../库外") == []


def test_runtime_days_ignores_non_date_files(tmp_path):
    d = tmp_path / "kb"
    d.mkdir(parents=True)
    (d / "2026-09-17.log").write_text("x\n", encoding="utf-8")
    (d / "backup.log").write_text("x\n", encoding="utf-8")

    assert runtime_days(d) == ["2026-09-17"]


def test_read_runtime_rejects_path_traversal(tmp_path):
    outside = tmp_path / "库外.log"
    outside.write_text("不该读到\n", encoding="utf-8")
    root = tmp_path / "kb"
    root.mkdir()

    assert read_runtime(root, "../库外") == ""


def test_box_label():
    """箱子名只是界面叫法——`2026-09-17` → `26_9_17箱子`。"""
    assert box_label("2026-09-17") == "26_9_17箱子"
    assert box_label("2026-10-01") == "26_10_1箱子"
