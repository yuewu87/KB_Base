# 定时整理（巡检）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 服务启动时若距上次巡检超过 6 天，后台跑一次只读扫描 + LLM 整理，收拾**标签和目录**（不碰正文），完事弹窗告知，报告放侧栏做成聊天式。

**Architecture:** **复用现有的整理链**——巡检只是换了个输入（整个库的标签与目录，而不是一条草稿），后面的校验 / 审核 / 落盘 / commit 一模一样。**一次 LLM 调用**：输入是标签清单 + 目录树，输出直接是变更计划（不先出「人话建议」再翻译一遍）。

**Tech Stack:** Python 3.11、FastAPI、Jinja2、pytest（LLM 全 mock）、ruff。

**依据：** [`docs/03_问题记录.md`](../../03_问题记录.md) Q81、[`docs/01_架构.md`](../../01_架构.md) 第九节。

---

## 范围（定过的边界）

| 做 | 不做 |
|---|---|
| 标签去重（近义标签合并） | **正文一个字不动** |
| 分类合并（近义词目录合并） | **补关联链接**——那要改正文的「相关」一节 |
| 更新索引页 | **新建分类**——「归一不新建」 |
| | 打包、入口替换、成功判据（用户说都不急） |

**连带后果（记着，不算这次的任务）：** 需求里「知识的**关联性**」那半仍然没着落——它现在只有「整理时强制至少一个链接」+ Obsidian 反链。补链接要改正文，被这次的范围排除了。

### 两个关键事实（决定了这件事比看上去轻）

**① 合并标签不用移动文件。** 标签是 frontmatter 里的 `主题` 字段，改它只改一行。

**② 合并目录不用改链接。** Obsidian 的 `[[链接]]` 按**文件名**解析，不按路径——笔记里写的都是 `[[窗口置前要请求前台]]`，目录挪了照样点得开。`known_link_targets` 也是短名与相对路径都收。

**所以目录合并只动两处：文件位置 + frontmatter 里的 `主题`。**

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `src/kb/core/sweep_state.py` | 「上次巡检」与「报告读没读」的存读 | **新建** |
| `src/kb/core/sweep.py` | 扫描（只读）+ 计划（LLM）+ 落盘 | **新建** |
| `src/kb/api/http.py` | 启动时触发；报告与回复端点 | 改 |
| `src/kb/api/cli.py` | `kb sweep`（手动跑一次，便于调试） | 改 |
| `src/kb/web/router.py` | 报告进侧栏；回复端点 | 改 |
| `src/kb/web/templates/flow.html` | 侧栏加「巡检报告」聊天块 | 改 |
| `src/kb/web/static/style.css` | 报告气泡、两个按钮 | 改 |
| `data/state.json` | 落点（**不进 git**，`data/` 整棵已排除） | — |

---

## Task 1: 状态文件

**Files:**
- Create: `src/kb/core/sweep_state.py`
- Create: `tests/core/test_sweep_state.py`

- [ ] **Step 1: 写失败测试**

`tests/core/test_sweep_state.py`：

```python
"""巡检的状态：上次什么时候跑的、报告读没读。"""

from datetime import datetime, timedelta

from kb.core.sweep_state import (
    SWEEP_INTERVAL,
    due,
    load_state,
    mark_read,
    save_report,
)


def test_missing_state_means_due(tmp_path):
    """从没跑过 —— 该跑。"""
    assert due(tmp_path) is True


def test_recent_sweep_not_due(tmp_path):
    save_report(tmp_path, {"summary": "x"}, when=datetime(2026, 9, 17, 10, 0))
    assert due(tmp_path, now=datetime(2026, 9, 20, 10, 0)) is False


def test_old_sweep_is_due(tmp_path):
    save_report(tmp_path, {"summary": "x"}, when=datetime(2026, 9, 1, 10, 0))
    assert due(tmp_path, now=datetime(2026, 9, 17, 10, 0)) is True


def test_boundary_is_six_days(tmp_path):
    """刚好 6 天不算超——超过才跑。"""
    base = datetime(2026, 9, 1, 10, 0)
    save_report(tmp_path, {"summary": "x"}, when=base)
    assert due(tmp_path, now=base + timedelta(days=6)) is False
    assert due(tmp_path, now=base + timedelta(days=7)) is True
    assert SWEEP_INTERVAL.days == 6


def test_report_starts_unread(tmp_path):
    save_report(tmp_path, {"summary": "合并了 2 组标签"})
    state = load_state(tmp_path)
    assert state["report"]["summary"] == "合并了 2 组标签"
    assert state["report"]["read"] is False


def test_mark_read(tmp_path):
    save_report(tmp_path, {"summary": "x"})
    mark_read(tmp_path)
    assert load_state(tmp_path)["report"]["read"] is True


def test_state_file_lives_under_data(tmp_path):
    save_report(tmp_path, {"summary": "x"})
    assert (tmp_path / "state.json").is_file()


def test_corrupt_state_treated_as_never_run(tmp_path):
    """文件坏了当作没跑过——宁可多跑一次，也不要永远不跑。"""
    (tmp_path / "state.json").write_text("{ 坏掉的", encoding="utf-8")
    assert due(tmp_path) is True
    assert load_state(tmp_path) == {}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_sweep_state.py -q
```

**Expected:** `ModuleNotFoundError: No module named 'kb.core.sweep_state'`

