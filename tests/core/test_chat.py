"""对话能力：LLM 选动作，代码执行，结果回喂。"""

import json

from kb.core.chat import (
    MAX_ROUNDS,
    build_system_prompt,
    handle,
    parse_reply,
    run_turn,
    run_turn_stream,
)
from kb.core.chat_store import load_chat
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
    # 中间那轮的工具结果要进历史，模型才看得到。
    # 断言的是**动作算出来的那串文本本身**——`tool` 轮没裹「工具结果（搜索）：」
    # 那层壳了：它现在要同时给人看（前端直接渲染），壳在 `_render_history`
    # 渲染时按角色加（见 `run_turn_stream`）。
    tool = next(m for m in messages if m["role"] == "tool")
    assert "没找到关于「锁表」" in tool["content"]
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


# ---------- 系统提示里的库规模 ----------

def test_system_prompt_carries_the_library_size(tmp_path):
    """对话要答得出「库里有多少条」——它得**先知道**。

    这条是那个需求的全部实现：不新增动作，直接把两个数写进系统提示。
    """
    from kb.core.vault import write_note

    (tmp_path / ".git").mkdir()          # 判据是 vault_ready，它认这个
    write_note(
        tmp_path / "计算机" / "甲.md", {"类型": "概念", "主题": ["计算机"]}, "x"
    )

    prompt = build_system_prompt(tmp_path)

    assert "1 篇笔记" in prompt
    assert "0 条待整理" in prompt


def test_system_prompt_says_so_when_there_is_no_vault(tmp_path):
    """没库时写「还没有知识库」，**不是「0 篇笔记」**。

    后者看着像库坏了；前者才是实话。

    **两个形状都要盖**：没配路径（`None`）、以及**配了路径但那儿不是个库**。
    后者才是线上真会碰到的那个——`None` 在 `vault_guard` 那儿就 409 了，
    只有测试递得进来。第一版只判 `None`，于是「路径打错一个字符」时系统提示
    照写「0 篇笔记 · 0 条待整理」，而同一时刻 `/setup/state` 报
    `initialized: false`、桌宠气泡说「还没有知识库」——三个面互相打脸。
    """
    assert "还没有知识库" in build_system_prompt(None)
    # 配了路径、但那儿没有 `.git` → 仍然不是库
    assert "还没有知识库" in build_system_prompt(tmp_path)


def test_run_turn_feeds_the_prompt_with_the_vault(tmp_path):
    """`run_turn` 要**把库传进去**——不传的话上面那段永远不出现。

    照着本文件已有的 `_Spy` 写法：截住 `system`，看它带没带那两个数。
    """
    from kb.core.vault import write_note

    (tmp_path / ".git").mkdir()          # 判据是 vault_ready，它认这个
    write_note(
        tmp_path / "计算机" / "甲.md", {"类型": "概念", "主题": ["计算机"]}, "x"
    )
    seen: list[str] = []

    class _Spy:
        def __init__(self, replies):
            self._inner = FakeLLM(replies)

        def complete(self, system, user):
            seen.append(system)
            return self._inner.complete(system, user)

    run_turn(tmp_path, [], "库里有多少条", _Spy([_reply("1 篇")]))

    assert "1 篇笔记" in seen[0]


# ---------- 流式事件 ----------

def test_run_turn_stream_emits_say_then_action_then_result(tmp_path):
    """一次带动作的跑，事件顺序是 say → action → result → done。"""
    llm = FakeLLM([
        _reply("好，我这就去存", action="search", params={"query": "x"}),
        _reply("查完了"),
    ])
    events = list(run_turn_stream(tmp_path, [], "查一下 x", llm))
    kinds = [e["type"] for e in events]

    assert kinds == ["say", "action", "result", "say", "done"]
    # 动作事件要带上动作名，前端才有机会按动作区分
    assert [e for e in events if e["type"] == "action"][0]["name"] == "search"
    # 最后那个 done 要把完整消息列表带出来，调用方靠它落盘
    assert events[-1]["messages"][-1]["role"] == "assistant"


def test_run_turn_stream_emits_error_at_max_rounds(tmp_path):
    """撞满上限时吐一个 error 事件——前端照着画红气泡。"""
    llm = FakeLLM([
        _reply(action="search", params={"query": "x"}) for _ in range(MAX_ROUNDS)
    ])
    events = list(run_turn_stream(tmp_path, [], "一直查", llm))

    assert events[-2]["type"] == "error"
    assert "圈数" in events[-2]["text"]
    assert events[-1]["type"] == "done"


def test_run_turn_stream_still_emits_done_when_the_action_blows_up(tmp_path):
    """动作抛异常（线上就是「没配库」那条）也要吐 `done`。

    `run_action` 只保证**自己**不抛——它管不住调用方传进来的回调
    （`api/http.py` 那份会走到 `require_vault`）。异常若逃出生成器，
    `done` 就没了，那轮对话一个字节都落不下盘。
    """
    def boom(*_):
        raise RuntimeError("没配库")

    llm = FakeLLM([
        _reply("我记一下", action="push", params={"content": "X"}),
        _reply("先不记了"),
    ])
    events = list(run_turn_stream(tmp_path, [], "记一下 X", llm, organize_fn=boom))
    kinds = [e["type"] for e in events]

    assert kinds == ["say", "action", "result", "say", "done"]
    assert "没配库" in [e["text"] for e in events if e["type"] == "result"][0]


def test_run_turn_stream_skips_an_empty_say(tmp_path):
    """模型回一条空话、又不要动作——不吐空事件，也不落一条空 assistant。

    空了还照吐，前端就会画一个空气泡；照存，回看时是一行光秃秃的
    「**助手**：」，像坏了。
    """
    llm = FakeLLM([_reply("", action=None)])
    events = list(run_turn_stream(tmp_path, [], "在吗", llm))

    assert [e["type"] for e in events] == ["done"]
    assert events[-1]["messages"] == [{"role": "user", "content": "在吗"}]


# ---------- 落盘 ----------

def test_handle_keeps_the_steps_but_only_the_last_one_is_the_reply(tmp_path):
    """过程要留下（存进会话），但**过渡语不能冒充回复**。

    ⚠️ 「过渡语留下了」和「它不是回复」是两件事，靠 role 分开（见
    `run_turn_stream` 的 docstring）：中间那句 `say` 存成 `step`，只有最后的
    `assistant` 是回复——刷新后前端分不出来就会画成两条回复（一问两答）。
    """
    llm = FakeLLM([
        _reply("我这就去查", action="search", params={"query": "x"}),
        _reply("查到了 1 篇"),
    ])
    chat_id, reply = handle(tmp_path, tmp_path, None, "查一下", llm)

    assert reply == "查到了 1 篇"                     # 回复是结论
    chat = load_chat(tmp_path, chat_id)
    roles = [m["role"] for m in chat["messages"]]
    assert roles == ["user", "step", "tool", "assistant"]   # 过程留下了，回复只一条
    assert chat["messages"][1]["content"] == "我这就去查"    # 过渡语也在，但是步骤
    # 「给人看的样子」= `run_action` 的返回值本身。**`search` 是唯一的例外**：
    # 它返回的是带正文的多行文本（模型靠它答题，见
    # `test_run_search_puts_the_body_in_the_result`），不裹「查库：」那层壳，
    # 所以这里断的是它自己那句「没找到…」。空库里搜什么都不命中。
    assert chat["messages"][2]["content"].startswith("没找到关于")
