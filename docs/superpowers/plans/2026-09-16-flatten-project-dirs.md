# 摊平项目目录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把知识库的项目目录从 `10_项目/<分组>/<项目名>/` 摊平成 `10_项目/<项目名>/`，删掉分组层的全部假设。

**Architecture:** 分组层是一个人造的中间层，只由一个常量 `PROJECT_GROUPS` 维护。摊平 = 删掉这个常量，再把 5 处「假设项目目录在两层之下」的代码改成一层。数据侧零迁移——`10_项目/` 下只有两个空目录。

**Tech Stack:** Python 3.11、pytest、ruff、conda 环境 `kn_base`

**前置背景（设计理由）：** 见 `docs/规划总纲.md` 第二节第 1 条、`docs/问题记录.md` Q63。这层当初的设想是分「个人项目」和「工作项目」，它也是 Q30「服务从不自动新建项目文件夹」的成因——服务要建目录就得在两个分组里选一个，那是需要判断的分类动作。摊平后 `10_项目/<项目名>/` 由项目名唯一确定，不再有「选哪个分组」这回事。

**不在本计划范围内（另立计划）：** 闭环重跑（把现有 4 篇笔记转成投递内容、移除、重投、验证「进项目 → 抽离可复用知识」这条路）。它与本计划独立，本计划做完后单独立一份。

---

## 文件结构

**不新增任何文件**，这是纯改造。

| 文件 | 职责 | 本计划动它什么 |
|---|---|---|
| `src/kb/core/vault.py` | vault 路径常量与笔记读写 | `find_project_dir`、`list_projects` |
| `src/kb/core/planning.py` | 提示词、目标路径判定、静态校验 | `_is_existing_project_dir`、`build_messages`、提示词、报错文案 |
| `src/kb/core/organize.py` | 落盘编排 | **不动**（只是透传 `list_projects` 的返回值） |
| `scripts/init_vault.py` | vault 骨架的唯一真源 | 删 `PROJECT_GROUPS` |
| `tests/core/test_vault.py` | | 7 处 |
| `tests/core/test_planning.py` | | 夹具 + 3 处 |
| `tests/core/test_organize.py` | | 夹具 1 处 |
| `tests/test_init_vault.py` | | 1 个用例 |
| `README.md`、`docs/问题记录.md`、`docs/需求梳理.md` | 结构描述 | 6 处 |

**测试总数基线：258 个。** 本计划会删掉 1 个用例（`test_creates_topic_and_group_dirs` 拆成一个）、改写 1 个（歧义用例换构造方式），最终数量以实跑为准。

**命令速查（本机 `conda run` 会报内部错误，勿用）：**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -v
```

---

## Task 1: 项目目录存在性校验改成一层

**这是整件事的核心。** 不改它，摊平后**所有**项目笔记都会被判「目录不存在」而进待归类。

**Files:**
- Modify: `tests/core/test_planning.py:29-40`（夹具）、`:166-190`（两个用例）
- Modify: `src/kb/core/planning.py:245-254`

- [ ] **Step 1: 把夹具改成一层目录**

`tests/core/test_planning.py:29-40`，改第 33 行：

```python
@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """一个最小可用的 vault：有一个主题、一个索引页、一个项目。"""
    (tmp_path / KNOWLEDGE / "后端").mkdir(parents=True)
    (tmp_path / "10_项目" / "电商后台").mkdir(parents=True)
    ensure_topic_index(tmp_path, "后端")
    write_note(
        tmp_path / KNOWLEDGE / "后端" / "队列串行化.md",
        {"类型": "概念", "主题": ["后端"]},
        "# 队列串行化\n",
    )
    return tmp_path
```

> 该夹具被 **22 个测试函数**使用，但这行改动只影响两个 `project_dir` 用例的具体路径。

- [ ] **Step 2: 改两个校验用例的 target_path**

`tests/core/test_planning.py:166-190` 整段替换：

```python
def test_validate_rejects_nonexistent_project_dir(vault):
    """Q30：服务从不自动新建项目文件夹——项目必须已经存在。

    否则模型给一个不存在的项目名，就能凭空造出一个项目目录。
    """
    plan = parse_plan(
        DRAFT.id,
        _plan_json(
            target_path="10_项目/不存在的项目/不存在的项目-踩坑.md",
            frontmatter={"类型": "踩坑", "主题": ["后端"], "项目": "不存在的项目"},
        ),
    )
    with pytest.raises(PlanError, match="项目目录不存在"):
        validate_plan(plan, vault)


