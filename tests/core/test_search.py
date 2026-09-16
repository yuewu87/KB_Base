"""检索（Q25：标签是检索主力）。"""
from kb.core.search import search_notes
from kb.core.vault import mark_superseded, write_note


def _note(root, domain, name, tags, body):
    write_note(root / domain / f"{name}.md", {"类型": "概念", "主题": tags}, body)


def test_search_matches_body(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["计算机"], "并发写入会锁表")
    _note(tmp_path, "艺术", "一点透视", ["艺术"], "近大远小")
    hits = search_notes(tmp_path, "锁表")
    assert [h.stem for h in hits] == ["队列串行化"]


def test_search_matches_tag(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["并发"], "内容无关")
    assert [h.stem for h in search_notes(tmp_path, "并发")] == ["队列串行化"]


def test_search_matches_title(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["计算机"], "内容无关")
    assert [h.stem for h in search_notes(tmp_path, "队列")] == ["队列串行化"]


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
    assert [h.stem for h in hits] == ["旧结论"]
