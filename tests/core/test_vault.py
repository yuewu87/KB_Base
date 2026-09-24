import re
from datetime import datetime

import pytest

from kb.core.models import Draft
from kb.core.vault import (
    INBOX,
    INDEX,
    PENDING,
    atomic_write,
    clean_title,
    counts,
    draft_path,
    ensure_topic_index,
    find_draft,
    list_classifications,
    list_domains,
    list_drafts,
    list_notes,
    move_to_pending,
    new_draft_id,
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
    path = tmp_path / "计算机" / "并发写锁.md"
    write_note(path, {"类型": "概念", "主题": ["计算机"]}, "# 并发写锁\n")
    meta, body = read_note(path)
    assert meta["类型"] == "概念"
    assert meta["主题"] == ["计算机"]
    assert body.strip() == "# 并发写锁"


def test_write_note_drops_none_values(tmp_path):
    """值为 None 的键直接不写——否则 YAML 里会出现 `项目: null`。"""
    path = tmp_path / "note.md"
    write_note(path, {"类型": "概念", "项目": None}, "正文")
    assert "null" not in path.read_text(encoding="utf-8")


def test_list_notes_covers_domains_and_meta(tmp_path):
    """扫正式笔记，不扫 _索引/。"""
    write_note(tmp_path / "计算机" / "a.md", {"类型": "概念"}, "a")
    write_note(tmp_path / "计算机" / "b.md", {"类型": "踩坑"}, "b")
    write_note(tmp_path / "_索引" / "计算机.md", {"类型": "索引"}, "不该被扫到")
    names = {p.name for p in list_notes(tmp_path)}
    assert names == {"a.md", "b.md"}


# ---------- 索引页（Q56）----------

def test_ensure_topic_index_creates_dataview_page(tmp_path):
    """空库第一天也要有东西可链，否则第一条笔记必然违反 Q21。"""
    path = ensure_topic_index(tmp_path, "计算机")
    assert path == tmp_path / INDEX / "计算机.md"
    meta, body = read_note(path)
    assert meta["类型"] == "索引"
    assert 'FROM "计算机"' in body


def test_ensure_topic_index_never_overwrites_user_edits(tmp_path):
    """幂等：用户手改过的索引页不能被服务覆盖回去。"""
    first = ensure_topic_index(tmp_path, "计算机")
    first.write_text("用户自己改的内容", encoding="utf-8")
    second = ensure_topic_index(tmp_path, "计算机")
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


# ---------- 领域（Q67）----------

def test_list_domains_reads_top_level_dirs(tmp_path):
    """一级目录里不带 _ 前缀的就是领域。"""
    (tmp_path / "计算机").mkdir()
    (tmp_path / "艺术").mkdir()
    (tmp_path / "_收件箱").mkdir()
    (tmp_path / "_索引").mkdir()
    (tmp_path / ".obsidian").mkdir()
    assert list_domains(tmp_path) == ["艺术", "计算机"]


def test_list_domains_empty_when_only_meta(tmp_path):
    (tmp_path / "_收件箱").mkdir()
    assert list_domains(tmp_path) == []


def test_list_domains_ignores_files(tmp_path):
    (tmp_path / "计算机").mkdir()
    (tmp_path / "note.md").write_text("x", encoding="utf-8")
    assert list_domains(tmp_path) == ["计算机"]


# ---------- 领域下的分类（提示词要列给模型看）----------

def test_list_classifications_empty_domain(tmp_path):
    """空领域与不存在的领域都返回空列表，不抛异常。"""
    (tmp_path / "艺术").mkdir()
    assert list_classifications(tmp_path, "艺术") == []
    assert list_classifications(tmp_path, "根本没有这个领域") == []


def test_list_classifications_one_layer(tmp_path):
    (tmp_path / "计算机" / "git").mkdir(parents=True)
    (tmp_path / "计算机" / "版本控制").mkdir(parents=True)
    assert list_classifications(tmp_path, "计算机") == ["git", "版本控制"]


def test_list_classifications_two_layers(tmp_path):
    """是递归的：路径相对领域根，不是只取一层。"""
    (tmp_path / "计算机" / "git" / "底层").mkdir(parents=True)
    assert list_classifications(tmp_path, "计算机") == ["git", "git/底层"]


# ---------- 标题清洗（Q72）----------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("正常标题", "正常标题"),
        ("含/斜杠", "含斜杠"),
        (r'含\反斜杠', "含反斜杠"),
        ('含:冒号*星号?问号"引号<尖>括号|竖线', "含冒号星号问号引号尖括号竖线"),
        ("  首尾空格  ", "首尾空格"),
        ("结尾有点...", "结尾有点"),
        ("a" * 80, "a" * 60),
    ],
)
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


def test_clean_title_rejects_empty():
    with pytest.raises(ValueError):
        clean_title("///")


# ---------- 库的规模（对话统计与桌宠共用） ----------

def test_counts_counts_notes_and_drafts(tmp_path):
    """数两样：正式笔记、待整理草稿。**判据只此一份。**"""
    write_note(
        tmp_path / "计算机" / "甲.md", {"类型": "概念", "主题": ["计算机"]}, "x"
    )
    write_note(
        tmp_path / "计算机" / "乙.md", {"类型": "概念", "主题": ["计算机"]}, "y"
    )
    write_draft(tmp_path, _draft(id="20260915-aaaa"))

    assert counts(tmp_path) == {"notes": 2, "drafts": 1}


def test_counts_on_a_dir_that_is_not_a_vault(tmp_path):
    """目录都不存在时返回 0，**不抛**。

    它会被**每一条对话**和 `/setup/state` 调到——抛出去就是整块界面死掉
    （`/setup/state` 是每个页面首屏都要打的端点）。
    """
    assert counts(tmp_path / "还没有这个目录") == {"notes": 0, "drafts": 0}


def test_counts_does_not_crash_when_the_path_is_a_file(tmp_path):
    """路径存在但是个**文件**时返回 0，**不抛**。

    `.env` 里 KB_VAULT_PATH 打错一个字符指到一个已有的文件上，走的就是这条。
    而 `/setup/state` 是每个页面首屏都要打的端点、`counts` 还被**每一轮对话**
    调到——抛出去就是整块界面死掉（2026-09-24 实测复现过：改前 `/chat` 200、
    改后 500）。

    这是**结果**那一半；**原因**钉在下面 `list_domains` 那条上。
    """
    a_file = tmp_path / "其实是个文件"
    a_file.write_text("x", encoding="utf-8")

    assert counts(a_file) == {"notes": 0, "drafts": 0}


def test_list_domains_on_a_file_returns_empty(tmp_path):
    """**根因这一处**：路径是个文件时返回空，不抛。

    崩溃本来发生在这个函数里的 `iterdir()` 上——它上一行判的是 `exists()`，
    而「存在」对文件也成立。

    为什么不只钉 `counts` 那条：`list_domains` / `list_notes` 还有**别的调用方**
    （`find_note_by_stem`、规划那条链），它们不经过 `counts`，却同样站在这条
    会发生 `NotADirectoryError` 的链上。
    """
    a_file = tmp_path / "其实是个文件"
    a_file.write_text("x", encoding="utf-8")

    assert list_domains(a_file) == []
