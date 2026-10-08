"""对话能力——「与用户对接的 AI」的核心。

**它是另一个入口，不是一层。** 能力和会话层 AI 相同，只是走 Web 不走 CLI。

## 形态：有界的动作循环

    用户说话
      → LLM 看 [系统提示 + 历史 + 动作清单] → 输出 {say, action, params}
      → 有 action → 代码执行 → 结果回喂 → 再问一轮
      → 没 action → 结束，say 就是回复

**上限 `MAX_ROUNDS` 轮**——模型一直要动作也不会转不完。

**动作的执行归代码**（`actions.run_action`），LLM 只负责「听懂人话、选一个」。
这和整理那条链是同一条原则：每个 LLM 调用点都有确定性校验兜着。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

from kb.core.actions import ACTION_LABELS, describe_actions, run_action
from kb.core.chat_store import load_chat, new_chat_id, save_chat
from kb.core.lifecycle import vault_ready
from kb.core.vault import counts
from kb.llm.base import LLM, LLMError

# **4 轮太小。** 用户在一条消息里列十几个条目、要求「每条单独存」是个常见用法，
# 而 `push` 一次只投一条（`actions.py`）——4 轮只够 4 条，到顶就截断成那句
# 「我转的圈数太多了」。2026-10-08 真撞上过：一条消息列了 10+ 个概念，
# 界面转圈 29 秒，只存进 4 条（`data/chats/20261008-7611.json` + 当天的流程日志）。
#
# 12 覆盖得了「一次列一批」这类用法。再往上就是拿等待时间换条目数了——
# 每轮都是一次对话 LLM + 一条完整整理链，代价不小。
MAX_ROUNDS = 12

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class ChatError(ValueError):
    """模型输出不可用。"""


def _size_line(vault_root: Path | None) -> str:
    """系统提示里那行「库有多大」。

    **没库时说实话**，不写「0 篇笔记」——那个看着像库坏了，而「还没有知识库」
    用户一眼就懂下一步该干什么。

    ⚠️ **判据是 `vault_ready`，不是 `vault_root is None`。** 第一版写的
    `is None`，看着没毛病、其实**判在了不发生的那根轴上**：线上这条路
    （`vault_guard` → `require_vault`）拿不到 `None`，没配路径就 409 了，
    所以 `None` 只有测试摸得到；而真正会走到这儿的，是**「路径配了、
    但那儿不是个库」**——`.env` 里打错一个字符、或者指到一个还没 `init` 的
    目录。那时 `is None` 判不出来，于是系统提示照写「0 篇笔记 · 0 条待整理」，
    同一时刻 `/setup/state` 报 `initialized: false`、桌宠气泡说「还没有知识库」
    ——**三个面互相打脸**。

    而 `lifecycle.vault_ready` 的 docstring 自己写着「**这个判据只有这一份**」
    「别在任何地方再写一遍」。这里就是那个「任何地方」。

    ⚠️ **每轮现算**，不缓存：一轮对话里用户可能刚投了一条，下一轮那个数就该变。
    代价是一次目录扫描（只走目录、不读正文），几十篇是瞬间的事。
    """
    if not vault_ready(vault_root):
        return "还没有知识库"
    counted = counts(vault_root)
    return f"{counted['notes']} 篇笔记 · {counted['drafts']} 条待整理"


def build_system_prompt(vault_root: Path | None) -> str:
    return f"""你是知识库助手，替用户处理他的个人知识库。

**只输出 JSON，不要输出任何其他文字，不要用代码块包裹。**

{{
  "say": "对用户说的话",
  "action": "要执行的动作名，不需要就填 null",
  "params": {{"参数名": "值"}}
}}

## 当前库

{_size_line(vault_root)}

## 你能做的动作

{describe_actions()}

## 怎么用

- 用户想**记东西** → `push`，正文**原样传他说的内容**，不要改写、不要补标题
- 用户想**查东西** → `search`
- 用户想**改东西** → `revise`，target 填笔记文件名（不含 .md）
- 用户说**可以整理了** → `organize`
- 只是闲聊或问你已经知道的事 → `action` 填 null

## 硬规矩

1. **不要替用户写他没说过的内容。** `push` 的 content 只能是他的原话。
2. **一次只做一个动作。** 需要多步（比如先查再改）就先做第一个，
   看到工具结果后再决定下一步。