def test_validate_allows_existing_project_dir(vault):
    plan = parse_plan(
        DRAFT.id,
        _plan_json(
            target_path="10_项目/电商后台/电商后台-踩坑.md",
            frontmatter={"类型": "踩坑", "主题": ["后端"], "项目": "电商后台"},
        ),
    )
    validate_plan(plan, vault)
```

- [ ] **Step 3: 跑测试，确认 `allows` 那个失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_planning.py -k "project_dir" -v
```

**Expected:** `test_validate_allows_existing_project_dir` **FAIL**，抛 `PlanError: 项目目录不存在，服务不会自动新建（Q30）…`

`test_validate_rejects_nonexistent_project_dir` 仍会 PASS——`len(parts) == 2` 对一层路径也返回 `False`，两种实现下它都不放行。**真正有区分度的是 `allows` 这个用例。**

- [ ] **Step 4: 改实现**

`src/kb/core/planning.py:245-254` 整段替换：

```python
def _is_existing_project_dir(vault_root: Path, path: Path) -> bool:
    """`path` 是否为 `10_项目/<项目名>` 这样的**既有**项目目录。

    项目目录必须真的存在——服务从不自动新建项目文件夹（Q30）。
    """
    try:
        rel = path.relative_to(vault_root / PROJECTS)
    except ValueError:
        return False
    return len(rel.parts) == 1 and path.is_dir()
```

- [ ] **Step 5: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_planning.py -v
```

**Expected:** 全 PASS

- [ ] **Step 6: 提交**

```bash
git add src/kb/core/planning.py tests/core/test_planning.py
git commit -m "refactor: 项目目录存在性校验改为一层（摊平 Q9）"
```

---

## Task 2: `find_project_dir` 摊平

**Files:**
- Modify: `tests/core/test_vault.py:194-220`
- Modify: `src/kb/core/vault.py:186-205`

- [ ] **Step 1: 改 5 个测试**

`tests/core/test_vault.py:194-220` 整段替换：

```python
def test_find_project_dir_unique_match(tmp_path):
    target = tmp_path / "10_项目" / "电商后台"
    target.mkdir(parents=True)
    assert find_project_dir(tmp_path, "电商后台") == target


def test_find_project_dir_matches_across_separator_styles(tmp_path):
    target = tmp_path / "10_项目" / "KN_Base"
    target.mkdir(parents=True)
    assert find_project_dir(tmp_path, "kn-base") == target


def test_find_project_dir_returns_none_when_absent(tmp_path):
    (tmp_path / "10_项目").mkdir(parents=True)
    assert find_project_dir(tmp_path, "不存在") is None


def test_find_project_dir_returns_none_for_empty_name(tmp_path):
    (tmp_path / "10_项目").mkdir(parents=True)
    assert find_project_dir(tmp_path, "") is None


def test_find_project_dir_returns_none_on_ambiguity(tmp_path):
    """规范化后同名 → 不猜，返回 None，走待归类。"""
    (tmp_path / "10_项目" / "KN_Base").mkdir(parents=True)
    (tmp_path / "10_项目" / "kn_base").mkdir(parents=True)
    assert find_project_dir(tmp_path, "kn-base") is None
```

> **最后一个用例的意图变了。** 原来是「两个分组下同名」，摊平后不可能了。但歧义**仍然存在**——`KN_Base` 和 `kn_base` 两个目录规范化后都是 `kn-base`。改用这个构造，保住 Q30「找不到或找到多个都不猜」的后半条。

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_vault.py -k "project_dir" -v
```

**Expected:** `unique_match` 和 `matches_across_separator_styles` **FAIL**（旧实现把 `10_项目/电商后台` 当成「分组」，再往下一层找，找不到项目）。

另外三个仍 PASS——旧实现下它们本来也返回 `None`。

- [ ] **Step 3: 改实现**

`src/kb/core/vault.py:186-205` 整段替换：

