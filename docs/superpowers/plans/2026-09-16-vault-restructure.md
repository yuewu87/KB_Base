# 知识库重建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把知识库从旧结构（编号目录 + 项目层）重建成新结构（**领域为一级目录**），补上审核、修改、检索、Web UI，最后用一个真实项目的副本做端到端投递验收。

**Architecture:** 三部分，顺序不能颠倒。

| 部分 | 做什么 | 完成的样子 |
|---|---|---|
| **一 · 清理** | 把建立在旧结构上的一切删干净——项目层代码、相关测试、测试数据 | 测试重新全绿（数量变少），代码只剩下与结构无关的部分 |
| **二 · 重建** | 按 [`docs/01_架构.md`](../../01_架构.md) 写新结构 | 能投递、能整理、能改、能查、有界面 |
| **三 · 测试** | 拿 `04_RPA_restart` 的副本做端到端投递 | 真实内容落进正确的领域，分类自己长出来且不重复 |

**清理部分的原则：不为兼容旧结构做任何妥协。** 凡是旧结构阻碍的，一律删除，不做「留着以后可能用得上」的处理。

**Tech Stack:** Python 3.11（conda 环境 `kn_base`）、FastAPI、Jinja2、pytest（LLM 全 mock）、ruff。

**依据文档：**

| 文档 | 作用 |
|---|---|
| [`docs/01_架构.md`](../../01_架构.md) | **目标架构**——本文实现的就是它 |
| [`docs/03_问题记录.md`](../../03_问题记录.md) | 逐条的理由与由来 |

**命令速查（本机 `conda run` 会报内部错误，勿用；默认 `python` 没装 pytest）：**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -v
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

---

## 文件结构

**不新增模块目录，只调整已有的。**

| 文件 | 本计划动它什么 |
|---|---|
| `src/kb/core/vault.py` | **大改**——删项目函数、改路径常量、加标题清洗 |
| `src/kb/core/planning.py` | **大改**——删项目校验、重写提示词、加审核调用点 |
| `src/kb/core/classify.py` | 改 `knowledge_topics` → `list_domains` |
| `src/kb/core/organize.py` | 加审核步骤、加修改能力 |
| `src/kb/core/journal.py` | 改日志目录常量 |
| `src/kb/core/models.py` | 加失效标记字段、加审核结果类型 |
| `src/kb/api/cli.py` | 加 `search`、`revise` 参数 |
| `src/kb/api/http.py` | 加 `/search`、`/revise` 端点 |
| `src/kb/web/` | **新建**——Web UI |
| `scripts/init_vault.py` | 改目录清单 |
| `templates/` | 删死文件 `日志.md` |
| `tests/` | 删 26 个、改若干、加新的 |

---

# 第一部分：清理

## Task 1: 清空 vault

**为什么先做这个：** 现有 7 篇笔记全是测试数据（用户明确说过「没有正式使用前都是测试」），而新结构要求领域目录在根上——留着旧目录只会让后面每一步都要处理「新旧并存」。

**Files:**
- Modify: `E:/KB_Library`（整个 vault 的内容）

- [ ] **Step 1: 确认仓库干净、记下当前状态**

```bash
git -C "E:/KB_Library" status --short
git -C "E:/KB_Library" rev-list --count HEAD
```

**Expected:** 无输出（干净），提交数 `12`。**若有未提交改动，停下来问**——可能有人在 Obsidian 里编辑过。

- [ ] **Step 2: 删掉所有旧目录与笔记**

```bash
cd "E:/KB_Library" && git rm -r -q --ignore-unmatch \
  "00_收件箱" "10_项目" "20_知识" "30_素材" "40_索引" "90_附件"
find . -type d -empty -not -path "./.git/*" -delete
```

**Expected:** `git status --short` 显示大量 `D` 开头的删除。

- [ ] **Step 3: 留下仓库与历史，提交这次清空**

```bash
git -C "E:/KB_Library" commit -q -m "chore: 清空测试内容，准备按新结构重建

现有 7 篇笔记全部是测试数据（没有正式使用前都是测试），不做迁移。
旧结构 00_收件箱/10_项目/20_知识/30_素材/40_索引/90_附件 整个作废，
改为领域为一级目录 + _收件箱/_索引/_附件。

仓库与历史保留——历史是测试记录，删掉没好处。"
git -C "E:/KB_Library" status --short
```

**Expected:** 无输出。

> **不删 `.git`。** 如果之后确实想彻底重来，那是单独一条命令的事（`rm -rf .git && git init -b main`），但**不在本计划内**——保留历史能看到当初测试了什么。

- [ ] **Step 4: 确认 vault 只剩空壳**

```bash
ls -a "E:/KB_Library"
```

**Expected:** 只有 `.`、`..`、`.git`、`.gitignore`。

---

## Task 2: 删掉项目层的代码

旧结构里「项目」是一个**目录**：`10_项目/<项目名>/`。新结构里它降为 frontmatter 字段，**不影响笔记的物理位置**。所以相关代码整块删除。

**Files:**
- Modify: `src/kb/core/vault.py:28-37`（常量）、`:176-220`（项目函数）
- Modify: `src/kb/core/planning.py`（校验 + 提示词 + `build_messages`）
- Modify: `src/kb/core/organize.py:34,175`
- Modify: `scripts/init_vault.py:29,51`

- [ ] **Step 1: 删 `vault.py` 的项目函数**

删掉这三块（`src/kb/core/vault.py`）：

```python
# 删掉整个「项目名（Q30）」小节，即 L176 的分隔线注释到 L220 之前
def normalize_project(name: str) -> str: ...
def find_project_dir(vault_root: Path, name: str) -> Path | None: ...
def list_projects(vault_root: Path) -> list[Path]: ...
```

**保留 `project_name_from_cwd`（L213-233）**——CLI 的 `--project` 默认值还用它，它只是从 git 根取个名字，与目录结构无关。

同时删掉只被 `normalize_project` 使用的 `_SEPARATOR_RE`（`vault.py:39`）：

```python
_SEPARATOR_RE = re.compile(r"[-_\s]+")
```

删完后跑：

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src/kb/core/vault.py
```

**Expected:** 若报 `re` 未使用，把 `import re` 一并删掉（`vault.py` 顶部）。

- [ ] **Step 2: 删 `planning.py` 的项目校验**

`src/kb/core/planning.py` 删掉三个函数：

```python
def _is_existing_project_dir(vault_root: Path, path: Path) -> bool: ...      # L253-262
def _project_note_name_error(target: Path) -> str | None: ...               # L265-282
```

改 `allowed_prefixes`（L246-250），**只保留领域根**：

```python
def allowed_prefixes(vault_root: Path) -> list[Path]:
    """允许写入的目录。领域是固定的几个，子分类由 LLM 自建。"""
    return [vault_root / domain for domain in list_domains(vault_root)]
```

改 `validate_plan`——**删掉三处 PROJECTS 分支**（L315-319 的报错文案改掉、L321-328、L330-333、L348-354 的名称一致性检查）。

- [ ] **Step 3: 删 `build_messages` 的 projects 参数**

`src/kb/core/planning.py:153-199`，签名去掉 `projects`，并删掉渲染它的那段：

```python
def build_messages(
    draft: Draft,
    candidates: list[Candidate],
    topics: list[str],
    vault_root: Path,
) -> list[dict]:
```

删掉 `proj_lines` 的构造（L169-173）和 `## 知识库现有项目` 小节（L188）。

调用点 `src/kb/core/organize.py:175` 同步去掉 `list_projects(vault_root)` 这个实参，并删掉 L34 的 import。

- [ ] **Step 4: 跑测试，看炸了什么**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q 2>&1 | tail -20
```

**Expected:** 收集期大量 `ImportError`（测试还在 import 已删的函数）。**这是对的**——Task 3 处理测试。

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/vault.py src/kb/core/planning.py src/kb/core/organize.py
git commit -m "refactor: 删掉项目层代码（Q68）
"
```

> 这条提交**测试是红的**（Task 3 才修）。这是刻意的——代码和测试分开提交，review 时能看清各自改了什么。

---

## Task 3: 删掉项目层的测试

