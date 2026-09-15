"""领域数据模型：只有数据与枚举，不含逻辑。

三条约定，下游所有模块都要守：

1. **枚举是 `StrEnum`，写进 YAML frontmatter 前仍必须取 `.value`。**
   取值语义与裸字符串一致（`f"{Outcome.CREATE}"` 就是 `'create'`），
   但 **PyYAML 不认识枚举对象**——直接塞进 `frontmatter.Post(**{K_TYPE: NoteType.CONCEPT})`
   会抛 `RepresenterError`。这处响亮失败是保留下来的，别指望枚举能直接进 YAML。
2. **下游一律用 `is` 比较枚举，因此不得传入裸字符串。**
   （`str` 混入让 `Outcome.PENDING == "pending"` 成立，`is` 不成立——
   一旦实现里被喂进裸字符串，`is` 为假会静默走错分支。）
3. **frontmatter 键名一律引用本模块的 `K_*` 常量，不要写字面量。**
   写错键名不会报错，只会静默返回 `None`——归类信号消失、索引页不生成，
   而你什么都看不到。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------- frontmatter 键名
# 单一来源：这些键跨 vault / classify / journal / planning / organize 等多个模块使用

K_STATUS = "状态"          # 草稿的待整理标记
K_ID = "id"
K_SUBMITTED_AT = "投递时间"
K_SOURCE = "来源"
K_PROJECT = "项目"
K_TYPE = "类型"
K_TOPIC = "主题"
K_CREATED = "创建"
K_UPDATED = "更新"


class NoteType(StrEnum):
    """笔记类型。固定枚举（Q24），不许自由发挥。"""

    CONCEPT = "概念"
    PITFALL = "踩坑"
    DECISION = "决策"
    EXPERIENCE = "经验"
    CHECKLIST = "清单"
    JOURNAL = "日志"
    INDEX = "索引"


class Outcome(StrEnum):
    """整理**计划**（Q45）——LLM 打算做什么，尚未执行。

    与 ResultKind 的区别：这个是 LLM 产出的，可能幻觉；那个是实际发生的，不会。
    """

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
    """LLM 产出的变更计划（Q45）。

    只描述「要做什么」，不执行任何文件操作。落盘由 organize 模块按计划执行。

    **保持可变**：`frontmatter` 是 dict，`frozen=True` 挡不住它的内容被改，
    买到的保护很弱。约定是「生产者一次性构造，读取方不得修改」。

    **链接不单设字段**：唯一权威来源是 `content` 里的 `[[...]]`，
    `validate_plan` 校验的也是它。单设一个 `links` 字段是冗余——
    它会和 content 打架，且没有消费者。
    """

    draft_id: str
    outcome: Outcome
    target_path: str | None = None
    frontmatter: dict[str, object] = field(default_factory=dict)
    content: str = ""
    pending_reason: str | None = None


class ResultKind(StrEnum):
    """一次整理的执行结果。

    与 Outcome 的区别：Outcome 是 LLM 的计划，ResultKind 是实际发生的事情。
    FAILED 永远不会由 LLM 产出——它是执行失败（Q45：按条隔离，该条保持原样）。
    """

    CREATED = "created"
    FOLDED = "folded"
    PENDING = "pending"
    FAILED = "failed"


@dataclass(frozen=True)
class OrganizeResult:
    """单条草稿的整理结果。

    与 `Draft` 同为「已发生的记录」，故一并 `frozen`。字段全是不可变标量，
    这里的 frozen 是真保护（不像 OrganizePlan 那样被 dict 架空）。

    **报告与工作日志同源（Q50）**：服务产出本结构，然后渲染成两个出口——
    文本报告给会话，markdown 写进 vault 的整理日志。
    """

    draft_id: str
    kind: ResultKind
    detail: str                       # 一行摘要，如「新建 并发写锁.md」
    error: str | None = None
