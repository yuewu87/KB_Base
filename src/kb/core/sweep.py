"""巡检——周期性地收拾**标签和目录**。

## 与整理草稿的区别

| | 输入 | 输出 |
|---|---|---|
| 整理草稿 | 一条草稿 | 一篇笔记的变更 |
| **巡检** | **整个库的标签与目录** | **一批重命名与合并** |

**不看正文**（用户定的边界：只整理标签、目录这些）。所以输入很小，
一次 LLM 调用就够——不用先出「人话建议」再翻译一遍。

**只合并，不新建。** 「归一不新建」那条同样适用：合并的目标必须是**已有**的
目录，否则校验拒掉。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from kb.core.vault import list_domains, list_notes, read_note
from kb.llm.base import LLM, LLMError

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class SweepError(ValueError):
    """模型输出不可用，或计划不合规。"""


@dataclass
class SweepPlan:
    tag_merges: list[tuple[str, str]] = field(default_factory=list)
    dir_merges: list[tuple[str, str]] = field(default_factory=list)
    summary: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.tag_merges and not self.dir_merges


# ------------------------------------------------------------ 扫描（只读）

def collect_tags(vault_root: Path) -> dict[str, int]:
    """全库的标签 → 出现次数。**不看正文**，只读 frontmatter。"""
    counts: dict[str, int] = {}
    for path in list_notes(vault_root):
        meta, _ = read_note(path)
        tags = meta.get("主题") or []
        if isinstance(tags, str):
            tags = [tags]
        for tag in tags:
            name = str(tag).strip()
            if name:
                counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def list_dir_tree(vault_root: Path) -> list[str]:
    """领域以下的目录（相对 vault 根）。机器目录（`_` 开头）不算。"""
    out: list[str] = []
    for domain in list_domains(vault_root):
        out.append(domain)
        root = vault_root / domain
        for path in sorted(root.rglob("*")):
            if path.is_dir():
                out.append(path.relative_to(vault_root).as_posix())
    return out


def build_prompt(vault_root: Path) -> str:
    """给模型的输入——**只有标签和目录，没有正文**。"""
    tags = collect_tags(vault_root)
    dirs = list_dir_tree(vault_root)

    tag_lines = "\n".join(f"- {t}（{n} 篇）" for t, n in tags.items()) or "（无）"
    dir_lines = "\n".join(f"- {d}" for d in dirs) or "（无）"

    return f"""你在定期收拾一个个人知识库的**标签和目录**。

**你只整理标签和目录，不碰任何笔记的正文。** 你没看到正文，也不需要看。

## 现有标签（括注是用了多少次）

{tag_lines}

## 现有目录

{dir_lines}

## 你的任务

找出**明显是同一回事**的标签和目录，给出合并方案。

**只输出 JSON，不要输出任何其他文字，不要用代码块包裹。**

{{
  "tag_merges": [{{"from": "被并掉的", "to": "保留的"}}],
  "dir_merges": [{{"from": "计算机/被并掉的", "to": "计算机/保留的"}}],
  "summary": "一句话说这次收拾了什么"
}}

## 硬规矩

1. **只合并明显重复的。** 拿不准就不动——宁可少合并，不要合并错。
   两个词意思相近但不是一回事（比如「编码」和「字符集」），不算重复。
