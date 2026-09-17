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


def test_validate_rejects_unknown_tag_target(tmp_path):
    from kb.core.sweep import SweepPlan, validate

    plan = SweepPlan(tag_merges=[("git", "根本没这个标签")])
    with pytest.raises(SweepError, match="不存在的标签"):
        validate(plan, _vault(tmp_path))


def test_validate_rejects_unknown_dir_target(tmp_path):
    from kb.core.sweep import SweepPlan, validate

    plan = SweepPlan(dir_merges=[("计算机/git", "计算机/没这个目录")])
    with pytest.raises(SweepError, match="不存在的目录"):
        validate(plan, _vault(tmp_path))


def test_validate_rejects_chain(tmp_path):
    """a→b 且 b→c 会绕圈。"""
    from kb.core.sweep import SweepPlan, validate

    plan = SweepPlan(tag_merges=[("git", "版本控制"), ("版本控制", "计算机")])
    with pytest.raises(SweepError, match="绕"):
        validate(plan, _vault(tmp_path))


def test_validate_accepts_good_plan(tmp_path):
    from kb.core.sweep import SweepPlan, validate

    validate(SweepPlan(tag_merges=[("git", "版本控制")]), _vault(tmp_path))


def test_apply_merges_tags_in_notes(tmp_path):
    from kb.core.sweep import SweepPlan, apply_plan
    from kb.core.vault import read_note

    v = _vault(tmp_path)
    apply_plan(SweepPlan(tag_merges=[("git", "版本控制")]), v)

    meta, _ = read_note(v / "计算机" / "git" / "a.md")
    assert "版本控制" in meta["主题"]
    assert "git" not in meta["主题"]


def test_apply_merges_tags_without_duplicating(tmp_path):
    """a 里本来就有「版本控制」，合并不该出现两个。"""
    from kb.core.sweep import SweepPlan, apply_plan
    from kb.core.vault import read_note, write_note

    v = tmp_path
    write_note(v / "计算机" / "x.md", {"类型": "概念", "主题": ["git", "版本控制"]}, "y")
    apply_plan(SweepPlan(tag_merges=[("git", "版本控制")]), v)

    assert read_note(v / "计算机" / "x.md")[0]["主题"] == ["版本控制"]


def test_apply_moves_directory_and_retags(tmp_path):
    from kb.core.sweep import SweepPlan, apply_plan
    from kb.core.vault import read_note

    v = _vault(tmp_path)
    apply_plan(SweepPlan(dir_merges=[("计算机/git", "计算机/版本控制")]), v)

    assert not (v / "计算机" / "git").exists()
    assert (v / "计算机" / "版本控制" / "a.md").is_file()
    meta, _ = read_note(v / "计算机" / "版本控制" / "a.md")
    assert "git" not in meta["主题"]
    assert "版本控制" in meta["主题"]


def test_apply_returns_files_touched(tmp_path):
    """落盘要报告动过哪些文件——落盘后的 commit 照它 add。"""
    from kb.core.sweep import SweepPlan, apply_plan

    v = _vault(tmp_path)
    touched = apply_plan(SweepPlan(tag_merges=[("git", "版本控制")]), v)
    assert any(p.name == "a.md" for p in touched)


def test_apply_reports_both_sides_of_a_move(tmp_path):
    """目录移动要**旧路径和新路径都报**。

    `commit_changes` 拿这份清单去 `git add`：新路径让 git 看见新增，
    旧路径（已从磁盘消失但 git 跟踪过）让 git 看见删除。只报新路径的话，
    **移动过的文件会漏提交**——而且 commit 照样成功，你看不出来。
    """
    from kb.core.sweep import SweepPlan, apply_plan

    v = _vault(tmp_path)
    touched = apply_plan(SweepPlan(dir_merges=[("计算机/git", "计算机/版本控制")]), v)

    rels = {p.relative_to(v).as_posix() for p in touched}
    assert "计算机/git/a.md" in rels        # 旧路径（让 git 看见删除）
    assert "计算机/版本控制/a.md" in rels    # 新路径（让 git 看见新增）


