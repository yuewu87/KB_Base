"""巡检接进服务：手动跑一次、启动时按需触发。"""

import json

from kb.api.http import run_sweep
from kb.core.vault import write_note
from kb.llm.base import FakeLLM


def _merge_json() -> str:
    """一份合法的合并计划——`to` 都是库里已有的名字（校验要求）。"""
    return json.dumps(
        {
            "tag_merges": [{"from": "git", "to": "版本控制"}],
            "dir_merges": [{"from": "计算机/git", "to": "计算机/版本控制"}],
            "summary": "把 git 并进版本控制",
        },
        ensure_ascii=False,
    )


def _two_topics(tmp_path) -> None:
    write_note(
        tmp_path / "计算机" / "git" / "a.md",
        {"类型": "概念", "主题": ["计算机", "git"]},
        "x",
    )
    write_note(
        tmp_path / "计算机" / "版本控制" / "b.md",
        {"类型": "概念", "主题": ["计算机", "版本控制"]},
        "y",
    )


def test_run_sweep_saves_report(tmp_path):
    from kb.core.sweep_state import load_state

    _two_topics(tmp_path)

    report = run_sweep(tmp_path, tmp_path, FakeLLM(_merge_json()))
    assert report["tag_merges"] or report["dir_merges"]
    assert load_state(tmp_path)["report"]["read"] is False


def test_run_sweep_on_clean_vault_reports_nothing(tmp_path):
    (tmp_path / "计算机").mkdir(parents=True)
    report = run_sweep(tmp_path, tmp_path, FakeLLM('{"tag_merges": [], "dir_merges": []}'))
    assert report["summary"] is not None


# ---------- 透传用户要求（Q96）----------

class _CaptureLLM:
    """留下一份提示词，好断言要求进没进。空计划——不落盘。"""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.seen.append((system, user))
        return '{"tag_merges": [], "dir_merges": [], "summary": "无"}'


def test_run_sweep_passes_requirement_to_the_model(tmp_path):
    """用户的要求要真的进到模型手里。"""
    _two_topics(tmp_path)

    llm = _CaptureLLM()
    run_sweep(tmp_path, tmp_path, llm, requirement="那两个分类不该合并")

    assert "那两个分类不该合并" in llm.seen[0][0]


def test_run_sweep_without_requirement_unchanged(tmp_path):
    """不传要求时，prompt 与以前一样——不许回归。"""
    _two_topics(tmp_path)

    llm = _CaptureLLM()
    run_sweep(tmp_path, tmp_path, llm)
    assert "用户对上次结果的意见" not in llm.seen[0][0]
