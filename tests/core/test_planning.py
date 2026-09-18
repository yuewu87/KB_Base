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
        # frontmatter 里只剩类型——主题与项目由服务算（Q101）
        "frontmatter": {"类型": "概念"},
        "semantic_tags": [],
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


def test_system_prompt_demands_a_reason_for_every_link():
    """链接要说得出共性（Q100）。

    只管「有没有把要求写出来」，管不了模型写得好不好——这正是 Q100 里
    决定不加机械校验的地方，别在这儿加格式检查。
    """
    prompt = build_system_prompt()
    assert "共性" in prompt
    assert "——" in prompt          # `## 相关` 里的理由怎么写，得给个样子


def test_system_prompt_says_the_reason_must_be_checkable():
    """光有理由不够，还得具体（Q100 的第二句）。

    「都是坑」这种话放哪两篇上都成立——模型分得清具体和泛泛，
    但得先把边界告诉它，否则最省力的合规路径就是写一句空话。
    """
    prompt = build_system_prompt()
    assert "具体到能被检验" in prompt
    assert "说了等于没说" in prompt


# ---------- 标签：路径派生归代码（Q101）----------

def test_normalize_tag_folds_whitespace_and_lowercases():
    assert planning.normalize_tag("  Git  Bash ") == "git-bash"
    assert planning.normalize_tag("PowerShell") == "powershell"


def test_normalize_tag_truncates_to_twenty_chars():
    assert len(planning.normalize_tag("a" * 50)) == 20


def test_normalize_tag_of_blank_is_empty():
    assert planning.normalize_tag("   ") == ""


def test_derive_tags_puts_path_dirs_first():
    """路径派生排最前，领域名打头（规则 7 原话）。"""
    tags = planning.derive_tags("计算机/Python/并发写锁.md", [])
    assert tags == ["计算机", "python"]


def test_derive_tags_keeps_semantic_tags_after_path_ones():
    tags = planning.derive_tags("计算机/艺术生成.md", ["艺术", "图像"])
    assert tags == ["计算机", "艺术", "图像"]


def test_derive_tags_dedups_path_against_semantic():
    """语义标签重复路径派生时不许出现两遍。"""
    tags = planning.derive_tags("计算机/Python/x.md", ["计算机", "python", "asyncio"])
    assert tags == ["计算机", "python", "asyncio"]


def test_derive_tags_never_empty_when_path_has_a_domain():
    """这条是重点：**标签空不再可能**。

    路径至少有一级目录，所以派生出来至少有一个标签——检索的命脉
    不再靠模型记得填。改之前 48 篇全都填了，纯属自觉，代码一行没兜。
    """
    assert planning.derive_tags("计算机/x.md", []) == ["计算机"]
    assert planning.derive_tags("计算机/x.md", [""]) == ["计算机"]


def test_parse_plan_reads_semantic_tags():
    plan = parse_plan(DRAFT.id, _plan_json(semantic_tags=["git", "版本控制"]))
    assert plan.semantic_tags == ["git", "版本控制"]


def test_parse_plan_semantic_tags_default_to_empty():
    data = json.loads(_plan_json())
    del data["semantic_tags"]
    assert parse_plan(DRAFT.id, json.dumps(data, ensure_ascii=False)).semantic_tags == []


def test_validate_create_rejects_more_than_three_semantic_tags(vault):
    """0-3 个是规则 7 写的数——数字是机械约束，落成一行 if。"""
    plan = parse_plan(DRAFT.id, _plan_json(semantic_tags=["a", "b", "c", "d"]))
    with pytest.raises(PlanError, match="最多 3 个"):
        validate_plan(plan, vault)


def test_validate_create_accepts_exactly_three_semantic_tags(vault):
    plan = parse_plan(DRAFT.id, _plan_json(semantic_tags=["a", "b", "c"]))
    validate_plan(plan, vault)      # 不抛就算过


def test_resolve_frontmatter_takes_project_from_the_draft():
    """项目名**由代码搬运**，不问模型（Q101）。

    实测四篇笔记的 `项目` 字段丢了——草稿里明明有，模型生成 frontmatter
    时漏掉了，而校验只管 `类型`。搬运没有任何判断成分，不该交给模型。
    """
    draft = Draft(
        id="x", body="b", source="会话", project="KN_Base", created_at="t"
    )
    plan = parse_plan(DRAFT.id, _plan_json())
    assert planning.resolve_frontmatter(plan, draft)["项目"] == "KN_Base"