- [ ] **Step 3: 实现**

`src/kb/core/sweep_state.py`：

```python
"""巡检的状态：上次什么时候跑的、报告读没读。

存在 `data/state.json`（服务侧，**不进 git**——`data/` 整棵已排除）。

**为什么不用日志推**：流程日志是流水，要算「上次巡检」得倒着找；这里就两个
字段，单独放一个文件最省事。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

# 距上次超过这个间隔就该跑。用户定的是「一次（6 天），超过才跑」。
SWEEP_INTERVAL = timedelta(days=6)

_FILE = "state.json"
_FMT = "%Y-%m-%d %H:%M:%S"


def state_path(data_dir: Path) -> Path:
    return data_dir / _FILE


def load_state(data_dir: Path) -> dict:
    """读状态。文件不存在或坏掉都返回 `{}`——**宁可多跑一次，也别永远不跑**。"""
    path = state_path(data_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data_dir: Path, state: dict) -> None:
    path = state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def due(data_dir: Path, now: datetime | None = None) -> bool:
    """距上次巡检是否已超过 `SWEEP_INTERVAL`。从没跑过 → True。"""
    last = load_state(data_dir).get("last_sweep")
    if not last:
        return True
    try:
        last_at = datetime.strptime(last, _FMT)
    except ValueError:
        return True
    return (now or datetime.now()) - last_at > SWEEP_INTERVAL


def save_report(data_dir: Path, report: dict, when: datetime | None = None) -> None:
    """记下「跑过了」并留一份**未读**报告。"""
    when = when or datetime.now()
    state = load_state(data_dir)
    state["last_sweep"] = f"{when:{_FMT}}"
    state["report"] = {**report, "at": f"{when:{_FMT}}", "read": False}
    _write(data_dir, state)


def mark_read(data_dir: Path) -> None:
    state = load_state(data_dir)
    if "report" in state:
        state["report"]["read"] = True
        _write(data_dir, state)
```

- [ ] **Step 4: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_sweep_state.py -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests
git add -A && git commit -m "feat: 巡检的状态文件——上次何时跑、报告读没读"
```

---

## Task 2: 扫描与计划

**巡检只看标签和目录，不看正文。** 所以输入很小。

**Files:**
- Create: `src/kb/core/sweep.py`
- Create: `tests/core/test_sweep.py`

- [ ] **Step 1: 写失败测试**

`tests/core/test_sweep.py`：

```python
"""巡检：扫标签与目录 → 让 LLM 决定怎么合并。"""

import json

import pytest

from kb.core.sweep import SweepError, collect_tags, list_dir_tree, parse_plan
from kb.core.vault import write_note

# 注意：`SweepPlan` 和 `FakeLLM` 这两轮用不上——Task 3 的测试在函数里
# 局部 import `SweepPlan`，Task 4 才用 `FakeLLM`。写在这里会 F401。


def _vault(tmp_path):
    """一个能看出「有近义词该合并」的小库。

    **每行都拆开写**——中文按东亚宽度算两列，塞一行就过不了
    `line-length = 100`（看着只有 90 来个字符，实际超）。
    """
    write_note(
        tmp_path / "计算机" / "git" / "a.md",
        {"类型": "概念", "主题": ["计算机", "git"]},
        "x",
    )
    write_note(
        tmp_path / "计算机" / "版本控制" / "b.md",
        {"类型": "概念", "主题": ["计算机", "版本控制"]},
        "y",
    )
    write_note(
        tmp_path / "艺术" / "透视" / "c.md",
        {"类型": "概念", "主题": ["艺术", "透视"]},
        "z",
    )
    return tmp_path


def test_collect_tags_counts_and_sorts(tmp_path):
    got = collect_tags(_vault(tmp_path))
    assert got["计算机"] == 2
    assert got["git"] == 1
    assert list(got) == sorted(got)


def test_list_dir_tree_is_relative(tmp_path):
    got = list_dir_tree(_vault(tmp_path))
    assert "计算机/git" in got
    assert "艺术/透视" in got
    assert "计算机" in got


def test_dir_tree_excludes_meta_dirs(tmp_path):
    v = _vault(tmp_path)
    (v / "_索引").mkdir(exist_ok=True)
    assert not any(d.startswith("_") for d in list_dir_tree(v))


def test_parse_plan_reads_merges():
    raw = json.dumps(
        {
            "tag_merges": [{"from": "git", "to": "版本控制"}],
            "dir_merges": [{"from": "计算机/git", "to": "计算机/版本控制"}],
            "summary": "合并 git 到版本控制",
        },
        ensure_ascii=False,
    )
    plan = parse_plan(raw)
    assert plan.tag_merges == [("git", "版本控制")]
    assert plan.dir_merges == [("计算机/git", "计算机/版本控制")]
    assert plan.summary


def test_parse_plan_tolerates_empty_merges():
    plan = parse_plan('{"tag_merges": [], "dir_merges": []}')
    assert plan.tag_merges == []
    assert plan.is_empty


def test_parse_plan_rejects_bad_json():
    with pytest.raises(SweepError):
        parse_plan("不是 JSON")


def test_parser_rejects_non_list_merges():
    with pytest.raises(SweepError, match="tag_merges"):
        parse_plan('{"tag_merges": {"from": "a"}, "dir_merges": []}')


