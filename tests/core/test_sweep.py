"""巡检：扫标签与目录 → 让 LLM 决定怎么合并。"""

import json

import pytest

from kb.core.sweep import SweepError, collect_tags, list_dir_tree, parse_plan
from kb.core.vault import write_note


def _vault(tmp_path):
    write_note(
        tmp_path / "计算机" / "git" / "a.md",
        {"类型": "概念", "主题": ["计算机", "git"]},
        "x",
    )
    write_note(
        tmp_path / "计算机" / "版本控制" / "b.md",
        {"类型": "概念", "主题": ["计算机", "版本控制"]},
        "y",
    )
    write_note(
        tmp_path / "艺术" / "透视" / "c.md",
        {"类型": "概念", "主题": ["艺术", "透视"]},
        "z",
    )
    return tmp_path


def test_collect_tags_counts_and_sorts(tmp_path):
    got = collect_tags(_vault(tmp_path))
    assert got["计算机"] == 2
    assert got["git"] == 1
    assert list(got) == sorted(got)


def test_list_dir_tree_is_relative(tmp_path):
    got = list_dir_tree(_vault(tmp_path))
    assert "计算机/git" in got
    assert "艺术/透视" in got
    assert "计算机" in got


def test_dir_tree_excludes_meta_dirs(tmp_path):
    v = _vault(tmp_path)
    (v / "_索引").mkdir(exist_ok=True)
    assert not any(d.startswith("_") for d in list_dir_tree(v))


def test_parse_plan_reads_merges():
    raw = json.dumps(
        {
            "tag_merges": [{"from": "git", "to": "版本控制"}],
            "dir_merges": [{"from": "计算机/git", "to": "计算机/版本控制"}],
            "summary": "合并 git 到版本控制",
        },
        ensure_ascii=False,
    )
    plan = parse_plan(raw)
    assert plan.tag_merges == [("git", "版本控制")]
    assert plan.dir_merges == [("计算机/git", "计算机/版本控制")]
    assert plan.summary


def test_parse_plan_tolerates_empty_merges():
    plan = parse_plan('{"tag_merges": [], "dir_merges": []}')
    assert plan.tag_merges == []
    assert plan.is_empty


def test_parse_plan_rejects_bad_json():
    with pytest.raises(SweepError):
        parse_plan("不是 JSON")


def test_parser_rejects_non_list_merges():
    with pytest.raises(SweepError, match="tag_merges"):
        parse_plan('{"tag_merges": {"from": "a"}, "dir_merges": []}')


def test_plan_tells_llm_only_about_tags_and_dirs(tmp_path):
    """提示词里只有标签和目录——**不喂正文**（用户定的边界）。"""
    from kb.core.sweep import build_prompt

    v = _vault(tmp_path)
    prompt = build_prompt(v)
    assert "git" in prompt
    assert "计算机/版本控制" in prompt
    assert "x" not in prompt          # 笔记正文不该出现