**Files:**
- Modify: `tests/core/test_vault.py`
- Modify: `tests/core/test_planning.py`
- Modify: `tests/api/test_cli.py`
- Modify: `tests/api/test_http.py`

- [ ] **Step 1: 删 `test_vault.py` 的「项目名匹配（Q30）」整节**

删掉 `tests/core/test_vault.py` L178-236 整个小节，共 8 个测试函数：

```python
def test_normalize_project(raw, expected): ...                    # param 5 组
def test_find_project_dir_unique_match(tmp_path): ...
def test_find_project_dir_matches_across_separator_styles(tmp_path): ...
def test_find_project_dir_returns_none_when_absent(tmp_path): ...
def test_find_project_dir_returns_none_for_empty_name(tmp_path): ...
def test_find_project_dir_returns_none_on_ambiguity(tmp_path): ...
def test_list_projects_returns_paths(tmp_path): ...
def test_list_projects_empty_when_absent(tmp_path): ...
```

删掉 L14-21 里对应的 import（`find_project_dir`、`list_projects`、`normalize_project`）。

改 `test_list_notes_covers_projects_and_knowledge`（L170-175）——把 `10_项目/个人/P/P-踩坑.md` 换成一个领域下的笔记：

```python
def test_list_notes_covers_domains_and_meta(tmp_path):
    """扫正式笔记，不扫 _索引/。"""
    write_note(tmp_path / "计算机" / "a.md", {"类型": "概念"}, "a")
    write_note(tmp_path / "计算机" / "b.md", {"类型": "踩坑"}, "b")
    write_note(tmp_path / "_索引" / "计算机.md", {"类型": "索引"}, "不该被扫到")
    names = {p.name for p in list_notes(tmp_path)}
    assert names == {"a.md", "b.md"}
```

> 这条此刻会失败——`list_notes` 还在扫 `10_项目`/`20_知识`，而路径常量要到 Task 4 才改。**先在 Task 4 里连同常量一起改**，这里只把测试写好。

- [ ] **Step 2: 删 `test_planning.py` 的项目校验组**

删掉 5 个测试（L166-233）：

```python
def test_validate_rejects_nonexistent_project_dir(vault): ...
def test_validate_allows_existing_project_dir(vault): ...
def test_validate_rejects_project_note_without_type_suffix(vault): ...
def test_validate_rejects_project_note_without_project_prefix(vault): ...
def test_validate_rejects_project_note_type_mismatch(vault): ...
```

删掉 `test_system_prompt_distinguishes_project_from_knowledge`（L277-286）——「项目 vs 知识」这个区分不存在了。

删掉 `test_build_messages_lists_topics_and_projects`（L359-363）和 `test_build_messages_handles_empty_vault`（L365-368）里的项目断言部分。

改夹具（L29-40）——去掉 `10_项目/电商后台` 那行，换成领域：

```python
@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """一个最小可用的 vault：一个领域、一个索引页、一篇笔记。"""
    (tmp_path / "计算机").mkdir(parents=True)
    ensure_topic_index(tmp_path, "计算机")
    write_note(
        tmp_path / "计算机" / "队列串行化.md",
        {"类型": "概念", "主题": ["计算机"]},
        "# 队列串行化\n",
    )
    return tmp_path
```

- [ ] **Step 3: 改 `test_cli.py` 与 `test_http.py` 的项目相关测试**

这 4 个测试**不是删，是保留语义**——`--project` 还在，只是不再影响路径：

- `test_default_project_uses_git_root`（L89-97）——保留，断言不变
- `test_default_project_falls_back_to_cwd`（L100-104）——保留，断言不变
- `test_push_then_inbox_then_organize`（L109-119）——保留 `--project 电商后台`，但断言不再涉及项目目录
- `test_push_defaults_project_from_cwd`（L122-128）——保留
- `test_push_accepts_content_without_project`（`test_http.py:86-88`）——**语义要改**：以前「没项目 → 走 20_知识」，现在「没项目 → 照常归领域」。改名并改注释：

```python
def test_push_accepts_content_without_project(client):
    """没项目不是错误——`项目` 只是可选字段，不影响归到哪个领域。"""
```

- [ ] **Step 4: 跑全量测试**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q 2>&1 | tail -10
```

**Expected:** 仍有失败——`list_notes` 还在扫旧目录（Task 1 的 Step 1 埋的）。数量应比 Task 2 之后大幅减少。

- [ ] **Step 5: 提交**

```bash
git add tests/
git commit -m "test: 删掉项目层相关测试（26 个）
"
```

---

# 第二部分：重建

## Task 4: 路径常量与 vault 骨架改新结构

**这是重建的地基。** 后面的路径逻辑、提示词、模板全依赖它。

**Files:**
- Modify: `src/kb/core/vault.py:28-37`
- Modify: `src/kb/core/vault.py:164-173`（`list_notes`）
- Modify: `scripts/init_vault.py`
- Modify: `tests/test_init_vault.py`、`tests/core/test_organize.py`、`tests/core/test_vault.py`

- [ ] **Step 1: 改路径常量**

`src/kb/core/vault.py:28-37` 整段替换：

```python
# ---------------------------------------------------------------- 路径常量

INBOX = "_收件箱"
PENDING = "待归类"
INDEX = "_索引"
ATTACHMENTS = "_附件"
JOURNAL_DIR = "整理日志"

# 内置领域——`init_vault.py` 用它建目录。运行时的领域清单以磁盘为准。
SEED_DOMAINS = ["计算机", "艺术", "文学"]

# 机器目录前缀——一级目录里带这个前缀的不是领域
META_PREFIX = "_"

DRAFT_STATUS = "待整理"
```

> **为什么 `PROJECTS` / `KNOWLEDGE` / `MATERIALS` 直接不见了：** 它们不是改名，是**没了**。领域取代了 `20_知识`，而领域名不是常量（由磁盘上的目录决定）。

- [ ] **Step 2: 写失败测试——问领域清单**

在 `tests/core/test_vault.py` 末尾加：

```python
# ---------- 领域（Q67）----------

def test_list_domains_reads_top_level_dirs(tmp_path):
    """一级目录里不带 _ 前缀的就是领域。"""
    (tmp_path / "计算机").mkdir()
    (tmp_path / "艺术").mkdir()
    (tmp_path / "_收件箱").mkdir()
    (tmp_path / "_索引").mkdir()
    (tmp_path / ".obsidian").mkdir()
    assert list_domains(tmp_path) == ["艺术", "计算机"]


def test_list_domains_empty_when_only_meta(tmp_path):
    (tmp_path / "_收件箱").mkdir()
    assert list_domains(tmp_path) == []


def test_list_domains_ignores_files(tmp_path):
    (tmp_path / "计算机").mkdir()
    (tmp_path / "note.md").write_text("x", encoding="utf-8")
    assert list_domains(tmp_path) == ["计算机"]
```

并在文件顶部 import 加上 `list_domains`。

- [ ] **Step 3: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_vault.py -k domain -v
```

**Expected:** `ImportError: cannot import name 'list_domains'`

- [ ] **Step 4: 实现 `list_domains`**

`src/kb/core/vault.py`，放在 `list_notes` 后面：

```python
def list_domains(vault_root: Path) -> list[str]:
    """vault 一级目录里的领域名。

    机器目录（`_` 前缀）与隐藏目录（`.` 前缀）不算领域。
    """
    if not vault_root.exists():
        return []
    return sorted(
        p.name
        for p in vault_root.iterdir()
        if p.is_dir() and not p.name.startswith((META_PREFIX, "."))
    )
```

- [ ] **Step 5: 改 `list_notes` 扫领域**

`src/kb/core/vault.py:164-173` 整段替换：

```python
def list_notes(vault_root: Path) -> list[Path]:
    """列出正式笔记（各领域下的全部 *.md）。

    不含 `_索引/`——索引页与整理日志是结构性文件，不是知识笔记。
    """
    found: list[Path] = []
    for name in list_domains(vault_root):
        found.extend(p for p in (vault_root / name).rglob("*.md") if p.is_file())
    return sorted(found)
```

- [ ] **Step 6: 删 `classify.knowledge_topics`，改用 `list_domains`**

删掉 `src/kb/core/classify.py:95-104` 整个 `knowledge_topics` 函数，改 `src/kb/core/planning.py:26` 的 import：

