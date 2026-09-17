"""对话能力：LLM 选动作，代码执行，结果回喂。"""

import json

from kb.core.chat import MAX_ROUNDS, parse_reply, run_turn
from kb.llm.base import FakeLLM


def _reply(say="收到", action=None, params=None, ask=None):
    return json.dumps(
        {"say": say, "action": action, "params": params or {}, "ask": ask},
        ensure_ascii=False,
    )


def test_parse_reply_plain_json():
    got = parse_reply(_reply("你好"))
    assert got["say"] == "你好"
    assert got["action"] is None


def test_parse_reply_strips_fence():
    got = parse_reply(f"```json\n{_reply('好')}\n```")
    assert got["say"] == "好"


def test_parse_reply_bad_json_raises():
    import pytest

    from kb.core.chat import ChatError

    with pytest.raises(ChatError):
        parse_reply("这不是 JSON")


def test_run_turn_no_action_ends_immediately(tmp_path):
    llm = FakeLLM([_reply("好的，我记下了")])
    messages, rounds = run_turn(tmp_path, [], "记一下 X", llm)
    assert rounds == 1
    assert messages[-1]["content"] == "好的，我记下了"


def test_run_turn_executes_action_then_reports(tmp_path):
    """第一轮选 search，第二轮总结。"""
    llm = FakeLLM([
        _reply("我先查查", action="search", params={"query": "锁表"}),
        _reply("查到了，没有相关笔记"),
    ])
    messages, rounds = run_turn(tmp_path, [], "锁表是怎么说的", llm)
    assert rounds == 2
    # 中间那轮的工具结果要进历史，模型才看得到
    assert any("工具结果" in m["content"] for m in messages)
    assert messages[-1]["content"] == "查到了，没有相关笔记"


def test_run_turn_stops_at_max_rounds(tmp_path):
    """模型一直要动作也不会转不完——有上限。"""
    llm = FakeLLM([
        _reply(action="search", params={"query": "x"}) for _ in range(MAX_ROUNDS + 3)
    ])
    _, rounds = run_turn(tmp_path, [], "一直查", llm)
    assert rounds == MAX_ROUNDS


def test_run_turn_reports_unknown_action_back_to_model(tmp_path):
    """模型给了个不存在的动作——不炸，把错误喂回去让它自己改。"""
    llm = FakeLLM([
        _reply(action="放火", params={}),
        _reply("我换个说法"),
    ])
    messages, _ = run_turn(tmp_path, [], "放火", llm)
    assert any("未知动作" in m["content"] for m in messages)


def test_run_turn_carries_prior_messages(tmp_path):
    llm = FakeLLM([_reply("接着上次说")])
    prior = [
        {"role": "user", "content": "上一轮的话"},
        {"role": "assistant", "content": "上一轮的回"},
    ]
    messages, _ = run_turn(tmp_path, prior, "继续", llm)
    assert messages[0]["content"] == "上一轮的话"


def test_render_history_labels_tool_separately():
    """`tool` 不能和 `assistant` 一样都叫「助手」。

    否则模型看到的是「我上一条说：工具结果（search）…」——那是它自己说的话，
    不是它拿到的数据，它会当成「我已经说过了」而不去用。
    """
    from kb.core.chat import _render_history

    text = _render_history([
        {"role": "user", "content": "查锁表"},
        {"role": "assistant", "content": "我查查"},
        {"role": "tool", "content": "没找到"},
    ])
    assert "**工具结果**：没找到" in text
    assert "**助手**：没找到" not in text


def test_run_turn_labels_tool_result_in_same_turn(tmp_path):
    """整轮跑下来也一样——工具结果在同一轮里就不能被标成助手。

    这条守的是跨轮之外的场景：`run_turn` 自己的循环里也会 `_render_history`。
    """
    seen: list[str] = []

    class _Spy:
        def __init__(self, replies):
            self._inner = FakeLLM(replies)

        def complete(self, system, user):
            seen.append(user)
            return self._inner.complete(system, user)

    llm = _Spy([
        _reply("我查查", action="search", params={"query": "锁表"}),
        _reply("没有相关的"),
    ])
    run_turn(tmp_path, [], "查锁表", llm)
    # 第二轮时历史上已经有 tool 消息了
    assert "**工具结果**" in seen[1]
    assert "**助手**：没找到" not in seen[1]
