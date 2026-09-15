"""领域数据模型：只有数据与枚举，不含逻辑。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NoteType(str, Enum):
    """笔记类型。固定枚举（Q24），不许自由发挥。"""

    CONCEPT = "概念"
    PITFALL = "踩坑"
    DECISION = "决策"
    EXPERIENCE = "经验"
    CHECKLIST = "清单"
    JOURNAL = "日志"
    INDEX = "索引"


class Outcome(str, Enum):
    """整理结果（Q45）。"""

    CREATE = "create"    # 新建笔记
    FOLD = "fold"        # 合并进已有笔记
    PENDING = "pending"  # 归不了类，移入待归类


@dataclass(frozen=True)
class Draft:
    """收件箱里的一条草稿。

    正文原样保存，服务不改写（Q55）——改写属于整理阶段。
    """

    id: str
    body: str
    source: str | None
    project: str | None
    created_at: str


@dataclass
class OrganizePlan:
    """LLM 产出的变更计划。

    只描述「要做什么」，不执行任何文件操作。落盘由 organize 模块按计划执行（Q45）。
    """

    draft_id: str
    outcome: Outcome
    target_path: str | None = None
    frontmatter: dict = field(default_factory=dict)
    content: str = ""
    links: list[str] = field(default_factory=list)
    pending_reason: str | None = None


class ResultKind(str, Enum):
    """一次整理的执行结果。

    与 Outcome 的区别：Outcome 是 LLM 的计划，ResultKind 是实际发生的事情。
    FAILED 永远不会由 LLM 产出——它是执行失败（Q45：按条隔离，该条保持原样）。
    """

    CREATED = "created"
    FOLDED = "folded"
    PENDING = "pending"
    FAILED = "failed"


@dataclass
class OrganizeResult:
    """单条草稿的整理结果。

    **报告与工作日志同源（Q50）**：服务产出本结构，然后渲染成两个出口——
    文本报告给会话，markdown 写进 vault 的整理日志。
    """

    draft_id: str
    kind: ResultKind
    detail: str                       # 一行摘要，如「新建 并发写锁.md」
    links: list[str] = field(default_factory=list)
    error: str | None = None
