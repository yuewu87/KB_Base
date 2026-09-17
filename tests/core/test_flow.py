"""流程日志：自然语言，一条一个动作（Q89）。存服务侧，不进 vault。"""

import pytest

from kb.core import flow
from kb.core.flow import STEPS, emit, read_flow, set_run


@pytest.fixture(autouse=True)
def _reset():
    """每个测试前后都把模块状态清干净——它是模块级的，会串。"""
    flow.configure(None)
    set_run("")
    yield
    flow.configure(None)
    set_run("")


def _boom(*_args, **_kwargs):
    raise OSError("磁盘满了")


def test_emit_writes_jsonl(tmp_path):
    flow.configure(tmp_path)
    emit("投递", "你在网页上投递了一条草稿")

    rows = read_flow(tmp_path)
    assert len(rows) == 1
    assert rows[0]["step"] == "投递"
    assert rows[0]["text"] == "你在网页上投递了一条草稿"
    assert rows[0]["at"]


def test_emit_is_noop_when_not_configured(tmp_path):
    """没配落点就不记——不抛、也不往别处写。"""
    emit("投递", "x")
    assert read_flow(tmp_path) == []


def test_emit_never_raises_on_write_failure(tmp_path, monkeypatch):
    """写日志失败不该让正事挂掉——日志是附属品。"""
    flow.configure(tmp_path)
    monkeypatch.setattr(flow.Path, "open", _boom)

    emit("投递", "x")          # 不抛


def test_set_run_tags_subsequent_entries(tmp_path):
    flow.configure(tmp_path)
    set_run("20260917-1400")
    emit("投递", "a")
    assert read_flow(tmp_path)[0]["run"] == "20260917-1400"


def test_read_flow_missing_file(tmp_path):
    assert read_flow(tmp_path) == []


def test_read_flow_skips_broken_lines(tmp_path):
    """半行（进程被杀）跳过，别让整页挂掉。"""
    flow.configure(tmp_path)
    emit("投递", "好的")
    path = tmp_path / "logs" / "flow.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"step": "规划", "tex')      # 截断的半行

    rows = read_flow(tmp_path)
    assert [r["text"] for r in rows] == ["好的"]


def test_emit_rotates_when_large(tmp_path, monkeypatch):
    """超过上限就轮转一份，别让单文件无限长。"""
    monkeypatch.setattr(flow, "MAX_BYTES", 10)
    flow.configure(tmp_path)
    emit("投递", "第一条够长了")
    emit("投递", "第二条")

    assert (tmp_path / "logs" / "flow.jsonl.1").is_file()
    assert [r["text"] for r in read_flow(tmp_path)] == ["第二条"]


def test_steps_are_the_pipeline_order():
    """链上的顺序就是流水线的顺序——页面的流程图照它画。"""
    assert STEPS == ["投递", "规划", "校验", "审核", "落盘", "提交"]
