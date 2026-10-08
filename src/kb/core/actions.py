"""动作清单——对话层能调用的东西。

**只有服务已有的能力**，不新增判断。每个动作都返回一段**给人看的文本**，
直接作为下一轮 LLM 的输入。

为什么用「LLM 输出动作名 + 参数」而不是 SDK 的 tool calling：
- `llm/base.py` 的抽象只有 `complete(system, user) -> str`，加 tool 要动抽象层
- 结构化 JSON 和整理那条链是同一套路，解析与校验都能复用
"""

from __future__ import annotations

from pathlib import Path

from kb.core.search import search_notes

ACTIONS: dict[str, dict] = {
    "search": {
        "desc": "在知识库里检索。用户问「X 是怎么说的」「有没有关于 X 的」时用。",
        "params": {"query": "关键词或一段描述"},
    },
    "push": {
        "desc": "投递一条新内容进收件箱。用户说「记一下 X」「帮我记着」时用。",
        "params": {"content": "正文，原样投递，不要改写"},
    },
    "revise": {
        "desc": "修改已有笔记。用户说「那条不对」「改成 X」时用。",
        "params": {"target": "目标笔记的文件名（不含 .md）", "content": "新内容"},
    },
    "organize": {
        "desc": "触发整理。用户说「可以整理了」「收拾一下」时用。",
        "params": {},
    },
}


# 动作 → 中文。**和 `lifecycle._BUSY_LABELS` 是两回事**：那个说「谁在动 vault」，
# 这个说「对话正在干什么」，别合并。漏配时走 `.get(action, action)` 兜底，
# 顶多吐个英文动作名，不像 `Busy` 那样必须当场炸。
ACTION_LABELS = {
    "search": "查库", "push": "投递", "revise": "修改", "organize": "整理",
}


def describe_actions() -> str:
    """给 LLM 看的动作清单。"""
    lines = []
    for name, spec in ACTIONS.items():
        params = "、".join(f"`{k}`（{v}）" for k, v in spec["params"].items()) or "无"
        lines.append(f"- `{name}`：{spec['desc']}\n  参数：{params}")
    return "\n".join(lines)


def run_action(
    name: str, params: dict, vault_root: Path, llm=None, *, organize_fn=None
) -> str:
    """执行一个动作，返回**给人看的文本**。

    **从不抛异常**——出错也返回文本，让对话能把它说给用户听。

    ⚠️ **返回值同时给两边看**：模型拿它当工具结果，前端拿它当「这一步干了什么」
    （`chat.handle` 会把它整条存进会话历史）。所以开头要有动作名——人一眼知道
    在干什么；长度要短——它会进历史、也会被回喂给模型（见 `chat.handle` 里那段
    注释）。

    不裹动作名的三处：`search`（它带正文，见下）、以及「未知动作」「缺少参数」
    这两条校验早退——那是要**模型改正**的报错，不是「这一步干了什么」，
    给前端看也没有意义。
    """
    if name not in ACTIONS:
        return f"未知动作：{name}"

    required = set(ACTIONS[name]["params"])
    missing = [k for k in required if not params.get(k)]
    if missing:
        return f"缺少参数：{'、'.join(missing)}"

    if name == "search":
        hits = search_notes(vault_root, params["query"])
        if not hits:
            # **这条不裹动作名。** 空结果也是模型要读的答复，裹上「查库：」
            # 只是给它多一层噪音；而下面那条（带正文）更不能裹——见那里的注释。
            return f"没找到关于「{params['query']}」的内容。"
        blocks = [f"找到 {len(hits)} 篇："]
        for hit in hits:
            rel = hit.path.relative_to(vault_root).as_posix()
            tags = "、".join(hit.tags) or "无"
            # **正文必须在这里。** 这段文本是模型能看到的全部——它的返回值
            # 直接进了对话上下文，而 search 是它唯一的查库动作。只给标题，
            # 它就只能在「我不知道」和编内容之间选（Q103）。
            #
            # 也**不能压成一行**（上面那条通用规则在这里例外）：正文就是模型
            # 的答案来源。前端渲染时自己截断。
            blocks.append(f"## {hit.title}（{rel}）标签：{tags}\n\n{hit.body.strip()}")
        return "\n\n".join(blocks)

    if name == "push":
        if organize_fn is None:
            text = "投递通道没接上（调用方没传 push 回调）。"
        else:
            text = organize_fn("push", params["content"], None)
    elif name == "revise":
        if organize_fn is None:
            text = "投递通道没接上（调用方没传 push 回调）。"
        else:
            text = organize_fn("revise", params["content"], params["target"])
    elif name == "organize":
        if organize_fn is None:
            text = "整理通道没接上（调用方没传 organize 回调）。"
        else:
            text = organize_fn("organize", "", None)
    else:
        text = f"动作 {name} 没有实现。"

    # 末尾统一包一层动作名。漏配时走 `.get(name, name)` 兜底——顶多吐个英文
    # 动作名，不像 `lifecycle._BUSY_LABELS` 那样必须当场炸。
    label = ACTION_LABELS.get(name, name)
    return f"{label}：{text}"