def test_plan_tells_llm_only_about_tags_and_dirs(tmp_path):
    """提示词里只有标签和目录——**不喂正文**（用户定的边界）。

    **正文里要放一个独有的标记再断言它不在提示词里。**
    早先这版断言的是 `"x" not in prompt`，而笔记正文正好是 `"x"`——
    它碰巧过了，但过的原因是**提示词里根本没出现过字母 x**，不是因为
    正文被挡住了。将来提示词里出现 `text`、`example` 这类词，这条就会
    因为无关原因挂掉，而且挂的时候你会以为是边界破了。
    """
    from kb.core.sweep import build_prompt

    v = tmp_path
    write_note(
        v / "计算机" / "git" / "a.md",
        {"类型": "概念", "主题": ["计算机", "git"]},
        "# 标题\n\n正文里有个独有标记 ZQXMARK。\n",
    )
    write_note(
        v / "计算机" / "版本控制" / "b.md",
        {"类型": "概念", "主题": ["计算机", "版本控制"]},
        "y",
    )

    prompt = build_prompt(v)
    assert "git" in prompt
    assert "计算机/版本控制" in prompt
    assert "ZQXMARK" not in prompt      # 正文的独有标记没进提示词
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_sweep.py -q
```

**Expected:** `ModuleNotFoundError: No module named 'kb.core.sweep'`

- [ ] **Step 3: 实现**

`src/kb/core/sweep.py`：

```python
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
```

- [ ] **Step 4: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_sweep.py -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests
git add -A && git commit -m "feat: 巡检的扫描与计划——只看标签和目录，不看正文"
```

---

## Task 3: 校验与落盘

**只合并、不新建。** 目标必须已存在——这条把「模型乱起名字」挡在门外。

**Files:**
- Modify: `src/kb/core/sweep.py`
- Modify: `tests/core/test_sweep.py`

- [ ] **Step 1: 写失败测试**

```python
def test_validate_rejects_unknown_tag_target(tmp_path):
    from kb.core.sweep import SweepPlan, validate

    plan = SweepPlan(tag_merges=[("git", "根本没这个标签")])
    with pytest.raises(SweepError, match="不存在的标签"):
        validate(plan, _vault(tmp_path))


def test_validate_rejects_unknown_dir_target(tmp_path):
    from kb.core.sweep import SweepPlan, validate

    plan = SweepPlan(dir_merges=[("计算机/git", "计算机/没这个目录")])
    with pytest.raises(SweepError, match="不存在的目录"):
        validate(plan, _vault(tmp_path))


def test_validate_rejects_chain(tmp_path):
    """a→b 且 b→c 会绕圈。"""
    from kb.core.sweep import SweepPlan, validate

    plan = SweepPlan(tag_merges=[("git", "版本控制"), ("版本控制", "计算机")])
    with pytest.raises(SweepError, match="绕"):
        validate(plan, _vault(tmp_path))


def test_validate_accepts_good_plan(tmp_path):
    from kb.core.sweep import SweepPlan, validate

    validate(SweepPlan(tag_merges=[("git", "版本控制")]), _vault(tmp_path))


def test_apply_merges_tags_in_notes(tmp_path):
    from kb.core.sweep import SweepPlan, apply_plan
    from kb.core.vault import read_note

    v = _vault(tmp_path)
    apply_plan(SweepPlan(tag_merges=[("git", "版本控制")]), v)

    meta, _ = read_note(v / "计算机" / "git" / "a.md")
    assert "版本控制" in meta["主题"]
    assert "git" not in meta["主题"]


def test_apply_merges_tags_without_duplicating(tmp_path):
    """a 里本来就有「版本控制」，合并不该出现两个。"""
    from kb.core.sweep import SweepPlan, apply_plan
    from kb.core.vault import read_note, write_note

    v = tmp_path
    write_note(v / "计算机" / "x.md", {"类型": "概念", "主题": ["git", "版本控制"]}, "y")
    apply_plan(SweepPlan(tag_merges=[("git", "版本控制")]), v)

    assert read_note(v / "计算机" / "x.md")[0]["主题"] == ["版本控制"]


def test_apply_moves_directory_and_retags(tmp_path):
    from kb.core.sweep import SweepPlan, apply_plan
    from kb.core.vault import read_note

    v = _vault(tmp_path)
    apply_plan(SweepPlan(dir_merges=[("计算机/git", "计算机/版本控制")]), v)

    assert not (v / "计算机" / "git").exists()
    assert (v / "计算机" / "版本控制" / "a.md").is_file()
    meta, _ = read_note(v / "计算机" / "版本控制" / "a.md")
    assert "git" not in meta["主题"]
    assert "版本控制" in meta["主题"]


def test_apply_returns_files_touched(tmp_path):
    """落盘要报告动过哪些文件——落盘后的 commit 照它 add。"""
    from kb.core.sweep import SweepPlan, apply_plan

    v = _vault(tmp_path)
    touched = apply_plan(SweepPlan(tag_merges=[("git", "版本控制")]), v)
    assert any(p.name == "a.md" for p in touched)


def test_apply_reports_both_sides_of_a_move(tmp_path):
    """目录移动要**旧路径和新路径都报**。

    `commit_changes` 拿这份清单去 `git add`：新路径让 git 看见新增，
    旧路径（已从磁盘消失但 git 跟踪过）让 git 看见删除。只报新路径的话，
    **移动过的文件会漏提交**——而且 commit 照样成功，你看不出来。
    """
    from kb.core.sweep import SweepPlan, apply_plan

    v = _vault(tmp_path)
    touched = apply_plan(SweepPlan(dir_merges=[("计算机/git", "计算机/版本控制")]), v)

    rels = {p.relative_to(v).as_posix() for p in touched}
    assert "计算机/git/a.md" in rels        # 旧路径（让 git 看见删除）
    assert "计算机/版本控制/a.md" in rels    # 新路径（让 git 看见新增）


def test_apply_reports_a_moved_file_even_if_its_tags_did_not_change(tmp_path):
    """光移动目录、标签没变的文件也要进清单。

    早先的写法只在 `_retag` 返回 True 时才 append，于是这类文件
    **不会被 add**——目录挪了，文件却留在 git 的旧位置上。
    """
    from kb.core.sweep import SweepPlan, apply_plan

    v = tmp_path
    # 主题里本来就没有目录名那一级，所以移动之后 `_retag` 不会改它
    write_note(v / "计算机" / "git" / "a.md", {"类型": "概念", "主题": ["计算机"]}, "x")
    write_note(v / "计算机" / "版本控制" / "b.md", {"类型": "概念", "主题": ["计算机"]}, "y")

    touched = apply_plan(SweepPlan(dir_merges=[("计算机/git", "计算机/版本控制")]), v)

    rels = {p.relative_to(v).as_posix() for p in touched}
    assert "计算机/版本控制/a.md" in rels
    assert "计算机/git/a.md" in rels


def test_apply_empty_plan_is_noop(tmp_path):
    from kb.core.sweep import SweepPlan, apply_plan

    v = _vault(tmp_path)
    assert apply_plan(SweepPlan(), v) == []
```

