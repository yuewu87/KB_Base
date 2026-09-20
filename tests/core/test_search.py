"""检索（Q25：标签是检索主力）。"""
from kb.core.search import search_notes
from kb.core.vault import mark_superseded, write_note


def _note(root, domain, name, tags, body):
    write_note(root / domain / f"{name}.md", {"类型": "概念", "主题": tags}, body)


def test_search_matches_body(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["计算机"], "并发写入会锁表")
    _note(tmp_path, "艺术", "一点透视", ["艺术"], "近大远小")
    hits = search_notes(tmp_path, "锁表")
    assert [h.path.stem for h in hits] == ["队列串行化"]


def test_search_matches_tag(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["并发"], "内容无关")
    assert [h.path.stem for h in search_notes(tmp_path, "并发")] == ["队列串行化"]


def test_search_matches_title(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["计算机"], "内容无关")
    assert [h.path.stem for h in search_notes(tmp_path, "队列")] == ["队列串行化"]


def test_search_skips_superseded(tmp_path):
    """失效的默认不出现在检索结果里（Q60）。"""
    _note(tmp_path, "计算机", "旧结论", ["计算机"], "锁表")
    mark_superseded(tmp_path / "计算机" / "旧结论.md", by="新结论")
    assert search_notes(tmp_path, "锁表") == []


def test_search_returns_superseded_when_rebuilding(tmp_path):
    """点时间查——把历史也要回来。"""
    _note(tmp_path, "计算机", "旧结论", ["计算机"], "锁表")
    mark_superseded(tmp_path / "计算机" / "旧结论.md", by="新结论")
    hits = search_notes(tmp_path, "锁表", include_superseded=True)
    assert [h.path.stem for h in hits] == ["旧结论"]


# ---------- 命中项要带正文（Q103）----------

def test_hit_carries_the_body(tmp_path):
    """**这是这一版的重点。** 以前只回路径，调用方拿到的是一个「索引记录」，
    读不出内容——会话层只能再说一句「要我把调出来读给你听吗」。
    """
    _note(tmp_path, "计算机", "队列串行化", ["并发"], "# 队列串行化\n\n并发写入会锁表")
    (hit,) = search_notes(tmp_path, "锁表")
    assert "并发写入会锁表" in hit.body


def test_hit_title_prefers_the_first_heading(tmp_path):
    """标题取正文里的一级标题——那才是「一句话结论」，文件名只是它的退化。"""
    _note(tmp_path, "计算机", "文件名不是标题", ["并发"], "# 真正的标题\n\n锁表")
    (hit,) = search_notes(tmp_path, "锁表")
    assert hit.title == "真正的标题"


def test_hit_title_falls_back_to_the_filename(tmp_path):
    """正文是空的（只有 frontmatter）才退回文件名。

    注意「没有 `# ` 标题」不算这种情形——那时退回的是**首个非空行**，
    见 `vault.first_heading`。所以要让这条测到文件名，正文得真的是空的。
    """
    _note(tmp_path, "计算机", "只有文件名", ["并发"], "")
    (hit,) = search_notes(tmp_path, "并发")
    assert hit.title == "只有文件名"


def test_hit_carries_tags(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["并发", "数据库"], "锁表")
    (hit,) = search_notes(tmp_path, "锁表")
    assert hit.tags == ["并发", "数据库"]


def test_hit_tags_of_a_note_with_no_tags_is_empty(tmp_path):
    """没标签就是空列表，不是 None——调用方 `'、'.join` 时不至于炸。"""
    _note(tmp_path, "计算机", "队列串行化", [], "锁表")
    (hit,) = search_notes(tmp_path, "锁表")
    assert hit.tags == []


def test_hit_path_is_the_file_it_came_from(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["并发"], "锁表")
    (hit,) = search_notes(tmp_path, "锁表")
    assert hit.path == tmp_path / "计算机" / "队列串行化.md"