2. **`to` 必须是上面列过的、已经存在的名字。** 不许新建标签或目录。
3. **`to` 不能同时出现在 `from` 里**（那会绕圈）。
4. **没得合并就返回空数组**，`summary` 里说「没什么要收拾的」。
   空计划是完全正常的结果——大多数时候都该是空的。"""


def parse_plan(raw: str) -> SweepPlan:
    """解析模型输出。容忍代码块包裹。"""
    text = _FENCE.sub("", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SweepError(f"模型输出不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise SweepError("模型输出不是 JSON 对象")

    def pairs(key: str) -> list[tuple[str, str]]:
        value = data.get(key, [])
        if not isinstance(value, list):
            raise SweepError(f"{key} 必须是数组")
        out: list[tuple[str, str]] = []
        for item in value:
            if not isinstance(item, dict) or "from" not in item or "to" not in item:
                raise SweepError(f"{key} 里每一项都要有 from 和 to")
            out.append((str(item["from"]), str(item["to"])))
        return out

    return SweepPlan(
        tag_merges=pairs("tag_merges"),
        dir_merges=pairs("dir_merges"),
        summary=str(data.get("summary") or ""),
    )


def make_plan(vault_root: Path, llm: LLM) -> SweepPlan:
    """跑一次巡检的规划。只读——不碰文件。"""
    try:
        raw = llm.complete(build_prompt(vault_root), "请给出合并方案。")
    except LLMError as exc:
        raise SweepError(f"巡检失败：{exc}") from exc
    return parse_plan(raw)


# ------------------------------------------------------------ 校验

def validate(plan: SweepPlan, vault_root: Path) -> None:
    """纯静态检查。不过就抛 SweepError，**vault 一个字节没动**。"""
    tags = set(collect_tags(vault_root))
    dirs = set(list_dir_tree(vault_root))

    for src, dst in plan.tag_merges:
        if src not in tags:
            raise SweepError(f"合并源是不存在的标签：{src}")
        if dst not in tags:
            raise SweepError(f"合并目标是不存在的标签（不许新建）：{dst}")

    for src, dst in plan.dir_merges:
        if src not in dirs:
            raise SweepError(f"合并源是不存在的目录：{src}")
        if dst not in dirs:
            raise SweepError(f"合并目标是不存在的目录（不许新建）：{dst}")

    # a→b 且 b→c 会绕圈。所有 from 也不能出现在任何 to 里。
    sources = {s for s, _ in plan.tag_merges} | {s for s, _ in plan.dir_merges}
    targets = {d for _, d in plan.tag_merges} | {d for _, d in plan.dir_merges}
    if sources & targets:
        raise SweepError(
            f"合并方案会绕圈——这些既是源又是目标：{'、'.join(sorted(sources & targets))}"
        )


# ------------------------------------------------------------ 落盘

def _retag(meta: dict, merges: dict[str, str]) -> bool:
    """按合并表改 `主题`。改动了返回 True。"""
    tags = meta.get("主题") or []
    if isinstance(tags, str):
        tags = [tags]

    out: list[str] = []
    for tag in tags:
        name = merges.get(str(tag), str(tag))
        if name not in out:          # 合并后可能与已有的重了——去重
            out.append(name)
    if out == list(tags):
        return False
    meta["主题"] = out
    return True


def apply_plan(plan: SweepPlan, vault_root: Path) -> list[Path]:
    """按计划落盘。**不调 LLM**。返回动过的文件（供 commit 用）。

    **返回的清单要同时收旧路径和新路径。**
    `commit_changes` 拿它去 `git add`——新路径让 git 看见新增，
    旧路径（已从磁盘消失但 git 跟踪过）让 git 看见删除，两边都 staged
    才会被识别成一次 rename。**只收新路径的话，移动过的文件会漏提交。**
    """
    from kb.core.vault import write_note

    tag_merges = dict(plan.tag_merges)
    touched: list[Path] = []

    # ① 目录合并：先移文件（连带它的子目录），再改每篇的标签
    for src, dst in plan.dir_merges:
        src_dir = vault_root / src
        dst_dir = vault_root / dst
        dst_dir.mkdir(parents=True, exist_ok=True)
        # 目录名本身也是一级标签——并过去
        tag_merges.setdefault(src.rsplit("/", 1)[-1], dst.rsplit("/", 1)[-1])
        for path in sorted(src_dir.rglob("*")):
            if not path.is_file():
                continue
            target = dst_dir / path.relative_to(src_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            path.replace(target)
            touched.append(path)       # 旧路径——让 git 看见「删了」
            touched.append(target)     # 新路径——让 git 看见「新增」
        for leftover in sorted(src_dir.rglob("*"), reverse=True):
            if leftover.is_dir():
                leftover.rmdir()
        src_dir.rmdir()

    # ② 标签合并：全库过一遍 frontmatter。
    #    **放在移动之后**——这时路径已经是新的了。
    if tag_merges:
        for path in sorted(vault_root.rglob("*.md")):
            if any(part.startswith("_") for part in path.relative_to(vault_root).parts):
                continue
            meta, body = read_note(path)
            if _retag(meta, tag_merges):
                write_note(path, meta, body)
                if path not in touched:        # 移过来的那些已经在里面了
                    touched.append(path)

    return touched