- [ ] **Step 2: 跑测试确认失败**

**Expected:** `ImportError: cannot import name 'validate'`

- [ ] **Step 3: 实现**

`src/kb/core/sweep.py` 追加：

```python
# ------------------------------------------------------------ 校验

def validate(plan: SweepPlan, vault_root: Path) -> None:
    """纯静态检查。不过就抛 SweepError，**vault 一个字节没动**。"""
    tags = set(collect_tags(vault_root))
    dirs = set(list_dir_tree(vault_root))

    for src, dst in plan.tag_merges:
        if src not in tags:
            raise SweepError(f"要合并的标签不存在：{src}")
        if dst not in tags:
            raise SweepError(f"合并目标的标签不存在（不许新建）：{dst}")

    for src, dst in plan.dir_merges:
        if src not in dirs:
            raise SweepError(f"要合并的目录不存在：{src}")
        if dst not in dirs:
            raise SweepError(f"合并目标的目录不存在（不许新建）：{dst}")

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
```

> **顺序要紧：先移目录，再全库改标签。** 反过来的话，移动完路径变了，刚改过的标签就白改。

- [ ] **Step 4: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_sweep.py -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests
git add -A && git commit -m "feat: 巡检的校验与落盘——只合并已有的，不许新建"
```

---

## Task 4: 接进服务 + 启动时触发

**Files:**
- Modify: `src/kb/api/http.py`、`src/kb/api/cli.py`
- Create: `tests/api/test_sweep_api.py`

- [ ] **Step 1: 写失败测试**

```python
"""巡检接进服务：手动跑一次、启动时按需触发。"""

from kb.api.http import run_sweep


def test_run_sweep_saves_report(tmp_path):
    from kb.core.sweep_state import load_state

    (tmp_path / "计算机" / "git").mkdir(parents=True)
    write_note(tmp_path / "计算机" / "git" / "a.md", {"类型": "概念", "主题": ["计算机", "git"]}, "x")
    write_note(tmp_path / "计算机" / "版本控制" / "b.md", {"类型": "概念", "主题": ["计算机", "版本控制"]}, "y")

    report = run_sweep(tmp_path, tmp_path, FakeLLM(_merge_json()))
    assert report["tag_merges"] or report["dir_merges"]
    assert load_state(tmp_path)["report"]["read"] is False


def test_run_sweep_on_clean_vault_reports_nothing(tmp_path):
    (tmp_path / "计算机").mkdir(parents=True)
    report = run_sweep(tmp_path, tmp_path, FakeLLM('{"tag_merges": [], "dir_merges": []}'))
    assert report["summary"] is not None
```

- [ ] **Step 2: 跑测试确认失败**

**Expected:** `ImportError: cannot import name 'run_sweep'`

- [ ] **Step 3: 实现 `run_sweep`**

`src/kb/api/http.py`：

```python
def run_sweep(vault_root: Path, data_dir: Path, llm: LLM) -> dict:
    """跑一次巡检：规划 → 校验 → 落盘 → commit → 存报告。

    **它走的是和整理草稿同一条链**，只是输入换成了整个库的标签与目录。
    """
    plan = sweep.make_plan(vault_root, llm)
    sweep.validate(plan, vault_root)

    if plan.is_empty:
        report = {"summary": plan.summary or "没什么要收拾的", "tag_merges": [], "dir_merges": []}
        sweep_state.save_report(data_dir, report)
        return report

    flow.set_run(flow.new_run_id())
    flow.emit("规划", f"巡检发现：{plan.summary or '有可以合并的'}")
    touched = sweep.apply_plan(plan, vault_root)
    _commit_sweep(vault_root, touched, plan)

    report = {
        "summary": plan.summary,
        "tag_merges": [{"from": a, "to": b} for a, b in plan.tag_merges],
        "dir_merges": [{"from": a, "to": b} for a, b in plan.dir_merges],
        "touched": [p.relative_to(vault_root).as_posix() for p in touched],
    }
    sweep_state.save_report(data_dir, report)
    return report
