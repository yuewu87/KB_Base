"""审核：新分类与已有分类是否近义（Q78）。"""
from kb.core.models import OrganizePlan, Outcome
from kb.core.review import new_dirs_in, review_plan
from kb.llm.base import FakeLLM


def _plan(target_path: str) -> OrganizePlan:
    return OrganizePlan(
        draft_id="20260916-a3f2",
        outcome=Outcome.CREATE,
        target_path=target_path,
        frontmatter={"类型": "概念", "主题": ["计算机"]},
        content="# x\n\n[[某篇]]\n",
    )


def test_new_dirs_in_lists_missing_layers(tmp_path):
    (tmp_path / "计算机" / "版本控制").mkdir(parents=True)
    assert new_dirs_in(tmp_path, "计算机/版本控制/a.md") == []
    assert new_dirs_in(tmp_path, "计算机/git/a.md") == ["git"]
    assert new_dirs_in(tmp_path, "计算机/git/底层/a.md") == ["git", "底层"]


def test_review_skipped_when_no_new_dirs(tmp_path):
    """没新建分类就不调 LLM——不做无谓的往返。"""
    (tmp_path / "计算机" / "版本控制").mkdir(parents=True)
    llm = FakeLLM([])           # 队列为空；一旦被调用就会抛错
    plan = _plan("计算机/版本控制/a.md")
    assert review_plan(plan, tmp_path, llm) == plan


def test_review_rewrites_path_when_llm_says_reuse(tmp_path):
    """LLM 判定近义 → 改用已有分类。"""
    (tmp_path / "计算机" / "版本控制").mkdir(parents=True)
    llm = FakeLLM(['{"target_path": "计算机/版本控制/a.md"}'])
    got = review_plan(_plan("计算机/git/a.md"), tmp_path, llm)
    assert got.target_path == "计算机/版本控制/a.md"


def test_review_keeps_path_when_llm_says_ok(tmp_path):
    (tmp_path / "计算机" / "版本控制").mkdir(parents=True)
    llm = FakeLLM(['{"target_path": "计算机/git/a.md"}'])
    got = review_plan(_plan("计算机/git/a.md"), tmp_path, llm)
    assert got.target_path == "计算机/git/a.md"
