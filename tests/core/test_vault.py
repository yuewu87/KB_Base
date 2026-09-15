import re
from datetime import datetime

import pytest

from kb.core.models import Draft
from kb.core.vault import (
    INBOX,
    INDEX,
    PENDING,
    atomic_write,
    draft_path,
    ensure_topic_index,
    find_draft,
    find_project_dir,
    list_drafts,
    list_notes,
    list_projects,
    move_to_pending,
    new_draft_id,
    normalize_project,
    read_draft,
    read_note,
    write_draft,
    write_note,
)


def _draft(**kw) -> Draft:
    base = dict(
        id="20260915-a3f2",
        body="并发写入会锁表\n",
        source="会话",
        project="电商后台",
        created_at="2026-09-15 14:32",
    )
    base.update(kw)
    return Draft(**base)


# ---------- 草稿 id ----------

def test_draft_id_format():
    assert re.fullmatch(r"\d{8}-[0-9a-f]{4}", new_draft_id())


def test_draft_id_uses_given_date():
    assert new_draft_id(datetime(2026, 9, 15)).startswith("20260915-")


# ---------- 草稿读写 ----------

def test_write_then_read_draft_roundtrip(tmp_path):
    write_draft(tmp_path, _draft())
    got = read_draft(draft_path(tmp_path, "20260915-a3f2"))
    assert got.id == "20260915-a3f2"
    assert got.body.strip() == "并发写入会锁表"
    assert got.project == "电商后台"
    assert got.source == "会话"
    assert got.created_at == "2026-09-15 14:32"


def test_draft_frontmatter_marks_status(tmp_path):
    path = write_draft(tmp_path, _draft())
    assert "状态: 待整理" in path.read_text(encoding="utf-8")


def test_draft_body_is_stored_verbatim(tmp_path):
    """Q55：投递是纯粹的，服务不改写正文。"""
    body = "第一行\n\n  缩进的第二段  \n结尾无换行"
    path = write_draft(tmp_path, _draft(body=body))
    assert read_draft(path).body.strip() == body.strip()


def test_draft_omits_absent_optional_fields(tmp_path):
    """没有项目时不写 `项目: null`——空字段不该出现在 frontmatter 里。"""
    path = write_draft(tmp_path, _draft(project=None, source=None))
    text = path.read_text(encoding="utf-8")
    assert "项目" not in text
    assert "来源" not in text
    assert "null" not in text


def test_write_draft_refuses_to_overwrite(tmp_path):
    """id 冲突要响亮失败，不能静默覆盖——静默覆盖就是数据丢失。

    4 位随机十六进制只有 65536 种，长期使用撞号并非不可能。
    """
    write_draft(tmp_path, _draft())
    with pytest.raises(FileExistsError, match="拒绝覆盖"):
        write_draft(tmp_path, _draft(body="另一条内容"))

    # 原有内容必须没被破坏
    assert read_draft(draft_path(tmp_path, "20260915-a3f2")).body.strip() == "并发写入会锁表"


def test_read_draft_coerces_non_string_fields(tmp_path):
    """YAML 里给出非字符串时，`str | None` 的注解不能变成假话。"""
    path = draft_path(tmp_path, "20260915-a3f2")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nid: 20260915-a3f2\n项目: 123\n来源:\n---\n\n正文\n",
        encoding="utf-8",
    )
    got = read_draft(path)
    assert got.project == "123"
    assert got.source is None


# ---------- 草稿列举 ----------

def test_list_drafts_scans_inbox_and_pending(tmp_path):
    """Q55：待归类子目录里的草稿也要被扫到，否则永远卡着。"""
    write_draft(tmp_path, _draft(id="20260915-0001"))
    (tmp_path / INBOX / PENDING).mkdir(parents=True)
    write_draft(tmp_path, _draft(id="20260915-0002"))
    move_to_pending(tmp_path, draft_path(tmp_path, "20260915-0002"))

    ids = {read_draft(p).id for p in list_drafts(tmp_path)}
    assert ids == {"20260915-0001", "20260915-0002"}


def test_list_drafts_empty_when_no_inbox(tmp_path):
    assert list_drafts(tmp_path) == []


def test_find_draft_locates_by_id(tmp_path):
    write_draft(tmp_path, _draft())
    found = find_draft(tmp_path, "20260915-a3f2")
    assert found is not None and found.exists()


def test_find_draft_finds_one_in_pending(tmp_path):
    write_draft(tmp_path, _draft())
    move_to_pending(tmp_path, draft_path(tmp_path, "20260915-a3f2"))
    assert find_draft(tmp_path, "20260915-a3f2") is not None


def test_find_draft_returns_none_when_absent(tmp_path):
    assert find_draft(tmp_path, "不存在") is None