```

配套：
- `_commit_sweep(vault_root, touched, plan)`：照 `organize.commit_changes` 写，一次一个 commit，message 用 `plan.summary`
- `GET /sweep` 返回当前报告与「读没读」
- `POST /sweep/reply` `{"reply": "知道了" | "调整", "note": "..."}`
  - 「知道了」→ `mark_read`
  - 「调整」→ 把 `note` 当一条草稿投进收件箱并立刻整理（走 `push_and_organize`）
- **启动时**：`create_app` 里

```python
    # 距上次巡检超过 6 天就跑一次——**后台线程**，不挡启动
    if sweep_state.due(data_dir):
        threading.Thread(
            target=_sweep_in_background, args=(cfg.vault_path, data_dir), daemon=True
        ).start()
```

`_sweep_in_background` 里**先把 last_sweep 写上再跑**——否则服务重启会重复跑：

```python
def _sweep_in_background(vault_root: Path, data_dir: Path) -> None:
    """后台跑巡检。**绝不抛异常**——后台线程里抛了没人接。"""
    # 先占坑：万一跑挂了也不会每次重启都重跑
    sweep_state.save_report(data_dir, {"summary": "巡检正在跑…"})
    try:
        run_sweep(vault_root, data_dir, build_llm(load_config()))
    except Exception:      # noqa: BLE001
        logging.getLogger("kb.sweep").exception("巡检失败")
        sweep_state.save_report(data_dir, {"summary": "这次巡检没跑成，看运行日志"})
```

- [ ] **Step 4: CLI 加 `kb sweep`**（手动跑一次，调试用）

```python
def cmd_sweep(args) -> int:
    cfg = load_config()
    with make_client(cfg) as client:
        resp = client.post("/sweep")
        resp.raise_for_status()
        data = resp.json()
    print(f"巡检完成：{data['summary']}")
    for m in data["tag_merges"]:
        print(f"  标签：{m['from']} → {m['to']}")
    for m in data["dir_merges"]:
        print(f"  目录：{m['from']} → {m['to']}")
    return 0
```

- [ ] **Step 5: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
git add -A && git commit -m "feat: 巡检接进服务——启动时按需触发，另留 kb sweep 手动跑"
```

---

## Task 5: 报告进侧栏（聊天式 + 两个按钮）

**Files:**
- Modify: `src/kb/web/router.py`、`flow.html`、`style.css`
- Modify: `tests/web/test_router.py`

- [ ] **Step 1: 写失败测试**

```python
def test_flow_page_shows_sweep_report(client, vault):
    from kb.core.sweep_state import save_report

    save_report(vault, {"summary": "合并了 2 组近义标签", "tag_merges": [], "dir_merges": []})
    body = client.get("/flow").text
    aside = re.search(r'<aside class="chat-history">(.*?)</aside>', body, re.S).group(1)
    assert "合并了 2 组近义标签" in aside


def test_flow_page_has_two_reply_buttons(client, vault):
    from kb.core.sweep_state import save_report

    save_report(vault, {"summary": "x", "tag_merges": [], "dir_merges": []})
    body = client.get("/flow").text
    assert "我知道了" in body
    assert "还需调整" in body


def test_reply_known_marks_read(client, vault):
    from kb.core.sweep_state import load_state, save_report

    save_report(vault, {"summary": "x"})
    client.post("/sweep/reply", data={"reply": "知道了"}, follow_redirects=False)
    assert load_state(vault)["report"]["read"] is True


def test_reply_adjust_queues_a_draft(client, vault):
    """「还需调整」——把你写的话当一条草稿投出去，走整理流程。"""
    from kb.core.sweep_state import save_report
    from kb.core.vault import list_drafts

    save_report(vault, {"summary": "x"})
    client.post(
        "/sweep/reply",
        data={"reply": "调整", "note": "别把 shell 并进命令行"},
        follow_redirects=False,
    )
    drafts = list_drafts(vault)
    assert len(drafts) == 1
    assert "别把 shell 并进命令行" in read_draft(drafts[0]).body


def test_sweep_run_button_exists_on_every_page(client):
    """侧栏上有个「巡检一次」按钮——两个动作按钮之一。"""
    assert "巡检一次" in client.get("/").text
    assert "巡检一次" in client.get("/flow").text


def test_sweep_run_updates_last_sweep(client, vault):
    """手动跑一次，上次巡检时间要跟着更新（用户明说的要求）。"""
    from kb.core.sweep_state import load_state

    client.post("/sweep/run", follow_redirects=False)
    assert load_state(vault).get("last_sweep")


def test_sweep_run_ignores_the_six_day_gate(client, vault):
    """刚跑过也能再手动跑——不受 6 天限制（那是自动触发才看的）。"""
    from kb.core.sweep_state import save_report

    save_report(vault, {"summary": "刚跑过"})
    resp = client.post("/sweep/run", follow_redirects=False)
    assert resp.status_code == 303
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 路由**

`web/router.py` 的 `/flow` 把报告带进上下文：

```python
    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request):
        state = sweep_state.load_state(data_dir)
        return templates.TemplateResponse(
            request,
            "flow.html",
            _ctx(
                "flow",
                groups=group_flow(read_flow(data_dir)),
                steps=STEPS,
                report=state.get("report"),
            ),
        )

    @router.post("/sweep/reply")
    def sweep_reply(reply: str = Form(...), note: str = Form("")):
        if reply == "知道了":
            sweep_state.mark_read(data_dir)
        elif note.strip():
            # 你的意见当一条草稿投出去——走整理那条链
            push_and_organize(cfg, note, get_llm(), source="Web")
            sweep_state.mark_read(data_dir)
        return RedirectResponse("/flow", status_code=303)