```python
def find_project_dir(vault_root: Path, name: str) -> Path | None:
    """在 `10_项目/<项目名>` 下搜唯一匹配。

    找不到或有多个同名 → 返回 None（不猜，走待归类）。
    """
    if not name:
        return None
    root = vault_root / PROJECTS
    if not root.exists():
        return None

    target = normalize_project(name)
    matches = [
        p for p in sorted(root.iterdir())
        if p.is_dir() and normalize_project(p.name) == target
    ]
    return matches[0] if len(matches) == 1 else None
```

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_vault.py -v
```

**Expected:** 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/vault.py tests/core/test_vault.py
git commit -m "refactor: find_project_dir 摊平为一层"
```

---

## Task 3: `list_projects` 去掉分组名

`list_projects` 现在返回 `list[tuple[str, Path]]`，那个 `str` 就是分组名。返回值形状一路透传到 `build_messages` 的签名和喂给 LLM 的提示词文本。**三处必须同时改，否则中途是坏状态。**

**Files:**
- Modify: `tests/core/test_vault.py:223-227`
- Modify: `tests/core/test_planning.py:305-310`
- Modify: `src/kb/core/vault.py:208-220`
- Modify: `src/kb/core/planning.py:145-165`

> `src/kb/core/organize.py:175` 只是把 `list_projects(vault_root)` 的结果原样传给 `build_messages`，**不需要改**。

- [ ] **Step 1: 改两个测试**

`tests/core/test_vault.py:223-227` 替换：

```python
def test_list_projects_returns_paths(tmp_path):
    (tmp_path / "10_项目" / "A").mkdir(parents=True)
    (tmp_path / "10_项目" / "B").mkdir(parents=True)
    assert [p.name for p in list_projects(tmp_path)] == ["A", "B"]
```

`tests/core/test_planning.py:305-310` 替换：

```python
def test_build_messages_lists_topics_and_projects(vault):
    msgs = build_messages(DRAFT, [], [vault / "10_项目" / "电商后台"], ["后端"], vault)
    assert "后端" in msgs[1]["content"]
    assert "电商后台" in msgs[1]["content"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_vault.py tests/core/test_planning.py -k "list_projects or build_messages" -v
```

**Expected:** `test_list_projects_returns_paths` **FAIL**（`p.name` 作用在 tuple 上，`AttributeError`）。`test_build_messages_lists_topics_and_projects` 断言本身只查子串，可能仍 PASS——但入参形状已经不对了，以 Task 3 全部跑完为准。

- [ ] **Step 3: 改 `vault.py`**

`src/kb/core/vault.py:208-220` 整段替换：

```python
def list_projects(vault_root: Path) -> list[Path]:
    """列出 `10_项目/<项目名>` 下的所有项目。"""
    root = vault_root / PROJECTS
    if not root.exists():
        return []
    return [p for p in sorted(root.iterdir()) if p.is_dir()]
```

- [ ] **Step 4: 改 `planning.py`**

`src/kb/core/planning.py:148` 签名改一个类型：

```python
def build_messages(
    draft: Draft,
    candidates: list[Candidate],
    projects: list[Path],
    topics: list[str],
    vault_root: Path,
) -> list[dict]:
```

`src/kb/core/planning.py:161-165` 替换：

```python
    proj_lines = (
        "\n".join(f"- {p.name}" for p in projects)
        if projects
        else "（知识库里还没有任何项目文件夹）"
    )
```

- [ ] **Step 5: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_vault.py tests/core/test_planning.py -v
```

**Expected:** 全 PASS

- [ ] **Step 6: 提交**

```bash
git add src/kb/core/vault.py src/kb/core/planning.py tests/core/test_vault.py tests/core/test_planning.py
git commit -m "refactor: list_projects 不再返回分组名"
```

---

## Task 4: 删掉分组常量

**Files:**
- Modify: `tests/test_init_vault.py:13`、`:31-36`
- Modify: `scripts/init_vault.py:33`、`:60`

- [ ] **Step 1: 改测试**

`tests/test_init_vault.py:13` 替换：

```python
from scripts.init_vault import KNOWLEDGE_TOPICS, init_vault, vault_dirs
```

`tests/test_init_vault.py:31-36` 整段替换：

```python
def test_creates_topic_dirs(tmp_path):
    init_vault(tmp_path)
    for topic in KNOWLEDGE_TOPICS:
        assert (tmp_path / KNOWLEDGE / topic).is_dir()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_init_vault.py -v