```python
from kb.core.classify import Candidate
from kb.core.vault import INDEX, list_domains, list_notes
```

`planning.py` 里所有 `knowledge_topics(vault_root)` 改成 `list_domains(vault_root)`（共 3 处：`allowed_prefixes`、`build_messages` 的调用、`known_link_targets`）。

`tests/core/test_classify.py` 里测 `knowledge_topics` 的用例**移到 `test_vault.py`**（已在 Step 2 写了新的），原用例删除。

- [ ] **Step 7: 改 `init_vault.py`**

`scripts/init_vault.py` 的 import 块（L21-30）改成：

```python
from kb.core.vault import (  # noqa: E402 —— 必须在 sys.path 自举之后
    ATTACHMENTS,
    INBOX,
    INDEX,
    JOURNAL_DIR,
    PENDING,
    SEED_DOMAINS,
)
```

删掉 `KNOWLEDGE_TOPICS = [...]`（L32），`vault_dirs`（L46-59）改成：

```python
def vault_dirs(vault_root: Path) -> list[Path]:
    """列出骨架包含的全部目录（顺序即创建顺序）。"""
    dirs = [
        vault_root / INBOX,
        vault_root / INBOX / PENDING,
        vault_root / INDEX,
        vault_root / INDEX / JOURNAL_DIR,
        vault_root / ATTACHMENTS,
    ]
    dirs += [vault_root / d for d in SEED_DOMAINS]
    return dirs
```

- [ ] **Step 8: 改 `test_init_vault.py`**

`tests/test_init_vault.py` 全量调整——import 换常量、目录断言换新清单：

```python
from kb.core.vault import (
    ATTACHMENTS,
    INBOX,
    INDEX,
    JOURNAL_DIR,
    PENDING,
    SEED_DOMAINS,
)
from scripts.init_vault import init_vault, vault_dirs


def test_creates_all_skeleton_dirs(tmp_path):
    init_vault(tmp_path)
    for rel in (
        INBOX,
        f"{INBOX}/{PENDING}",
        INDEX,
        f"{INDEX}/{JOURNAL_DIR}",
        ATTACHMENTS,
        *SEED_DOMAINS,
    ):
        assert (tmp_path / rel).is_dir(), f"缺少目录 {rel}"
```

删掉 `test_creates_topic_dirs`（领域断言已并入上面）。`test_second_run_keeps_existing_notes` 里的 `KNOWLEDGE / "后端"` 改成 `"计算机"`。

- [ ] **Step 9: 改测试里对旧常量的引用**

**⚠️ 这一步比看起来大。** 两类都要改，别只改字面量：

```bash
# ① 硬编码的目录名字面量
grep -rn '"20_知识"\|"40_索引"\|"10_项目"\|"00_收件箱"\|"90_附件"\|"30_素材"' tests/
# ② 已被删掉的常量——这类才是大头，删了常量后整个文件都会 ImportError
grep -rn '\bKNOWLEDGE\b\|\bPROJECTS\b\|\bMATERIALS\b' tests/
```

**实测（2026-09-16 清理阶段跑出来的）：** `KNOWLEDGE` 被 6 个测试文件引用约 55 处——`test_organize.py`（约 25）、`test_classify.py`（10）、`test_planning.py`（7）、`test_http.py`（6）、`test_cli.py`（4）、`test_init_vault.py`（3）。**这些文件全部要改，否则 Task 4 Step 10 不可能全绿。**

替换规则：

| 旧 | 新 |
|---|---|
| `KNOWLEDGE / "后端"` | `"计算机"` |
| `KNOWLEDGE`（单独用） | 删掉，或换成具体的领域名 |
| `f"{KNOWLEDGE}/后端/…"` | `"计算机/…"` |
| `"40_索引"` / `INDEX` | `INDEX`（常量本身改成 `_索引`，不用动引用） |
| `"20_知识"` / `"40_索引"` 字面量 | 同上 |
| `PROJECTS` / `MATERIALS` | 删（没有对应物） |

**`INDEX`、`INBOX`、`ATTACHMENTS`、`JOURNAL_DIR` 这几个常量的引用不用动**——它们的值在 Step 1 已经改了，引用处自动跟着变。

- [ ] **Step 10: 跑全量测试**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q 2>&1 | tail -15
```

**Expected:** 全 PASS。**这一步是第一部分 + Task 4 的收口**——测试第一次重新全绿。

- [ ] **Step 11: 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
git add src/kb/core/vault.py src/kb/core/classify.py src/kb/core/planning.py scripts/init_vault.py tests/
git commit -m "refactor: 路径常量与 vault 骨架改为新结构（Q67/Q70）"
```

---

## Task 5: 文件名规则——统一内容标题

**Files:**
- Modify: `src/kb/core/vault.py`（加清洗函数）
- Modify: `src/kb/core/planning.py`（提示词规则里加文件名要求）

- [ ] **Step 1: 写失败测试**

在 `tests/core/test_vault.py` 加：

```python
# ---------- 标题清洗（Q72）----------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("正常标题", "正常标题"),
        ("含/斜杠", "含斜杠"),
        (r'含\反斜杠', "反斜杠"),
        ('含:冒号*星号?问号"引号<尖>括号|竖线', "含冒号星号问号引号尖括号竖线"),
        ("  首尾空格  ", "首尾空格"),
        ("结尾有点...", "结尾有点"),
        ("a" * 80, "a" * 60),
    ],
)
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


def test_clean_title_rejects_empty():
    with pytest.raises(ValueError):
        clean_title("///")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_vault.py -k clean_title -v
```

**Expected:** `ImportError: cannot import name 'clean_title'`

- [ ] **Step 3: 实现**

`src/kb/core/vault.py` 末尾加：

```python
# ---------------------------------------------------------------- 文件名（Q72）

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
_TITLE_MAX = 60


def clean_title(raw: str) -> str:
    """把笔记标题清洗成合法文件名。非法或全空 → 抛 ValueError。

    规则见 `docs/01_架构.md` 第五节。
    """
    cleaned = _ILLEGAL_CHARS.sub("", raw).strip().rstrip(".")
    cleaned = cleaned[:_TITLE_MAX]
    if not cleaned:
        raise ValueError(f"标题清洗后为空：{raw!r}")
    return cleaned
```

> `import re` 在 Task 2 可能被删过——**确认它在**，没有就加回来。

- [ ] **Step 4: 在 `validate_plan` 里用它**

`src/kb/core/planning.py` 的 `validate_plan`，在 CREATE 分支里加一条（放在类型检查之后）：

```python
        stem = Path(plan.target_path).stem
        if clean_title(stem) != stem:
            raise PlanError(
                f"文件名不合规，必须是清洗过的内容标题（见架构第五节）：{stem}"
            )
```

`planning.py` 顶部 import 加 `clean_title`。

- [ ] **Step 5: 加对应测试**

`tests/core/test_planning.py` 加：

```python
def test_validate_rejects_illegal_filename(vault):
    """文件名必须是清洗过的内容标题（Q72）。"""
    plan = parse_plan(
        DRAFT.id,
        _plan_json(target_path="计算机/队列串行化: 补充.md"),
    )
    with pytest.raises(PlanError, match="文件名不合规"):
        validate_plan(plan, vault)
```

- [ ] **Step 6: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q 2>&1 | tail -5
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests
git add -A && git commit -m "feat: 文件名统一内容标题 + 清洗规则（Q72）"
```

---

## Task 6: 提示词重写

旧提示词的 9 条硬规则全围绕 `10_项目/` 与 `20_知识/` 的分工。新结构只剩一个去处，规则要重写。

**Files:**
- Modify: `src/kb/core/planning.py:97-141`（`build_system_prompt`）

- [ ] **Step 1: 写失败测试**

`tests/core/test_planning.py` 加：

```python
def test_system_prompt_targets_domains():
    """路径只允许落在领域下（Q67）。"""
    prompt = build_system_prompt()
    assert "领域" in prompt
    assert "10_项目" not in prompt
    assert "20_知识" not in prompt


def test_system_prompt_states_tag_rule():
    """标签规则要写进提示词（Q76）。"""
    prompt = build_system_prompt()
    assert "路径派生" in prompt
    assert "最多 3 个" in prompt or "0-3" in prompt


