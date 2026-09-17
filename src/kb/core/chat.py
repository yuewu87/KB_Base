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
from pathlib import Path

from kb.core.actions import describe_actions, run_action
from kb.core.chat_store import load_chat, new_chat_id, save_chat
from kb.llm.base import LLM, LLMError

MAX_ROUNDS = 4

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class ChatError(ValueError):
    """模型输出不可用。"""


def build_system_prompt() -> str:
    return f"""你是知识库助手，替用户处理他的个人知识库。

**只输出 JSON，不要输出任何其他文字，不要用代码块包裹。**

{{
  "say": "对用户说的话",
  "action": "要执行的动作名，不需要就填 null",
  "params": {{"参数名": "值"}}
}}

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


_ROLE_LABEL = {"user": "用户", "assistant": "助手", "tool": "工具结果"}


def _render_history(messages: list[dict]) -> str:
    """把消息渲染成给模型看的文本。

    **`tool` 必须单独标出来**——不能和 `assistant` 一样都叫「助手」。
    否则同一轮里工具结果会被冠上「助手」，模型看到的是「我上一条说：
    工具结果（search）…」——那是它自己说的话，不是它拿到的数据，
    它会当成「我已经说过了」而不去用。
    """
    lines = []
    for m in messages:
        who = _ROLE_LABEL.get(m["role"], "助手")
        lines.append(f"**{who}**：{m['content']}")
    return "\n\n".join(lines)


def run_turn(
    vault_root: Path,
    history: list[dict],
    user_message: str,
    llm: LLM,
    *,
    organize_fn=None,
) -> tuple[list[dict], int]:
    """跑一轮对话。

    返回 `(新的完整消息列表, 实际跑了几轮)`。调用方负责落盘。
    """
    messages = list(history)
    messages.append({"role": "user", "content": user_message})
    system = build_system_prompt()

    for round_no in range(1, MAX_ROUNDS + 1):
        try:
            raw = llm.complete(system, _render_history(messages))
        except LLMError as exc:
            messages.append({"role": "assistant", "content": f"我这边出错了：{exc}"})
            return messages, round_no

        try:
            reply = parse_reply(raw)
        except ChatError as exc:
            messages.append({"role": "assistant", "content": f"我输出的格式不对：{exc}"})
            return messages, round_no

        say = reply["say"]
        action = reply["action"]

        if not action:
            messages.append({"role": "assistant", "content": say})
            return messages, round_no

        result = run_action(action, reply["params"], vault_root, llm, organize_fn=organize_fn)
        messages.append({"role": "assistant", "content": say})
        messages.append({"role": "tool", "content": f"工具结果（{action}）：\n{result}"})

    # 到达上限——模型还在要动作，说明它没收住。用一句固定话收尾，
    # 不取它最后一轮的 say（那句通常是「我这就去查」之类的过渡语，
    # 说出来会让人以为还在办）。
    messages.append(
        {"role": "assistant", "content": "我转的圈数太多了，先停下。你再说一句我接着办。"}
    )
    return messages, MAX_ROUNDS


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
    「落盘只留 user / assistant」这条规则也会跟着分叉。

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

    # 落盘只留 [这一句用户消息] + [最终回复]，中间的全丢：
    #
    # - `tool` 是过程不是对话，存下去下次会当历史回喂给模型，越堆越长
    # - **中间几轮的 `say` 也要丢**：模型每个动作轮都会说一句话，
    #   于是「记一下 X」会落成「我这就去记」+「记好了，编号 …」两条回复
    #   ——一问两答，对话流看着很吵。用户要的是结论。
    save_chat(
        data_dir,
        chat_id,
        [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply},
        ],
    )
    return chat_id, reply
