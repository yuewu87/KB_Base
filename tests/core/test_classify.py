from pathlib import Path

from kb.core.classify import (
    bigrams,
    find_candidates,
    note_title_and_tags,
    similarity,
)

# `first_heading` 2026-09-18 搬到了 vault（检索也要用它，见 Q103）。
from kb.core.vault import first_heading, write_note


def _note(root: Path, rel: str, body: str, tags: list[str] | None = None) -> Path:
    path = root / rel
    write_note(path, {"类型": "概念", "主题": tags or []}, body)
    return path


# ---------- 2-gram ----------

def test_bigrams_ignores_whitespace():
    assert bigrams("并发 写入") == bigrams("并发写入")


def test_bigrams_of_single_char():
    assert bigrams("锁") == {"锁"}


def test_bigrams_of_empty_string():
    assert bigrams("   ") == set()


# ---------- 相似度 ----------

def test_identical_text_scores_one():
    assert similarity("并发写入会锁表", "并发写入会锁表") == 1.0


def test_unrelated_text_scores_zero():
    assert similarity("并发写入会锁表", "红烧肉的做法") == 0.0


def test_similarity_is_between_zero_and_one():
    s = similarity("并发写入会锁表", "并发写入偶尔锁表")
    assert 0.0 < s < 1.0


def test_similarity_with_empty_side_is_zero():
    assert similarity("", "任意内容") == 0.0


# ---------- 标题提取 ----------

def test_first_heading_prefers_h1():
    assert first_heading("前言\n# 并发写锁\n正文") == "并发写锁"


def test_first_heading_falls_back_to_first_nonempty_line():
    assert first_heading("\n\n没有标题的行\n后面") == "没有标题的行"


def test_first_heading_of_empty_body():
    assert first_heading("   \n\n") == ""


# ---------- 候选召回 ----------

def test_find_candidates_ranks_similar_first(tmp_path):
    _note(tmp_path, "计算机/后端/并发写锁.md", "# 并发写入会锁表\n")
    _note(tmp_path, "计算机/前端/居中布局.md", "# 用 flex 居中\n")

    got = find_candidates(tmp_path, "并发写入的时候会锁表，怎么办")
    assert got[0].title == "并发写入会锁表"


def test_find_candidates_scores_body_against_body(tmp_path):
    """**打分的两侧要同量级。** 拿「草稿正文」对「标题 + 标签」的话，Jaccard
    的并集被正文撑满，分数全挤在 0.04–0.11，排序不带信息。

    这条钉的是「正文是打分的依据」：三篇笔记里，只有目标那篇的**正文**跟
    查询重合，标题一个是「甲」一个是「乙」——旧算法会随机挑一个，
    新算法必须把目标排第一。
    """
    _note(tmp_path, "计算机/甲.md", "队列串行化解决并发写锁表\n")
    _note(tmp_path, "计算机/乙.md", "完全不搭界的一段话\n")
    target = _note(tmp_path, "计算机/目标.md", "并发写锁表最后用队列串行化解决\n")

    got = find_candidates(tmp_path, "并发写锁表最后用队列串行化解决", limit=3)

    assert got[0].path == target


def test_find_candidates_falls_back_to_title_for_an_empty_body(tmp_path):
    """正文空的笔记退回用标题打分——否则那条恒得 0 分、永远垫底，
    而它可能正是要 fold 进去的那一篇。"""
    empty = tmp_path / "计算机" / "空笔记.md"
    empty.parent.mkdir(parents=True, exist_ok=True)
    empty.write_text("---\n类型: 概念\n---\n", encoding="utf-8")

    got = find_candidates(tmp_path, "空笔记", limit=1)

    assert got[0].path == empty


def test_find_candidates_respects_limit(tmp_path):
    for i in range(5):
        _note(tmp_path, f"计算机/后端/n{i}.md", f"# 并发写入会锁表 {i}\n")
    assert len(find_candidates(tmp_path, "并发写入会锁表", limit=3)) == 3


def test_find_candidates_returns_empty_for_empty_vault(tmp_path):
    assert find_candidates(tmp_path, "任意内容") == []


def test_find_candidates_uses_tags_as_signal(tmp_path):
    """标题不含关键词，但主题标签命中的笔记也应被召回。"""
    _note(tmp_path, "计算机/后端/杂记.md", "# 一些零散的记录\n", tags=["并发", "锁"])
    got = find_candidates(tmp_path, "并发 锁")
    assert got[0].path.name == "杂记.md"


def test_candidates_are_sorted_by_score_desc(tmp_path):
    _note(tmp_path, "计算机/后端/a.md", "# 并发写入会锁表\n")
    _note(tmp_path, "计算机/后端/b.md", "# 并发\n")
    got = find_candidates(tmp_path, "并发写入会锁表")
    assert [c.score for c in got] == sorted([c.score for c in got], reverse=True)


def test_candidate_carries_path_and_tags(tmp_path):
    path = _note(tmp_path, "计算机/后端/杂记.md", "# 记录\n", tags=["后端"])
    got = find_candidates(tmp_path, "记录")
    assert got[0].path == path
    assert got[0].tags == ["后端"]


# ---------- 标题标签读取 ----------

def test_note_title_and_tags_falls_back_to_stem(tmp_path):
    """正文没有标题时用文件名兜底，而不是给出空标题。"""
    path = tmp_path / "无标题.md"
    write_note(path, {"类型": "概念", "主题": ["后端"]}, "只有正文，没标题\n")
    title, tags = note_title_and_tags(path)
    assert title == "只有正文，没标题"
    assert tags == ["后端"]


def test_note_title_and_tags_normalizes_single_string_tag(tmp_path):
    """YAML 里写成 `主题: 后端`（字符串而非列表）时也要能用。"""
    path = tmp_path / "x.md"
    path.write_text("---\n主题: 后端\n---\n\n# 标题\n", encoding="utf-8")
    _, tags = note_title_and_tags(path)
    assert tags == ["后端"]
