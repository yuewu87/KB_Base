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
from kb.core.classify import Candidate
from kb.core.models import (
    K_PROJECT,
    K_TOPIC,
    K_TYPE,
    Draft,
    NoteType,
    OrganizePlan,
    Outcome,
)
from kb.core.vault import (
    INDEX,
    clean_title,
    list_classifications,
    list_domains,
    list_notes,
    read_note,
    section_headings,
)

TEMPLATES_DIR = PROJECT_ROOT / "templates" / "笔记"

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_RELATED_HEADING_RE = re.compile(r"^##\s*相关\s*$", re.MULTILINE)
_ANY_HEADING_RE = re.compile(r"^##\s", re.MULTILINE)


def _links_without_reason(content: str) -> list[str]:
    """`## 相关` 一节里**链接后面没写理由**的那些。

    规则 4 说得很清楚（见 `build_system_prompt`）：列在 `## 相关` 里的链接
    要在后面用 `——` 写一句共性。而 `validate_plan` 原先只机械地查了
    「正文有链接」「链接目标存在」——**「有没有理由」同样是机械的、能写成
    `if`**，它却只写在提示词里。实测同一批次：一篇 3 条链接全带理由、另一篇
    3 条全裸，**同一份提示词，一次做到一次没做到**。正是 CLAUDE.md 那条
    「机械约束归代码」要收的东西。

    **只查 `## 相关` 这一节。** 正文句子里的链接不查——那句话本身就是理由，
    而提示词把这两种写法并列写着的（「链在正文句子里的，让那句话把它说清楚」）。
    查全篇的话，推荐的写法反而会被一条条打回。
    """
    head = _RELATED_HEADING_RE.search(content)
    if not head:
        return []
    rest = content[head.end():]
    end = _ANY_HEADING_RE.search(rest)
    section = rest[: end.start()] if end else rest

    bare: list[str] = []
    for line in section.splitlines():
        for match in _LINK_RE.finditer(line):
            # 链接后面（同一行内）要跟 `——`；`- [[X]] —— 理由` 也算。
            if not line[match.end():].lstrip().startswith("——"):
                bare.append(match.group(1).strip())
    return bare

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


def _skeleton_block() -> str:
    skeletons = load_note_skeletons()
    if not skeletons:
        return ""

    lines = ["## 各类型的正文骨架（create 时照此结构写，章节名不要改）", ""]
    for name, body in skeletons.items():
        lines += [f"### {name}", "```markdown", body, "```", ""]
    return "\n".join(lines)


# ------------------------------------------------------------ 标签（Q101）

# 单个标签最长多少字符。规则 7 本来只是提示词里的一句话，但「截到 20 字」
# 是数得出来的——**数得出来的就别指望模型**（Q91/Q94 同一类）。
_TAG_MAX = 20

# 模型最多补几个跨领域语义标签（规则 7 原话是 0-3）。
_SEMANTIC_TAG_MAX = 3


def normalize_tag(raw: str) -> str:
    """标签规范化：折空白为 `-`、转小写、截到 20 字符。

    **机械约束，归代码。** 这三条以前只写在提示词里（规则 7），
    模型照不照做没有任何东西兜底——现在照不照做都一样，代码会把它掰回来。
    """
    tag = re.sub(r"\s+", "-", str(raw or "").strip()).lower()
    return tag[:_TAG_MAX]


def derive_tags(target_path: str, semantic: list[str]) -> list[str]:
    """最终的 `主题` 标签 = **路径派生** + 模型给的语义标签。

    路径派生：目标路径上每一级目录名，领域名排最前。规则 7 本来就要求这个，
    但它要模型**抄一遍代码手里已有的东西**——抄漏了 `主题` 就空，
    而 `主题` 是检索的命脉（Q25），空了这篇笔记只剩全文搜得到。

    实测 48 篇 `主题` 全都填了，靠的是模型自觉；代码里一行兜底都没有
    （2026-09-18）。而 `target_tags`——提示词里让它填的那个字段——
    `OrganizePlan` 根本没有对应属性，模型认真算完直接丢掉。

    **路径至少有一级目录，所以这个函数不会返回空列表**：只要路径合法，
    笔记一定有几个标签。
    """
    out: list[str] = []
    path_dirs = Path(target_path).parts[:-1] if target_path else ()
    for raw in [*path_dirs, *semantic]:
        tag = normalize_tag(raw)
        if tag and tag not in out:
            out.append(tag)
    return out