def test_apply_reports_a_moved_file_even_if_its_tags_did_not_change(tmp_path):
    """光移动目录、标签没变的文件也要进清单。

    早先的写法只在 `_retag` 返回 True 时才 append，于是这类文件
    **不会被 add**——目录挪了，文件却留在 git 的旧位置上。
    """
    from kb.core.sweep import SweepPlan, apply_plan

    v = tmp_path
    # 主题里本来就没有目录名那一级，所以移动之后 `_retag` 不会改它
    write_note(v / "计算机" / "git" / "a.md", {"类型": "概念", "主题": ["计算机"]}, "x")
    write_note(v / "计算机" / "版本控制" / "b.md", {"类型": "概念", "主题": ["计算机"]}, "y")

    touched = apply_plan(SweepPlan(dir_merges=[("计算机/git", "计算机/版本控制")]), v)

    rels = {p.relative_to(v).as_posix() for p in touched}
    assert "计算机/版本控制/a.md" in rels
    assert "计算机/git/a.md" in rels


def test_apply_empty_plan_is_noop(tmp_path):
    from kb.core.sweep import SweepPlan, apply_plan

    v = _vault(tmp_path)
    assert apply_plan(SweepPlan(), v) == []


def test_validate_rejects_missing_source(tmp_path):
    """源不存在也要拦——而且措辞要和目标那一支对齐。

    （原来这两支句式不一致，「不存在的标签」这个说法只在目标那支出现，
    源那支没有测试守，所以一直没暴露。）
    """
    from kb.core.sweep import SweepPlan, validate

    with pytest.raises(SweepError, match="不存在的标签"):
        validate(SweepPlan(tag_merges=[("根本没这个", "版本控制")]), _vault(tmp_path))

    with pytest.raises(SweepError, match="不存在的目录"):
        validate(SweepPlan(dir_merges=[("计算机/没这个", "计算机/版本控制")]), _vault(tmp_path))


# ---------- 带用户要求重跑（Q96）----------

class _CaptureLLM:
    """把收到的提示词留下来，好断言要求进没进。"""

    def __init__(self, reply: str = '{"tag_merges": [], "dir_merges": [], "summary": "无"}'):
        self.reply = reply
        self.seen: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.seen.append((system, user))
        return self.reply


def test_prompt_without_requirement_has_no_extra_section(tmp_path):
    """不带要求时，提示词里不该出现「用户对上次结果的意见」那一段。

    （原来那条 `build_prompt(v) == build_prompt(v, None)` 是同一个 falsy
    分支跑两遍，证明不了任何事——模板正文改坏了它也不红。）
    """
    from kb.core.sweep import build_prompt

    v = _vault(tmp_path)
    for prompt in (build_prompt(v), build_prompt(v, None), build_prompt(v, "")):
        assert "用户对上次结果的意见" not in prompt
        # 锚：JSON 块与「硬规矩」之间不许夹进任何东西
        assert '"summary": "一句话说这次收拾了什么"\n}\n\n## 硬规矩' in prompt


def test_prompt_with_requirement_inserts_between_json_and_rules(tmp_path):
    from kb.core.sweep import build_prompt

    prompt = build_prompt(_vault(tmp_path), "别并到 X，并到 Y")
    fence = prompt.index('"summary": "一句话说这次收拾了什么"')
    opinion = prompt.index("## 用户对上次结果的意见")
    rules = prompt.index("## 硬规矩")
    assert fence < opinion < rules
    assert "别并到 X，并到 Y" in prompt


def test_prompt_carries_the_requirement(tmp_path):
    from kb.core.sweep import build_prompt

    prompt = build_prompt(_vault(tmp_path), "那两个分类不该合并，拆开")
    assert "那两个分类不该合并，拆开" in prompt
    assert "用户对上次结果的意见" in prompt


def test_requirement_goes_to_the_model(tmp_path):
    """真的送到了模型手里——不只是拼进了字符串。"""
    from kb.core.sweep import make_plan

    llm = _CaptureLLM()
    make_plan(_vault(tmp_path), llm, requirement="把 art 拆回来")

    system, user = llm.seen[0]
    assert "把 art 拆回来" in system
    assert "把 art 拆回来" in user


def test_no_requirement_leaves_user_message_alone(tmp_path):
    """不带要求时，user 那句不许变——它是回归的锚点。"""
    from kb.core.sweep import make_plan

    llm = _CaptureLLM()
    make_plan(_vault(tmp_path), llm)
    assert llm.seen[0][1] == "请给出合并方案。"