```

- [ ] **Step 4: 侧栏加报告块**

`flow.html` 的 `<aside>` 里，流程链**上面**加：

```html
{% if report and not report.read %}
  <div class="thread">
    <div class="bubble assistant">
      <strong>这次巡检收拾了这些：</strong>
      <ul>
        {% for m in report.tag_merges %}<li>标签：{{ m.from }} → {{ m.to }}</li>{% endfor %}
        {% for m in report.dir_merges %}<li>目录：{{ m.from }} → {{ m.to }}</li>{% endfor %}
      </ul>
      <p>{{ report.summary }}</p>
    </div>
  </div>
  <form class="sweep-reply" method="post" action="/sweep/reply">
    <button name="reply" value="知道了">我知道了</button>
    <button name="reply" value="调整" formnovalidate
            onclick="document.getElementById('sweep-note').hidden = false">还需调整</button>
    <input id="sweep-note" name="note" placeholder="要改哪里？" hidden>
  </form>
{% endif %}
```

- [ ] **Step 5: 加样式** —— `.sweep-reply` 两个按钮并排；`.bubble.assistant` 复用现成的。

- [ ] **Step 6: 加「一键巡检」按钮**

**用户要的：不光能等它自动跑，也能手动点一下就跑；跑完更新「上次巡检时间」。**

按钮放**侧栏顶部**，和「＋ 记一条」并列——两个都是动作，不是页面：

```html
<form method="post" action="/sweep/run">
  <button class="side-action" type="submit">
    <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M20 11a8 8 0 1 0-2.3 5.7"/>
      <path d="M20 5v6h-6"/>
    </svg>
    <span class="side-label">巡检一次</span>
  </button>
</form>
```

路由（`web/router.py`）：

```python
    @router.post("/sweep/run")
    def sweep_run():
        """手动跑一次巡检。

        **不受 6 天限制**——是你主动要跑的。跑完 `run_sweep` 会写
        `last_sweep`，所以自动那条也跟着顺延。
        """
        run_sweep(cfg.vault_path, data_dir, get_llm())
        return RedirectResponse("/flow", status_code=303)
```

> **同步跑**，和 `/new`（Q88 之后投递也走完整理）一个路子：点完等它跑完，
> 页面转到工作日志看报告。**巡检比单条投递慢**（要全库过一遍 + 一次 LLM），
> 但它是低频动作，等一会儿可以接受。
>
> **如果实测下来太慢**（比如库大了要等几十秒），再改成后台跑 + 页面轮询——
> 那时 `_sweep_in_background` 已经在了，复用即可。

**「跑完更新整理时间」不用额外写**：`run_sweep` 最后调 `sweep_state.save_report`，
它本来就写 `last_sweep`（Task 1）。

- [ ] **Step 7: 跑测试 + 全量 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
git add -A && git commit -m "feat: 巡检报告进侧栏 + 一键巡检按钮"
```

---

## Task 6: 侧栏统一（手机聊天式）+ 流程链三态

**两件事一起做，因为它们落在同一处：**

1. **流程链要区分三态**（原来只有两态）——`审核` 常常显示成「没走到」，但它其实是**没触发**（没新建分类，所以不跑）。看到 ○ 会以为卡住了
2. **侧栏统一成一套手机聊天样式**——整理日志、工作日志、巡检报告都用同一个组件；**每一条内容一个气泡**

**以及一条硬规矩：界面里不得出现 emoji 或类 emoji 符号，需要的标记一律内联 SVG。**

> 现状：`flow.html:31` 用了 `✓`（U+2713）和 `○`（U+25CB）——**这两处要换掉**（它们是唯一的）。

**Files:**
- Modify: `src/kb/web/data.py`（`group_flow` 算出三态）
- Modify: `src/kb/web/templates/flow.html`、`journal.html`
- Modify: `src/kb/web/static/style.css`
- Modify: `tests/web/test_data.py`、`tests/web/test_router.py`

- [ ] **Step 1: 写失败测试**

`tests/web/test_data.py` 追加：

