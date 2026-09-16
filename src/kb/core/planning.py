"""把 LLM 的输出变成一份经过校验的变更计划。

三段式的第一段（规划）与第二段（校验）都在这。

本模块是**纯函数**——只做只读查询，绝不落盘。校验不过就抛 PlanError，
此时 vault 一个字节都没动（Q45）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kb.config import PROJECT_ROOT
from kb.core.classify import Candidate, knowledge_topics
from kb.core.models import (
    K_PROJECT,
    K_TOPIC,
    K_TYPE,
    Draft,
    NoteType,
    OrganizePlan,
    Outcome,
)
from kb.core.vault import INDEX, KNOWLEDGE, PROJECTS, list_notes

TEMPLATES_DIR = PROJECT_ROOT / "templates"

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# 日志与索引页由服务生成，不由 LLM 产出——所以不在给模型的允许列表里
_LLM_ALLOWED_TYPES = [t for t in NoteType if t not in (NoteType.JOURNAL, NoteType.INDEX)]


class PlanError(ValueError):
    """计划不合规。校验不过时抛出——此时 vault 未被修改。"""


# ------------------------------------------------------------ 模板

def load_note_skeletons() -> dict[str, str]:
    """读取各类型的正文骨架。

    **每次现读不缓存**——模板是用户可以随手改的（Q26），缓存会让改动不生效。
    文件缺失时跳过，不抛异常：模板没了不该让整个整理挂掉。
    """
    skeletons: dict[str, str] = {}
    for note_type in _LLM_ALLOWED_TYPES:
        path = TEMPLATES_DIR / f"{note_type.value}.md"
        if path.exists():
            skeletons[note_type.value] = path.read_text(encoding="utf-8").rstrip()
    return skeletons


JUDGMENT_HEADING = "## 用户的判断"


def strip_user_judgment(content: str) -> str:
    """清空「## 用户的判断」一节的正文，只保留标题。

    Q23：这一节记录的是**用户本人的立场**，只能由用户自己在 Obsidian 里写。

    不能靠提示词保证：模型面对一个空标题，默认行为就是把它填满，而且分不清
    「用户陈述的事实」与「用户的观点」——实测第一条真实草稿就被代填了
    （还写成第三人称「用户认为……」）。所以在这里机械清空，写了也丢掉。
    """
    out: list[str] = []
    skipping = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == JUDGMENT_HEADING:
            out.append(line)
            out.append("")          # 留一个空行，别让标题贴住下一节
            skipping = True
            continue
        if skipping and stripped.startswith("## "):
            skipping = False
        if not skipping:
            out.append(line)

    text = "\n".join(out)
    return text + "\n" if content.endswith("\n") else text


def _skeleton_block() -> str:
    skeletons = load_note_skeletons()
    if not skeletons:
        return ""

    lines = ["## 各类型的正文骨架（create 时照此结构写，章节名不要改）", ""]
    for name, body in skeletons.items():
        lines += [f"### {name}", "```markdown", body, "```", ""]
    return "\n".join(lines)


def build_system_prompt() -> str:
    """构造系统提示词。

    模板内容在每次调用时现读，所以用户改了 `templates/*.md` 之后新会话即生效。
    """
    allowed = "、".join(t.value for t in _LLM_ALLOWED_TYPES)
    return f"""你是知识库整理助手。你会收到一条待整理的草稿、可能相关的已有笔记、
现有项目清单和知识区主题清单。

你的任务：把草稿整理成一篇正式笔记（create）、合并进已有笔记（fold），
或判断为无法归类（pending）。

**只输出 JSON，不要输出任何其他文字，不要用代码块包裹。**

{{
  "outcome": "create" | "fold" | "pending",
  "target_path": "相对 vault 根的路径",
  "frontmatter": {{"{K_TYPE}": "概念", "{K_TOPIC}": ["后端"], "{K_PROJECT}": "项目名"}},
  "content": "笔记正文（markdown）",
  "pending_reason": "仅 outcome=pending 时填"
}}

硬规则：
1. target_path 必须落在 `10_项目/<项目名>/` 或 `20_知识/<既有主题>/` 下。
2. {K_TYPE} 只能取：{allowed}。
3. {K_TOPIC} 只能取「知识区现有主题」里列出的名字。
4. content 必须至少包含一个 [[双向链接]]，指向已有笔记或索引页。
5. create 的目标路径不能已存在；fold 的目标路径必须已存在。
6. 不要发明新的主题分类。都不合适就用 pending，并在 pending_reason 说明原因。
7. 项目笔记的文件名必须带项目前缀，如 `项目名-踩坑.md`，避免 [[链接]] 歧义。
8. 骨架里的「## 用户的判断」一节**必须留空**（保留标题，标题下什么都不写）。
   这一节记录用户本人的立场，服务端会机械清空——写了也会被丢掉，别浪费。
   绝不要替用户总结、推断或改写成第三人称（「用户认为……」是典型的伪造）。
9. fold 时 content **只写要追加的段落**——不要带一级标题（`# `），不要写
   frontmatter，也不要重复目标笔记已有的章节。追加不是嵌一篇新笔记进去。

{_skeleton_block()}"""


# ------------------------------------------------------------ 提示词

def _rel(path: Path, vault_root: Path) -> str:
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError:
        return path.as_posix()


def build_messages(
    draft: Draft,
    candidates: list[Candidate],
    projects: list[Path],
    topics: list[str],
    vault_root: Path,
) -> list[dict]:
    """构造给 LLM 的 messages。"""
    if candidates:
        cand_lines = "\n".join(
            f"- {c.title}｜标签：{'、'.join(c.tags) or '无'}｜路径：{_rel(c.path, vault_root)}"
            for c in candidates
        )
    else:
        cand_lines = "（没有明显相关的已有笔记）"

    proj_lines = (
        "\n".join(f"- {p.name}" for p in projects)
        if projects
        else "（知识库里还没有任何项目文件夹）"
    )

    user = f"""## 待整理的草稿

