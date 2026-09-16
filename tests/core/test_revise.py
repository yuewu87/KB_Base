"""修改：--revise 指定目标，落盘后旧笔记标记失效（Q59/Q60）。"""

from kb.core.models import Draft
from kb.core.vault import (
    find_note_by_stem,
    is_superseded,
    mark_superseded,
    read_draft,
    read_note,
    write_draft,
    write_note,
)


def test_find_note_by_stem_unique(tmp_path):
    write_note(tmp_path / "计算机" / "a.md", {"类型": "概念"}, "x")
    assert find_note_by_stem(tmp_path, "a") == tmp_path / "计算机" / "a.md"


def test_find_note_by_stem_returns_none_on_ambiguity(tmp_path):
    """多个同名 → 不猜。"""
    write_note(tmp_path / "计算机" / "a.md", {"类型": "概念"}, "x")
    write_note(tmp_path / "艺术" / "a.md", {"类型": "概念"}, "y")
    assert find_note_by_stem(tmp_path, "a") is None


def test_mark_superseded_sets_flags(tmp_path):
    path = tmp_path / "计算机" / "a.md"
    write_note(path, {"类型": "概念"}, "x")
    mark_superseded(path, by="b")
    meta, _ = read_note(path)
    assert meta["失效"] is True
    assert meta["被取代于"] == "b"
    assert is_superseded(meta) is True


def test_is_superseded_false_by_default(tmp_path):
    path = tmp_path / "计算机" / "a.md"
    write_note(path, {"类型": "概念"}, "x")
    meta, _ = read_note(path)
    assert is_superseded(meta) is False


def test_draft_roundtrip_keeps_revise_target(tmp_path):
    """`--revise` 的目标必须能穿过草稿这一层。

    不写进 frontmatter 的话，push 时丢掉、整理时 `plan.revise_target` 恒为
    None，标记失效的代码永远进不去——**而且是静默无效**，用户以为生效了。
    """
    draft = Draft(
        id="20260916-a3f2",
        body="正文",
        source=None,
        project=None,
        created_at="2026-09-16 10:00",
        revise_target="队列串行化",
    )
    path = write_draft(tmp_path, draft)
    got = read_draft(path)
    assert got.revise_target == "队列串行化"


def test_draft_roundtrip_without_revise_target(tmp_path):
    draft = Draft(
        id="20260916-a3f3",
        body="正文",
        source=None,
        project=None,
        created_at="2026-09-16 10:00",
    )
    path = write_draft(tmp_path, draft)
    assert read_draft(path).revise_target is None
