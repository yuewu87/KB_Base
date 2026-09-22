"""巡检接进服务：手动跑一次、启动时按需触发。"""

import json

import pytest

from kb.api.http import run_sweep
from kb.core import sweep as sweep_mod
from kb.core.lifecycle import Busy, BusyError
from kb.core.sweep import SweepError
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


def _make_vault(tmp_path):
    """一个已初始化的库。**`.git` 是判据**——`run_sweep` 会自验这一点。"""
    (tmp_path / ".git").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_run_sweep_refuses_a_path_that_is_not_a_vault(tmp_path):
    """**巡检是最会毁东西的那一个，它也得自验。**

    它会把文件从一个分类 `replace()` 到另一个、`rmdir` 掉空目录，再在库里
    `git add` / `commit`。`.env` 里手打成 `KB_VAULT_PATH=.`（`config._build`
    只做 `Path(vault_raw)`，不 resolve、不校验；服务 cwd 是 `PROJECT_ROOT`）
    时，它会**对着 KN_Base 仓库自己**跑一整轮：模型给出
    `{"from": "tests", "to": "src"}` 这种合并，`validate` 照样通过，
    然后项目里的目录就被搬了、还落一个 commit。

    判据和搬家/移除共用 `lifecycle.vault_path_problem`——`run_sweep` 是
    最里面那一层，三个入口（`main()` 的后台线程、`POST /sweep`、
    `/sweep/run`）谁都绕不过去。
    """
    plain = tmp_path / "我的文档"
    plain.mkdir()
    (plain / "重要.txt").write_text("别动我", encoding="utf-8")

    with pytest.raises(SweepError, match="不是一个知识库"):
        run_sweep(plain, tmp_path, FakeLLM(_merge_json()), Busy())

    assert (plain / "重要.txt").is_file()


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

    _two_topics(_make_vault(tmp_path))

    report = run_sweep(tmp_path, tmp_path, FakeLLM(_merge_json()), Busy())
    assert report["tag_merges"] or report["dir_merges"]
    assert load_state(tmp_path)["report"]["read"] is False


def test_run_sweep_on_clean_vault_reports_nothing(tmp_path):
    (tmp_path / "计算机").mkdir(parents=True)
    _make_vault(tmp_path)
    report = run_sweep(
        tmp_path, tmp_path,
        FakeLLM('{"tag_merges": [], "dir_merges": []}'), Busy(),
    )
    assert report["summary"] is not None


def test_run_sweep_holds_the_lock_only_while_touching_files(tmp_path, monkeypatch):
    """**规划那一段不占锁**——它最长（一次 LLM 调用），而且只读。

    锁原先是在三个调用点各挂一次、把整轮巡检（含规划）全罩住：冷启动那轮
    后台巡检一跑几十秒到几分钟，期间**所有写入口都 409**，而 `POST /new`
    是个纯 HTML 表单——浏览器把 `{"detail": …}` 直接渲染成一页，
    **用户刚写的正文既没落草稿也没进 vault**。真正需要互斥的是「两个写者
    交错」（迁移搬到一半巡检插进来），那只发生在动文件那一段。
    """
    _two_topics(_make_vault(tmp_path))
    busy = Busy()
    real = sweep_mod.make_plan

    def spy(vault_root, llm):
        assert busy.what is None, "规划的时候锁不该被占着"
        return real(vault_root, llm)

    monkeypatch.setattr(sweep_mod, "make_plan", spy)

    report = run_sweep(tmp_path, tmp_path, FakeLLM(_merge_json()), busy)

    assert report["tag_merges"] or report["dir_merges"]
    assert busy.what is None                      # 跑完照样还回去


def test_run_sweep_refuses_at_the_write_step_not_before(tmp_path):
    """有人在动文件时，巡检**在动文件那一步**失败，而且一根汗毛都不动。

    它抛 `BusyError`（不是 `SweepError`）——调用方要能把它映成 409 / 一份
    「被挡住了」的报告，而不是当成「巡检自己坏了」。
    """
    _two_topics(_make_vault(tmp_path))
    busy = Busy()
    assert busy.acquire("organize") is True
    try:
        with pytest.raises(BusyError, match="整理"):
            run_sweep(tmp_path, tmp_path, FakeLLM(_merge_json()), busy)
    finally:
        busy.release()

    assert (tmp_path / "计算机" / "git" / "a.md").is_file()   # 一个文件都没动
    assert (tmp_path / "计算机" / "版本控制" / "b.md").is_file()