```python
def test_group_flow_splits_three_states():
    """走过 / 跳过 / 没走到，是三回事。

    中间没出现的步骤，要看**它后面有没有记录**：
    后面有 → 流程越过了它，是「跳过」（比如审核没触发）
    后面没有 → 流程停在那里了，是「没走到」
    """
    rows = [
        {"run": "a", "step": "投递", "text": "t", "at": "t"},
        {"run": "a", "step": "规划", "text": "t", "at": "t"},
        {"run": "a", "step": "落盘", "text": "t", "at": "t"},
    ]
    g = group_flow(rows, steps=["投递", "规划", "校验", "审核", "落盘", "提交"])[0]
    assert g["reached"] == {"投递", "规划", "落盘"}
    assert g["skipped"] == {"校验", "审核"}      # 越过了
    assert g["todo"] == {"提交"}                 # 停在落盘之后


def test_group_flow_last_record_failure_leaves_rest_todo():
    """流程停在「规划」——后面全是没走到，不是跳过。"""
    rows = [
        {"run": "a", "step": "投递", "text": "t", "at": "t"},
        {"run": "a", "step": "规划", "text": "t", "at": "t"},
    ]
    g = group_flow(rows, steps=["投递", "规划", "校验", "审核", "落盘", "提交"])[0]
    assert g["skipped"] == set()
    assert g["todo"] == {"校验", "审核", "落盘", "提交"}


def test_group_flow_without_steps_keeps_old_shape():
    """不传 steps 时不算三态——向后兼容，老的调用点不炸。"""
    rows = [{"run": "a", "step": "投递", "text": "t", "at": "t"}]
    g = group_flow(rows)[0]
    assert g["reached"] == {"投递"}
```

`tests/web/test_router.py` 追加：

```python
def test_flow_chain_uses_svg_marks_not_text_symbols(client, vault):
    """界面里不许出现 emoji / 类 emoji 符号——标记一律内联 SVG。"""
    from kb.core.flow import emit, set_run

    set_run("20260917-1400")
    emit("投递", "投了")
    emit("落盘", "落了")

    body = client.get("/flow").text
    assert "✓" not in body
    assert "○" not in body
    assert body.count("<svg") >= 6          # 六个步骤各一个标记


def test_journal_sidebar_uses_bubbles(client):
    """整理日志的侧栏也是气泡流。"""
    import re

    body = client.get("/journal").text
    aside = re.search(r'<aside class="chat-history">(.*?)</aside>', body, re.S).group(1)
    assert 'class="bubble assistant"' in aside
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/web/ -q
```

**Expected:** 三态那条 `KeyError: 'skipped'`

- [ ] **Step 3: `group_flow` 算出三态**

`src/kb/web/data.py`：

```python
def group_flow(rows: list[dict], steps: list[str] | None = None) -> list[dict]:
    """按 run 分组，**新的在前**。

    传了 `steps` 就把六个步骤分成三类：

    - `reached` —— 有记录的
    - `skipped` —— 没记录，但**它后面有记录**（流程越过了它）
    - `todo`    —— 没记录，且后面也没有（流程停在前头了）

    **`skipped` 和 `todo` 要分开。** 比如「审核」常常没记录——那是没触发
    （没新建分类所以不跑），不是卡住了。画成一样会让人以为出了问题。
    """
    groups: dict[str, dict] = {}
    for row in rows:
        run = row.get("run") or "（未分组）"
        g = groups.setdefault(
            run, {"run": run, "rows": [], "reached": set(), "at": ""}
        )
        g["rows"].append(row)
        g["reached"].add(row.get("step", ""))
        g["at"] = g["at"] or row.get("at", "")

    out = list(groups.values())
    if steps:
        for g in out:
            seen = [i for i, s in enumerate(steps) if s in g["reached"]]
            last = max(seen) if seen else -1
            g["skipped"] = {s for i, s in enumerate(steps) if i < last and s not in g["reached"]}
            g["todo"] = {s for i, s in enumerate(steps) if i > last}
    return list(reversed(out))
```

- [ ] **Step 4: 三个 SVG 标记 + 统一气泡**

`flow.html` 的链，把 `{{ '✓' if ... }}` 换成三个内联 SVG：

```html
{% for step in steps %}
  {% set state = 'done' if step in g.reached
                 else ('skipped' if step in g.skipped else 'todo') %}
  <div class="chain-step {{ state }}">
    {% if state == 'done' %}
      <svg class="mark" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7" fill="currentColor"/>
        <path d="M4.8 8.3l2.1 2.1 4.3-4.5" fill="none" stroke="#fff"
              stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    {% elif state == 'skipped' %}
      <svg class="mark" viewBox="0 0 16 16" aria-hidden="true">
        <title>这一步没触发</title>
        <circle cx="8" cy="8" r="6.3" fill="none" stroke="currentColor" stroke-width="1.4"/>
        <path d="M5 8h6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
      </svg>
    {% else %}
      <svg class="mark" viewBox="0 0 16 16" aria-hidden="true">
        <title>还没走到</title>
        <circle cx="8" cy="8" r="6.3" fill="none" stroke="currentColor" stroke-width="1.4"/>
      </svg>
    {% endif %}
    <span>{{ step }}</span>
  </div>
  {% if not loop.last %}<div class="chain-line"></div>{% endif %}
{% endfor %}
```

**工作日志的侧栏：每条流程一个气泡**（现在是一行 `<li>`）：

```html
<aside class="chat-history">
  <h2>流程</h2>
  {% for g in groups %}
    <div class="thread">
      {% for r in g.rows %}
        <div class="bubble assistant">
          <span class="bubble-at">{{ r.at[-8:] }}</span>{{ r.text }}
        </div>
      {% endfor %}
    </div>
    <div class="chain">…（上面的三态链）…</div>
  {% endfor %}
</aside>
```

**整理日志的侧栏** 也是同一套（每条 = 一个气泡），跟现在一样，只是套上统一的 `.thread > .bubble`。

- [ ] **Step 5: 加样式**

