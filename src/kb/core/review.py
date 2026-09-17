"""审核（Q58/Q78）：链上一步，在静态校验之后、落盘之前。

**只审一条：新建的分类跟同层已有的是否近义。** 其余都是机械项，归
`planning.validate_plan` 用代码管——机械约束不能交给模型判断
（见 `docs/04_踩坑与经验.md` 第 10 条）。

位置：`organize.make_plan` 在 `validate_plan` 通过后调用本模块。
"""
from __future__ import annotations

import json
from pathlib import Path

from kb.core.models import OrganizePlan
from kb.core.planning import PlanError
from kb.llm.base import LLM, LLMError

REVIEW_SYSTEM = """你是知识库的分类审核员。

别人已经决定把一篇笔记放到某条路径下，但那条路径里有**新建的目录层**。
你的任务：判断这些新目录，跟同一层已有的目录**是不是近义的**。

**近义就用已有的，别新建。** 有「版本控制」就别建「git」；有「批处理」就别建「bat」。

只输出 JSON，不要输出任何其他文字：
{"target_path": "最终应该用的相对路径"}

如果新目录确实和任何一个已有目录都不近义，就把原路径原样返回。
如果近义，把路径里那一层换成已有目录名。"""


def new_dirs_in(vault_root: Path, target_path: str) -> list[str]:
    """`target_path` 里**还不存在**的目录层名（从浅到深）。没有则空列表。"""
    rel = Path(target_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise PlanError(f"target_path 不能是绝对路径或含 ..：{target_path}")
    missing: list[str] = []
    cur = vault_root
    for part in rel.parts[:-1]:          # 最后一段是文件名
        cur = cur / part
        if not cur.is_dir():
            missing.append(part)
    return missing


def _siblings(vault_root: Path, target_path: str, missing: list[str]) -> list[str]:
    """新目录所在那一层的已有目录名，供 LLM 对照。"""
    first = missing[0]
    parent = vault_root
    for part in Path(target_path).parts[:-1]:
        if part == first:
            break
        parent = parent / part
    if not parent.is_dir():
        return []
    return sorted(
        p.name
        for p in parent.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )


def review_plan(plan: OrganizePlan, vault_root: Path, llm: LLM) -> OrganizePlan:
    """审一遍。没新建分类就原样返回，不调 LLM。"""
    if not plan.target_path:
        return plan
    missing = new_dirs_in(vault_root, plan.target_path)
    if not missing:
        return plan

    siblings = _siblings(vault_root, plan.target_path, missing)
    user = (
        f"原路径：{plan.target_path}\n"
        f"新建的目录层：{'、'.join(missing)}\n"
        f"同层已有目录：{'、'.join(siblings) if siblings else '（空）'}\n"
    )
    try:
        raw = llm.complete(REVIEW_SYSTEM, user)
        data = json.loads(raw)
        new_path = data["target_path"]
    except (LLMError, json.JSONDecodeError, KeyError) as exc:
        raise PlanError(f"审核失败：{exc}") from exc

    if not isinstance(new_path, str) or not new_path:
        raise PlanError(f"审核返回的 target_path 不合法：{new_path!r}")

    plan.target_path = new_path
    return plan