```

**Expected:** 收集期 `ImportError: cannot import name 'PROJECT_GROUPS' from 'scripts.init_vault'`

- [ ] **Step 3: 改脚本**

`scripts/init_vault.py:33` —— **整行删掉**：

```python
PROJECT_GROUPS = ["个人", "工作"]
```

`scripts/init_vault.py:60` —— **整行删掉**：

```python
    dirs += [vault_root / PROJECTS / g for g in PROJECT_GROUPS]
```

> `vault_root / PROJECTS` 已在 `:52` 建过，删除后目录列表依然完整。

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_init_vault.py -v
```

**Expected:** 全 PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/init_vault.py tests/test_init_vault.py
git commit -m "refactor: vault 骨架不再创建个人/工作分组目录"
```

---

## Task 5: 清掉剩下的「分组」文案

代码逻辑已经改完，剩下两处写死在字符串里的层级模板。它们不影响行为，但会误导读它的人（和读它的 LLM）。

**Files:**
- Modify: `src/kb/core/planning.py:120`
- Modify: `src/kb/core/planning.py:296-300`

- [ ] **Step 1: 先确认没有测试依赖这些文案**

```bash
grep -rn "分组" tests/ src/ scripts/
```

**Expected:** 只剩 `src/kb/core/planning.py` 的两处（`120` 行的提示词、`296-300` 行的报错文案）。若 `tests/` 下有命中，先改测试再改源码。

- [ ] **Step 2: 改提示词硬规则**

`src/kb/core/planning.py:120` 替换：

```
1. target_path 必须落在 `10_项目/<项目名>/` 或 `20_知识/<既有主题>/` 下。
```

- [ ] **Step 3: 改报错文案**

`src/kb/core/planning.py:296-300` 替换：

```python
        raise PlanError(
            "项目目录不存在，服务不会自动新建（Q30）。"
            "请先手工建好 `10_项目/<项目名>/`，或改走 20_知识/ 或 pending："
            f"{plan.target_path}"
        )
```

- [ ] **Step 4: 跑全量测试**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -v
```

**Expected:** 全 PASS。`test_validate_rejects_nonexistent_project_dir` 的 `match="项目目录不存在"` 只匹配子串，不受影响。

- [ ] **Step 5: 跑风格检查**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**Expected:** `All checks passed!`

- [ ] **Step 6: 提交**

```bash
git add src/kb/core/planning.py
git commit -m "docs: 提示词与报错文案同步为摊平后的路径模板"
```

---

## Task 6: 更新文档里的结构描述

**Files:**
- Modify: `README.md:140-142`、`README.md:358`
- Modify: `docs/问题记录.md:76-78`、`:243-246`、`:566`
- Modify: `docs/需求梳理.md:168`

- [ ] **Step 1: 改 README 目录树**

`README.md:140-142` 把三行：

```
├── 10_项目/
│   ├── 个人/<项目名>/       ← <项目名>-架构.md、<项目名>-决策.md、<项目名>-踩坑.md
│   └── 工作/<项目名>/
```

改成两行：

```
├── 10_项目/
│   └── <项目名>/            ← <项目名>-架构.md、<项目名>-决策.md、<项目名>-踩坑.md
```

- [ ] **Step 2: 改 README 的 commit message 示例**

`README.md:358`：`- 合并入 10_项目/个人/XXX/XXX-踩坑.md` → `- 合并入 10_项目/XXX/XXX-踩坑.md`

- [ ] **Step 3: 改问题记录**（三处同一性质）

- `docs/问题记录.md:76-78`（Q9 目录树）：`个人/<项目名>/` + `工作/<项目名>/` 两行 → `<项目名>/` 一行
- `docs/问题记录.md:243-246`（Q30 说明）：保持结论不变，只把路径模板从 `10_项目/<分组>/<项目名>` 改成 `10_项目/<项目名>`
- `docs/问题记录.md:566`（Q46 的 commit 示例）：同 Step 2

- [ ] **Step 4: 改需求梳理**

`docs/需求梳理.md:168`：把「库里现在实际是 `10_项目/个人/<项目名>/`」改为 `10_项目/<项目名>/`

- [ ] **Step 5: 核对剩下几处已经写对了的**