`style.css` 加一段「侧栏气泡」，整理日志 / 工作日志 / 巡检报告共用：

```css
/* ---- 侧栏气泡：手机聊天式 ---- */
.thread { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }

.bubble {
  position: relative;
  padding: 9px 12px;
  border-radius: 12px;
  font-size: 12.5px;
  line-height: 1.6;
  background: var(--surface);
  border: 1px solid var(--line);
  color: #37445a;
  word-break: break-word;
}
.bubble.assistant {
  border-top-left-radius: 4px;          /* 左边一个小尾巴的圆角 */
  background: #f6f8fb;
}
.bubble.user { background: var(--blue-soft); border-color: #dbe7f4; }

.bubble-at {
  display: block;
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--faint);
  margin-bottom: 2px;
}

/* ---- 流程链的三个标记 ---- */
.mark { width: 14px; height: 14px; flex-shrink: 0; }
.chain-step.done    .mark { color: var(--blue); }
.chain-step.skipped .mark { color: var(--faint); }
.chain-step.todo    .mark { color: var(--line); }
.chain-step.skipped { color: var(--faint); }
.chain-step.todo    { color: #b9c3d0; }
```

`.chain-line` 的 `margin-left` 要与 `.mark` 居中——**标记从 14px 变成 14px 不变，不用改**。

- [ ] **Step 6: 跑测试 + 全量 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
git add -A && git commit -m "design: 侧栏统一为手机聊天式；流程链区分走过/跳过/未走到"
```

- [ ] **Step 7: 全仓扫一遍 emoji**

```bash
PYTHONIOENCODING=utf-8 "D:/Conda_base/envs/kn_base/python.exe" -c "
import re, pathlib
pat = re.compile('[\U0001F300-\U0001FAFF\U00002600-\U000027BF\u2713\u2714\u2717\u2718\u25CB\u25CF\u2261]')
hits = [(p, i, line.strip()[:50])
        for p in pathlib.Path('src/kb/web').rglob('*') if p.is_file()
        for i, line in enumerate(p.read_text(encoding='utf-8', errors='replace').splitlines(), 1)
        if pat.search(line)]
print(f'命中 {len(hits)} 处')
for p, i, line in hits:
    print(f'  {p}:{i}  {line}')
"
```

**Expected:** `命中 0 处`

---

## Self-Review

**1. 范围覆盖：**

| 定过的 | 落在哪 |
|---|---|
| 服务启动时检查、超 6 天跑 | Task 1（判定）+ Task 4（触发） |
| 后台跑，不挡用户 | Task 4（daemon 线程） |
| 只碰标签和目录，不碰正文 | Task 2（prompt 里没有正文）+ Task 3（只动 frontmatter 与位置） |
| 一次 LLM 调用 | Task 2 |
| 要建文件的走审核 | **不适用**——「只合并不新建」把这条路堵死了（见下） |
| 弹窗 + 侧栏聊天式 + 两个回复按钮 | Task 5 |
| 「还需调整」→ 输入 → 交给整理 LLM | Task 5 |
| **手动一键巡检**（不受 6 天限制，跑完更新上次时间） | Task 5 Step 6 |
| **流程链区分「跳过」与「未走到」** | Task 6 |
| **侧栏统一手机聊天式，每条一个气泡，两页共用** | Task 6 |
| **界面里不得出现 emoji，标记一律内联 SVG** | Task 6 |

**2. 「审核」这条为什么不在这份计划里：**

用户说「如有建立文件之类的需要审核的需求就给审核判定」。**但巡检按设计只能合并到已有目录，不许新建**——所以「建立文件」这个需求根本不会出现。`review.review_plan` 那条链在整理草稿时仍然跑着，巡检这边不需要。

**如果以后放开「巡检可以新建分类」，那时才需要接审核。**

**3. 占位符扫描：** 无 TBD / TODO。

**4. 已知风险：**

- **`apply_plan` 里的目录移动没做事务回滚。** `organize` 有 `Transaction` 做精确回滚，巡检这边没接。移到一半失败会留下半拉子。**先记着**——真要接，`Transaction` 现成，加进去不难。
- **`_sweep_in_background` 里 `load_config()`** 会读 `.env`，而 `load_dotenv` **同进程只该调一次**（`config.load_config` 的 docstring 写了）。`create_app` 已经调过，所以这里应该复用那个 `cfg` ——**执行时照这个改**，别重新 load。
- **目录移动之后，`_索引/` 里的索引页** 的 Dataview 查询是 `FROM "计算机"`（领域），子目录移动不影响它。**但如果以后索引页按子目录出，就要跟着改。**

---

## 验收

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**端到端（真实 LLM）：**

1. `kb sweep` 手动跑一次 → 看它提的合并建议**准不准**（这一步最重要，建议的质量决定这件事值不值得做）
2. vault 里确认：标签真的合并了、目录真的移了、**正文一个字没动**
3. `git -C E:/KB_Library log -1` → 一次巡检 = 一个 commit
4. 打开**工作日志页** → 侧栏有报告，两个按钮
5. 点「我知道了」→ 刷新，报告不在了
6. 再跑一次，点「还需调整」→ 填一句话 → 收件箱里多一条草稿
7. 把 `data/state.json` 的 `last_sweep` 改成 7 天前 → `kb stop` 再 `kb inbox`（拉起服务）→ 后台应自动跑起来
