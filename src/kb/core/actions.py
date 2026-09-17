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
from kb.core.vault import read_note

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
            return f"没找到关于「{params['query']}」的内容。"
        lines = [f"找到 {len(hits)} 篇："]
        for path in hits:
            meta, _ = read_note(path)
            tags = meta.get("主题") or []
            rel = path.relative_to(vault_root).as_posix()
            lines.append(f"- {path.stem}（{rel}）标签：{'、'.join(map(str, tags)) or '无'}")
        return "\n".join(lines)

    if name == "push":
        if organize_fn is None:
            return "投递通道没接上（调用方没传 push 回调）。"
        return organize_fn("push", params["content"], None)

    if name == "revise":
        if organize_fn is None:
            return "投递通道没接上（调用方没传 push 回调）。"
        return organize_fn("revise", params["content"], params["target"])

    if name == "organize":
        if organize_fn is None:
            return "整理通道没接上（调用方没传 organize 回调）。"
        return organize_fn("organize", "", None)

    return f"动作 {name} 没有实现。"