def test_system_prompt_states_reuse_classification_rule():
    """能复用已有分类就复用（Q77）。"""
    prompt = build_system_prompt()
    assert "能用已有的就用已有的" in prompt
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_planning.py -k system_prompt -v
```

**Expected:** 3 个新测试 FAIL。

- [ ] **Step 3: 重写 `build_system_prompt`**

`src/kb/core/planning.py:97-141` 整段替换：

```python
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
  "frontmatter": {{"{K_TYPE}": "概念", "{K_TOPIC}": ["计算机", "git"], "{K_PROJECT}": "项目名"}},
  "target_tags": ["计算机", "git", "版本控制"],
  "content": "笔记正文（markdown）",
  "pending_reason": "仅 outcome=pending 时填"
}}

硬规则：
1. target_path 必须落在**某个既有领域**下，形如 `<领域>/…/<标题>.md`。
   领域是 vault 的一级目录，由人维护，**不许新建**。清单见「现有领域」一节。
   领域内的子分类**由你决定**——但要遵守第 6 条。
2. 文件名（`<标题>.md` 的标题部分）必须是**清洗过的内容标题**：
   不含 `\\ / : * ? " < > |`，不以点结尾，不超过 60 字。
3. {K_TYPE} 只能取：{allowed}。
4. content 必须至少包含一个 [[双向链接]]，指向已有笔记或索引页。
5. create 的目标路径不能已存在；fold 的目标路径必须已存在。
6. **分类能复用就复用。** 「领域下已有分类」里列出的名字，只要装得下这条内容，
   就**必须用它**，不许另起一个近义的（有「版本控制」就别建「git」）。
   真的都装不下，才新建一层或一个新分类——新建要在 `pending_reason` 里说明理由。
7. {K_TOPIC} 与 `target_tags` 按**标签规则**填：
   - 路径派生：目标路径上的**每一级目录名**都要进 `target_tags`，领域名排最前
   - 另提语义：再补 0–3 个跨领域的标签（如一篇讲「用代码生成艺术」的笔记，
     除路径派生外还可以带 `艺术`）
   - 英文标签一律小写；中间空白折成 `-`；单个标签不超过 20 字符
8. 骨架里的「## 用户的判断」一节**必须留空**（保留标题，标题下什么都不写）。
   这一节记录用户本人的立场，服务端会机械清空——写了也会被丢掉，别浪费。
   绝不要替用户总结、推断或改写成第三人称（「用户认为……」是典型的伪造）。
9. fold 时 content **只写要追加的段落**——不要带一级标题（`# `），不要写
   frontmatter，也不要重复目标笔记已有的章节。追加不是嵌一篇新笔记进去。

{_skeleton_block()}"""
```

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_planning.py -q 2>&1 | tail -5
```

**Expected:** 全 PASS。**若旧测试里有断言旧文案的，一并改。**

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/planning.py tests/
git commit -m "feat: 提示词重写——单去处 + 标签规则 + 分类归旧（Q67/Q76/Q77）"
```

---

## Task 7: 放开领域内分类 + 审核

**这两件必须同时上。** 放开自由分类而不加去重，标签和目录会一起长乱（`git`/`Git`/`版本控制`）。

**审核是什么：** 链上一步，位置在静态校验之后、落盘之前。**机械项由代码管（`validate_plan`），AI 只审一条——新建的分类跟同层已有的近义吗。** 这一条是判断题，代码判不了。

**Files:**
- Modify: `src/kb/core/models.py`（加审核结果）
- Create: `src/kb/core/review.py`
- Modify: `src/kb/core/planning.py`（加 `new_dirs_in` 辅助）
- Modify: `src/kb/core/organize.py`（`make_plan` 里插入审核）

- [ ] **Step 1: 写失败测试**

`tests/core/test_review.py`（新建）：

```python
"""审核：新分类与已有分类是否近义（Q78）。"""
from pathlib import Path

import pytest

from kb.core.models import Outcome, OrganizePlan
from kb.core.review import new_dirs_in, review_plan
from kb.llm.base import FakeLLM


def _plan(target_path: str) -> OrganizePlan:
    return OrganizePlan(
        draft_id="20260916-a3f2",
        outcome=Outcome.CREATE,
        target_path=target_path,
        frontmatter={"类型": "概念", "主题": ["计算机"]},
        content="# x\n\n[[某篇]]\n",
    )


def test_new_dirs_in_lists_missing_layers(tmp_path):
    (tmp_path / "计算机" / "版本控制").mkdir(parents=True)
    assert new_dirs_in(tmp_path, "计算机/版本控制/a.md") == []
    assert new_dirs_in(tmp_path, "计算机/git/a.md") == ["git"]
    assert new_dirs_in(tmp_path, "计算机/git/底层/a.md") == ["git", "底层"]


def test_review_skipped_when_no_new_dirs(tmp_path):
    """没新建分类就不调 LLM——不做无谓的往返。"""
    (tmp_path / "计算机" / "版本控制").mkdir(parents=True)
    llm = FakeLLM([])           # 队列为空；一旦被调用就会抛错
    plan = _plan("计算机/版本控制/a.md")
    assert review_plan(plan, tmp_path, llm) == plan


def test_review_rewrites_path_when_llm_says_reuse(tmp_path):
    """LLM 判定近义 → 改用已有分类。"""
    (tmp_path / "计算机" / "版本控制").mkdir(parents=True)
    llm = FakeLLM(['{"target_path": "计算机/版本控制/a.md"}'])
    got = review_plan(_plan("计算机/git/a.md"), tmp_path, llm)
    assert got.target_path == "计算机/版本控制/a.md"


def test_review_keeps_path_when_llm_says_ok(tmp_path):
    (tmp_path / "计算机" / "版本控制").mkdir(parents=True)
    llm = FakeLLM(['{"target_path": "计算机/git/a.md"}'])
    got = review_plan(_plan("计算机/git/a.md"), tmp_path, llm)
    assert got.target_path == "计算机/git/a.md"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_review.py -v
```

**Expected:** `ModuleNotFoundError: No module named 'kb.core.review'`

- [ ] **Step 3: 实现 `review.py`**

```python
"""审核（Q58/Q78）：链上一步，在静态校验之后、落盘之前。

