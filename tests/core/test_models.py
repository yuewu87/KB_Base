import pytest

from kb.core.models import (
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


def test_plan_create_carries_path_and_frontmatter():
    p = OrganizePlan(
        draft_id="20260915-a3f2",
        outcome=Outcome.CREATE,
        target_path="20_知识/后端/并发写锁.md",
        frontmatter={"类型": "概念", "主题": ["后端"]},
        content="# 并发写锁\n",
        links=["40_索引/后端"],
    )
    assert p.outcome is Outcome.CREATE
    assert p.frontmatter["类型"] == "概念"
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


def test_plan_defaults_are_independent():
    """list/dict 默认值不能共享——否则会串数据。"""
    a = OrganizePlan(draft_id="a", outcome=Outcome.PENDING)
    b = OrganizePlan(draft_id="b", outcome=Outcome.PENDING)
    a.links.append("x")
    a.frontmatter["k"] = "v"
    assert b.links == []
    assert b.frontmatter == {}


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
    assert r.links == []