```bash
grep -rn "个人\|工作" README.md docs/问题记录.md docs/需求梳理.md docs/命名规则.md docs/规划总纲.md
```

**Expected:** 剩余命中都是「工作日志」「工作记录」这类概念名，不是分组名。

- [ ] **Step 6: 提交**

```bash
git add README.md docs/问题记录.md docs/需求梳理.md
git commit -m "docs: 目录结构描述同步为摊平后的一层"
```

---

## Task 7: 数据迁移 + 端到端验证

**逻辑改完了不代表能用。** 这一步确认「摊平」和「Q30 校验」真的对上了。

**Files:**
- 数据：`E:\KB_Library\10_项目\个人\`、`E:\KB_Library\10_项目\工作\`

- [ ] **Step 1: 确认那两个目录确实是空的**

```bash
find "E:/KB_Library/10_项目" -type f
```

**Expected:** 无输出（零文件）。**若有输出就停下来**——说明有项目笔记，迁移需要搬文件改链接，本计划的假设不成立。

- [ ] **Step 2: 删掉两个空的组目录**

```bash
rmdir "E:/KB_Library/10_项目/个人" "E:/KB_Library/10_项目/工作"
```

- [ ] **Step 3: 停掉在跑的服务**

```bash
cd "E:/Study_Projects/KN_Base" && ./kb.bat stop
```

> **这一步不能省。** 改了 `src/` 下的代码，在跑的服务仍执行旧逻辑。`kb status` 会告警，但停掉最干净。

- [ ] **Step 4: 手工建项目目录**

```bash
mkdir "E:/KB_Library/10_项目/KN_Base"
```

> Q30：服务不自动新建项目目录。阶段一保留这条（「审核拦乱建」要等阶段二）。

- [ ] **Step 5: 投一条草稿**

```bash
cd "E:/Study_Projects/KN_Base" && ./kb.bat push --content "摊平目录的验证草稿：项目目录从两层改成一层，分组层删掉了。" --project KN_Base --source 会话
```

**Expected:** `已收，id=2026xxxx-xxxx`

- [ ] **Step 6: 触发整理**

```bash
./kb.bat organize
```

**Expected:** `整理完成，1 条：` 且该条 `[created]` 的 detail 里路径是 `10_项目/KN_Base/KN_Base-<类型>.md`

**这是本计划的验收点。** 如果 detail 显示 `[pending] … 项目目录不存在`，说明 Task 1 的 `len(rel.parts) == 1` 没生效。

- [ ] **Step 7: 确认文件真的落在那儿**

```bash
find "E:/KB_Library/10_项目" -type f
```

**Expected:** 一条 `10_项目/KN_Base/KN_Base-<类型>.md`。打开看 frontmatter 里 `项目: KN_Base`。

- [ ] **Step 8: 提交这步产生的 vault 改动**

```bash
git -C "E:/KB_Library" -c core.quotepath=false status --short
```

确认只有 `10_项目/` 的删除（两个空目录，git 不跟踪空目录，所以可能没有）+ 新笔记 + 索引页 + 整理日志，然后提交。

---

## Self-Review

**1. 规格覆盖：** `10_项目/<分组>/<项目名>` → `10_项目/<项目名>` 的每一处「两层假设」都对应到任务了——校验（Task 1）、同名搜索（Task 2）、项目清单形状（Task 3）、骨架常量（Task 4）、文案（Task 5）、文档（Task 6）、数据与验证（Task 7）。

**2. 占位符扫描：** 无 TBD / TODO / 「类似 Task N」/ 无代码的代码步骤。

**3. 类型一致性：** `list_projects` 在 Task 3 里从 `list[tuple[str, Path]]` 改成 `list[Path]`，`build_messages` 的 `projects` 参数同步改成 `list[Path]`。Task 2 的 `find_project_dir` 仍返回 `Path | None`（未变）。`_is_existing_project_dir` 仍返回 `bool`（未变）。调用点 `organize.py:175` 不做改动，因为它只透传。

**4. 已知的认定：** 本计划假设 `10_项目/` 下只有两个空目录——Task 7 Step 1 用命令再确认一次，不成立就停。

---

## 收尾

跑完 Task 7 后：

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -v
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

全绿即本计划完成。**下一步是另一份计划：闭环重跑。**