def resolve_frontmatter(plan: OrganizePlan, draft: Draft) -> dict:
    """落盘前把 frontmatter 补全——**这里才是「什么归代码」的分界线**。

    | 字段 | 归谁 | 为什么 |
    |---|---|---|
    | `类型` | 模型 | 判断题：这条算概念还是踩坑 |
    | `主题` | **代码** | 派生 + 搬运，没有判断成分 |
    | `项目` | **代码** | 从草稿搬过来，一个字都不用改 |

    `项目` 从草稿搬而不是问模型：实测四篇笔记的 `项目` 丢了，草稿里明明有
    （模型生成 frontmatter 时漏了，而校验只管类型）。**草稿是唯一真源**——
    草稿没有时（Web 投递）把模型自己编的删掉，不许它无中生有。

    只用于 create。fold 是往已有笔记里追加，frontmatter 不动。
    """
    meta = dict(plan.frontmatter)
    meta[K_TOPIC] = derive_tags(plan.target_path or "", plan.semantic_tags)
    if draft.project:
        meta[K_PROJECT] = draft.project
    else:
        meta.pop(K_PROJECT, None)
    return meta


def build_system_prompt() -> str:
    """系统提示词。规则见 `docs/01_架构.md` 第五、六、七节。

    模板内容在每次调用时现读，所以用户改了 `templates/*.md` 之后新会话即生效。
    """
    allowed = "、".join(t.value for t in _LLM_ALLOWED_TYPES)
    return f"""你是知识库整理助手。你会收到一条待整理的草稿、可能相关的已有笔记、
现有领域清单，以及领域下已有的分类。

你的任务：把草稿整理成一篇正式笔记（create）、合并进已有笔记（fold），
或判断为无法归类（pending）。

**只输出 JSON，不要输出任何其他文字，不要用代码块包裹。**

{{
  "outcome": "create" | "fold" | "pending",
  "target_path": "相对 vault 根的路径",
  "frontmatter": {{"{K_TYPE}": "概念"}},
  "semantic_tags": ["版本控制"],
  "content": "笔记正文（markdown）",
  "pending_reason": "仅 outcome=pending 时填"
}}

硬规则：
1. target_path 必须落在**某个既有领域**下，形如 `<领域>/…/<标题>.md`。
   领域是 vault 的一级目录，由人维护，**不许新建**。清单见「现有领域」一节。
   领域内的子分类**由你决定**——但要遵守第 6 条。
   **整条路径的目录最多 {MAX_DIR_LEVELS} 层**（领域算第一层，文件名不算）。
2. 文件名（`<标题>.md` 的标题部分）必须是**清洗过的内容标题**：
   不含 `\\ / : * ? " < > |`，不以点结尾，不超过 60 字。
3. {K_TYPE} 只能取：{allowed}。
4. content 必须至少包含一个 [[双向链接]]，指向已有笔记或索引页。
   **每一条链接都要说得出「这两篇的共性是什么」**：
   - 链在正文句子里的，让那句话把它说清楚（「同属路径在什么时机被解释这类坑，见 [[X]]」）
   - 列在 `## 相关` 一节里的，**在链接后面用 `——` 写一句**：
     `- [[X]]——同属编码问题，都是「设了却不生效」`
   **共性要具体到能被检验**：同一个工具、同一层机制、同一类失败模式。
   「都是坑」「都要显式写」「同属知识管理」这种说了等于没说的不算——
   那只是在讲「两篇都是好笔记」，换个标题也成立。
   **说不出来共性就别链。** 凑数的链接比没有链接更糟——它会把「相关」这一节
   变成装饰，读的人再也分不清哪些是真关联。
5. create 的目标路径不能已存在；fold 的目标路径必须已存在。
6. **放哪一层，看这一篇跟谁同类，不看路径深不浅。**
   - 先看「领域下已有分类」：这一篇跟哪一类是**同一个工具、同一层机制、或同一类失败模式**
     （判据同规则 4 的「共性」）？是，就放进那一类——**不许另起近义名**
     （有「版本控制」就别建「git」，有「前端」就别建「前端工程」）。
   - 一类都不属于，就问一句：**这一类以后还会有新的进来吗？** 会，就新开一层。
     按工具或机制分的类——`git`、`.bat`、无头浏览器、测试——都属这种：只要还在用，
     同类问题就会反复出现。**目录名用这一类共同的名字，不要用这一篇自己的标题。**
   - 确实是个孤例、跟谁都不成类，**就直放在领域目录下**（`计算机/标题.md`）。
     这是允许的，不是「没归好类」。
   - **平铺不是省事的默认值**：只有「确实想不出这一篇跟谁是同类」才放领域根下。
7. frontmatter 里**只填 `{K_TYPE}` 一个**。`{K_TOPIC}` 和 `{K_PROJECT}` 由服务自己算，
   你填了也会被覆盖——`{K_PROJECT}` 从草稿原样搬过来，`{K_TOPIC}` 的路径派生部分
   服务会从 target_path 拆（每一级目录名一个标签，领域名排最前）。
   你只负责 `semantic_tags`：**路径上看不出来的跨领域标签**，0-3 个。
   跟路径上的目录名重复的，一个都不要写。比如一篇讲「用代码生成艺术」的笔记
   放在 `计算机/` 下，可以带 `艺术`；但 `计算机` 不用填，服务自己会加。
   （大小写、空格怎么折、超长怎么办，服务统一处理，你不用操心。）
8. fold 时 content **只写要追加的段落**——不要带一级标题（`# `），不要写
   frontmatter，也不要重复目标笔记已有的章节。追加不是嵌一篇新笔记进去。
   新章节插在 `## 相关` **之前**（那是收尾节），位置服务会处理，你不用管。
9. **先看「可能相关的已有笔记」里有没有已经讲过同一条洞见的。**
   换个说法、换个例子，还是同一条结论——那就 fold 进去补充，**不要另起一篇**。
   只有确实是新的一条（新的成因、新的适用场景、新的取舍）才 create。
   同一个洞见摊成三篇，读的人会以为有三条结论。

{_skeleton_block()}"""