id: {draft.id}
来源: {draft.source or '未说明'}
项目: {draft.project or '未说明'}

正文：
{draft.body}

## 可能相关的已有笔记

{cand_lines}

## 知识库现有项目

{proj_lines}

## 知识区现有主题

{'、'.join(topics) if topics else '（无）'}
"""
    return [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": user},
    ]


# ------------------------------------------------------------ 解析

def extract_json(raw: str) -> dict:
    """从模型输出里抠出 JSON 对象。容忍代码块包裹。"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanError(f"模型输出不是合法 JSON：{exc}") from exc

    if not isinstance(data, dict):
        raise PlanError("模型输出不是 JSON 对象")
    return data


def parse_plan(draft_id: str, raw: str) -> OrganizePlan:
    """把模型输出解析成 OrganizePlan。只做结构检查，不做业务校验。"""
    data = extract_json(raw)

    try:
        outcome = Outcome(data.get("outcome", ""))
    except ValueError as exc:
        raise PlanError(f"outcome 非法：{data.get('outcome')!r}") from exc

    frontmatter = data.get("frontmatter") or {}
    if not isinstance(frontmatter, dict):
        raise PlanError("frontmatter 必须是对象")

    return OrganizePlan(
        draft_id=draft_id,
        outcome=outcome,
        target_path=(data.get("target_path") or None),
        frontmatter=frontmatter,
        content=data.get("content") or "",
        pending_reason=(data.get("pending_reason") or None),
    )


# ------------------------------------------------------------ 校验

def allowed_prefixes(vault_root: Path) -> list[Path]:
    """允许写入的目录。主题必须已经存在——新主题要用户决定（Q11）。"""
    prefixes = [vault_root / PROJECTS]
    prefixes += [vault_root / KNOWLEDGE / t for t in knowledge_topics(vault_root)]
    return prefixes


def _is_existing_project_dir(vault_root: Path, path: Path) -> bool:
    """`path` 是否为 `10_项目/<项目名>` 这样的**既有**项目目录。

    项目目录必须真的存在——服务从不自动新建项目文件夹（Q30）。
    """
    try:
        rel = path.relative_to(vault_root / PROJECTS)
    except ValueError:
        return False
    return len(rel.parts) == 1 and path.is_dir()


def known_link_targets(vault_root: Path) -> set[str]:
    """正文里 [[链接]] 可以指向谁。

    已有笔记的短名与相对路径，加上各主题的索引页。
    """
    names: set[str] = set()
    for path in list_notes(vault_root):
        names.add(path.stem)
        names.add(path.relative_to(vault_root).with_suffix("").as_posix())
    for topic in knowledge_topics(vault_root):
        names.add(topic)
        names.add(f"{INDEX}/{topic}")
    return names


def validate_plan(plan: OrganizePlan, vault_root: Path) -> None:
    """第二段：纯静态检查。不过就抛 PlanError，vault 一个字节没动。"""
    if plan.outcome is Outcome.PENDING:
        if not plan.pending_reason:
            raise PlanError("outcome=pending 但没有给出 pending_reason")
        return

    if not plan.target_path:
        raise PlanError(f"outcome={plan.outcome.value} 但没有 target_path")

    rel = Path(plan.target_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise PlanError(f"target_path 不能是绝对路径或包含 ..：{plan.target_path}")

    target = vault_root / rel
    if not any(target.is_relative_to(p) for p in allowed_prefixes(vault_root)):
        raise PlanError(
            "target_path 不在允许范围内，必须落在 10_项目/ 或 20_知识/<既有主题>/ 下："
            f"{plan.target_path}"
        )

    if target.is_relative_to(vault_root / PROJECTS) and not _is_existing_project_dir(
        vault_root, target.parent
    ):
        raise PlanError(
            "项目目录不存在，服务不会自动新建（Q30）。"
            "请先手工建好 `10_项目/<项目名>/`，或改走 20_知识/ 或 pending："
            f"{plan.target_path}"
        )

    if plan.outcome is Outcome.CREATE:
        if target.exists():
            raise PlanError(f"create 的目标已存在，不能覆盖：{plan.target_path}")

        note_type = plan.frontmatter.get(K_TYPE)
        allowed_values = {t.value for t in _LLM_ALLOWED_TYPES}
        if note_type not in allowed_values:
            raise PlanError(
                f"{K_TYPE} 非法：{note_type!r}。只能取 "
                f"{'、'.join(t.value for t in _LLM_ALLOWED_TYPES)}"
                "——日志与索引页由服务生成，不由模型产出"
            )

        if not _LINK_RE.search(plan.content):
            raise PlanError("正文必须包含至少一个 [[双向链接]]（不允许孤儿笔记）")

        known = known_link_targets(vault_root)
        missing = [
            name.strip()
            for name in _LINK_RE.findall(plan.content)
            if name.strip() not in known
        ]
        if missing:
            raise PlanError(f"链接指向不存在的笔记：{'、'.join(missing)}")
        return

    # Outcome.FOLD
    if not target.exists():
        raise PlanError(f"fold 的目标不存在：{plan.target_path}")
    if not plan.content.strip():
        raise PlanError("fold 但没有给出要追加的内容")
