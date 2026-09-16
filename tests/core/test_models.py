from dataclasses import FrozenInstanceError

import pytest

from kb.core.models import (
    K_CREATED,
    K_ID,
    K_PROJECT,
    K_SOURCE,
    K_STATUS,
    K_SUBMITTED_AT,
    K_TOPIC,
    K_TYPE,
    K_UPDATED,
    Draft,
    NoteType,
    OrganizePlan,
    OrganizeResult,
    Outcome,
    ResultKind,
)


def test_note_type_has_seven_values():
    """Q24：枚举固定，不许自由发挥。日志给整理日志，索引给自动生成的索引页。"""
    assert [t.value for t in NoteType] == [
        "概念",
        "踩坑",
        "决策",
        "经验",
        "清单",
        "日志",
        "索引",
    ]


def test_note_type_rejects_unknown_value():
    with pytest.raises(ValueError):
        NoteType("学习笔记")


def test_outcome_values_are_the_wire_contract():
    """这三个字符串是与 LLM 的 wire 契约——Task 8 按它们解析模型输出。

    假的保护长这样：`p.outcome is Outcome.CREATE` 是恒等比较，对 .value 不敏感，
    把 FOLD 改成 "merge" 也不会红。必须断言 .value 本身。
    """
    assert [o.value for o in Outcome] == ["create", "fold", "pending"]


def test_draft_holds_submitted_content_verbatim():
    """Q55：投递是纯粹的，正文原样保存。"""
    d = Draft(
        id="20260915-a3f2",
        body="并发写入会锁表\n",
        source="会话",
        project="电商后台",
        created_at="2026-09-15T14:32:00",
    )
    assert d.body == "并发写入会锁表\n"
    assert d.project == "电商后台"


def test_draft_project_is_optional():
    """Q30：允许没有项目——纯知识点场景。"""
    d = Draft(id="x", body="b", source=None, project=None, created_at="t")
    assert d.project is None


def test_draft_is_immutable():
    """Q55：草稿投递后原样保存，服务不改写——frozen 是这条承诺的机制保证。"""
    d = Draft(id="x", body="原始正文", source=None, project=None, created_at="t")
    with pytest.raises(FrozenInstanceError):
        d.body = "被改写了"


def test_plan_create_carries_path_and_frontmatter():
    p = OrganizePlan(
        draft_id="20260915-a3f2",
        outcome=Outcome.CREATE,
        target_path="计算机/并发写锁.md",
        frontmatter={K_TYPE: NoteType.CONCEPT.value, K_TOPIC: ["计算机"]},
        content="# 并发写锁\n",
    )
    assert p.outcome is Outcome.CREATE
    assert p.frontmatter[K_TYPE] == "概念"
    assert p.pending_reason is None


def test_plan_pending_requires_reason():
    """归不了类时必须给出原因，供报告展示。"""
    p = OrganizePlan(
        draft_id="x",
        outcome=Outcome.PENDING,
        pending_reason="无法判断归属主题",
    )
    assert p.outcome is Outcome.PENDING
    assert p.target_path is None
    assert p.pending_reason == "无法判断归属主题"


def test_plan_defaults_are_independent():
    """可变默认值不能共享——否则会串数据。"""
    a = OrganizePlan(draft_id="a", outcome=Outcome.PENDING)
    b = OrganizePlan(draft_id="b", outcome=Outcome.PENDING)
    a.frontmatter["k"] = "v"
    assert b.frontmatter == {}


def test_plan_defaults_cover_all_optional_fields():
    """契约快照：最小构造下每个可选字段的默认值。

    这些默认值会被落盘逻辑直接消费（`apply_plan` 把 `plan.content` 写盘），
    改成 None 会让 frontmatter.Post 炸——而现有断言不会红。
    """
    p = OrganizePlan(draft_id="x", outcome=Outcome.CREATE)
    assert p.target_path is None
    assert p.frontmatter == {}
    assert p.content == ""
    assert p.pending_reason is None


def test_result_kind_covers_all_execution_outcomes():
    """Q45/Q50：执行结果有四种——成功新建、成功合并、待归类、失败。"""
    assert [k.value for k in ResultKind] == ["created", "folded", "pending", "failed"]


def test_organize_result_carries_error_separately():
    """失败时 error 有值，detail 仍可读——报告和工作日志都要用。"""
    r = OrganizeResult(
        draft_id="x",
        kind=ResultKind.FAILED,
        detail="模型返回格式不合规",
        error="JSONDecodeError: Expecting value",
    )
    assert r.kind is ResultKind.FAILED
    assert r.error is not None
    assert r.detail == "模型返回格式不合规"


def test_organize_result_is_immutable():
    """与 Draft 同为「已发生的记录」，frozen 是真保护（字段全是不可变标量）。"""
    r = OrganizeResult(draft_id="x", kind=ResultKind.CREATED, detail="d")
    with pytest.raises(FrozenInstanceError):
        r.detail = "被改了"


def test_frontmatter_key_constants_are_stable():
    """这些常量是跨模块契约——改名或写错会让读取端静默返回 None。"""
    assert (K_STATUS, K_ID, K_SUBMITTED_AT, K_SOURCE, K_PROJECT) == (
        "状态",
        "id",
        "投递时间",
        "来源",
        "项目",
    )
    assert (K_TYPE, K_TOPIC, K_CREATED, K_UPDATED) == ("类型", "主题", "创建", "更新")