# ------------------------------------------------------------ 提示词

def _sections_suffix(path: Path) -> str:
    """候选笔记**已有的章节名**，接在候选行末尾。

    「这条洞见属于哪一篇」和「这篇里已经写过没有」是两个问题，而原先的候选
    清单（标题、标签、路径）只够回答第一个。2026-09-18 实测：把「文本模式写
    bat 换行是 LF」fold 进 `Windows 批处理文件必须用 GBK 编码`，模型新加了
    一节——**而那一篇里本来就有同一段内容**，于是同一篇里说了两遍。
    Q101 解决的是「同一洞见摊成多篇」，**篇内的重复它管不着**。

    **只带章节名，不带正文。** 候选默认 8 条，正文会让提示词线性膨胀；而
    「大概讲过没有」这件事，章节名配标题通常够判断。真不够时还有一条兜底：
    模型可以选 `rewrite`，或者把内容 fold 进**已有的**那一节（提示词里写着
    「同一个洞见摊成三篇…」那一段）。**这是一个折中，不是完整解**——
    要彻底解决得让模型看见正文，那笔 token 账没人算过。
    """
    try:
        _, body = read_note(path)
    except OSError:
        return ""
    heads = section_headings(body)
    return f"｜已有章节：{'、'.join(heads)}" if heads else ""


def _rel(path: Path, vault_root: Path) -> str:
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError:
        return path.as_posix()


