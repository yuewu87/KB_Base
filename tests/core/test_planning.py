import json
from pathlib import Path

import pytest

from kb.core import planning
from kb.core.classify import find_candidates
from kb.core.models import K_PROJECT, K_TOPIC, K_TYPE, Draft, NoteType, Outcome
from kb.core.planning import (
    PlanError,
    build_messages,
    build_system_prompt,
    extract_json,
    load_note_skeletons,
    parse_plan,
    validate_plan,
)
from kb.core.vault import INDEX, ensure_topic_index, write_note

DRAFT = Draft(
    id="20260915-a3f2",
    body="并发写入会锁表，最后用队列串行化解决",
    source="会话",
    project=None,
    created_at="2026-09-15 14:32",
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """一个最小可用的 vault：一个领域、一个索引页、一篇笔记。"""
    (tmp_path / "计算机").mkdir(parents=True)
    ensure_topic_index(tmp_path, "计算机")
    write_note(
        tmp_path / "计算机" / "队列串行化.md",
        {"类型": "概念", "主题": ["计算机"]},
        "# 队列串行化\n",
    )
    return tmp_path


def _plan_json(**overrides) -> str:
    data = {
        "outcome": "create",
        "target_path": "计算机/并发写锁.md",
        "frontmatter": {"类型": "概念", "主题": ["后端"]},
        "content": "# 并发写锁\n\n见 [[队列串行化]]\n",
        "pending_reason": None,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ---------- JSON 提取 ----------

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_markdown_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_strips_bare_fence():
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_bad_json_raises():
    with pytest.raises(PlanError, match="不是合法 JSON"):
        extract_json("这不是 JSON")


def test_extract_json_rejects_non_object():
    with pytest.raises(PlanError, match="JSON 对象"):
        extract_json("[1, 2, 3]")


# ---------- 解析 ----------

def test_parse_plan_builds_domain_object():
    plan = parse_plan(DRAFT.id, _plan_json())
    assert plan.draft_id == DRAFT.id
    assert plan.outcome is Outcome.CREATE
    assert plan.target_path == "计算机/并发写锁.md"
    assert plan.frontmatter["类型"] == "概念"
    assert plan.content == "# 并发写锁\n\n见 [[队列串行化]]\n"


def test_parse_plan_rejects_unknown_outcome():
    with pytest.raises(PlanError, match="outcome 非法"):
        parse_plan(DRAFT.id, _plan_json(outcome="rewrite"))


def test_parse_plan_rejects_non_object_frontmatter():
    with pytest.raises(PlanError, match="frontmatter"):
        parse_plan(DRAFT.id, _plan_json(frontmatter="不是对象"))


def test_parse_plan_tolerates_absent_optional_fields():
    plan = parse_plan(
        DRAFT.id,
        json.dumps({"outcome": "pending", "pending_reason": "拿不准"}, ensure_ascii=False),
    )
    assert plan.target_path is None
    assert plan.frontmatter == {}


# ---------- 校验：pending ----------

def test_validate_pending_requires_reason(vault):
    plan = parse_plan(DRAFT.id, json.dumps({"outcome": "pending"}))
    with pytest.raises(PlanError, match="pending_reason"):
        validate_plan(plan, vault)


def test_validate_pending_passes_with_reason(vault):
    plan = parse_plan(
        DRAFT.id,
        json.dumps({"outcome": "pending", "pending_reason": "主题不明"}, ensure_ascii=False),
    )
    validate_plan(plan, vault)


def test_validate_pending_ignores_target_path(vault):
    """pending 不需要路径——即便模型给了也不该因此报错。"""
    plan = parse_plan(
        DRAFT.id,
        json.dumps(
            {"outcome": "pending", "pending_reason": "拿不准", "target_path": "随便"},
            ensure_ascii=False,
        ),
    )
    validate_plan(plan, vault)


# ---------- 校验：路径 ----------

def test_validate_create_requires_target_path(vault):
    plan = parse_plan(DRAFT.id, _plan_json(target_path=None))
    with pytest.raises(PlanError, match="target_path"):
        validate_plan(plan, vault)


@pytest.mark.parametrize("bad", ["/etc/passwd", "C:/Windows/x.md", "../../逃逸.md"])
def test_validate_rejects_unsafe_paths(vault, bad):
    plan = parse_plan(DRAFT.id, _plan_json(target_path=bad))
    with pytest.raises(PlanError):
        validate_plan(plan, vault)


def test_validate_rejects_path_outside_allowed_dirs(vault):
    """只允许落在既有领域下。"""
    plan = parse_plan(DRAFT.id, _plan_json(target_path="_附件/x.md"))
    with pytest.raises(PlanError, match="允许范围"):
        validate_plan(plan, vault)


def test_validate_rejects_invented_topic(vault):
    """Q11：AI 不得自行发明分类——新主题必须走 pending。"""
    plan = parse_plan(DRAFT.id, _plan_json(target_path="运维/新笔记.md"))
    with pytest.raises(PlanError, match="允许范围"):
        validate_plan(plan, vault)


# ---------- 校验：create ----------

def test_validate_create_rejects_existing_target(vault):
    existing = "计算机/队列串行化.md"
    plan = parse_plan(DRAFT.id, _plan_json(target_path=existing))
    with pytest.raises(PlanError, match="已存在"):
        validate_plan(plan, vault)


@pytest.mark.parametrize("bad_type", ["学习笔记", "知识点", ""])
def test_validate_create_rejects_bad_note_type(vault, bad_type):
    plan = parse_plan(
        DRAFT.id, _plan_json(frontmatter={"类型": bad_type, "主题": ["后端"]})
    )
    with pytest.raises(PlanError, match="类型"):
        validate_plan(plan, vault)


@pytest.mark.parametrize("service_type", ["日志", "索引"])
def test_validate_create_rejects_service_generated_type(vault, service_type):
    """日志与索引页由服务生成，模型不许声称要建它们。

    校验必须用**和提示词同一个集合**（_LLM_ALLOWED_TYPES），不能对着全部
    枚举值放宽——否则模型不听话时校验拦不住，会写出一篇声称是索引页的笔记。
    """
    plan = parse_plan(
        DRAFT.id, _plan_json(frontmatter={"类型": service_type, "主题": ["后端"]})
    )
    with pytest.raises(PlanError, match="服务生成"):
        validate_plan(plan, vault)


def test_allowed_types_match_prompt_and_validator():
    """提示词里承诺的类型集合，必须与校验接受的完全相同。"""
    from kb.core.planning import _LLM_ALLOWED_TYPES

    prompt = build_system_prompt()
    for t in _LLM_ALLOWED_TYPES:
        assert t.value in prompt
    assert len(_LLM_ALLOWED_TYPES) == len(NoteType) - 2


def test_validate_create_rejects_orphan_note(vault):
    """Q21：不允许孤儿笔记——正文必须至少有一个 [[链接]]。"""
    plan = parse_plan(DRAFT.id, _plan_json(content="# 没有链接的笔记\n"))
    with pytest.raises(PlanError, match="双向链接"):
        validate_plan(plan, vault)


def test_validate_create_rejects_link_to_missing_note(vault):
    plan = parse_plan(
        DRAFT.id, _plan_json(content="# 并发写锁\n\n见 [[根本不存在的笔记]]\n")
    )
    with pytest.raises(PlanError, match="根本不存在的笔记"):
        validate_plan(plan, vault)


def test_validate_create_accepts_link_to_index_page(vault):
    """索引页由服务自动创建，所以空库第一天也有东西可链。"""
    plan = parse_plan(
        DRAFT.id, _plan_json(content=f"# 并发写锁\n\n见 [[{INDEX}/计算机]]\n")
    )
    validate_plan(plan, vault)


def test_validate_create_passes_for_good_plan(vault):
    validate_plan(parse_plan(DRAFT.id, _plan_json()), vault)


def test_validate_rejects_illegal_filename(vault):
    """文件名必须是清洗过的内容标题（Q72）。"""
    plan = parse_plan(
        DRAFT.id,
        _plan_json(target_path="计算机/队列串行化: 补充.md"),
    )
    with pytest.raises(PlanError, match="文件名不合规"):
        validate_plan(plan, vault)


# ---------- 校验：fold ----------

def test_validate_fold_requires_existing_target(vault):
    plan = parse_plan(
        DRAFT.id,
        _plan_json(outcome="fold", target_path="计算机/不在这里.md"),
    )
    with pytest.raises(PlanError, match="不存在"):
        validate_plan(plan, vault)


def test_validate_fold_requires_content(vault):
    plan = parse_plan(
        DRAFT.id,
        _plan_json(
            outcome="fold",
            target_path="计算机/队列串行化.md",
            content="   ",
        ),
    )
    with pytest.raises(PlanError, match="追加的内容"):
        validate_plan(plan, vault)


def test_validate_fold_passes(vault):
    plan = parse_plan(
        DRAFT.id,
        _plan_json(
            outcome="fold",
            target_path="计算机/队列串行化.md",
            content="补充：队列满时要限流\n",
        ),
    )
    validate_plan(plan, vault)


# ---------- 提示词 ----------

def test_build_messages_includes_draft_body(vault):
    msgs = build_messages(DRAFT, [], ["后端"], vault)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "并发写入会锁表" in msgs[1]["content"]


def test_build_messages_lists_topics_and_projects(vault):
    msgs = build_messages(DRAFT, [], ["后端"], vault)
    assert "后端" in msgs[1]["content"]


def test_build_messages_handles_empty_vault(tmp_path):
    msgs = build_messages(DRAFT, [], [], tmp_path)
    assert "没有明显相关的已有笔记" in msgs[1]["content"]


def test_build_messages_lists_candidates(vault):
    cands = find_candidates(vault, DRAFT.body)
    msgs = build_messages(DRAFT, cands, ["后端"], vault)
    assert "队列串行化" in msgs[1]["content"]


def test_system_prompt_lists_allowed_note_types():
    prompt = build_system_prompt()
    for t in NoteType:
        if t in (NoteType.JOURNAL, NoteType.INDEX):
            continue          # 日志与索引页由服务生成，不由 LLM 产出
        assert t.value in prompt


def test_system_prompt_targets_domains():
    """路径只允许落在领域下（Q67）。"""
    prompt = build_system_prompt()
    assert "领域" in prompt
    assert "10_项目" not in prompt
    assert "20_知识" not in prompt


def test_system_prompt_states_tag_rule():
    """标签规则要写进提示词（Q76）。"""
    prompt = build_system_prompt()
    assert "路径派生" in prompt
    assert "最多 3 个" in prompt or "0-3" in prompt


def test_system_prompt_states_reuse_classification_rule():
    """能复用已有分类就复用（Q77）。"""
    prompt = build_system_prompt()
    assert "能用已有的就用已有的" in prompt


def test_system_prompt_uses_frontmatter_key_constants():
    """提示词里的键名必须与 K_* 同源。

    否则改了常量、忘了改提示词，模型仍按旧键名输出——而两边都不会报错，
    只会一直拿不到字段。
    """
    prompt = build_system_prompt()
    for key in (K_TYPE, K_TOPIC, K_PROJECT):
        assert key in prompt


# ---------- 用户的判断（Q23）----------

def test_strip_user_judgment_empties_the_section():
    content = "# 标题\n\n## 用户的判断\n\n他说这个方案更好。\n\n## 相关\n"
    out = planning.strip_user_judgment(content)
    assert "他说这个方案更好" not in out
    # 标题与下一节之间要留空行，否则 Markdown 里两行标题会贴在一起
    assert "## 用户的判断\n\n## 相关" in out


def test_strip_user_judgment_keeps_other_sections():
    content = "# 标题\n\n## 展开\n\n正文\n\n## 用户的判断\n\n代填\n\n## 相关\n\n- [[x]]\n"
    out = planning.strip_user_judgment(content)
    assert "正文" in out
    assert "- [[x]]" in out
    assert "代填" not in out


def test_strip_user_judgment_when_last_section():
    content = "# 标题\n\n## 用户的判断\n\n代填\n"
    out = planning.strip_user_judgment(content)
    assert "代填" not in out
    assert out.rstrip().endswith("## 用户的判断")


def test_strip_user_judgment_noop_when_absent():
    content = "# 标题\n\n## 展开\n\n正文\n"
    assert planning.strip_user_judgment(content) == content


def test_strip_user_judgment_preserves_trailing_newline():
    assert planning.strip_user_judgment("## 用户的判断\n\n代填\n").endswith("\n")


# ---------- 模板接入 ----------

def test_load_note_skeletons_reads_templates():
    """模板必须真的被读进来——否则它们就是 write-only 的死文件。"""
    skeletons = load_note_skeletons()
    assert "概念" in skeletons
    assert "## 展开" in skeletons["概念"]
    assert "## 现象" in skeletons["踩坑"]


def test_load_note_skeletons_excludes_service_generated_types():
    """日志与索引页由服务生成，不该出现在给模型的骨架里。"""
    skeletons = load_note_skeletons()
    assert NoteType.JOURNAL.value not in skeletons
    assert NoteType.INDEX.value not in skeletons


def test_system_prompt_embeds_skeletons():
    prompt = build_system_prompt()
    assert "各类型的正文骨架" in prompt
    assert "## 用户的判断" in prompt


def test_system_prompt_survives_missing_templates(monkeypatch, tmp_path):
    """模板目录没了不该让整个整理挂掉——退化成没有骨架的提示词。"""
    monkeypatch.setattr(planning, "TEMPLATES_DIR", tmp_path / "不存在")
    prompt = planning.build_system_prompt()
    assert "你是知识库整理助手" in prompt
    assert "各类型的正文骨架" not in prompt


# ---------- 校验：修改请求（Q59/Q60）----------

def test_validate_rejects_revise_folding_into_superseded_note(vault):
    """`--revise` 是「这条取代那条」，新内容不能折进被取代的那一篇。

    2026-09-16 端到端验收跑出来的真 bug：模型看到内容相似就选了 fold，
    把新说法追加进原笔记，随后 revise 逻辑又把这同一篇标记失效——
    落成 `失效: true` + `被取代于: 自己`。同一个文件里新旧两种说法并存，
    再声明它被取代，自相矛盾。
    """
    plan = parse_plan(
        DRAFT.id,
        _plan_json(outcome="fold", target_path="计算机/队列串行化.md"),
    )
    plan.revise_target = "队列串行化"
    with pytest.raises(PlanError, match="另起一篇"):
        validate_plan(plan, vault)


def test_validate_allows_revise_creating_new_note(vault):
    """正常形态：新建一篇，旧的那篇在落盘时才标记失效。"""
    plan = parse_plan(
        DRAFT.id, _plan_json(target_path="计算机/队列串行化的修订.md")
    )
    plan.revise_target = "队列串行化"
    validate_plan(plan, vault)