3. **不要编造检索结果。** 没查就别说得像查过。
4. 动作失败时，把失败原因如实告诉用户，别装作成功。"""


def parse_reply(raw: str) -> dict:
    """解析模型输出。容忍代码块包裹。"""
    text = _FENCE.sub("", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ChatError(f"模型输出不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ChatError("模型输出不是 JSON 对象")
    data.setdefault("say", "")
    data.setdefault("action", None)
    data.setdefault("params", {})
    if not isinstance(data["params"], dict):
        raise ChatError("params 必须是对象")
    return data


_ROLE_LABEL = {"user": "用户", "assistant": "助手", "step": "步骤", "tool": "工具结果"}


def _render_history(messages: list[dict]) -> str:
    """把消息渲染成给模型看的文本。

    **`tool` 必须单独标出来**——不能和 `assistant` 一样都叫「助手」。
    否则同一轮里工具结果会被冠上「助手」，模型看到的是「我上一条说：
    工具结果（search）…」——那是它自己说的话，不是它拿到的数据，
    它会当成「我已经说过了」而不去用。

    **`step`（中间几轮的过渡语）同理**，也不能叫「助手」：模型会以为自己
    已经把结论说过了，于是该总结时不总结（它是**过程**，不是**回答**——
    回答只有最后那条 `assistant`，见 `run_turn_stream`）。
    """
    lines = []
    for m in messages:
        who = _ROLE_LABEL.get(m["role"], "助手")
        lines.append(f"**{who}**：{m['content']}")
    return "\n\n".join(lines)


def run_turn_stream(
    vault_root: Path,
    history: list[dict],
    user_message: str,
    llm: LLM,
    *,
    organize_fn=None,
) -> Iterator[dict]:
    """跑一轮对话，**边跑边吐事件**。

    事件是**给人看的步骤流**（设计见
    `docs/superpowers/specs/2026-10-08-对话流式-design.md`）：

        {"type": "say",    "text": ...}                 模型每轮说的话
        {"type": "action", "name": ..., "text": ...}    动作开始
        {"type": "result", "text": ...}                 动作结果
        {"type": "error",  "text": ...}                 出错（含撞上限）
        {"type": "done",   "messages": [...], "rounds": n}   收尾

    **`done` 一定在最后，且一定被吐出来**——正常结束、LLM 出错、输出解析失败、
    动作抛异常、撞满上限，条条路都吐。调用方靠它落盘，少吐一次那轮对话就丢了。

    ## 落进 `messages` 的 role —— 「过程」和「回复」靠它分开

    | role | 是什么 | 几条 |
    |---|---|---|
    | `user` | 用户这一句 | 1 |
    | `step` | 中间几轮模型的 `say`（过渡语，如「我这就去查」） | 0..n |
    | `tool` | 动作结果（`run_action` 的返回值） | 0..n |
    | `assistant` | **最终回复**，全局一条（出错时就是那串报错文本） | 1 |

    流式时前端按**事件类型**画；但**刷新后重画读的是会话历史、只能按 role 判断**
    ——role 不说清楚，中间那些过渡语就会被画成回复气泡，一问两答（正是这次要避免的）。
    """
    messages = list(history)
    messages.append({"role": "user", "content": user_message})
    system = build_system_prompt(vault_root)

    def done(rounds: int) -> dict:
        return {"type": "done", "messages": messages, "rounds": rounds}

    for round_no in range(1, MAX_ROUNDS + 1):
        try:
            raw = llm.complete(system, _render_history(messages))
        except LLMError as exc:
            text = f"我这边出错了：{exc}"
            messages.append({"role": "assistant", "content": text})
            yield {"type": "error", "text": text}
            yield done(round_no)
            return

        try:
            reply = parse_reply(raw)
        except ChatError as exc:
            text = f"我输出的格式不对：{exc}"
            messages.append({"role": "assistant", "content": text})
            yield {"type": "error", "text": text}
            yield done(round_no)
            return

        say = reply["say"]
        action = reply["action"]

        if not action:
            # **`say` 可能为空**（模型回了条空话、又不要动作）——空的既别吐事件，
            # 也别落历史：一条空的 `assistant` 在前端就是一行光秃秃的「**助手**：」，
            # 回看时像坏了。
            if say:
                messages.append({"role": "assistant", "content": say})
                yield {"type": "say", "text": say}
            yield done(round_no)
            return

        # 同一条规矩（见上）：空的别吐，前端会画个空气泡
        if say:
            yield {"type": "say", "text": say}
        yield {
            "type": "action",
            "name": action,
            "text": f"正在{ACTION_LABELS.get(action, action)}…",
        }

        try:
            result = run_action(
                action, reply["params"], vault_root, llm, organize_fn=organize_fn
            )
        except Exception as exc:      # 故意兜全部——异常源是外面传进来的回调
            # **`run_action` 自己承诺不抛，但它管不住调用方传进来的回调。**
            # 线上那份 `organize_fn`（`api/http.py`）会走到 `require_vault`，
            # 没配库就当场抛。异常若从生成器里逃出去，`done` 就吐不出来——
            # 调用方一个字节都落不下盘，那轮对话永久丢失（docstring 已打包票）。
            # 所以在这儿兜住，把异常当结果往下走：事件流照走、`done` 照吐。
            result = f"这一步没办成：{exc}"
        yield {"type": "result", "text": result}

        # 这一轮的 `say` 是**过程**不是回答，存成 `step`（见 docstring 那张表）：
        # 混成 `assistant` 的话，刷新后前端分不出「步骤」和「回复」，又是两答。
        # 空的（模型只给了动作没说话）不存。
        if say:
            messages.append({"role": "step", "content": say})
        messages.append({"role": "tool", "content": result})

    # 到达上限——模型还在要动作，说明它没收住。用一句固定话收尾，
    # 不取它最后一轮的 say（那句通常是「我这就去查」之类的过渡语，
    # 说出来会让人以为还在办）。
    text = "我转的圈数太多了，先停下。你再说一句我接着办。"
    messages.append({"role": "assistant", "content": text})
    yield {"type": "error", "text": text}
    yield done(MAX_ROUNDS)


def run_turn(
    vault_root: Path,
    history: list[dict],
    user_message: str,
    llm: LLM,
    *,
    organize_fn=None,
) -> tuple[list[dict], int]:
    """跑一轮对话（同步版）。

    返回 `(新的完整消息列表, 实际跑了几轮)`。调用方负责落盘。

    **它只是 `run_turn_stream` 的一个消费者**——同步的调用方（`handle`、
    `POST /chat` 那条 JSON 端点）继续用它，签名和返回值形状没变。

    ⚠️ **但消息列表的「内容」确实变了**，按消息下断言的地方要跟着看：
    - `tool` 轮的 `content` 从 `f"工具结果（{action}）：\\n{result}"` 变成裸
      `result`——那层壳改由 `_render_history` 按角色加（正文同时要给前端看）
    - 中间几轮的 `say` 从 `assistant` 变成 `step`（过程与回复分开，见
      `run_turn_stream` 的 docstring）
    """
    rounds = 0
    messages: list[dict] = []
    for event in run_turn_stream(
        vault_root, history, user_message, llm, organize_fn=organize_fn
    ):
        if event["type"] == "done":
            messages = event["messages"]
            rounds = event["rounds"]
    return messages, rounds


def handle(
    data_dir: Path,
    vault_root: Path,
    chat_id: str | None,
    message: str,
    llm: LLM,
    *,
    organize_fn=None,
) -> tuple[str, str]:
    """一轮对话的完整处理：读历史 → 跑 → 落盘。返回 `(会话 id, 回复)`。

    **Web 层与 HTTP 端点共用这一份**——否则对话会有两份实现，
    「怎么落盘」这条规则（过程留着、但 `reply` 只取最后那条 `assistant`）
    也会跟着分叉。

    ⚠️ 第一个参数是 `data_dir`（= `config.DATA_DIR`），**不是工程根**——
    传错会话就落进仓库了，见 `chat_store` 的模块说明。
    """
    if chat_id:
        chat = load_chat(data_dir, chat_id)
        history = chat["messages"] if chat else []
    else:
        history, chat_id = [], new_chat_id()

    messages, _ = run_turn(vault_root, history, message, llm, organize_fn=organize_fn)
    reply = next(
        (m["content"] for m in reversed(messages) if m["role"] == "assistant"), ""
    )

    # **过程要留着**（用户要能回头看「它干了什么」），但两条老顾虑得各自有交代：
    #
    # - **「一问两答」**：`reply` 只取**最后**那条 `assistant`；过程**另有角色**
    #   ——中间几轮的 `say` 是 `step`、动作结果是 `tool`（见 `run_turn_stream`
    #   的 docstring 那张表）。**刷新后**前端只看 role 就能把过程画成小字步骤、
    #   把回复画成气泡，不必猜「哪条 assistant 是步骤」。
    # - **「越堆越长」**：`tool` 轮存的是 `run_action` 的返回值——动作自己的结果
    #   摘要（带动作名，几行以内），不是整篇正文；`search` 例外（它带正文，
    #   模型答题靠它，Q103）。再加 `chat_store._MSG_LIMIT = 200` 兜住总量。
    save_chat(
        data_dir,
        chat_id,
        [*history, *messages[len(history):]],
    )
    return chat_id, reply