def test_resolve_frontmatter_drops_a_project_the_model_invented():
    """草稿没有项目（Web 投递）时，模型自己编的要丢掉——草稿是唯一真源。"""
    plan = parse_plan(DRAFT.id, _plan_json())
    plan.frontmatter["项目"] = "模型编的项目"
    assert "项目" not in planning.resolve_frontmatter(plan, DRAFT)


def test_resolve_frontmatter_computes_topic_in_code():
    plan = parse_plan(DRAFT.id, _plan_json(semantic_tags=["版本控制"]))
    meta = planning.resolve_frontmatter(plan, DRAFT)
    assert meta["主题"] == ["计算机", "版本控制"]


def test_resolve_frontmatter_overrides_whatever_the_model_put_in_topic():
    plan = parse_plan(DRAFT.id, _plan_json())
    plan.frontmatter["主题"] = ["模型自己填的"]
    assert planning.resolve_frontmatter(plan, DRAFT)["主题"] == ["计算机"]


def test_resolve_frontmatter_keeps_the_note_type_from_the_model():
    """类型是判断题，仍归模型。"""
    plan = parse_plan(DRAFT.id, _plan_json())
    assert planning.resolve_frontmatter(plan, DRAFT)["类型"] == "概念"


def test_system_prompt_uses_frontmatter_key_constants():
    """提示词里的键名必须与 K_* 同源。

    否则改了常量、忘了改提示词，模型仍按旧键名输出——而两边都不会报错，
    只会一直拿不到字段。
    """
    prompt = build_system_prompt()
    for key in (K_TYPE, K_TOPIC, K_PROJECT):
        assert key in prompt


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
    assert "## 展开" in prompt


def test_the_judgment_section_is_gone_everywhere():
    """「用户的判断」2026-09-18 删了——用户说基本不看，48 篇一次没填过。

    这一节原本靠机械清空防 AI 代填（Q23）。整节删掉之后，**提示词、模板、
    落盘三处都不该再有它的影子**——留一处，模型就会照着写一个没人看的空标题。
    """
    assert "用户的判断" not in build_system_prompt()
    assert not any("用户的判断" in body for body in load_note_skeletons().values())


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


# ---------- 层级上限（Q94）----------

def test_validate_allows_exactly_four_levels(vault):
    """4 层是上限，正好 4 层放行。"""
    (vault / "计算机" / "a" / "b" / "c").mkdir(parents=True)
    plan = parse_plan(DRAFT.id, _plan_json(target_path="计算机/a/b/c/x.md"))
    validate_plan(plan, vault)


def test_validate_rejects_five_levels(vault):
    """Q94：目录最多 4 层（领域算第一层）。

    你原话是「顶多三四层的样子吧」——**这话得由代码说了算**，
    不然模型理论上能建任意深的嵌套。和兜底分类名同一类：机械约束归代码。
    """
    (vault / "计算机" / "a" / "b" / "c" / "d").mkdir(parents=True)
    plan = parse_plan(DRAFT.id, _plan_json(target_path="计算机/a/b/c/d/x.md"))
    with pytest.raises(PlanError, match="最多 4 层"):
        validate_plan(plan, vault)


def test_prompt_states_the_depth_limit():
    """提示词里也要说——不然模型每次都撞校验，白跑一轮。"""
    prompt = build_system_prompt()
    assert "最多 4 层" in prompt


# ---------- 兜底分类名（Q14）----------

@pytest.mark.parametrize(
    "bad",
    ["计算机/其他/x.md", "计算机/其它/x.md", "计算机/杂项/x.md",
     "计算机/临时/x.md", "计算机/未分类/x.md", "计算机/misc/x.md",
     "计算机/Other/x.md", "计算机/tmp/深层/x.md"],
)
def test_validate_rejects_fallback_dir(vault, bad):
    """Q14：兜底分类注定变垃圾桶——**目录**里不许出现。

    模型看到一条装不下的内容时，最省事的做法就是往「其他」里一塞。
    闸门要卡在它迈不过去的地方，不能只写在提示词里。
    """
    plan = parse_plan(DRAFT.id, _plan_json(target_path=bad))
    with pytest.raises(PlanError, match="兜底分类"):
        validate_plan(plan, vault)


def test_validate_allows_fallback_word_in_the_title(vault):
    """**文件名不查**——笔记标题里可以有「其他」。

    「其他语言怎么处理」是一篇正经笔记，不是兜底分类。
    """
    plan = parse_plan(DRAFT.id, _plan_json(target_path="计算机/其他语言怎么处理.md"))
    validate_plan(plan, vault)