def build_messages(
    draft: Draft,
    candidates: list[Candidate],
    topics: list[str],
    vault_root: Path,
) -> list[dict]:
    """构造给 LLM 的 messages。"""
    if candidates:
        cand_lines = "\n".join(
            f"- {c.title}｜标签：{'、'.join(c.tags) or '无'}｜"
            f"路径：{_rel(c.path, vault_root)}{_sections_suffix(c.path)}"
            for c in candidates
        )
    else:
        cand_lines = "（没有明显相关的已有笔记）"

    if topics:
        cls_lines = "\n".join(
            f"- {domain}：{'、'.join(list_classifications(vault_root, domain)) or '（无）'}"
            for domain in topics
        )
    else:
        cls_lines = "（无）"

    user = f"""## 待整理的草稿

id: {draft.id}
来源: {draft.source or '未说明'}
项目: {draft.project or '未说明'}

正文：
{draft.body}

## 可能相关的已有笔记

{cand_lines}

## 现有领域

{'、'.join(topics) if topics else '（无）'}

## 领域下已有分类

{cls_lines}
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

    semantic = data.get("semantic_tags") or []
    if not isinstance(semantic, list):
        raise PlanError("semantic_tags 必须是数组")

    return OrganizePlan(
        draft_id=draft_id,
        outcome=outcome,
        target_path=(data.get("target_path") or None),
        frontmatter=frontmatter,
        content=data.get("content") or "",
        pending_reason=(data.get("pending_reason") or None),
        semantic_tags=[str(t) for t in semantic],
    )


# ------------------------------------------------------------ 校验

def allowed_prefixes(vault_root: Path) -> list[Path]:
    """允许写入的目录。领域是固定的几个，子分类由 LLM 自建。"""
    return [vault_root / domain for domain in list_domains(vault_root)]


def known_link_targets(vault_root: Path) -> set[str]:
    """正文里 [[链接]] 可以指向谁。

    已有笔记的短名与相对路径，加上各主题的索引页。
    """
    names: set[str] = set()
    for path in list_notes(vault_root):
        names.add(path.stem)
        names.add(path.relative_to(vault_root).with_suffix("").as_posix())
    for topic in list_domains(vault_root):
        names.add(topic)
        names.add(f"{INDEX}/{topic}")
    return names


# 兜底分类名——**目录**里不许出现（文件名不查，笔记标题里可以有「其他」）。
#
# 用户的原话：「原方案叫『其他分类』，注定变成垃圾桶——凡没明确归属的都往里塞」。
# 落成代码的理由见 Q91 与 `docs/04_踩坑与经验.md` 第 23 条。
#
# **这条归代码不归模型**：名字里带这些词就是兜底，跟内容是什么无关，
# 是一眼可判的机械约束。模型看到一条装不下的内容时，最省事的做法就是
# 往「其他」里一塞——所以闸门要卡在它迈不过去的地方。
_FALLBACK_NAMES = {
    "其他", "其它", "杂项", "杂类", "杂物",
    "临时", "暂时", "未分类", "待分类", "待定", "未整理", "未归类",
    "misc", "miscellaneous", "other", "others", "temp", "tmp", "todo", "unknown",
}


def _is_fallback_name(name: str) -> bool:
    return name.strip().lower() in _FALLBACK_NAMES


# 目录最多几层（Q94）。**领域算第一层**——`计算机/Python/x.md` 是两层。
#
# 用户原话是「顶多三四层的样子吧」，定在 4。**这条归代码不归模型**：层数是
# 数出来的，一眼可判，跟兜底分类名（Q91）同一类。
MAX_DIR_LEVELS = 4


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

    depth = len(rel.parts) - 1          # 减掉文件名那一段
    if depth > MAX_DIR_LEVELS:
        raise PlanError(
            f"目录最多 {MAX_DIR_LEVELS} 层，这条排到第 {depth} 层了（Q94）："
            f"{plan.target_path}。换个浅一点的位置，或者把中间那几层合并掉。"
        )

    fallback = [d for d in rel.parts[:-1] if _is_fallback_name(d)]
    if fallback:
        raise PlanError(
            f"不许建兜底分类（Q14：「其他分类注定变垃圾桶」）：{'、'.join(fallback)}。"
            "装不下的内容就用 pending，别硬塞进一个什么都装的目录。"
            f"目标路径：{plan.target_path}"
        )

    target = vault_root / rel
    if not any(target.is_relative_to(p) for p in allowed_prefixes(vault_root)):
        raise PlanError(
            "target_path 不在允许范围内，必须落在既有领域下："
            f"{plan.target_path}"
        )

    if plan.revise_target and target.stem == plan.revise_target:
        raise PlanError(
            f"这是修改请求（--revise {plan.revise_target}），新内容必须另起一篇笔记。"
            "不能 fold 进被取代的那一篇——那样同一个文件里会同时有新说法和旧说法，"
            "落盘时再把它标记失效就自相矛盾（2026-09-16 端到端验收跑出来的实例）。"
            "请改成 create，并另取一个内容标题。"
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

        stem = Path(plan.target_path).stem
        if clean_title(stem) != stem:
            raise PlanError(
                f"文件名不合规，必须是清洗过的内容标题（见架构第五节）：{stem}"
            )

        if len(plan.semantic_tags) > _SEMANTIC_TAG_MAX:
            raise PlanError(
                f"semantic_tags 最多 {_SEMANTIC_TAG_MAX} 个，给了 "
                f"{len(plan.semantic_tags)} 个：{'、'.join(plan.semantic_tags)}。"
                "这里只放**路径上看不出来的**跨领域标签——路径派生由服务自己做，"
                "别把目录名抄一遍。"
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

        bare = _links_without_reason(plan.content)
        if bare:
            raise PlanError(
                "`## 相关` 里的链接要说得出共性（规则 4）："
                f"{'、'.join(bare)} 后面没有用 `——` 写一句。"
                "说不出来共性就别链——凑数的链接比没有链接更糟。"
            )
        return

    # Outcome.FOLD
    if not target.exists():
        raise PlanError(f"fold 的目标不存在：{plan.target_path}")
    if not plan.content.strip():
        raise PlanError("fold 但没有给出要追加的内容")