def test_move_to_pending_is_idempotent(tmp_path):
    write_draft(tmp_path, _draft())
    path = draft_path(tmp_path, "20260915-a3f2")
    once = move_to_pending(tmp_path, path)
    twice = move_to_pending(tmp_path, once)
    assert once == twice
    assert once.parent.name == PENDING


# ---------- 笔记读写 ----------

def test_write_then_read_note_roundtrip(tmp_path):
    path = tmp_path / "20_知识" / "后端" / "并发写锁.md"
    write_note(path, {"类型": "概念", "主题": ["后端"]}, "# 并发写锁\n")
    meta, body = read_note(path)
    assert meta["类型"] == "概念"
    assert meta["主题"] == ["后端"]
    assert body.strip() == "# 并发写锁"


def test_write_note_drops_none_values(tmp_path):
    """值为 None 的键直接不写——否则 YAML 里会出现 `项目: null`。"""
    path = tmp_path / "note.md"
    write_note(path, {"类型": "概念", "项目": None}, "正文")
    assert "null" not in path.read_text(encoding="utf-8")


def test_list_notes_covers_projects_and_knowledge(tmp_path):
    write_note(tmp_path / "20_知识" / "后端" / "a.md", {"类型": "概念"}, "a")
    write_note(tmp_path / "10_项目" / "个人" / "P" / "P-踩坑.md", {"类型": "踩坑"}, "b")
    write_note(tmp_path / "40_索引" / "后端.md", {"类型": "索引"}, "不该被扫到")
    names = {p.name for p in list_notes(tmp_path)}
    assert names == {"a.md", "P-踩坑.md"}


# ---------- 项目名匹配（Q30）----------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KN_Base", "kn-base"),
        ("kn-base", "kn-base"),
        ("KN Base", "kn-base"),
        ("  KN_Base  ", "kn-base"),
        ("电商后台", "电商后台"),
    ],
)
def test_normalize_project(raw, expected):
    assert normalize_project(raw) == expected


def test_find_project_dir_unique_match(tmp_path):
    target = tmp_path / "10_项目" / "工作" / "电商后台"
    target.mkdir(parents=True)
    assert find_project_dir(tmp_path, "电商后台") == target


def test_find_project_dir_matches_across_separator_styles(tmp_path):
    target = tmp_path / "10_项目" / "个人" / "KN_Base"
    target.mkdir(parents=True)
    assert find_project_dir(tmp_path, "kn-base") == target


def test_find_project_dir_returns_none_when_absent(tmp_path):
    (tmp_path / "10_项目" / "个人").mkdir(parents=True)
    assert find_project_dir(tmp_path, "不存在") is None


def test_find_project_dir_returns_none_for_empty_name(tmp_path):
    (tmp_path / "10_项目" / "个人").mkdir(parents=True)
    assert find_project_dir(tmp_path, "") is None


def test_find_project_dir_returns_none_on_ambiguity(tmp_path):
    """同名项目出现在两个分组下 → 不猜，返回 None，走待归类。"""
    (tmp_path / "10_项目" / "个人" / "P").mkdir(parents=True)
    (tmp_path / "10_项目" / "工作" / "P").mkdir(parents=True)
    assert find_project_dir(tmp_path, "P") is None


def test_list_projects_returns_group_and_path(tmp_path):
    (tmp_path / "10_项目" / "个人" / "A").mkdir(parents=True)
    (tmp_path / "10_项目" / "工作" / "B").mkdir(parents=True)
    got = list_projects(tmp_path)
    assert [(g, p.name) for g, p in got] == [("个人", "A"), ("工作", "B")]


def test_list_projects_empty_when_absent(tmp_path):
    assert list_projects(tmp_path) == []


# ---------- 索引页（Q56）----------

def test_ensure_topic_index_creates_dataview_page(tmp_path):
    """空库第一天也要有东西可链，否则第一条笔记必然违反 Q21。"""
    path = ensure_topic_index(tmp_path, "后端")
    assert path == tmp_path / INDEX / "后端.md"
    meta, body = read_note(path)
    assert meta["类型"] == "索引"
    assert 'FROM "20_知识/后端"' in body


def test_ensure_topic_index_never_overwrites_user_edits(tmp_path):
    """幂等：用户手改过的索引页不能被服务覆盖回去。"""
    first = ensure_topic_index(tmp_path, "后端")
    first.write_text("用户自己改的内容", encoding="utf-8")
    second = ensure_topic_index(tmp_path, "后端")
    assert second.read_text(encoding="utf-8") == "用户自己改的内容"


# ---------- 原子写 ----------

def test_atomic_write_leaves_no_tmp_file(tmp_path):
    target = tmp_path / "x.md"
    atomic_write(target, "内容")
    assert target.read_text(encoding="utf-8") == "内容"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_creates_parent_dirs(tmp_path):
    target = tmp_path / "深层" / "目录" / "x.md"
    atomic_write(target, "内容")
    assert target.read_text(encoding="utf-8") == "内容"