**只审一条：新建的分类跟同层已有的是否近义。** 其余都是机械项，归
`planning.validate_plan` 用代码管——机械约束不能交给模型判断（见 Q64）。

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
    return sorted(p.name for p in parent.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


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
```

> **注意：审核改了路径之后，调用方必须重新跑一遍 `validate_plan`。** 审核的输出也要过静态校验——这是「确定性校验兜着每个 LLM 调用点」那条原则（Q60 的结论）。

- [ ] **Step 4: 接进 `organize.make_plan`**

`src/kb/core/organize.py` 的 `make_plan`（L185 附近），在 `planning.validate_plan(...)` 之后加：

```python
    plan = review.review_plan(plan, vault_root, llm)
    planning.validate_plan(plan, vault_root)      # 审核的输出也要过静态校验
```

顶部加 `from kb.core import review`。

- [ ] **Step 5: 跑测试**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_review.py -v
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q 2>&1 | tail -5
```

**Expected:** 全 PASS。

- [ ] **Step 6: 提交**

```bash
git add src/kb/core/review.py src/kb/core/organize.py tests/core/test_review.py
git commit -m "feat: 审核——新建分类与已有分类近义则复用（Q69/Q78）"
```

---

## Task 8: 修改能力（`--revise` + 失效标记）

**语义：** 会话层显式指明「这条取代那条」。旧笔记**不删**，打失效标记保留，**默认排除出检索**。

**Files:**
- Modify: `src/kb/core/models.py`（`Draft.revise_target`、`K_*` 常量）
- Modify: `src/kb/core/vault.py`（读写失效字段）
- Modify: `src/kb/core/organize.py`（落盘时标记失效）
- Modify: `src/kb/api/cli.py`、`src/kb/api/http.py`

- [ ] **Step 1: 写失败测试**

`tests/core/test_revise.py`（新建）：

```python
"""修改：--revise 指定目标，落盘后旧笔记标记失效（Q59/Q60）。"""
from pathlib import Path

import pytest

from kb.core.models import Draft
from kb.core.vault import find_note_by_stem, is_superseded, mark_superseded, read_note, write_note


def test_find_note_by_stem_unique(tmp_path):
    write_note(tmp_path / "计算机" / "a.md", {"类型": "概念"}, "x")
    assert find_note_by_stem(tmp_path, "a") == tmp_path / "计算机" / "a.md"


def test_find_note_by_stem_returns_none_on_ambiguity(tmp_path):
    """多个同名 → 不猜。"""
    write_note(tmp_path / "计算机" / "a.md", {"类型": "概念"}, "x")
    write_note(tmp_path / "艺术" / "a.md", {"类型": "概念"}, "y")
    assert find_note_by_stem(tmp_path, "a") is None


def test_mark_superseded_sets_flags(tmp_path):
    path = tmp_path / "计算机" / "a.md"
    write_note(path, {"类型": "概念"}, "x")
    mark_superseded(path, by="b")
    meta, _ = read_note(path)
    assert meta["失效"] is True
    assert meta["被取代于"] == "b"
    assert is_superseded(meta) is True


def test_is_superseded_false_by_default(tmp_path):
    path = tmp_path / "计算机" / "a.md"
    write_note(path, {"类型": "概念"}, "x")
    meta, _ = read_note(path)
    assert is_superseded(meta) is False
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_revise.py -v
```

**Expected:** `ImportError: cannot import name 'find_note_by_stem'`

- [ ] **Step 3: 实现 `vault.py` 侧**

`src/kb/core/models.py` 加常量：

```python
K_SUPERSEDED = "失效"
K_SUPERSEDED_BY = "被取代于"
```

`src/kb/core/vault.py` 加：

```python
# ---------------------------------------------------------------- 修改与失效（Q59/Q60）

def find_note_by_stem(vault_root: Path, stem: str) -> Path | None:
    """全库按文件名（不含 .md）搜唯一匹配。找不到或有多个 → None，不猜。"""
    if not stem:
        return None
    matches = [p for p in list_notes(vault_root) if p.stem == stem]
    return matches[0] if len(matches) == 1 else None


def is_superseded(meta: dict) -> bool:
    return bool(meta.get(K_SUPERSEDED))


def mark_superseded(path: Path, by: str) -> None:
    """把一篇笔记标记失效。正文一个字节不动——「当初为什么那么想」比结论有用。"""
    meta, body = read_note(path)
    meta[K_SUPERSEDED] = True
    meta[K_SUPERSEDED_BY] = by
    write_note(path, meta, body)
```

- [ ] **Step 4: 加 `Draft.revise_target` 与 CLI 参数**

`src/kb/core/models.py` 的 `Draft` 加字段：

```python
    revise_target: str | None = None      # --revise 指定的目标文件名（不含 .md）
```

`src/kb/api/cli.py` 的 `build_parser` 里给 `push` 加参数：

```python
    p_push.add_argument("--revise", help="修改已有笔记：指定目标文件名（不含 .md）")
```

`cmd_push` 把它传进 body：

```python
            json={
                "content": content,
                "project": project,
                "source": args.source,
                "revise_target": args.revise,
            },
```

`src/kb/api/http.py` 的 `PushRequest` 加同名字段，`/push` 里透传给 `write_draft`。

- [ ] **Step 5: 落盘时标记失效**

`src/kb/core/organize.py` 的 `apply_plan`，在 CREATE 落盘之后加：

```python
    if plan.revise_target:
        old = find_note_by_stem(vault_root, plan.revise_target)
        if old is None:
            raise PlanError(
                f"--revise 指定的目标找不到或不唯一：{plan.revise_target}"
            )
        txn.touch_modify(old)
        mark_superseded(old, by=Path(plan.target_path).stem)
```

（`plan` 上也要加 `revise_target`，从 draft 带过来；`make_plan` 里赋值。）

- [ ] **Step 6: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q 2>&1 | tail -5
git add -A && git commit -m "feat: 修改能力——--revise + 失效标记（Q59/Q60）"
```

---

## Task 9: 检索

**给会话层代查用。** 不引入向量库——库规模是几十到几百篇，全文匹配 + 标签足够。真到了需要 RAG 的规模再说。

**Files:**
- Modify: `src/kb/core/classify.py`（或新建 `search.py`）
- Modify: `src/kb/api/cli.py`、`src/kb/api/http.py`

- [ ] **Step 1: 写失败测试**

`tests/core/test_search.py`（新建）：

```python
"""检索（Q25：标签是检索主力）。"""
from kb.core.search import search_notes
from kb.core.vault import mark_superseded, write_note


def _note(root, domain, name, tags, body):
    write_note(root / domain / f"{name}.md", {"类型": "概念", "主题": tags}, body)


def test_search_matches_body(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["计算机"], "并发写入会锁表")
    _note(tmp_path, "艺术", "一点透视", ["艺术"], "近大远小")
    hits = search_notes(tmp_path, "锁表")
    assert [h.stem for h in hits] == ["队列串行化"]


def test_search_matches_tag(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["并发"], "内容无关")
    assert [h.stem for h in search_notes(tmp_path, "并发")] == ["队列串行化"]


def test_search_matches_title(tmp_path):
    _note(tmp_path, "计算机", "队列串行化", ["计算机"], "内容无关")
    assert [h.stem for h in search_notes(tmp_path, "队列")] == ["队列串行化"]


def test_search_skips_superseded(tmp_path):
    """失效的默认不出现在检索结果里（Q60）。"""
    _note(tmp_path, "计算机", "旧结论", ["计算机"], "锁表")
    mark_superseded(tmp_path / "计算机" / "旧结论.md", by="新结论")
    assert search_notes(tmp_path, "锁表") == []


def test_search_returns_superseded_when_rebuilding(tmp_path):
    """点时间查——把历史也要回来。"""
    _note(tmp_path, "计算机", "旧结论", ["计算机"], "锁表")
    mark_superseded(tmp_path / "计算机" / "旧结论.md", by="新结论")
    hits = search_notes(tmp_path, "锁表", include_superseded=True)
    assert [h.stem for h in hits] == ["旧结论"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_search.py -v
```

**Expected:** `ModuleNotFoundError: No module named 'kb.core.search'`

- [ ] **Step 3: 实现**

`src/kb/core/search.py`（新建）：

```python
"""检索（Q25）。**标签是主力，全文是补充。**

不引入向量库——库规模是几十到几百篇，全文匹配足够。真到了需要 RAG
的规模再说。失效的笔记**默认不出现在结果里**（Q60），
`include_superseded=True` 时把历史也要回来。
"""
from __future__ import annotations

from pathlib import Path

from kb.core.vault import is_superseded, list_notes, read_note

MAX_HITS = 20


def _matches(path: Path, meta: dict, body: str, query: str) -> bool:
    q = query.lower()
    if q in path.stem.lower():
        return True
    tags = meta.get("主题") or []
    if isinstance(tags, str):
        tags = [tags]
    if any(q in str(t).lower() for t in tags):
        return True
    return q in body.lower()


def search_notes(
    vault_root: Path, query: str, *, include_superseded: bool = False
) -> list[Path]:
    """按关键词搜笔记。返回命中的笔记路径，最多 `MAX_HITS` 条。"""
    if not query.strip():
        return []
    hits: list[Path] = []
    for path in list_notes(vault_root):
        meta, body = read_note(path)
        if not include_superseded and is_superseded(meta):
            continue
        if _matches(path, meta, body, query):
            hits.append(path)
            if len(hits) >= MAX_HITS:
                break
    return hits
```

- [ ] **Step 4: 加 CLI 与 HTTP 出口**

`src/kb/api/cli.py` 加子命令：

```python
def cmd_search(args) -> int:
    cfg = load_config()
    with make_client(cfg) as client:
        resp = client.get("/search", params={"q": args.query})
        resp.raise_for_status()
        data = resp.json()

    if not data["count"]:
        print("没找到。")
        return 0
    print(f"找到 {data['count']} 条：")
    for item in data["items"]:
        tags = "、".join(item["tags"]) or "无"
        print(f"  {item['path']}")
        print(f"    {item['title']}｜标签：{tags}")
    return 0
```

```python
    p_search = sub.add_parser("search", help="检索笔记")
    p_search.add_argument("query", help="关键词")
    p_search.set_defaults(func=cmd_search)
```

`src/kb/api/http.py` 加端点：

```python
@app.get("/search")
def search(q: str = "") -> dict:
    hits = search_notes(cfg.vault_path, q)
    items = []
    for path in hits:
        meta, _ = read_note(path)
        items.append({
            "path": path.relative_to(cfg.vault_path).as_posix(),
            "title": path.stem,
            "tags": meta.get("主题") or [],
        })
    return {"count": len(items), "items": items}
```

- [ ] **Step 5: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q 2>&1 | tail -5
git add -A && git commit -m "feat: 检索——按标签与全文匹配，失效的默认不出现（Q25/Q60）"
```

---

## Task 10: Web UI

**界面先做出来，功能后接。** 布局按 [`docs/02_需求.md`](../../02_需求.md) 第五节。

> `tests/test_architecture.py` 已经预留 `FORBIDDEN = ("kb.api", "kb.web")`——`core`/`llm` 不许依赖它，**建包时不用动那个测试**。

**Files:**
- Create: `src/kb/web/__init__.py`、`src/kb/web/router.py`
- Create: `src/kb/web/templates/`（4 个页面 + 1 个布局）
- Create: `src/kb/web/static/style.css`
- Modify: `requirements.txt`（加 `jinja2>=3.1`）
- Modify: `src/kb/api/http.py`（挂载）

- [ ] **Step 1: 写失败测试**

`tests/web/test_router.py`（新建目录）：

```python
"""Web UI 路由。功能后接，先保证四个页面能打开。"""
import pytest
from fastapi.testclient import TestClient

from kb.api.http import create_app
from kb.config import Config


@pytest.fixture
def client(tmp_path):
    cfg = Config(
        llm_api_key="k", llm_base_url="http://x", llm_model="m",
        vault_path=tmp_path, port=None,
    )
    return TestClient(create_app(cfg))


@pytest.mark.parametrize("path", ["/", "/journal", "/flow", "/runtime"])
def test_pages_render(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_index_has_four_nav_buttons(client):
    body = client.get("/").text
    for label in ("ai对话", "整理日志", "工作日志", "运行日志"):
        assert label in body
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web/ -v
```

**Expected:** `ModuleNotFoundError: No module named 'kb.web'`

- [ ] **Step 3: 建包与路由**

`src/kb/web/__init__.py`：

```python
"""管理 Web UI（Q31）。薄层——只做展示，判断逻辑全在 core/。"""
```

`src/kb/web/router.py`：

```python
"""Web UI 路由。布局见 `docs/02_需求.md` 第五节。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kb.config import Config
from kb.core.vault import list_domains

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def build_router(cfg: Config) -> APIRouter:
    router = APIRouter()

    def _ctx(name: str, **extra) -> dict:
        return {"active": name, "vault": str(cfg.vault_path), **extra}

    @router.get("/", response_class=HTMLResponse)
    def chat(request: Request):
        return templates.TemplateResponse(request, "chat.html", _ctx("chat"))

    @router.get("/journal", response_class=HTMLResponse)
    def journal(request: Request):
        return templates.TemplateResponse(request, "journal.html", _ctx("journal"))

    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request):
        return templates.TemplateResponse(request, "flow.html", _ctx("flow"))

    @router.get("/runtime", response_class=HTMLResponse)
    def runtime_page(request: Request):
        return templates.TemplateResponse(request, "runtime.html", _ctx("runtime"))

    return router
```

- [ ] **Step 4: 写模板**

`src/kb/web/templates/base.html`：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>KN_Base</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div class="shell">
    <nav class="sidebar" id="sidebar">
      <button class="toggle" onclick="document.body.classList.toggle('collapsed')">≡</button>
      <a href="/"           class="side-btn {{ 'active' if active == 'chat' }}">ai对话</a>
      <a href="/journal"    class="side-btn {{ 'active' if active == 'journal' }}">整理日志</a>
      <a href="/flow"       class="side-btn {{ 'active' if active == 'flow' }}">工作日志</a>
      <a href="/runtime"    class="side-btn {{ 'active' if active == 'runtime' }}">运行日志</a>
    </nav>
    <main class="main">
      {% block content %}{% endblock %}
    </main>
  </div>
</body>
</html>
```

`chat.html` / `journal.html` / `flow.html` / `runtime.html` 各自 `{% extends "base.html" %}`，内容区先放占位标题与说明。**`chat.html` 另外加一个右侧栏**（会话历史的位置）：

```html
{% extends "base.html" %}
{% block content %}
<div class="chat-layout">
  <section class="chat-main"><h1>ai对话</h1><p class="muted">界面占位——检索接在 Task 9 的 /search 上，下一轮接。</p></section>
  <aside class="chat-history"><h2>会话历史</h2><p class="muted">（右侧栏，借鉴 DeepSeek 布局）</p></aside>
</div>
{% endblock %}
```

- [ ] **Step 5: 写样式**

`src/kb/web/static/style.css`：布局用 flex，**可折叠左栏**（`body.collapsed .sidebar { width: 48px }`），主区自动撑满。配色按需求：**白 + 蓝，别太亮**；整理日志卡片淡蓝、工作日志卡片淡粉。

```css
:root {
  --blue: #2f6fb3;
  --blue-soft: #eaf2fb;    /* 整理日志卡片 */
  --pink-soft: #fdeef2;    /* 工作日志卡片 */
  --ink: #1f2328;
  --line: #dde3ea;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; color: var(--ink); background: #fff; }
.shell { display: flex; min-height: 100vh; }
.sidebar { width: 200px; border-right: 1px solid var(--line); padding: 12px; display: flex; flex-direction: column; gap: 6px; transition: width .15s; }
body.collapsed .sidebar { width: 48px; }
.side-btn { padding: 8px 10px; border-radius: 6px; text-decoration: none; color: var(--ink); white-space: nowrap; overflow: hidden; }
.side-btn.active { background: var(--blue); color: #fff; }
.main { flex: 1; padding: 20px; min-width: 0; }
.muted { color: #6b7280; }
.chat-layout { display: flex; gap: 16px; height: 70vh; }
.chat-main { flex: 1; }
.chat-history { width: 260px; border-left: 1px solid var(--line); padding-left: 12px; }
.card { border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
.card.journal { background: var(--blue-soft); }
.card.flow { background: var(--pink-soft); }
.term { background: #1f2328; color: #d7dde5; padding: 14px; border-radius: 8px; font-family: Consolas, monospace; white-space: pre-wrap; }
```

- [ ] **Step 6: 挂载到 `http.py`**

`src/kb/api/http.py` 的 `create_app` 里加：

```python
    from fastapi.staticfiles import StaticFiles
    from kb.web.router import STATIC_DIR, build_router

    app.include_router(build_router(cfg))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
```

`requirements.txt` 加 `jinja2>=3.1`，然后：

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pip install -r requirements.txt
```

- [ ] **Step 7: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q 2>&1 | tail -5
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
git add -A && git commit -m "feat: Web UI 骨架——可折叠侧栏 + 四个页面（Q31/Q61）"
```

---

# 第三部分：测试

**用真实内容验收，不用编的。** 素材来自 `E:\Work_Projects\04_RPA_restart`——一个真实在做的 RPA 平台项目，它的 `docs/` 下有大量**成篇的踩坑记录**（每条都是「现象 / 根因 / 修法 / 核实 / 回归用例」五段式），而且**自带脏数据**（一条「记反了」的说明、两条被更正的旧结论），正好测「冲突消解」。

## Task 11: 建 RPA 项目副本

**为什么要副本：** 测试要动的是知识库，但素材来自那个项目。**绝不在原项目里做任何写操作。**

**⚠️ 安全：`manager_data/` 里有 `.secret_key`（Fernet 凭据加密密钥），必须排除。**

**Files:**
- Create: `E:/Work_Projects/_kb_test/04_RPA_restart/`（副本）

- [ ] **Step 1: 建副本目录，按白名单复制**

原项目 1.1G，其中 **548M 是 360 浏览器安装包与解包产物、429M 是 Chrome for Testing、80M 是驱动**——这些跟投递测试无关。

```bash
SRC="E:/Work_Projects/04_RPA_restart"
DST="E:/Work_Projects/_kb_test/04_RPA_restart"
mkdir -p "$DST"
for item in CLAUDE.md pyproject.toml .gitignore rpacore designer manager tests tools \
            packaging config docs flows robot_tasks .claude \
            "RPA流程设计执行管理器_日志及规划.txt" start_designer.bat start_manager.bat; do
  [ -e "$SRC/$item" ] && cp -r "$SRC/$item" "$DST/"
done
```

**Expected:** 无报错。**逐个确认这些不在副本里：**

```bash
ls "$DST"
```

- [ ] **Step 2: 确认危险与冗余目录没被带过来**

```bash
for bad in save browser drivers manager_data runs .pytest_cache .superpowers __pycache__; do
  [ -e "$DST/$bad" ] && echo "⚠️ 不该存在：$bad" || true
done
du -sh "$DST"
```

**Expected:** 无 `⚠️` 输出，体积 **10M 以下**（`manager_data` 不在则 `.secret_key` 必然不在）。

- [ ] **Step 3: 副本里开一个 git 仓库**

副本不是一个真仓库（`.git` 没复制）。**但这正是要测的场景之一**——`--project` 默认取 **git 仓库根**的目录名，非 git 目录回退到 cwd 名。两种都要覆盖：

```bash
cd "$DST" && git init -q -b main && git add -A && \
git -c user.name=t -c user.email=t@x commit -q -m "chore: RPA 项目副本（供知识库投递测试）"
git rev-parse --show-toplevel
```

**Expected:** 打印副本路径——`--project` 会取到 `04_RPA_restart`。

---

## Task 12: 投递端到端验收

**这是整个计划的验收点。** 之前所有测试都是 mock 的；这一步用真实 LLM、真实内容跑。

**Files:**
- Modify: `E:/KB_Library`（真实写入）

- [ ] **Step 1: 确认服务跑的是新代码**

```bash
cd "E:/Study_Projects/KN_Base" && ./kb.bat stop
./kb.bat status
```

**Expected:** `服务已停止。下次调用会自动用当前代码拉起。` + `服务未在运行`。

> **不能省。** 改了 `src/` 下的代码，在跑的服务仍执行旧逻辑。

- [ ] **Step 2: 从副本目录投递第 1 条——bat 编码**

```bash
cd "E:/Work_Projects/_kb_test/04_RPA_restart"
KB="E:/Study_Projects/KN_Base/kb.bat"
"$KB" push --content "Windows 批处理文件必须存成 GBK + CRLF，不能是 UTF-8。中文 Windows 的 cmd 默认按 GBK(936) 逐个字节读 .bat，UTF-8 的中文注释会被误解码、REM 行提前断裂，后半截当成命令执行。表现为双击报「不是内部或外部命令」、中文乱码、命令被拆散。也不要在 .bat 里写 chcp 65001——那会反过来把 GBK 内容读错。" --source 会话
```

**Expected:** `已收，id=20260916-xxxx`

- [ ] **Step 3: 投递第 2 条——PowerShell 判定式静默失效（**这条和上一条同类，用来测分类复用**）**

```bash
"$KB" push --content "PowerShell 判定式在 Python 里拼串时，引号/空格极易出错，而且错了是静默的。实例：conftest 的收尾清理写成 \`\$_ .Name\`（\`\$_\` 后多一个空格）→ PowerShell 报错 → 整条命令 exit 1 → Stop-Process 根本没执行，测试残留进程一直拖死机器。教训：要么检查 exit code，要么加自检用例。" --source 会话
```

**Expected:** `已收，id=...`

- [ ] **Step 4: 投递第 3–6 条——四条 RPA/浏览器自动化的坑**

```bash
"$KB" push --content "IE 自动化里「热身」鼠标移动不能随便挑坐标：IEDriverServer 把 move_by_offset(1,1) 当**绝对坐标**用，光标落到窗口左上角的浏览器菜单栏、根本没进文档。于是紧随其后的 element.click() 仍是文档收到的第一条输入，照旧被 IE 吞掉，报「完成」却什么都没发生。修法：热身要落在**马上要操作的那个元素**上。中途试过移到 body，反而更糟——body 的中心可能不在可视区。" --source 会话

"$KB" push --content "要把浏览器窗口置前时，要的是「请求前台」，不是「摆弄窗口」，这两件事被混为一谈绕了一大圈。请求前台=必需（IE 的点击发真实鼠标键盘事件，窗口不在前台就发不出去）；摆弄窗口=一律不做（ShowWindow/SetWindowPos 翻 z-order 会把窗口留在「活跃但不重绘」的僵尸态，而且挑窗口会挑中 IE 那个 160x27 @-32000,-32000 的辅助小窗）。" --source 会话

"$KB" push --content "屏幕 800x600 太小会让 IE 缩放不是 100%，点击坐标因此算歪，报错形如「鼠标要移到 (877, 438)，但视口是 left:0 right:800」。877/800≈1.1 正是缩放补偿。options.ignore_zoom_level = True 只管让驱动不报错退出，**不修坐标**。排障顺序：先看日志里的「前台实际=」（前台问题），再看视口边界与元素坐标的比值（缩放问题）。" --source 会话

"$KB" push --content "跨版本陷阱：@classmethod 与 @staticmethod 叠着写在同一个函数上，开发机 Python 3.11 恰好还能调、全量测试全绿；目标机 3.8 一调就 TypeError: 'staticmethod' object is not callable。教训：**全量测试全绿不代表目标机能跑**。项目为此加了 tools/check_py38.py 做静态检查兜底。" --source 会话
```

**Expected:** 四条都 `已收，id=...`

- [ ] **Step 5: 看收件箱**

```bash
"$KB" inbox
```

**Expected:** `收件箱：6 条待整理`，每条带 `[项目名]` 标记（`04_RPA_restart`）。

- [ ] **Step 6: 触发整理**

```bash
"$KB" organize
```

**Expected:** `整理完成，6 条：` 每条 `[created]`，路径落在 `计算机/` 下。

> **可能有步骤报错**（版本 1 没做「按条隔离」之外的兜底）：`[failed]` 的条目会说明原因。**记下来**，继续往下看别的条目。

- [ ] **Step 7: 验收甲——六条都进了 `计算机/`**

```bash
find "E:/KB_Library" -name "*.md" -not -path "*/_索引/*" | sort
```

**Expected:** 6 篇，全部形如 `E:/KB_Library/计算机/...`。**没有落在 `艺术/` 或 `文学/` 的。**

- [ ] **Step 8: 验收乙——分类自己长出来了，而且没长近义的**

```bash
find "E:/KB_Library/计算机" -type d | sort
```

**Expected:** 至少一层子目录。**关键检查：没有 `git`/`Git` 并存，没有 `批处理`/`bat` 并存**——第 1、2 条同属「Windows 脚本」类，应落在同一个分类下；若 LLM 建了两个近义分类，说明 Task 7 的审核没生效。

- [ ] **Step 9: 验收丙——标签符合规则**

```bash
head -8 "E:/KB_Library/计算机"/*/*.md | head -40
```

**逐条核对**（对照 [`docs/01_架构.md`](.../01_架构.md) 第六节）：

- `主题` 里**第一项是领域名**（`计算机`）
- 有**路径派生**的部分（子目录名也在里面）
- 英文标签**全小写**
- 单个标签**不超过 20 字符**
- 总数合理（派生 + 最多 3 个另提）

- [ ] **Step 10: 验收丁——修改能力**

找一篇刚建出来的笔记，改它：

```bash
"$KB" search "热身"
```

拿到路径后，用它的**文件名（不含 .md）**做 `--revise`：

```bash
"$KB" push --content "更正：热身落在「马上要操作的那个元素」上仍然不够稳。更可靠的做法是先把元素滚动进可视区再移到它上面——否则元素在视口边缘时热身照样会被裁掉一半。这条是对前一条的修订。" --source 会话 --revise "<上一步拿到的文件名>"
"$KB" organize
```

**Expected:** 新笔记创建；旧笔记的 frontmatter 多了 `失效: true` 和 `被取代于: <新笔记名>`，**正文一个字节没变**。

```bash
grep -l "失效: true" -r "E:/KB_Library/计算机" || echo "⚠️ 没找到失效标记"
```

- [ ] **Step 11: 验收戊——失效的不出现在检索里**

```bash
"$KB" search "热身"
```

**Expected:** 结果里**只有新笔记**，没有刚被标记失效的那篇。**这是「失效默认排除出检索」的验收点。**

- [ ] **Step 12: 验收己——索引页与整理日志**

```bash
ls "E:/KB_Library/_索引" && cat "E:/KB_Library/_索引/整理日志/$(date +%Y-%m-%d).md"
```

**Expected:** 有索引页；整理日志按天聚合，本次整理追加了一节，**失败的条目也记了**。

- [ ] **Step 13: 跑全量测试收口**

```bash
cd "E:/Study_Projects/KN_Base"
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q 2>&1 | tail -5
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**Expected:** 全 PASS + `All checks passed!`

- [ ] **Step 14: 提交 vault 与代码**

```bash
git -C "E:/KB_Library" -c core.quotepath=false status --short
git -C "E:/KB_Library" log --oneline -8
```

**Expected:** 服务的每次整理各是一个 commit（一次整理 = 一个 commit，Q46）。确认没有夹带无关文件后，代码侧：

```bash
cd "E:/Study_Projects/KN_Base" && git add -A && \
git commit -m "test: RPA 项目副本投递端到端验收"
```

---

## Self-Review

**1. 规格覆盖：** 实现步骤 1–7、9、10 各对应到任务——

| 架构里的步骤 | 本计划 |
|---|---|
| 1 重建 vault 骨架 | Task 4 |
| 2 删掉项目层 | Task 2、3 |
| 3 领域化路径 | Task 4（`list_domains`） |
| 4 文件名规则 | Task 5 |
| 5 提示词重写 | Task 6 |
| 6 修改能力 | Task 8 |
| 7 审核 | Task 7 |
| 9 检索 | Task 9 |
| 10 Web UI | Task 10 |

架构里没有、但计划加的：**Task 1**（清空 vault）——不先清，后面每步都要处理新旧并存。**Task 11、12**——第三部分。

**2. 占位符扫描：** 无 TBD / TODO / 「类似 Task N」/ 无代码的代码步骤。每个实现步骤都给了可直接粘贴的完整代码。

**3. 类型一致性：**

- `list_domains(vault_root) -> list[str]`：Task 4 定义，Task 4/6/7 一致使用
- `clean_title(raw) -> str`：Task 5 定义，Task 5 在 `validate_plan` 里用
- `new_dirs_in(vault_root, target_path) -> list[str]`：Task 7 定义并测试
- `review_plan(plan, vault_root, llm) -> OrganizePlan`：Task 7 返回同类型，可链式再校验
- `find_note_by_stem(vault_root, stem) -> Path | None`：Task 8 定义，Task 8 落盘时用
- `search_notes(vault_root, query, *, include_superseded=False) -> list[Path]`：Task 9 定义，CLI 与 HTTP 都用
- `Draft.revise_target: str | None`：Task 8 加，`OrganizePlan.revise_target` 同步

**4. 已知风险：**

- **Task 4 是唯一的「大爆炸」步骤**——路径常量一改，全库测试都动。已拆成 11 个 Step 逐步验证。
- **Task 12 的真实 LLM 输出不可预测**——Step 7–11 是**验收清单**，不是断言。不达标就回去改提示词或审核规则，**不要改验收标准**。
- **`_siblings` 的实现**（Task 7 Step 3）只在「第一个新目录层的父级」这一简单情形下正确。多级新建时给 LLM 的对照清单不完整——**够用，但知道它有这个边界**。

---

## 执行记录（2026-09-16）

**12 个任务全部完成。测试 258 → 281，ruff 干净。** 分四波执行，每波一个 subagent。

### 计划本身被纠正的地方

写这份计划时对代码的理解有偏差，执行时逐条纠正。**记在这里，因为「计划错了什么」比「计划写了什么」更能说明当时哪里没想清楚。**

| # | 计划说 | 实际 |
|---|---|---|
| 1 | Task 4 Step 9 用 grep 找旧目录字面量 | **漏了大头**——`KNOWLEDGE` 常量被 6 个测试文件引用约 55 处，常量一删全部 ImportError |
| 2 | 路径常量只影响 `planning.py` | `ensure_topic_index` 的 Dataview 查询 `FROM "{KNOWLEDGE}/…"` 会炸 |
| 3 | Task 4 Step 6「planning.py 里 3 处」 | 真正的调用点在 `organize.py:108,174` |
| 4 | Task 5 测试用例 `(r'含\反斜杠', "反斜杠")` | 期望值写错，应为 `"含反斜杠"` |
| 5 | Task 6 两条新测试 | **在计划给的提示词原文下不可能通过**（全角 `0–3`；`"能用已有的就用已有的"` 那句话根本不存在）。改的是提示词，不是测试 |
| 6 | Task 10 的 `TemplateResponse(name, context)` | Starlette 1.6.0 已删该签名，要用 `(request, name, context)` |
| 7 | Task 8「透传给 write_draft」 | `write_draft` 根本不写 `revise_target`，**整条链空转**（见下） |
| 8 | Task 9 的 Files 只说「加端点」 | `http.py` 还缺两个 import |
| 9 | 计划里多处 `git add -A` | 与项目约定「禁 `git add -A`」相冲 |
| 10 | 没有「跑 `init_vault.py` 重建真实 vault」这一步 | 漏了，Task 12 前补做 |

**每一条都是 subagent 报上来的，不是照抄过去的。** 计划里反复写的「对不上就停下来报告，别自己判断『大概是这个意思』」是这些能被发现的唯一原因。

### 端到端验收抓到的两个真 bug

**这两个单测都覆盖不到，只有真实 LLM 跑才暴露。**

**① `--revise` 整条链是空转的。** `write_draft` 只写 `状态/id/投递时间/来源/项目` 五个键，`read_draft` 也只读这五个——`revise_target` 在 push 时被丢掉，整理时 `plan.revise_target` 恒为 `None`，标记失效的代码永远进不去。**而且是静默无效。** Task 8 的测试只覆盖 vault 层那三个函数，恰好绕过整条链。修法：加 `K_REVISE` 键 + 一条 push→read 往返测试。

**② 修完之后又发现：`--revise` 会自我失效。** 模型看到内容相似就选了 `fold`，把新说法追加进原笔记；随后 revise 逻辑去找「被取代的那篇」，找到的正是刚被 fold 的同一篇，落成：

```
失效: true
被取代于: <它自己>
```

修法：`validate_plan` 拦住「目标路径 == 被取代的那一篇」，报错并说明「新内容必须另起一篇」——重试循环会把这段话喂回模型，它下一次就改成 `create`。`apply_plan` 再加一层兜底。

### 验收结果（Task 12）

6 条真实内容从 RPA 副本投递，**分类自己长出来且没有近义**：

```
计算机/Shell/     2 篇（bat 编码、PowerShell 静默失败）
计算机/Windows/   3 篇（窗口置前、IE 热身、IE 缩放）
计算机/Python/    1 篇（跨版本陷阱）
```

标签符合规则：领域名排最前、路径派生的目录名都在且全小写、AI 另提的跨领域标签 0–3 个。

`--revise` 复验：新建一篇 + 旧笔记标 `失效: true` 且**正文一字节未变**；`kb search` 里旧的不出现；索引页 `FROM "计算机"`；整理日志按天聚合。

---

## 收尾

代码侧：

- 测试 **281 passed**，ruff 干净
- `docs/01_架构.md` 第十三节的 1–7、9、10 全部落地
- **8（定时整理）、11（可移植打包）没做**——前者「暂时不管」，后者排在最后

vault 侧：`计算机/` 下有 7 篇真实内容，三个子分类，`_索引/` 有索引页与整理日志。

**这一轮最值钱的东西不是代码，是那句话：机械约束归代码，判断题归模型。** 计划里十个偏差里有三个（#1 #5 #7）都是因为没分清这两类——把该由代码保证的事写成了「期望模型照做」。



