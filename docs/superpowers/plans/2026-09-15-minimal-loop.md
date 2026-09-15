# 最小闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「投递 → 整理 → 落盘」跑通——能在任意项目里用 CLI 投递一条草稿，服务用 LLM 把它归类、查重、写入 vault，并留下工作日志和 git commit。

**Architecture:** Python 服务，领域逻辑（`core/`）与接口层（`api/`）严格分离。整理走**三段式**：规划（调 LLM，只读）→ 校验（纯静态检查，只读）→ 落盘（纯文件操作，不调 LLM）。所有写入经服务进程，CLI 通过 HTTP 调用。

**Tech Stack:** Python 3.11 / FastAPI / Jinja2（本阶段未用）/ `openai` SDK（指向 DeepSeek 兼容端点）/ python-frontmatter / pytest

**设计依据：** 全部决策见 [`docs/问题记录.md`](../../问题记录.md)。本计划只实现**最小闭环**，MOC 自动更新、Web UI、MCP、撤回界面均不在范围内。

---

## 执行前的既定约束

来自设计文档，实现时必须遵守：

| 约束 | 出处 |
|---|---|
| `core/` 不许 import `web/` 或 `api/` | Q33 |
| LLM 调用全部 mock，不跑真实 API | Q52 |
| 所有写入经服务进程，CLI 不直接碰文件 | Q29 |
| 投递是纯粹的——正文原样保存，不改写 | Q55 |
| 失败的草稿什么也不写，保持原样（保证重试幂等） | Q45 |
| 回滚精确到文件，禁用 `git checkout .` | Q45 |
| 服务只 `git add` 自己动过的文件，禁用 `git add -A` | Q46 |
| 一次整理 = 一个 commit | Q46 |
| 服务 git author 为 `kb-service` | Q46 |
| 归不了类的草稿移入 `00_收件箱/待归类/`，不阻塞其余 | Q20 |

---

## 文件结构

```
KN_Base/
├── requirements.txt
├── pyproject.toml              # pytest 配置
├── .env.example                # 配置项清单（入库）
├── src/kb/
│   ├── __init__.py
│   ├── config.py               # 读 .env
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py           # 类型枚举、Draft、OrganizePlan
│   │   ├── vault.py            # vault 读写、路径解析、frontmatter
│   │   ├── classify.py         # 查重预筛
│   │   ├── organize.py         # 三段式整理流程
│   │   └── journal.py          # 工作日志
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py             # LLM 抽象接口 + FakeLLM
│   │   └── providers/
│   │       ├── __init__.py
│   │       └── openai_compat.py
│   └── api/
│       ├── __init__.py
│       ├── http.py             # FastAPI 应用
│       ├── cli.py              # 命令行
│       └── runtime.py          # service.json 读写 + 服务拉起
├── templates/                  # 笔记模板（.md，代码读取）
├── scripts/init_vault.py       # 建 vault 骨架（幂等）
└── tests/
```

**职责边界：** `models.py` 只有数据和枚举，无逻辑；`vault.py` 只管文件与 frontmatter，不做判断；`classify.py` 只做查重预筛；`organize.py` 编排三段式；`journal.py` 只写日志。

---

## Task 1: 项目脚手架与配置

**Files:**
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/kb/__init__.py`
- Create: `src/kb/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 建 conda 环境**

```bash
conda create -n kn_base python=3.11 -y
conda activate kn_base
```

- [ ] **Step 2: 写 `requirements.txt`**

**下界 + 关键包上界**（Q57）。下界防止装到过老的版本；只有 `openai` 这类大版本会破坏 API 的 SDK 才加上界。

```
# 下界约束 + 关键包破坏性大版本上界（Q57）
# 精确版本锁文件 requirements.lock.txt 是 pip freeze 的本机产物，不入库

fastapi>=0.141
uvicorn>=0.53
jinja2>=3.1
python-dotenv>=1.0
openai>=3.14,<4
python-frontmatter>=1.3
httpx>=0.28,<1
pytest>=9,<10
ruff>=0.9
```

（`ruff` 已按用户决定加入。只做 lint，不做类型检查。）

- [ ] **Step 3: 安装依赖**

```bash
conda activate kn_base
pip install -r requirements.txt
pip freeze > requirements.lock.txt
```

`requirements.lock.txt` 加入 `.gitignore`（本机产物，不跨平台）。

- [ ] **Step 4: 写 `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
```

`pythonpath = ["src"]` 让测试里能直接 `from kb.config import ...`，无需安装包。

跑 lint：

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check .
```

- [ ] **Step 5: 写 `.env.example`**

```
# 复制本文件为 .env 并填写。.env 不入库。
KB_LLM_API_KEY=
KB_LLM_BASE_URL=https://api.deepseek.com/v1
KB_LLM_MODEL=deepseek-chat
KB_VAULT_PATH=E:\KB_Library
KB_PORT=
```

- [ ] **Step 6: 建空包文件**

```bash
touch src/kb/__init__.py src/kb/core/__init__.py src/kb/llm/__init__.py tests/__init__.py
mkdir -p src/kb/llm/providers tests
touch src/kb/llm/providers/__init__.py
```

- [ ] **Step 7: 写失败的测试 `tests/test_config.py`**

```python
from pathlib import Path

import pytest

from kb.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个测试前清掉配置环境变量，避免测试间相互污染。"""
    for key in (
        "KB_LLM_API_KEY",
        "KB_LLM_BASE_URL",
        "KB_LLM_MODEL",
        "KB_VAULT_PATH",
        "KB_PORT",
    ):
        monkeypatch.delenv(key, raising=False)


def _write_env(tmp_path: Path, content: str) -> Path:
    env = tmp_path / ".env"
    env.write_text(content, encoding="utf-8")
    return env


VALID = "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=https://x/v1\nKB_LLM_MODEL=m\n"


def test_reads_required_values(tmp_path):
    cfg = load_config(_write_env(tmp_path, VALID))
    assert cfg.llm_api_key == "k"
    assert cfg.llm_base_url == "https://x/v1"
    assert cfg.llm_model == "m"


def test_missing_required_raises_with_key_name(tmp_path):
    env = _write_env(tmp_path, "KB_LLM_BASE_URL=https://x/v1\nKB_LLM_MODEL=m\n")
    with pytest.raises(ConfigError, match="KB_LLM_API_KEY"):
        load_config(env)


def test_vault_path_defaults_when_absent(tmp_path):
    cfg = load_config(_write_env(tmp_path, VALID))
    assert cfg.vault_path == Path(r"E:\KB_Library")


def test_port_parsed_and_optional(tmp_path):
    cfg = load_config(_write_env(tmp_path, VALID))
    assert cfg.port is None

    cfg2 = load_config(_write_env(tmp_path, VALID + "KB_PORT=5200\n"))
    assert cfg2.port == 5200


def test_vault_path_override(tmp_path):
    cfg = load_config(_write_env(tmp_path, VALID + "KB_VAULT_PATH=D:\\Other\n"))
    assert cfg.vault_path == Path("D:\\Other")
```

- [ ] **Step 8: 运行测试，确认失败**

```bash
conda activate kn_base
pytest tests/test_config.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.config'`

- [ ] **Step 9: 写 `src/kb/config.py`**

```python
"""读取工程根目录的 .env 配置。

配置集中在一个文件夹（Q32），不散到用户目录。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 本文件位于 <root>/src/kb/config.py，向上三层即工程根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_VAULT_PATH = Path(r"E:\KB_Library")


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


@dataclass(frozen=True)
class Config:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    vault_path: Path
    port: int | None


def load_config(env_file: Path | None = None) -> Config:
    """从 .env 读取配置。缺必填项时抛 ConfigError。"""
    env_file = env_file or PROJECT_ROOT / ".env"
    load_dotenv(env_file, override=False)

    def required(key: str) -> str:
        value = os.environ.get(key, "").strip()
        if not value:
            raise ConfigError(
                f"缺少必填配置 {key}。请复制 .env.example 为 .env 并填写。"
            )
        return value

    vault_raw = os.environ.get("KB_VAULT_PATH", "").strip()
    port_raw = os.environ.get("KB_PORT", "").strip()

    return Config(
        llm_api_key=required("KB_LLM_API_KEY"),
        llm_base_url=required("KB_LLM_BASE_URL"),
        llm_model=required("KB_LLM_MODEL"),
        vault_path=Path(vault_raw) if vault_raw else DEFAULT_VAULT_PATH,
        port=int(port_raw) if port_raw else None,
    )
```

- [ ] **Step 10: 运行测试，确认通过**

```bash
pytest tests/test_config.py -v
```

预期：5 passed

- [ ] **Step 11: 提交**

```bash
git add requirements.txt pyproject.toml .env.example src tests
git commit -m "feat: 项目脚手架与配置模块"
```

- [ ] **Step 12: 把 `requirements.lock.txt` 加进 `.gitignore`**

在 `.gitignore` 的「环境变量与密钥」段后追加：

```
# ---- 本机依赖锁定（含平台相关包，不跨平台）----
requirements.lock.txt
```

提交：

```bash
git add .gitignore
git commit -m "chore: 忽略本机依赖锁定文件"
```

---

## Task 2: 领域数据模型

**Files:**
- Create: `src/kb/core/models.py`
- Test: `tests/core/test_models.py`
- Test: `tests/test_architecture.py`

- [ ] **Step 1: 写失败的测试 `tests/core/test_models.py`**

```python
from dataclasses import FrozenInstanceError

import pytest

from kb.core.models import (
    K_CREATED,
    K_ID,
    K_PROJECT,
    K_SOURCE,
    K_STATUS,
    K_SUBMITTED_AT,
    K_TOPIC,
    K_TYPE,
    K_UPDATED,
    Draft,
    NoteType,
    OrganizePlan,
    OrganizeResult,
    Outcome,
    ResultKind,
)


def test_note_type_has_seven_values():
    """Q24：枚举固定，不许自由发挥。日志给整理日志，索引给自动生成的索引页。"""
    assert [t.value for t in NoteType] == [
        "概念",
        "踩坑",
        "决策",
        "经验",
        "清单",
        "日志",
        "索引",
    ]


def test_note_type_rejects_unknown_value():
    with pytest.raises(ValueError):
        NoteType("学习笔记")


def test_outcome_values_are_the_wire_contract():
    """这三个字符串是与 LLM 的 wire 契约——Task 8 按它们解析模型输出。

    假的保护长这样：`p.outcome is Outcome.CREATE` 是恒等比较，对 .value 不敏感，
    把 FOLD 改成 "merge" 也不会红。必须断言 .value 本身。
    """
    assert [o.value for o in Outcome] == ["create", "fold", "pending"]


def test_draft_holds_submitted_content_verbatim():
    """Q55：投递是纯粹的，正文原样保存。"""
    d = Draft(
        id="20260915-a3f2",
        body="并发写入会锁表\n",
        source="会话",
        project="电商后台",
        created_at="2026-09-15T14:32:00",
    )
    assert d.body == "并发写入会锁表\n"
    assert d.project == "电商后台"


def test_draft_project_is_optional():
    """Q30：允许没有项目——纯知识点场景。"""
    d = Draft(id="x", body="b", source=None, project=None, created_at="t")
    assert d.project is None


def test_draft_is_immutable():
    """Q55：草稿投递后原样保存，服务不改写——frozen 是这条承诺的机制保证。"""
    d = Draft(id="x", body="原始正文", source=None, project=None, created_at="t")
    with pytest.raises(FrozenInstanceError):
        d.body = "被改写了"


def test_plan_create_carries_path_and_frontmatter():
    p = OrganizePlan(
        draft_id="20260915-a3f2",
        outcome=Outcome.CREATE,
        target_path="20_知识/后端/并发写锁.md",
        frontmatter={K_TYPE: NoteType.CONCEPT.value, K_TOPIC: ["后端"]},
        content="# 并发写锁\n",
    )
    assert p.outcome is Outcome.CREATE
    assert p.frontmatter[K_TYPE] == "概念"
    assert p.pending_reason is None


def test_plan_pending_requires_reason():
    """归不了类时必须给出原因，供报告展示。"""
    p = OrganizePlan(
        draft_id="x",
        outcome=Outcome.PENDING,
        pending_reason="无法判断归属主题",
    )
    assert p.outcome is Outcome.PENDING
    assert p.target_path is None
    assert p.pending_reason == "无法判断归属主题"


def test_plan_defaults_are_independent():
    """可变默认值不能共享——否则会串数据。"""
    a = OrganizePlan(draft_id="a", outcome=Outcome.PENDING)
    b = OrganizePlan(draft_id="b", outcome=Outcome.PENDING)
    a.frontmatter["k"] = "v"
    assert b.frontmatter == {}


def test_plan_defaults_cover_all_optional_fields():
    """契约快照：最小构造下每个可选字段的默认值。

    这些默认值会被落盘逻辑直接消费（`apply_plan` 把 `plan.content` 写盘），
    改成 None 会让 frontmatter.Post 炸——而现有断言不会红。
    """
    p = OrganizePlan(draft_id="x", outcome=Outcome.CREATE)
    assert p.target_path is None
    assert p.frontmatter == {}
    assert p.content == ""
    assert p.pending_reason is None


def test_result_kind_covers_all_execution_outcomes():
    """Q45/Q50：执行结果有四种——成功新建、成功合并、待归类、失败。"""
    assert [k.value for k in ResultKind] == ["created", "folded", "pending", "failed"]


def test_organize_result_carries_error_separately():
    """失败时 error 有值，detail 仍可读——报告和工作日志都要用。"""
    r = OrganizeResult(
        draft_id="x",
        kind=ResultKind.FAILED,
        detail="模型返回格式不合规",
        error="JSONDecodeError: Expecting value",
    )
    assert r.kind is ResultKind.FAILED
    assert r.error is not None
    assert r.detail == "模型返回格式不合规"


def test_organize_result_is_immutable():
    """与 Draft 同为「已发生的记录」，frozen 是真保护（字段全是不可变标量）。"""
    r = OrganizeResult(draft_id="x", kind=ResultKind.CREATED, detail="d")
    with pytest.raises(FrozenInstanceError):
        r.detail = "被改了"


def test_frontmatter_key_constants_are_stable():
    """这些常量是跨模块契约——改名或写错会让读取端静默返回 None。"""
    assert (K_STATUS, K_ID, K_SUBMITTED_AT, K_SOURCE, K_PROJECT) == (
        "状态",
        "id",
        "投递时间",
        "来源",
        "项目",
    )
    assert (K_TYPE, K_TOPIC, K_CREATED, K_UPDATED) == ("类型", "主题", "创建", "更新")
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/core/test_models.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.core.models'`

- [ ] **Step 3: 写 `src/kb/core/models.py`**

```python
"""领域数据模型：只有数据与枚举，不含逻辑。

三条约定，下游所有模块都要守：

1. **枚举成员是 `str` 子类，写进 frontmatter 或文本前必须取 `.value`。**
   `f"{Outcome.CREATE}"` 得到的是 `'Outcome.CREATE'` 而不是 `'create'`；
   直接塞进 PyYAML 还会抛 `RepresenterError`。
2. **下游一律用 `is` 比较枚举，因此不得传入裸字符串。**
   （`str` 混入让 `Outcome.PENDING == "pending"` 成立，`is` 不成立——
   一旦实现里被喂进裸字符串，`is` 为假会静默走错分支。）
3. **frontmatter 键名一律引用本模块的 `K_*` 常量，不要写字面量。**
   写错键名不会报错，只会静默返回 `None`——归类信号消失、索引页不生成，
   而你什么都看不到。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

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


class ResultKind(str, Enum):
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
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/core/test_models.py -v
```

预期：14 passed

- [ ] **Step 5: 写架构守卫测试 `tests/test_architecture.py`**

「`core/` 与 `llm/` 不依赖接口层」这条约束（Q33）此前只靠人读代码保证。用 AST 检查把它变成机制——不用运行时 import，因为那要求目标模块能被成功导入，会掩盖问题。

```python
"""架构守卫：把「core/ 与 llm/ 不依赖接口层」从约定变成机制。

Q33 定的硬约束：领域逻辑必须能脱离界面单独测试。
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "kb"

GUARDED = ("core", "llm")
FORBIDDEN = ("kb.api", "kb.web")


def _python_files(package: str) -> list[Path]:
    folder = SRC / package
    return sorted(folder.rglob("*.py")) if folder.exists() else []


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("package", GUARDED)
def test_package_has_files(package):
    """防止守卫在包为空时静默通过——空目录会让下面那条测试恒绿。"""
    assert _python_files(package), f"src/kb/{package}/ 下没有 Python 文件，守卫失效"


@pytest.mark.parametrize("package", GUARDED)
def test_no_dependency_on_interface_layer(package):
    violations = [
        f"{path.relative_to(SRC.parent.parent)}: import {name}"
        for path in _python_files(package)
        for name in _imported_modules(path)
        if name.startswith(FORBIDDEN)
    ]
    assert not violations, "领域层不得依赖接口层（Q33）：\n" + "\n".join(violations)
```

- [ ] **Step 6: 运行守卫测试，确认通过**

```bash
pytest tests/test_architecture.py -v
```

预期：4 passed

**验证守卫真的有牙齿：** 临时在 `src/kb/core/models.py` 顶部加一行 `from kb.api import runtime  # noqa`，重跑应报 `领域层不得依赖接口层`；然后删掉那行。

- [ ] **Step 7: 跑全部测试**

```bash
pytest -v
```

预期：25 passed（Task 1 的 7 条 + 本任务的 18 条）

- [ ] **Step 8: 提交**

```bash
git add src/kb/core/models.py tests/core/test_models.py tests/test_architecture.py
git commit -m "feat: 领域数据模型、类型枚举与架构守卫测试"
```

## Task 3: vault 读写

**Files:**
- Create: `src/kb/core/vault.py`
- Test: `tests/core/test_vault.py`

- [ ] **Step 1: 写失败的测试 `tests/core/test_vault.py`**

```python
import re
from pathlib import Path

import pytest

from kb.core.models import Draft, NoteType
from kb.core.vault import (
    INBOX,
    PENDING,
    atomic_write,
    draft_path,
    ensure_topic_index,
    find_draft,
    find_project_dir,
    list_drafts,
    list_notes,
    list_projects,
    move_to_pending,
    new_draft_id,
    normalize_project,
    read_draft,
    read_note,
    write_draft,
    write_note,
)


def _draft(**kw) -> Draft:
    base = dict(
        id="20260915-a3f2",
        body="并发写入会锁表\n",
        source="会话",
        project="电商后台",
        created_at="2026-09-15 14:32",
    )
    base.update(kw)
    return Draft(**base)


# ---------- 草稿 id ----------

def test_draft_id_format():
    assert re.fullmatch(r"\d{8}-[0-9a-f]{4}", new_draft_id())


# ---------- 草稿读写 ----------

def test_write_then_read_draft_roundtrip(tmp_path):
    write_draft(tmp_path, _draft())
    got = read_draft(draft_path(tmp_path, "20260915-a3f2"))
    assert got.id == "20260915-a3f2"
    assert got.body.strip() == "并发写入会锁表"
    assert got.project == "电商后台"
    assert got.source == "会话"
    assert got.created_at == "2026-09-15 14:32"


def test_draft_frontmatter_marks_status(tmp_path):
    path = write_draft(tmp_path, _draft())
    text = path.read_text(encoding="utf-8")
    assert "状态: 待整理" in text


def test_draft_omits_absent_optional_fields(tmp_path):
    """没有项目时不写 '项目: null'——空字段不该出现在 frontmatter 里。"""
    path = write_draft(tmp_path, _draft(project=None, source=None))
    text = path.read_text(encoding="utf-8")
    assert "项目" not in text
    assert "来源" not in text
    assert "null" not in text


# ---------- 草稿列举 ----------

def test_list_drafts_scans_inbox_and_pending(tmp_path):
    """Q55：待归类子目录里的草稿也要被扫到，否则永远卡着。"""
    write_draft(tmp_path, _draft(id="20260915-0001"))
    (tmp_path / INBOX / PENDING).mkdir(parents=True)
    write_draft(tmp_path, _draft(id="20260915-0002"))
    move_to_pending(tmp_path, draft_path(tmp_path, "20260915-0002"))

    ids = {read_draft(p).id for p in list_drafts(tmp_path)}
    assert ids == {"20260915-0001", "20260915-0002"}


def test_list_drafts_empty_when_no_inbox(tmp_path):
    assert list_drafts(tmp_path) == []


def test_find_draft_locates_by_id(tmp_path):
    write_draft(tmp_path, _draft())
    found = find_draft(tmp_path, "20260915-a3f2")
    assert found is not None and found.exists()


def test_find_draft_returns_none_when_absent(tmp_path):
    assert find_draft(tmp_path, "不存在") is None


def test_move_to_pending_is_idempotent(tmp_path):
    write_draft(tmp_path, _draft())
    path = draft_path(tmp_path, "20260915-a3f2")
    once = move_to_pending(tmp_path, path)
    twice = move_to_pending(tmp_path, once)
    assert once == twice
    assert once.parent.name == PENDING


# ---------- 笔记读写 ----------

def test_write_then_read_note_roundtrip(tmp_path):
    path = tmp_path / "20_知识" / "后端" / "并发写锁.md"
    write_note(path, {"类型": "概念", "主题": ["后端"], "项目": None}, "# 并发写锁\n")
    meta, body = read_note(path)
    assert meta["类型"] == "概念"
    assert meta["主题"] == ["后端"]
    assert body.strip() == "# 并发写锁"


def test_list_notes_covers_projects_and_knowledge(tmp_path):
    write_note(tmp_path / "20_知识" / "后端" / "a.md", {"类型": "概念"}, "a")
    write_note(tmp_path / "10_项目" / "个人" / "P" / "P-踩坑.md", {"类型": "踩坑"}, "b")
    write_note(tmp_path / "40_索引" / "后端.md", {"类型": "清单"}, "不该被扫到")
    names = {p.name for p in list_notes(tmp_path)}
    assert names == {"a.md", "P-踩坑.md"}


# ---------- 项目名匹配（Q30）----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("KN_Base", "kn-base"),
        ("kn-base", "kn-base"),
        ("KN Base", "kn-base"),
        ("  KN_Base  ", "kn-base"),
    ],
)
def test_normalize_project(raw, expected):
    assert normalize_project(raw) == expected


def test_find_project_dir_unique_match(tmp_path):
    target = tmp_path / "10_项目" / "工作" / "电商后台"
    target.mkdir(parents=True)
    assert find_project_dir(tmp_path, "电商后台") == target


def test_find_project_dir_matches_across_separator_styles(tmp_path):
    target = tmp_path / "10_项目" / "个人" / "KN_Base"
    target.mkdir(parents=True)
    assert find_project_dir(tmp_path, "kn-base") == target


def test_find_project_dir_returns_none_when_absent(tmp_path):
    (tmp_path / "10_项目" / "个人").mkdir(parents=True)
    assert find_project_dir(tmp_path, "不存在") is None


def test_find_project_dir_returns_none_on_ambiguity(tmp_path):
    """同名项目出现在两个分组下 → 不猜，返回 None，走待归类。"""
    (tmp_path / "10_项目" / "个人" / "P").mkdir(parents=True)
    (tmp_path / "10_项目" / "工作" / "P").mkdir(parents=True)
    assert find_project_dir(tmp_path, "P") is None


def test_list_projects_returns_group_and_path(tmp_path):
    (tmp_path / "10_项目" / "个人" / "A").mkdir(parents=True)
    (tmp_path / "10_项目" / "工作" / "B").mkdir(parents=True)
    got = list_projects(tmp_path)
    assert [(g, p.name) for g, p in got] == [("个人", "A"), ("工作", "B")]


def test_list_projects_empty_when_absent(tmp_path):
    assert list_projects(tmp_path) == []


def test_ensure_topic_index_creates_dataview_page(tmp_path):
    """空库第一天也要有东西可链，否则第一条笔记必然违反 Q21。"""
    path = ensure_topic_index(tmp_path, "后端")
    assert path == tmp_path / INDEX / "后端.md"
    meta, body = read_note(path)
    assert meta["类型"] == "索引"
    assert 'FROM "20_知识/后端"' in body


def test_ensure_topic_index_never_overwrites_user_edits(tmp_path):
    """幂等：用户手改过的索引页不能被服务覆盖回去。"""
    first = ensure_topic_index(tmp_path, "后端")
    first.write_text("用户自己改的内容", encoding="utf-8")
    second = ensure_topic_index(tmp_path, "后端")
    assert second.read_text(encoding="utf-8") == "用户自己改的内容"


# ---------- 原子写 ----------

def test_atomic_write_leaves_no_tmp_file(tmp_path):
    target = tmp_path / "x.md"
    atomic_write(target, "内容")
    assert target.read_text(encoding="utf-8") == "内容"
    assert list(tmp_path.glob("*.tmp")) == []
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/core/test_vault.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.core.vault'`

- [ ] **Step 3: 写 `src/kb/core/vault.py`**

```python
"""vault 的读写：文件、frontmatter、路径解析。

只管文件与数据，不做任何判断——归类在 classify、编排在 organize。
"""

from __future__ import annotations

import random
import re
import subprocess
from datetime import datetime
from pathlib import Path

import frontmatter

from kb.core.models import Draft

INBOX = "00_收件箱"
PENDING = "待归类"
PROJECTS = "10_项目"
KNOWLEDGE = "20_知识"
MATERIALS = "30_素材"
INDEX = "40_索引"
ATTACHMENTS = "90_附件"

DRAFT_STATUS = "待整理"

_SEPARATOR_RE = re.compile(r"[-_\s]+")


# ---------------------------------------------------------------- 原子写

def atomic_write(path: Path, text: str) -> None:
    """先写临时文件再改名，避免中断时留下半个文件（Q45）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- 草稿

def new_draft_id(now: datetime | None = None) -> str:
    """`YYYYMMDD-` + 4 位随机十六进制（Q55）。"""
    now = now or datetime.now()
    return f"{now:%Y%m%d}-{random.randrange(16 ** 4):04x}"


def draft_path(vault_root: Path, draft_id: str) -> Path:
    return vault_root / INBOX / f"{draft_id}.md"


def write_draft(vault_root: Path, draft: Draft) -> Path:
    """把草稿落进收件箱。正文原样写入，不改写（Q55）。"""
    meta = {"状态": DRAFT_STATUS, "id": draft.id, "投递时间": draft.created_at}
    if draft.source:
        meta["来源"] = draft.source
    if draft.project:
        meta["项目"] = draft.project

    path = draft_path(vault_root, draft.id)
    post = frontmatter.Post(draft.body, **meta)
    atomic_write(path, frontmatter.dumps(post, allow_unicode=True))
    return path


def read_draft(path: Path) -> Draft:
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    return Draft(
        id=str(post.get("id") or path.stem),
        body=post.content,
        source=post.get("来源"),
        project=post.get("项目"),
        created_at=str(post.get("投递时间") or ""),
    )


def list_drafts(vault_root: Path) -> list[Path]:
    """列出所有待整理草稿：收件箱根目录 + 待归类子目录（Q55）。

    待归类的也要扫，否则它们永远卡着——库长大之后原本归不了类的可能变得可归类。
    """
    inbox = vault_root / INBOX
    if not inbox.exists():
        return []
    paths = [p for p in inbox.glob("*.md") if p.is_file()]
    pending = inbox / PENDING
    if pending.exists():
        paths.extend(p for p in pending.glob("*.md") if p.is_file())
    return sorted(paths)


def find_draft(vault_root: Path, draft_id: str) -> Path | None:
    """按 id 找草稿。收件箱与待归类都会找。"""
    for path in list_drafts(vault_root):
        if path.stem == draft_id:
            return path
    return None


def move_to_pending(vault_root: Path, path: Path) -> Path:
    """把归不了类的草稿移进 待归类/。已在其中则原样返回。"""
    dest = vault_root / INBOX / PENDING / path.name
    if path.parent == dest.parent:
        return path
    dest.parent.mkdir(parents=True, exist_ok=True)
    path.replace(dest)
    return dest


def remove_draft(path: Path) -> None:
    """整理成功后删除草稿。"""
    path.unlink(missing_ok=True)


# ---------------------------------------------------------------- 笔记

def read_note(path: Path) -> tuple[dict, str]:
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    return dict(post.metadata), post.content


def write_note(path: Path, metadata: dict, body: str) -> None:
    clean = {k: v for k, v in metadata.items() if v is not None}
    post = frontmatter.Post(body, **clean)
    atomic_write(path, frontmatter.dumps(post, allow_unicode=True))


def list_notes(vault_root: Path) -> list[Path]:
    """列出正式笔记（项目档案 + 知识区），供查重预筛取候选。"""
    found: list[Path] = []
    for folder in (vault_root / PROJECTS, vault_root / KNOWLEDGE):
        if folder.exists():
            found.extend(p for p in folder.rglob("*.md") if p.is_file())
    return sorted(found)


# ---------------------------------------------------------------- 项目名（Q30）

def normalize_project(name: str) -> str:
    """项目名规范化：转小写，`-`、`_`、空格视为等价。

    避免 `KN_Base` / `kn_base` / `KN-Base` 被当成三个项目。
    """
    return _SEPARATOR_RE.sub("-", name.strip().lower())


def find_project_dir(vault_root: Path, name: str) -> Path | None:
    """在 `10_项目/<分组>/<项目名>` 下搜唯一匹配。

    找不到或有多个同名 → 返回 None（不猜，走待归类）。
    """
    if not name:
        return None
    root = vault_root / PROJECTS
    if not root.exists():
        return None

    target = normalize_project(name)
    matches: list[Path] = []
    for group in sorted(root.iterdir()):
        if not group.is_dir():
            continue
        for project in sorted(group.iterdir()):
            if project.is_dir() and normalize_project(project.name) == target:
                matches.append(project)
    return matches[0] if len(matches) == 1 else None


def topic_index_path(vault_root: Path, topic: str) -> Path:
    return vault_root / INDEX / f"{topic}.md"


def ensure_topic_index(vault_root: Path, topic: str) -> Path:
    """确保 `40_索引/<主题>.md` 存在，返回其路径。

    索引页是**自动生成的 Dataview 查询页**，零维护——永远自动列出该主题下的所有笔记。
    它让「不允许孤儿笔记」（Q21）从空库第一天起就成立：第一条笔记就有东西可链。

    已存在则原样返回，**不覆盖**——用户可能自己改过。
    """
    path = topic_index_path(vault_root, topic)
    if path.exists():
        return path

    body = (
        f"# {topic}\n\n"
        "```dataview\n"
        "LIST\n"
        f'FROM "{KNOWLEDGE}/{topic}"\n'
        "SORT file.name ASC\n"
        "```\n"
    )
    write_note(path, {"类型": NoteType.INDEX.value, "主题": [topic]}, body)
    return path


def list_projects(vault_root: Path) -> list[tuple[str, Path]]:
    """列出 `10_项目/<分组>/<项目名>` 下的所有项目，返回 (分组名, 项目路径)。"""
    root = vault_root / PROJECTS
    if not root.exists():
        return []
    found: list[tuple[str, Path]] = []
    for group in sorted(root.iterdir()):
        if not group.is_dir():
            continue
        for project in sorted(group.iterdir()):
            if project.is_dir():
                found.append((group.name, project))
    return found


def project_name_from_cwd(cwd: Path) -> str | None:
    """取 git 仓库根的目录名作为项目名（Q30）。

    用 git 根而非 cwd 本身——agent 可能停在子目录（如 `src/kb/core/`），
    那样 basename 会取到 `core`。非 git 仓库回退到 cwd 的 basename。
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()).name
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd.name or None
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/core/test_vault.py -v
```

预期：23 passed

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/vault.py tests/core/test_vault.py
git commit -m "feat: vault 读写、frontmatter 与项目名匹配"
```

## Task 4: 笔记模板与 vault 初始化

**Files:**
- Create: `templates/{概念,踩坑,决策,经验,清单,日志}.md`
- Create: `scripts/init_vault.py`
- Test: `tests/test_init_vault.py`

模板只定义**正文骨架**，不定义 frontmatter——字段由代码按 `NoteType` 生成，这样枚举约束不会被模板绕过（Q24）。

- [ ] **Step 1: 写 6 个模板文件**

`templates/概念.md`

````markdown
# {{标题}}

## 展开

## 用户的判断

## 相关
````

`templates/踩坑.md`

````markdown
# {{标题}}

## 现象

## 原因

## 解决

## 用户的判断

## 相关
````

`templates/决策.md`

````markdown
# {{标题}}

## 背景

## 选项

## 决定

## 理由

## 用户的判断

## 相关
````

`templates/经验.md`

````markdown
# {{标题}}

## 情境

## 做法

## 效果

## 用户的判断

## 相关
````

`templates/清单.md`

````markdown
# {{标题}}

- [ ]

## 用户的判断

## 相关
````

`templates/日志.md`

````markdown
# 整理日志 {{日期}}
````

- [ ] **Step 2: 写失败的测试 `tests/test_init_vault.py`**

```python
from pathlib import Path

import pytest

from kb.core.vault import (
    ATTACHMENTS,
    INBOX,
    INDEX,
    KNOWLEDGE,
    MATERIALS,
    PENDING,
    PROJECTS,
)
from scripts.init_vault import init_vault, vault_dirs


def test_creates_all_skeleton_dirs(tmp_path):
    init_vault(tmp_path)
    for rel in (
        INBOX,
        f"{INBOX}/{PENDING}",
        PROJECTS,
        KNOWLEDGE,
        MATERIALS,
        INDEX,
        f"{INDEX}/整理日志",
        ATTACHMENTS,
    ):
        assert (tmp_path / rel).is_dir(), f"缺少目录 {rel}"


def test_creates_topic_and_group_dirs(tmp_path):
    init_vault(tmp_path)
    for topic in ("后端", "前端", "工具链", "方法论"):
        assert (tmp_path / KNOWLEDGE / topic).is_dir()
    for group in ("个人", "工作"):
        assert (tmp_path / PROJECTS / group).is_dir()


def test_writes_gitignore_ignoring_workspace(tmp_path):
    """Q53：workspace.json 每次开关 Obsidian 都变，必须忽略。"""
    init_vault(tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".obsidian/workspace.json" in text


def test_initializes_git_repo(tmp_path):
    init_vault(tmp_path)
    assert (tmp_path / ".git").is_dir()


def test_does_not_touch_existing_gitignore(tmp_path):
    """幂等：已存在的 .gitignore 不能被覆盖——用户可能自己加过规则。"""
    (tmp_path / ".gitignore").write_text("# 我自己加的\n", encoding="utf-8")
    init_vault(tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "# 我自己加的\n"


def test_is_idempotent(tmp_path):
    """重复执行不报错，且第二次无事可做。"""
    init_vault(tmp_path)
    second = init_vault(tmp_path)
    assert second == []


def test_second_run_keeps_existing_notes(tmp_path):
    """幂等：不能删掉用户已经写进去的内容。"""
    init_vault(tmp_path)
    note = tmp_path / KNOWLEDGE / "后端" / "已有笔记.md"
    note.write_text("内容", encoding="utf-8")
    init_vault(tmp_path)
    assert note.read_text(encoding="utf-8") == "内容"


def test_vault_dirs_are_absolute_under_root(tmp_path):
    for d in vault_dirs(tmp_path):
        assert d.is_relative_to(tmp_path)
```

- [ ] **Step 3: 运行测试，确认失败**

```bash
pytest tests/test_init_vault.py -v
```

预期：`ModuleNotFoundError: No module named 'scripts.init_vault'`

- [ ] **Step 4: 写 `scripts/init_vault.py`**

```python
"""建 vault 骨架。幂等——可重复执行，不破坏已有内容。

这个脚本是知识库结构的唯一真源：实际目录是它的产物。
想调结构就改这里重跑，不要手工建目录。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from kb.core.vault import (
    ATTACHMENTS,
    INBOX,
    INDEX,
    KNOWLEDGE,
    MATERIALS,
    PENDING,
    PROJECTS,
)

KNOWLEDGE_TOPICS = ["后端", "前端", "工具链", "方法论"]
PROJECT_GROUPS = ["个人", "工作"]
JOURNAL_DIR = "整理日志"

VAULT_GITIGNORE = """\
# Obsidian 工作区状态——每次开关都变，入库会淹没历史（Q53）
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/cache

# 系统文件
.DS_Store
Thumbs.db
"""


def vault_dirs(vault_root: Path) -> list[Path]:
    dirs = [
        vault_root / INBOX,
        vault_root / INBOX / PENDING,
        vault_root / PROJECTS,
        vault_root / KNOWLEDGE,
        vault_root / MATERIALS,
        vault_root / INDEX,
        vault_root / INDEX / JOURNAL_DIR,
        vault_root / ATTACHMENTS,
    ]
    dirs += [vault_root / KNOWLEDGE / t for t in KNOWLEDGE_TOPICS]
    dirs += [vault_root / PROJECTS / g for g in PROJECT_GROUPS]
    return dirs


def _git(vault_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=vault_root, capture_output=True, text=True
    )


def _has_commits(vault_root: Path) -> bool:
    return _git(vault_root, "rev-parse", "HEAD").returncode == 0


def init_vault(vault_root: Path) -> list[str]:
    """建目录、写 .gitignore、初始化 git。返回本次实际执行的动作。"""
    actions: list[str] = []

    for d in vault_dirs(vault_root):
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            actions.append(f"建目录 {d.relative_to(vault_root)}")

    gitignore = vault_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(VAULT_GITIGNORE, encoding="utf-8")
        actions.append("写 .gitignore")

    if not (vault_root / ".git").exists():
        _git(vault_root, "init", "-b", "main")
        actions.append("初始化 git 仓库")

    if not _has_commits(vault_root) and gitignore.exists():
        _git(vault_root, "add", ".gitignore")
        _git(vault_root, "commit", "-m", "chore: 初始化 vault 骨架")
        actions.append("首次提交")

    return actions
```

**注意：这里不设 `git config user.name`。** 服务要区分「AI 写的」和「我写的」（Q46），做法是在**自己提交时**用 `-c user.name=kb-service` 临时指定，而不是改仓库配置——改仓库配置会把用户手动提交也记成 kb-service。

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/test_init_vault.py -v
```

预期：8 passed

- [ ] **Step 6: 提交**

```bash
git add templates scripts tests/test_init_vault.py
git commit -m "feat: 笔记模板与 vault 初始化脚本"
```

---

## Task 5: LLM 抽象层

**Files:**
- Create: `src/kb/llm/base.py`
- Create: `src/kb/llm/providers/openai_compat.py`
- Test: `tests/llm/test_base.py`
- Test: `tests/llm/test_openai_compat.py`

- [ ] **Step 1: 写失败的测试 `tests/llm/test_base.py`**

```python
import pytest

from kb.llm.base import FakeLLM, LLM, LLMError


def test_llm_is_abstract():
    with pytest.raises(TypeError):
        LLM()


def test_fake_llm_records_calls_and_repeats_single_response():
    llm = FakeLLM("固定响应")
    assert llm.complete("sys", "u1") == "固定响应"
    assert llm.complete("sys", "u2") == "固定响应"
    assert len(llm.calls) == 2


def test_fake_llm_drains_queue_in_order():
    llm = FakeLLM(["第一次", "第二次"])
    assert llm.complete("s", "u") == "第一次"
    assert llm.complete("s", "u") == "第二次"


def test_fake_llm_raises_when_queue_exhausted():
    llm = FakeLLM(["只有一条"])
    llm.complete("s", "u")          # 队列长度 1 → 固定返回，不消耗
    assert llm.complete("s", "u") == "只有一条"


def test_fake_llm_two_responses_then_exhausted():
    llm = FakeLLM(["a", "b"])
    llm.complete("s", "u")
    llm.complete("s", "u")
    with pytest.raises(LLMError):
        llm.complete("s", "u")
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/llm/test_base.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.llm.base'`

- [ ] **Step 3: 写 `src/kb/llm/base.py`**

```python
"""LLM 抽象接口。

上层只依赖这个接口，不依赖具体供应商（Q33/Q54）。
测试时用 FakeLLM 替换真实实现，不跑真实 API（Q52）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """LLM 调用失败：网络、超时、限流、返回为空等。"""


class LLM(ABC):
    """模型的最小接口——只要能把提示词变成文本就够。"""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """返回模型输出的纯文本。失败时抛 LLMError。"""


class FakeLLM(LLM):
    """测试用假实现。

    传字符串 → 每次都返回它（不消耗队列）；
    传列表   → 按顺序吐出，用完再调用则抛 LLMError。
    """

    def __init__(self, responses: str | list[str]):
        self.responses: list[str] = (
            [responses] if isinstance(responses, str) else list(responses)
        )
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self.responses:
            raise LLMError("FakeLLM 的响应队列已空")
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses.pop(0)
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/llm/test_base.py -v
```

预期：5 passed

- [ ] **Step 5: 写失败的测试 `tests/llm/test_openai_compat.py`**

```python
import pytest

from kb.llm.base import LLMError
from kb.llm.providers.openai_compat import OpenAICompatLLM


class _Choice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _StubClient:
    def __init__(self, content=None, raises=None):
        self._content = content
        self._raises = raises
        self.calls = []

        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if outer._raises:
                    raise outer._raises
                return _Resp(outer._content)

        self.chat = type("C", (), {"completions": _Completions()})()


@pytest.fixture
def patched(monkeypatch):
    def _install(stub):
        monkeypatch.setattr(
            "kb.llm.providers.openai_compat.OpenAI",
            lambda **kwargs: stub,
        )
        return stub

    return _install


def test_returns_message_content(patched):
    stub = patched(_StubClient(content="模型输出"))
    llm = OpenAICompatLLM(api_key="k", base_url="https://x/v1", model="m")
    assert llm.complete("sys", "user") == "模型输出"


def test_passes_system_and_user_messages(patched):
    stub = patched(_StubClient(content="ok"))
    llm = OpenAICompatLLM(api_key="k", base_url="https://x/v1", model="m")
    llm.complete("系统提示", "用户内容")
    kwargs = stub.calls[0]
    assert kwargs["model"] == "m"
    assert kwargs["messages"] == [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户内容"},
    ]


def test_wraps_provider_error_as_llm_error(patched):
    from openai import OpenAIError

    patched(_StubClient(raises=OpenAIError("limit")))
    llm = OpenAICompatLLM(api_key="k", base_url="https://x/v1", model="m")
    with pytest.raises(LLMError, match="limit"):
        llm.complete("s", "u")


def test_empty_content_raises_llm_error(patched):
    patched(_StubClient(content=None))
    llm = OpenAICompatLLM(api_key="k", base_url="https://x/v1", model="m")
    with pytest.raises(LLMError, match="空内容"):
        llm.complete("s", "u")
```

- [ ] **Step 6: 运行测试，确认失败**

```bash
pytest tests/llm/test_openai_compat.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.llm.providers.openai_compat'`

- [ ] **Step 7: 写 `src/kb/llm/providers/openai_compat.py`**

```python
"""OpenAI 兼容端点实现（Q54）。

用 openai SDK 指向供应商的兼容端点。将来换供应商只改 base_url 和模型名，
本文件不用动。
"""

from __future__ import annotations

from openai import OpenAI, OpenAIError

from kb.llm.base import LLM, LLMError


class OpenAICompatLLM(LLM):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._model = model

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except OpenAIError as exc:
            raise LLMError(str(exc)) from exc

        content = resp.choices[0].message.content
        if not content:
            raise LLMError("模型返回了空内容")
        return content
```

- [ ] **Step 8: 运行测试，确认通过**

```bash
pytest tests/llm/ -v
```

预期：9 passed

- [ ] **Step 9: 提交**

```bash
git add src/kb/llm tests/llm
git commit -m "feat: LLM 抽象层与 OpenAI 兼容端点实现"
```

## Task 6: 查重预筛

**Files:**
- Create: `src/kb/core/classify.py`
- Test: `tests/core/test_classify.py`

这是 Q36 两段式的**第一段**：只做便宜的候选召回，**不下结论**。「完全重复 / 相关 / 全新」的判定交给 LLM（在 Task 8）。

用字符 2-gram + Jaccard 相似度，不引第三方分词库——中文没有空格，2-gram 是便宜且够用的近似。

- [ ] **Step 1: 写失败的测试 `tests/core/test_classify.py`**

```python
from pathlib import Path

from kb.core.classify import (
    bigrams,
    find_candidates,
    first_heading,
    knowledge_topics,
    similarity,
)
from kb.core.vault import KNOWLEDGE, write_note


def _note(root: Path, rel: str, body: str, tags: list[str] | None = None) -> Path:
    path = root / rel
    write_note(path, {"类型": "概念", "主题": tags or []}, body)
    return path


# ---------- 2-gram ----------

def test_bigrams_ignores_whitespace():
    assert bigrams("并发 写入") == bigrams("并发写入")


def test_bigrams_of_single_char():
    assert bigrams("锁") == {"锁"}


def test_bigrams_of_empty_string():
    assert bigrams("   ") == set()


# ---------- 相似度 ----------

def test_identical_text_scores_one():
    assert similarity("并发写入会锁表", "并发写入会锁表") == 1.0


def test_unrelated_text_scores_zero():
    assert similarity("并发写入会锁表", "红烧肉的做法") == 0.0


def test_similarity_is_between_zero_and_one():
    s = similarity("并发写入会锁表", "并发写入偶尔锁表")
    assert 0.0 < s < 1.0


def test_similarity_with_empty_side_is_zero():
    assert similarity("", "任意内容") == 0.0


# ---------- 标题提取 ----------

def test_first_heading_prefers_h1():
    assert first_heading("前言\n# 并发写锁\n正文") == "并发写锁"


def test_first_heading_falls_back_to_first_nonempty_line():
    assert first_heading("\n\n没有标题的行\n后面") == "没有标题的行"


def test_first_heading_of_empty_body():
    assert first_heading("   \n\n") == ""


# ---------- 候选召回 ----------

def test_find_candidates_ranks_similar_first(tmp_path):
    _note(tmp_path, f"{KNOWLEDGE}/后端/并发写锁.md", "# 并发写入会锁表\n")
    _note(tmp_path, f"{KNOWLEDGE}/前端/居中布局.md", "# 用 flex 居中\n")

    got = find_candidates(tmp_path, "并发写入的时候会锁表，怎么办")
    assert got[0].title == "并发写入会锁表"


def test_find_candidates_respects_limit(tmp_path):
    for i in range(5):
        _note(tmp_path, f"{KNOWLEDGE}/后端/n{i}.md", f"# 并发写入会锁表 {i}\n")
    assert len(find_candidates(tmp_path, "并发写入会锁表", limit=3)) == 3


def test_find_candidates_returns_empty_for_empty_vault(tmp_path):
    assert find_candidates(tmp_path, "任意内容") == []


def test_find_candidates_uses_tags_as_signal(tmp_path):
    """标题不含关键词，但主题标签命中的笔记也应被召回。"""
    _note(tmp_path, f"{KNOWLEDGE}/后端/杂记.md", "# 一些零散的记录\n", tags=["并发", "锁"])
    got = find_candidates(tmp_path, "并发 锁")
    assert got[0].path.name == "杂记.md"


def test_candidates_are_sorted_by_score_desc(tmp_path):
    _note(tmp_path, f"{KNOWLEDGE}/后端/a.md", "# 并发写入会锁表\n")
    _note(tmp_path, f"{KNOWLEDGE}/后端/b.md", "# 并发\n")
    got = find_candidates(tmp_path, "并发写入会锁表")
    assert [c.score for c in got] == sorted([c.score for c in got], reverse=True)


# ---------- 既有主题 ----------

def test_knowledge_topics_lists_dirs(tmp_path):
    (tmp_path / KNOWLEDGE / "后端").mkdir(parents=True)
    (tmp_path / KNOWLEDGE / "前端").mkdir(parents=True)
    (tmp_path / KNOWLEDGE / "散笔记.md").write_text("x", encoding="utf-8")
    assert knowledge_topics(tmp_path) == ["前端", "后端"]


def test_knowledge_topics_empty_when_absent(tmp_path):
    assert knowledge_topics(tmp_path) == []
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/core/test_classify.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.core.classify'`

- [ ] **Step 3: 写 `src/kb/core/classify.py`**

```python
"""查重预筛——Q36 两段式的第一段。

只做便宜的候选召回，**不下结论**。「完全重复 / 相关 / 全新」由 LLM 判定。
这样 LLM 只需要看 5-10 篇候选，而不是全库。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kb.core.vault import KNOWLEDGE, list_notes, read_note

DEFAULT_LIMIT = 8


@dataclass(frozen=True)
class Candidate:
    """一篇可能相关的已有笔记。"""

    path: Path
    title: str
    tags: list[str]
    score: float


def bigrams(text: str) -> set[str]:
    """字符 2-gram。

    中文没有空格可分词，字符 2-gram 是不引第三方库、且够用的近似。
    """
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def similarity(a: str, b: str) -> float:
    """Jaccard 相似度，取值 0.0 ~ 1.0。任一侧为空则返回 0.0。"""
    ga, gb = bigrams(a), bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def first_heading(body: str) -> str:
    """取正文第一个 `# ` 标题；没有就用首个非空行。"""
    for line in body.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()
    for line in body.splitlines():
        if line.strip():
            return line.strip()
    return ""


def note_title_and_tags(path: Path) -> tuple[str, list[str]]:
    meta, body = read_note(path)
    title = first_heading(body) or path.stem
    tags = meta.get("主题") or []
    if isinstance(tags, str):
        tags = [tags]
    return title, list(tags)


def find_candidates(vault_root: Path, text: str, limit: int = DEFAULT_LIMIT) -> list[Candidate]:
    """按相似度取前 `limit` 篇候选笔记。

    全库扫描，但只算字符串相似度——**不调 LLM**，所以便宜。阶段二会把这里换成向量召回，
    判定层不用动（Q36）。
    """
    scored: list[Candidate] = []
    for path in list_notes(vault_root):
        title, tags = note_title_and_tags(path)
        haystack = " ".join([title, *tags])
        scored.append(
            Candidate(
                path=path,
                title=title,
                tags=tags,
                score=similarity(text, haystack),
            )
        )
    scored.sort(key=lambda c: (-c.score, str(c.path)))
    return scored[:limit]


def knowledge_topics(vault_root: Path) -> list[str]:
    """`20_知识/` 下已有的主题目录名。

    服务的主题必须落在这些既有主题里——**新主题要用户决定**（Q11：AI 不得自行发明分类）。
    """
    root = vault_root / KNOWLEDGE
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/core/test_classify.py -v
```

预期：15 passed

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/classify.py tests/core/test_classify.py
git commit -m "feat: 查重预筛（2-gram 候选召回）"
```

---

## Task 7: 工作日志

**Files:**
- Create: `src/kb/core/journal.py`
- Test: `tests/core/test_journal.py`

- [ ] **Step 1: 写失败的测试 `tests/core/test_journal.py`**

```python
from datetime import datetime
from pathlib import Path

from kb.core.journal import append_results, format_entry, journal_path
from kb.core.models import OrganizeResult, ResultKind
from kb.core.vault import INDEX, read_note

WHEN = datetime(2026, 9, 15, 14, 32)


def _result(kind, detail, error=None):
    return OrganizeResult(draft_id="20260915-a3f2", kind=kind, detail=detail, error=error)


def test_journal_path_is_daily(tmp_path):
    assert journal_path(tmp_path, WHEN) == (
        tmp_path / INDEX / "整理日志" / "2026-09-15.md"
    )


def test_creates_daily_page_with_frontmatter(tmp_path):
    path = append_results(tmp_path, [_result(ResultKind.CREATED, "并发写锁")], WHEN)
    meta, body = read_note(path)
    assert meta["类型"] == "日志"
    assert "# 整理日志 2026-09-15" in body


def test_entry_carries_time_and_count(tmp_path):
    path = append_results(
        tmp_path,
        [
            _result(ResultKind.CREATED, "并发写锁"),
            _result(ResultKind.FOLDED, "XXX-踩坑"),
        ],
        WHEN,
    )
    _, body = read_note(path)
    assert "## 14:32 整理 2 条草稿" in body


def test_appends_second_run_to_same_day_file(tmp_path):
    """Q50：按天聚合——同一天第二次整理追加，不另建文件。"""
    append_results(tmp_path, [_result(ResultKind.CREATED, "第一条")], WHEN)
    path = append_results(
        tmp_path, [_result(ResultKind.CREATED, "第二条")], WHEN.replace(hour=16)
    )
    files = list((tmp_path / INDEX / "整理日志").glob("*.md"))
    assert len(files) == 1
    _, body = read_note(path)
    assert "第一条" in body and "第二条" in body
    assert "## 14:32" in body and "## 16:32" in body


def test_different_days_go_to_different_files(tmp_path):
    append_results(tmp_path, [_result(ResultKind.CREATED, "周一")], WHEN)
    append_results(
        tmp_path, [_result(ResultKind.CREATED, "周二")], WHEN.replace(day=16)
    )
    names = sorted(p.name for p in (tmp_path / INDEX / "整理日志").glob("*.md"))
    assert names == ["2026-09-15.md", "2026-09-16.md"]


def test_failures_are_recorded(tmp_path):
    """Q50：失败也记——只记成功的话，回头看不知道当时为什么卡住。"""
    path = append_results(
        tmp_path,
        [_result(ResultKind.FAILED, "格式不合规", error="JSONDecodeError")],
        WHEN,
    )
    _, body = read_note(path)
    assert "失败" in body
    assert "JSONDecodeError" in body


def test_pending_is_recorded(tmp_path):
    path = append_results(
        tmp_path, [_result(ResultKind.PENDING, "无法判断主题")], WHEN
    )
    _, body = read_note(path)
    assert "待归类" in body


def test_update_field_is_set(tmp_path):
    path = append_results(tmp_path, [_result(ResultKind.CREATED, "x")], WHEN)
    meta, _ = read_note(path)
    assert meta["更新"] == "2026-09-15"


def test_format_entry_labels_by_kind():
    assert format_entry(_result(ResultKind.CREATED, "甲")).startswith("- 新建：")
    assert format_entry(_result(ResultKind.FOLDED, "乙")).startswith("- 合并：")
    assert format_entry(_result(ResultKind.PENDING, "丙")).startswith("- 待归类：")
    assert format_entry(_result(ResultKind.FAILED, "丁")).startswith("- 失败：")
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/core/test_journal.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.core.journal'`

- [ ] **Step 3: 写 `src/kb/core/journal.py`**

```python
"""工作日志（Q50）。

按天聚合：`40_索引/整理日志/YYYY-MM-DD.md`，每次整理往当天那篇追加一节。

**报告与工作日志同源**——本模块只负责渲染成 markdown，文本报告由 api 层从同一批
OrganizeResult 渲染。不写两套逻辑，否则会出现报告说「新建 3 篇」而日志写 4 篇。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from kb.core.models import OrganizeResult, ResultKind
from kb.core.vault import INDEX, read_note, write_note

JOURNAL_DIR = "整理日志"

_LABEL: dict[ResultKind, str] = {
    ResultKind.CREATED: "新建",
    ResultKind.FOLDED: "合并",
    ResultKind.PENDING: "待归类",
    ResultKind.FAILED: "失败",
}


def journal_dir(vault_root: Path) -> Path:
    return vault_root / INDEX / JOURNAL_DIR


def journal_path(vault_root: Path, when: datetime) -> Path:
    return journal_dir(vault_root) / f"{when:%Y-%m-%d}.md"


def format_entry(result: OrganizeResult) -> str:
    """渲染一条结果。失败时把原因也带上——不然日志里看不出为什么卡住。"""
    line = f"- {_LABEL[result.kind]}：{result.detail}"
    if result.error:
        line += f"（{result.error}）"
    return line


def append_results(
    vault_root: Path,
    results: list[OrganizeResult],
    when: datetime | None = None,
) -> Path | None:
    """把一次整理的结果追加进当天的工作日志。results 为空时不写文件。"""
    if not results:
        return None

    when = when or datetime.now()
    path = journal_path(vault_root, when)

    if path.exists():
        meta, body = read_note(path)
    else:
        meta, body = {"类型": "日志"}, f"# 整理日志 {when:%Y-%m-%d}\n"

    meta["类型"] = "日志"
    meta["更新"] = f"{when:%Y-%m-%d}"

    section = "\n".join(
        [f"## {when:%H:%M} 整理 {len(results)} 条草稿", ""]
        + [format_entry(r) for r in results]
    )
    body = body.rstrip("\n") + "\n\n" + section + "\n"

    write_note(path, meta, body)
    return path
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/core/test_journal.py -v
```

预期：9 passed

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/journal.py tests/core/test_journal.py
git commit -m "feat: 工作日志（按天聚合）"
```

## Task 8: 计划解析与校验

**Files:**
- Create: `src/kb/core/planning.py`
- Test: `tests/core/test_planning.py`

这是三段式的**第一段（规划）和第二段（校验）**。本模块是**纯函数**——只做只读查询，绝不落盘。校验不过就抛 `PlanError`，此时 vault 一个字节都没动（Q45）。

- [ ] **Step 1: 写失败的测试 `tests/core/test_planning.py`**

```python
import json
from pathlib import Path

import pytest

from kb.core.classify import find_candidates
from kb.core.models import Draft, NoteType, Outcome
from kb.core.planning import (
    PlanError,
    build_messages,
    extract_json,
    parse_plan,
    validate_plan,
)
from kb.core.vault import KNOWLEDGE, ensure_topic_index, write_note

DRAFT = Draft(
    id="20260915-a3f2",
    body="并发写入会锁表，最后用队列串行化解决",
    source="会话",
    project=None,
    created_at="2026-09-15 14:32",
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """一个最小可用的 vault：有一个主题、一个索引页、一个项目。"""
    (tmp_path / KNOWLEDGE / "后端").mkdir(parents=True)
    (tmp_path / "10_项目" / "工作" / "电商后台").mkdir(parents=True)
    ensure_topic_index(tmp_path, "后端")
    write_note(
        tmp_path / KNOWLEDGE / "后端" / "队列串行化.md",
        {"类型": "概念", "主题": ["后端"]},
        "# 队列串行化\n",
    )
    return tmp_path


def _plan_json(**overrides) -> str:
    data = {
        "outcome": "create",
        "target_path": f"{KNOWLEDGE}/后端/并发写锁.md",
        "frontmatter": {"类型": "概念", "主题": ["后端"]},
        "content": "# 并发写锁\n\n见 [[队列串行化]]\n",
        "pending_reason": None,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ---------- JSON 提取 ----------

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_markdown_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_strips_bare_fence():
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_bad_json_raises():
    with pytest.raises(PlanError, match="不是合法 JSON"):
        extract_json("这不是 JSON")


def test_extract_json_rejects_non_object():
    with pytest.raises(PlanError, match="JSON 对象"):
        extract_json("[1, 2, 3]")


# ---------- 解析 ----------

def test_parse_plan_builds_domain_object():
    plan = parse_plan(DRAFT.id, _plan_json())
    assert plan.draft_id == DRAFT.id
    assert plan.outcome is Outcome.CREATE
    assert plan.target_path == f"{KNOWLEDGE}/后端/并发写锁.md"
    assert plan.frontmatter["类型"] == "概念"
    assert plan.content == "# 并发写锁\n\n见 [[队列串行化]]\n"


def test_parse_plan_rejects_unknown_outcome():
    with pytest.raises(PlanError, match="outcome 非法"):
        parse_plan(DRAFT.id, _plan_json(outcome="rewrite"))


def test_parse_plan_rejects_non_object_frontmatter():
    with pytest.raises(PlanError, match="frontmatter"):
        parse_plan(DRAFT.id, _plan_json(frontmatter="不是对象"))


def test_parse_plan_tolerates_absent_optional_fields():
    plan = parse_plan(
        DRAFT.id,
        json.dumps({"outcome": "pending", "pending_reason": "拿不准"}, ensure_ascii=False),
    )
    assert plan.target_path is None
    assert plan.frontmatter == {}


# ---------- 校验：pending ----------

def test_validate_pending_requires_reason(vault):
    plan = parse_plan(DRAFT.id, json.dumps({"outcome": "pending"}))
    with pytest.raises(PlanError, match="pending_reason"):
        validate_plan(plan, vault)


def test_validate_pending_passes_with_reason(vault):
    plan = parse_plan(
        DRAFT.id,
        json.dumps({"outcome": "pending", "pending_reason": "主题不明"}, ensure_ascii=False),
    )
    validate_plan(plan, vault)          # 不抛异常即通过


# ---------- 校验：路径 ----------

def test_validate_create_requires_target_path(vault):
    plan = parse_plan(DRAFT.id, _plan_json(target_path=None))
    with pytest.raises(PlanError, match="target_path"):
        validate_plan(plan, vault)


@pytest.mark.parametrize("bad", ["/etc/passwd", "C:/Windows/x.md", "../../逃逸.md"])
def test_validate_rejects_unsafe_paths(vault, bad):
    plan = parse_plan(DRAFT.id, _plan_json(target_path=bad))
    with pytest.raises(PlanError):
        validate_plan(plan, vault)


def test_validate_rejects_path_outside_allowed_dirs(vault):
    """只允许落在 10_项目/ 或 20_知识/<既有主题>/ 下。"""
    plan = parse_plan(DRAFT.id, _plan_json(target_path="90_附件/x.md"))
    with pytest.raises(PlanError, match="允许范围"):
        validate_plan(plan, vault)


def test_validate_rejects_invented_topic(vault):
    """Q11：AI 不得自行发明分类——新主题必须走 pending。"""
    plan = parse_plan(DRAFT.id, _plan_json(target_path=f"{KNOWLEDGE}/运维/新笔记.md"))
    with pytest.raises(PlanError, match="允许范围"):
        validate_plan(plan, vault)


def test_validate_allows_existing_project_dir(vault):
    plan = parse_plan(
        DRAFT.id,
        _plan_json(
            target_path="10_项目/工作/电商后台/电商后台-踩坑.md",
            frontmatter={"类型": "踩坑", "主题": ["后端"], "项目": "电商后台"},
        ),
    )
    validate_plan(plan, vault)


# ---------- 校验：create ----------

def test_validate_create_rejects_existing_target(vault):
    existing = f"{KNOWLEDGE}/后端/队列串行化.md"
    plan = parse_plan(DRAFT.id, _plan_json(target_path=existing))
    with pytest.raises(PlanError, match="已存在"):
        validate_plan(plan, vault)


@pytest.mark.parametrize("bad_type", ["学习笔记", "知识点", ""])
def test_validate_create_rejects_bad_note_type(vault, bad_type):
    plan = parse_plan(
        DRAFT.id, _plan_json(frontmatter={"类型": bad_type, "主题": ["后端"]})
    )
    with pytest.raises(PlanError, match="类型"):
        validate_plan(plan, vault)


def test_validate_create_rejects_orphan_note(vault):
    """Q21：不允许孤儿笔记——正文必须至少有一个 [[链接]]。"""
    plan = parse_plan(DRAFT.id, _plan_json(content="# 没有链接的笔记\n"))
    with pytest.raises(PlanError, match="双向链接"):
        validate_plan(plan, vault)


def test_validate_create_rejects_link_to_missing_note(vault):
    plan = parse_plan(
        DRAFT.id, _plan_json(content="# 并发写锁\n\n见 [[根本不存在的笔记]]\n")
    )
    with pytest.raises(PlanError, match="根本不存在的笔记"):
        validate_plan(plan, vault)


def test_validate_create_accepts_link_to_index_page(vault):
    """索引页由服务自动创建，所以空库第一天也有东西可链。"""
    plan = parse_plan(DRAFT.id, _plan_json(content="# 并发写锁\n\n见 [[40_索引/后端]]\n"))
    validate_plan(plan, vault)


def test_validate_create_passes_for_good_plan(vault):
    validate_plan(parse_plan(DRAFT.id, _plan_json()), vault)


# ---------- 校验：fold ----------

def test_validate_fold_requires_existing_target(vault):
    plan = parse_plan(
        DRAFT.id,
        _plan_json(outcome="fold", target_path=f"{KNOWLEDGE}/后端/不在这里.md"),
    )
    with pytest.raises(PlanError, match="不存在"):
        validate_plan(plan, vault)


def test_validate_fold_requires_content(vault):
    plan = parse_plan(
        DRAFT.id,
        _plan_json(
            outcome="fold",
            target_path=f"{KNOWLEDGE}/后端/队列串行化.md",
            content="   ",
        ),
    )
    with pytest.raises(PlanError, match="追加的内容"):
        validate_plan(plan, vault)


def test_validate_fold_passes(vault):
    plan = parse_plan(
        DRAFT.id,
        _plan_json(
            outcome="fold",
            target_path=f"{KNOWLEDGE}/后端/队列串行化.md",
            content="补充：队列满时要限流\n",
        ),
    )
    validate_plan(plan, vault)


# ---------- 提示词 ----------

def test_build_messages_includes_draft_body(vault):
    msgs = build_messages(DRAFT, [], [], ["后端"], vault)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "并发写入会锁表" in msgs[1]["content"]


def test_build_messages_lists_topics_and_projects(vault):
    msgs = build_messages(
        DRAFT, [], [("工作", vault / "10_项目" / "工作" / "电商后台")], ["后端"], vault
    )
    assert "后端" in msgs[1]["content"]
    assert "电商后台" in msgs[1]["content"]


def test_build_messages_handles_empty_vault(tmp_path):
    msgs = build_messages(DRAFT, [], [], [], tmp_path)
    assert "没有明显相关的已有笔记" in msgs[1]["content"]
    assert "还没有任何项目文件夹" in msgs[1]["content"]


def test_build_messages_lists_candidates(vault):
    cands = find_candidates(vault, DRAFT.body)
    msgs = build_messages(DRAFT, cands, [], ["后端"], vault)
    assert "队列串行化" in msgs[1]["content"]


def test_system_prompt_lists_allowed_note_types():
    from kb.core.planning import SYSTEM_PROMPT

    for t in NoteType:
        if t in (NoteType.JOURNAL, NoteType.INDEX):
            continue          # 日志与索引页由服务生成，不由 LLM 产出
        assert t.value in SYSTEM_PROMPT
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/core/test_planning.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.core.planning'`

- [ ] **Step 3: 写 `src/kb/core/planning.py`**

````python
"""把 LLM 的输出变成一份经过校验的变更计划。

三段式的第一段（规划）与第二段（校验）都在这。

本模块是**纯函数**——只做只读查询，绝不落盘。校验不过就抛 PlanError，
此时 vault 一个字节都没动（Q45）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kb.core.classify import Candidate, knowledge_topics
from kb.core.models import Draft, NoteType, OrganizePlan, Outcome
from kb.core.vault import INDEX, KNOWLEDGE, PROJECTS, list_notes

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# 日志与索引页由服务生成，不由 LLM 产出——所以不在给模型的允许列表里
_LLM_ALLOWED_TYPES = [
    t.value
    for t in NoteType
    if t not in (NoteType.JOURNAL, NoteType.INDEX)
]

SYSTEM_PROMPT = f"""你是知识库整理助手。你会收到一条待整理的草稿、可能相关的已有笔记、
现有项目清单和知识区主题清单。

你的任务：把草稿整理成一篇正式笔记（create）、合并进已有笔记（fold），
或判断为无法归类（pending）。

**只输出 JSON，不要输出任何其他文字，不要用代码块包裹。**

{{
  "outcome": "create" | "fold" | "pending",
  "target_path": "相对 vault 根的路径",
  "frontmatter": {{"类型": "概念", "主题": ["后端"], "项目": "项目名"}},
  "content": "笔记正文（markdown）",
  "pending_reason": "仅 outcome=pending 时填"
}}

硬规则：
1. target_path 必须落在 `10_项目/<分组>/<项目名>/` 或 `20_知识/<既有主题>/` 下。
2. 类型 只能取：{"、".join(_LLM_ALLOWED_TYPES)}。
3. 主题 只能取「知识区现有主题」里列出的名字。
4. content 必须至少包含一个 [[双向链接]]，指向已有笔记或索引页。
5. create 的目标路径不能已存在；fold 的目标路径必须已存在。
6. 不要发明新的主题分类。都不合适就用 pending，并在 pending_reason 说明原因。
7. 项目笔记的文件名必须带项目前缀，如 `项目名-踩坑.md`，避免 [[链接]] 歧义。
"""


class PlanError(ValueError):
    """计划不合规。校验不过时抛出——此时 vault 未被修改。"""


# ------------------------------------------------------------ 提示词

def _rel(path: Path, vault_root: Path) -> str:
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError:
        return path.as_posix()


def build_messages(
    draft: Draft,
    candidates: list[Candidate],
    projects: list[tuple[str, Path]],
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
        "\n".join(f"- {p.name}（分组：{g}）" for g, p in projects)
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
        {"role": "system", "content": SYSTEM_PROMPT},
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

    if plan.outcome is Outcome.CREATE:
        if target.exists():
            raise PlanError(f"create 的目标已存在，不能覆盖：{plan.target_path}")

        note_type = plan.frontmatter.get("类型")
        if note_type not in {t.value for t in NoteType}:
            raise PlanError(f"类型 非法：{note_type!r}")

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
````

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/core/test_planning.py -v
```

预期：30 passed

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/planning.py tests/core/test_planning.py
git commit -m "feat: 变更计划解析与静态校验"
```

## Task 9: 整理编排（落盘与事务）

**Files:**
- Create: `src/kb/core/organize.py`
- Test: `tests/core/test_organize.py`

编排三段式并负责落盘与 git 提交。**落盘阶段不调 LLM**——这是 Q45 的核心：LLM 只参与前两段（可无限重试），一旦产出计划，写入就是确定性的、可回滚的。

- [ ] **Step 1: 写失败的测试 `tests/core/test_organize.py`**

```python
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from kb.core import organize
from kb.core.models import Draft, ResultKind
from kb.core.vault import (
    INBOX,
    KNOWLEDGE,
    PENDING,
    draft_path,
    list_drafts,
    read_draft,
    read_note,
    write_draft,
    write_note,
)
from kb.llm.base import FakeLLM, LLMError

WHEN = datetime(2026, 9, 15, 14, 32)
NO_SLEEP = staticmethod(lambda _seconds: None)

DRAFT = Draft(
    id="20260915-a3f2",
    body="并发写入会锁表，最后用队列串行化解决",
    source="会话",
    project=None,
    created_at="2026-09-15 14:32",
)


def _plan_json(**overrides) -> str:
    import json

    data = {
        "outcome": "create",
        "target_path": f"{KNOWLEDGE}/后端/并发写锁.md",
        "frontmatter": {"类型": "概念", "主题": ["后端"]},
        "content": "# 并发写锁\n\n见 [[后端]]\n",
        "pending_reason": None,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / KNOWLEDGE / "后端").mkdir(parents=True)
    (tmp_path / "10_项目" / "工作" / "电商后台").mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@x", "commit",
         "--allow-empty", "-m", "init"],
        cwd=tmp_path, capture_output=True,
    )
    return tmp_path


def _run(vault: Path, llm, **kw):
    path = write_draft(vault, DRAFT)
    return organize.organize_draft(vault, path, llm, when=WHEN, sleep=NO_SLEEP, **kw)


# ---------- 成功路径 ----------

def test_create_writes_note_and_removes_draft(vault):
    result, _ = _run(vault, FakeLLM(_plan_json()))

    assert result.kind is ResultKind.CREATED
    note = vault / KNOWLEDGE / "后端" / "并发写锁.md"
    assert note.exists()

    meta, body = read_note(note)
    assert meta["类型"] == "概念"
    assert meta["主题"] == ["后端"]
    assert "见 [[后端]]" in body

    assert list_drafts(vault) == []      # 草稿已消费


def test_create_ensures_topic_index_page(vault):
    """空库第一天：索引页由服务自动建，第一条笔记才有东西可链（Q21）。"""
    _run(vault, FakeLLM(_plan_json()))
    idx = vault / "40_索引" / "后端.md"
    assert idx.exists()
    assert "索引" in idx.read_text(encoding="utf-8")


def test_create_does_not_touch_existing_index_page(vault):
    idx = vault / "40_索引" / "后端.md"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text("用户自己写的", encoding="utf-8")
    _run(vault, FakeLLM(_plan_json()))
    assert idx.read_text(encoding="utf-8") == "用户自己写的"


def test_create_sets_timestamps(vault):
    _run(vault, FakeLLM(_plan_json()))
    meta, _ = read_note(vault / KNOWLEDGE / "后端" / "并发写锁.md")
    assert meta["创建"] == "2026-09-15"
    assert meta["更新"] == "2026-09-15"


def test_fold_appends_to_existing_note(vault):
    target = vault / KNOWLEDGE / "后端" / "队列串行化.md"
    write_note(target, {"类型": "概念", "主题": ["后端"]}, "# 队列串行化\n\n原有内容\n")

    result, _ = _run(
        vault,
        FakeLLM(_plan_json(
            outcome="fold",
            target_path=f"{KNOWLEDGE}/后端/队列串行化.md",
            content="补充：队列满时要限流\n",
        )),
    )

    assert result.kind is ResultKind.FOLDED
    _, body = read_note(target)
    assert "原有内容" in body
    assert "队列满时要限流" in body
    assert list_drafts(vault) == []


def test_fold_bumps_update_date(vault):
    target = vault / KNOWLEDGE / "后端" / "队列串行化.md"
    write_note(target, {"类型": "概念", "更新": "2020-01-01"}, "# 队列串行化\n")

    _run(vault, FakeLLM(_plan_json(
        outcome="fold",
        target_path=f"{KNOWLEDGE}/后端/队列串行化.md",
        content="补充内容\n",
    )))

    meta, _ = read_note(target)
    assert meta["更新"] == "2026-09-15"


def test_pending_moves_draft_aside(vault):
    result, _ = _run(
        vault,
        FakeLLM(_plan_json(outcome="pending", pending_reason="无法判断主题")),
    )

    assert result.kind is ResultKind.PENDING
    assert "无法判断主题" in result.detail
    assert list_drafts(vault)[0].parent.name == PENDING
    assert not (vault / KNOWLEDGE / "后端" / "并发写锁.md").exists()


# ---------- 失败路径（Q45：失败什么也不写）----------

def test_llm_error_leaves_everything_untouched(vault):
    class _Boom:
        def complete(self, system, user):
            raise LLMError("网络炸了")

    result, touched = _run(vault, _Boom())

    assert result.kind is ResultKind.FAILED
    assert "网络炸了" in result.error
    assert touched == []
    assert len(list_drafts(vault)) == 1          # 草稿原样留着，下次还能重试
    assert not (vault / KNOWLEDGE / "后端" / "并发写锁.md").exists()


def test_invalid_plan_leaves_everything_untouched(vault):
    result, touched = _run(vault, FakeLLM(_plan_json(target_path="90_附件/x.md")))

    assert result.kind is ResultKind.FAILED
    assert touched == []
    assert not (vault / "90_附件" / "x.md").exists()


def test_orphan_plan_is_rejected_and_nothing_written(vault):
    result, _ = _run(vault, FakeLLM(_plan_json(content="# 没有链接\n")))
    assert result.kind is ResultKind.FAILED
    assert not (vault / KNOWLEDGE / "后端" / "并发写锁.md").exists()


def test_bad_json_then_valid_json_succeeds(vault):
    """格式不合规时把错误喂回去重试——第二次成功。"""
    llm = FakeLLM(["这不是 JSON", _plan_json()])
    result, _ = _run(vault, llm)

    assert result.kind is ResultKind.CREATED
    assert len(llm.calls) == 2
    assert "不是合法 JSON" in llm.calls[1][1]     # 错误信息回喂进了第二次提示


def test_gives_up_after_max_attempts(vault):
    llm = FakeLLM("永远不是 JSON")
    result, _ = _run(vault, llm)
    assert result.kind is ResultKind.FAILED
    assert len(llm.calls) == organize.MAX_ATTEMPTS


def test_failure_reason_prevents_silent_loss(vault):
    """失败必须留下原因——不然用户不知道东西为什么卡在收件箱。"""
    result, _ = _run(vault, FakeLLM("坏输出"))
    assert result.error
    assert result.detail


# ---------- 事务回滚 ----------

def test_rollback_restores_vault_on_write_failure(vault, monkeypatch):
    """落盘中途失败 → 精确回滚，且不动用户未提交的改动。"""
    untouched = vault / KNOWLEDGE / "后端" / "用户手写的.md"
    write_note(untouched, {"类型": "概念"}, "# 用户手写的\n")

    def _boom(*a, **kw):
        raise OSError("磁盘满了")

    monkeypatch.setattr(organize, "_write_note_safe", _boom)

    result, _ = _run(vault, FakeLLM(_plan_json()))

    assert result.kind is ResultKind.FAILED
    assert "磁盘满了" in result.error
    assert not (vault / KNOWLEDGE / "后端" / "并发写锁.md").exists()
    assert untouched.read_text(encoding="utf-8").startswith("---")


def test_rollback_does_not_revert_user_changes(vault, monkeypatch):
    """Q45：禁用 `git checkout .`——那会连用户未提交的改动一起还原。"""
    user_file = vault / KNOWLEDGE / "后端" / "用户手写的.md"
    write_note(user_file, {"类型": "概念"}, "# 原始\n")
    user_file.write_text("用户刚改的内容", encoding="utf-8")   # 未提交

    monkeypatch.setattr(
        organize, "_write_note_safe",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("炸")),
    )
    _run(vault, FakeLLM(_plan_json()))

    assert user_file.read_text(encoding="utf-8") == "用户刚改的内容"


# ---------- 批量与隔离 ----------

def test_organize_all_isolates_failures(vault):
    """Q45：10 条里 1 条判不了，不该拖垮另外 9 条。"""
    write_draft(vault, Draft(id="20260915-0001", body="第一条", source=None,
                             project=None, created_at="2026-09-15 14:32"))
    write_draft(vault, Draft(id="20260915-0002", body="第二条", source=None,
                             project=None, created_at="2026-09-15 14:32"))

    llm = FakeLLM([_plan_json(), "坏输出"])      # 第一条好，第二条坏
    results = organize.organize_all(vault, llm, when=WHEN, sleep=NO_SLEEP, commit=False)

    kinds = [r.kind for r in results]
    assert ResultKind.CREATED in kinds
    assert ResultKind.FAILED in kinds
    assert len(list_drafts(vault)) == 1          # 失败的那条还留着


def test_organize_all_returns_empty_for_empty_inbox(vault):
    assert organize.organize_all(vault, FakeLLM(_plan_json()), commit=False) == []


# ---------- git ----------

def test_commit_message_lists_changes(vault):
    results, _ = organize.organize_draft(
        vault, write_draft(vault, DRAFT), FakeLLM(_plan_json()), when=WHEN, sleep=NO_SLEEP
    )
    msg = organize.build_commit_message([results])
    assert "整理草稿 1 条" in msg
    assert "新建" in msg


def test_commit_message_mentions_pending_and_failed():
    from kb.core.models import OrganizeResult

    msg = organize.build_commit_message([
        OrganizeResult("a", ResultKind.PENDING, "归不了"),
        OrganizeResult("b", ResultKind.FAILED, "炸了"),
    ])
    assert "待归类 1 条" in msg
    assert "失败 1 条" in msg


def test_commit_uses_service_author(vault):
    """Q46：服务用独立 author，便于分出「AI 写的」和「我写的」。"""
    path = write_draft(vault, DRAFT)
    result, touched = organize.organize_draft(
        vault, path, FakeLLM(_plan_json()), when=WHEN, sleep=NO_SLEEP
    )
    organize.commit_changes(vault, touched, [result], WHEN)

    out = subprocess.run(
        ["git", "log", "-1", "--format=%an <%ae>"],
        cwd=vault, capture_output=True, text=True,
    )
    assert "kb-service" in out.stdout


def test_commit_only_stages_touched_files(vault):
    """Q46：禁用 `git add -A`，否则会把用户未提交的编辑裹进来。"""
    user_file = vault / KNOWLEDGE / "后端" / "用户手写的.md"
    write_note(user_file, {"类型": "概念"}, "# 用户手写的\n")

    path = write_draft(vault, DRAFT)
    result, touched = organize.organize_draft(
        vault, path, FakeLLM(_plan_json()), when=WHEN, sleep=NO_SLEEP
    )
    organize.commit_changes(vault, touched, [result], WHEN)

    staged = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=vault, capture_output=True, text=True,
    ).stdout
    assert "用户手写的.md" not in staged
    assert "并发写锁.md" in staged


def test_commit_returns_false_when_nothing_touched(vault):
    assert organize.commit_changes(vault, [], [], WHEN) is False


def test_full_run_writes_journal_and_commits(vault):
    write_draft(vault, DRAFT)
    organize.organize_all(vault, FakeLLM(_plan_json()), when=WHEN, sleep=NO_SLEEP)

    journal = vault / "40_索引" / "整理日志" / "2026-09-15.md"
    assert journal.exists()
    assert "新建" in journal.read_text(encoding="utf-8")
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/core/test_organize.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.core.organize'`

- [ ] **Step 3: 写 `src/kb/core/organize.py`**

````python
"""整理编排：三段式的第三段（落盘）与整体调度。

① 规划：build_messages → llm.complete → parse_plan
② 校验：validate_plan（纯静态，不过就打回，vault 未动）
③ 落盘：本模块。**不调 LLM**，纯文件操作，确定、快、可回滚

按条隔离（Q45）：一条失败不影响其他条，失败那条什么也不写（所以重试天然幂等）。
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path

from kb.core import planning
from kb.core.classify import find_candidates, knowledge_topics
from kb.core.journal import append_results
from kb.core.models import (
    Draft,
    OrganizePlan,
    OrganizeResult,
    Outcome,
    ResultKind,
)
from kb.core.planning import PlanError
from kb.core.vault import (
    INBOX,
    PENDING,
    ensure_topic_index,
    list_drafts,
    list_projects,
    move_to_pending,
    read_draft,
    read_note,
    topic_index_path,
    write_note,
)
from kb.llm.base import LLM, LLMError

SERVICE_AUTHOR_NAME = "kb-service"
SERVICE_AUTHOR_EMAIL = "kb-service@localhost"

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2)


# ------------------------------------------------------------ 事务

class Transaction:
    """记录本次操作动过的文件，失败时**精确**回滚（Q45）。

    绝不能用 `git checkout .`——那会把用户尚未提交的改动一起还原掉。
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root
        self._originals: dict[Path, bytes | None] = {}

    def _remember(self, path: Path) -> None:
        if path not in self._originals:
            self._originals[path] = path.read_bytes() if path.exists() else None

    def touch_create(self, path: Path) -> None:
        self._remember(path)

    def touch_modify(self, path: Path) -> None:
        self._remember(path)

    def touch_delete(self, path: Path) -> None:
        self._remember(path)

    @property
    def touched(self) -> list[Path]:
        return sorted(self._originals)

    def rollback(self) -> None:
        for path, original in self._originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)


# ------------------------------------------------------------ 落盘辅助

def _write_note_safe(path: Path, meta: dict, body: str) -> None:
    """单独抽出来便于测试注入失败。"""
    write_note(path, meta, body)


def _today(when: datetime | None) -> str:
    return f"{(when or datetime.now()):%Y-%m-%d}"


def _ensure_indexes(vault_root: Path, plan: OrganizePlan, txn: Transaction) -> None:
    """确保引用的主题索引页存在——让第一条笔记就有东西可链（Q21）。"""
    topics = plan.frontmatter.get("主题") or []
    if isinstance(topics, str):
        topics = [topics]

    known = set(knowledge_topics(vault_root))
    for topic in topics:
        if topic not in known:
            continue
        idx = topic_index_path(vault_root, topic)
        if not idx.exists():
            txn.touch_create(idx)
            ensure_topic_index(vault_root, topic)


# ------------------------------------------------------------ 第三段：落盘

def apply_plan(
    vault_root: Path,
    draft_path: Path,
    plan: OrganizePlan,
    txn: Transaction,
    when: datetime | None = None,
) -> OrganizeResult:
    """按计划落盘。不调 LLM——所以慢不了，也几乎不会失败。"""
    if plan.outcome is Outcome.PENDING:
        move_to_pending(vault_root, draft_path)
        return OrganizeResult(
            draft_id=plan.draft_id,
            kind=ResultKind.PENDING,
            detail=plan.pending_reason or "无法归类",
        )

    assert plan.target_path is not None      # 已在 validate_plan 保证
    target = vault_root / plan.target_path

    if plan.outcome is Outcome.CREATE:
        txn.touch_create(target)
        meta = dict(plan.frontmatter)
        meta.setdefault("创建", _today(when))
        meta["更新"] = _today(when)
        _write_note_safe(target, meta, plan.content)
        _ensure_indexes(vault_root, plan, txn)
        kind = ResultKind.CREATED
    else:
        txn.touch_modify(target)
        meta, body = read_note(target)
        meta["更新"] = _today(when)
        body = body.rstrip("\n") + "\n\n" + plan.content.strip() + "\n"
        _write_note_safe(target, meta, body)
        kind = ResultKind.FOLDED

    txn.touch_delete(draft_path)
    draft_path.unlink(missing_ok=True)

    return OrganizeResult(
        draft_id=plan.draft_id,
        kind=kind,
        detail=f"[[{target.stem}]]（{plan.target_path}）",
    )


# ------------------------------------------------------------ 第一、二段：规划

def _complete(
    vault_root: Path, draft: Draft, llm: LLM, hint: str | None
) -> str:
    messages = planning.build_messages(
        draft,
        find_candidates(vault_root, draft.body),
        list_projects(vault_root),
        knowledge_topics(vault_root),
        vault_root,
    )
    user = messages[1]["content"]
    if hint:
        user += f"\n\n## 上次尝试失败的原因\n{hint}\n请修正后重新只输出 JSON。"
    return llm.complete(messages[0]["content"], user)


def make_plan(
    vault_root: Path,
    draft: Draft,
    llm: LLM,
    sleep=time.sleep,
    max_attempts: int = MAX_ATTEMPTS,
) -> OrganizePlan:
    """规划 + 校验。任一环节失败都抛 PlanError / LLMError。"""
    hint: str | None = None
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        if attempt:
            sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
        try:
            raw = _complete(vault_root, draft, llm, hint)
            plan = planning.parse_plan(draft.id, raw)
            planning.validate_plan(plan, vault_root)
            return plan
        except LLMError as exc:
            last_error = exc                       # 网络类：直接重试
        except PlanError as exc:
            last_error = exc
            hint = str(exc)                        # 格式类：把错误喂回去让它自己修

    raise PlanError(f"规划失败（尝试 {max_attempts} 次）：{last_error}")


# ------------------------------------------------------------ 单条编排

def organize_draft(
    vault_root: Path,
    draft_path: Path,
    llm: LLM,
    when: datetime | None = None,
    sleep=time.sleep,
) -> tuple[OrganizeResult, list[Path]]:
    """整理一条草稿。返回 (结果, 本次动过的文件)。"""
    draft = read_draft(draft_path)

    try:
        plan = make_plan(vault_root, draft, llm, sleep=sleep)
    except (PlanError, LLMError) as exc:
        return (
            OrganizeResult(
                draft_id=draft.id,
                kind=ResultKind.FAILED,
                detail="规划失败",
                error=str(exc),
            ),
            [],
        )

    txn = Transaction(vault_root)
    try:
        result = apply_plan(vault_root, draft_path, plan, txn, when)
    except Exception as exc:                              # noqa: BLE001
        txn.rollback()
        return (
            OrganizeResult(
                draft_id=draft.id,
                kind=ResultKind.FAILED,
                detail="落盘失败，已回滚",
                error=str(exc),
            ),
            [],
        )

    return result, txn.touched


# ------------------------------------------------------------ 批量编排

def organize_all(
    vault_root: Path,
    llm: LLM,
    when: datetime | None = None,
    sleep=time.sleep,
    commit: bool = True,
) -> list[OrganizeResult]:
    """整理收件箱里的全部草稿（含待归类），按条隔离。"""
    when = when or datetime.now()
    results: list[OrganizeResult] = []
    touched: list[Path] = []

    for path in list_drafts(vault_root):
        result, paths = organize_draft(vault_root, path, llm, when, sleep)
        results.append(result)
        touched.extend(paths)

    if not results:
        return results

    journal_path = append_results(vault_root, results, when)
    if journal_path is not None:
        touched.append(journal_path)

    if commit:
        commit_changes(vault_root, touched, results, when)

    return results


# ------------------------------------------------------------ git（Q46）

def build_commit_message(
    results: list[OrganizeResult], when: datetime | None = None
) -> str:
    ok = [r for r in results if r.kind in (ResultKind.CREATED, ResultKind.FOLDED)]
    lines = [f"整理草稿 {len(ok)} 条", ""]

    for r in ok:
        verb = "新建" if r.kind is ResultKind.CREATED else "合并入"
        lines.append(f"- {verb} {r.detail}")

    pending = sum(1 for r in results if r.kind is ResultKind.PENDING)
    failed = sum(1 for r in results if r.kind is ResultKind.FAILED)
    if pending:
        lines.append(f"- 待归类 {pending} 条")
    if failed:
        lines.append(f"- 失败 {failed} 条")

    return "\n".join(lines).rstrip() + "\n"


def _git(vault_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=vault_root, capture_output=True, text=True
    )


def commit_changes(
    vault_root: Path,
    touched: list[Path],
    results: list[OrganizeResult],
    when: datetime | None = None,
) -> bool:
    """一次整理 = 一个 commit（Q46）。

    **只 add 自己动过的文件**——禁用 `git add -A`，否则会把用户正在编辑、
    尚未提交的笔记一起裹进这次「AI 整理」的 commit，历史就骗人了。
    """
    rels: list[str] = []
    for path in touched:
        try:
            rels.append(path.relative_to(vault_root).as_posix())
        except ValueError:
            continue

    if not rels:
        return False

    _git(vault_root, "add", "--", *rels)
    proc = _git(
        vault_root,
        "-c", f"user.name={SERVICE_AUTHOR_NAME}",
        "-c", f"user.email={SERVICE_AUTHOR_EMAIL}",
        "commit", "-m", build_commit_message(results, when),
    )
    return proc.returncode == 0
````

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/core/test_organize.py -v
```

预期：24 passed

- [ ] **Step 5: 跑全部测试**

```bash
pytest -v
```

预期：全绿

- [ ] **Step 6: 提交**

```bash
git add src/kb/core/organize.py tests/core/test_organize.py
git commit -m "feat: 整理编排（三段式、事务回滚、单提交）"
```

## Task 10: 运行时文件与服务拉起

**Files:**
- Create: `src/kb/api/__init__.py`
- Create: `src/kb/api/runtime.py`
- Test: `tests/api/test_runtime.py`

实现 Q49 定的机制：服务把端口写进 `runtime/service.json`，CLI 读它探测。没跑就**自动后台拉起**（Q39），用户无感。

- [ ] **Step 1: 写失败的测试 `tests/api/test_runtime.py`**

```python
import json
import socket
from pathlib import Path

import pytest

from kb.api import runtime


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path: Path):
    """把运行时目录指到临时目录，避免污染真实工程。"""
    monkeypatch.setattr(runtime, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(runtime, "SERVICE_FILE", tmp_path / "runtime" / "service.json")


def test_find_free_port_returns_bindable_port():
    port = runtime.find_free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))      # 不抛异常即可用
    assert 1024 < port < 65536


def test_service_info_roundtrip():
    runtime.write_service_info(51723)
    info = runtime.read_service_info()
    assert info["port"] == 51723
    assert "pid" in info and "started" in info


def test_read_service_info_absent_returns_none():
    assert runtime.read_service_info() is None


def test_read_service_info_corrupt_returns_none():
    runtime.SERVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    runtime.SERVICE_FILE.write_text("不是 JSON", encoding="utf-8")
    assert runtime.read_service_info() is None


def test_clear_service_info_removes_file():
    runtime.write_service_info(1234)
    runtime.clear_service_info()
    assert runtime.read_service_info() is None


def test_clear_service_info_is_idempotent():
    runtime.clear_service_info()          # 不存在也不该抛


def test_is_alive_false_for_unused_port():
    port = runtime.find_free_port()
    assert runtime.is_alive(port) is False


def test_is_alive_true_for_listening_socket():
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert runtime.is_alive(port) is True


def test_running_port_none_without_file():
    assert runtime.running_port() is None


def test_running_port_ignores_dead_service():
    """文件在但端口不通（服务崩了）→ 视为没跑，触发重新拉起。"""
    runtime.write_service_info(runtime.find_free_port())
    assert runtime.running_port() is None


def test_ensure_service_reuses_running_one(monkeypatch):
    port = runtime.find_free_port()
    runtime.write_service_info(port)
    monkeypatch.setattr(runtime, "is_alive", lambda p, timeout=0.5: True)

    spawned = []
    monkeypatch.setattr(runtime, "spawn_service", lambda p: spawned.append(p))

    cfg = type("C", (), {"port": None})()
    assert runtime.ensure_service(cfg) == port
    assert spawned == []                  # 已在跑，不该再拉起


def test_ensure_service_spawns_when_absent(monkeypatch):
    started = {"alive": False}

    def _spawn(port):
        started["alive"] = True
        started["port"] = port

    monkeypatch.setattr(runtime, "spawn_service", _spawn)
    monkeypatch.setattr(runtime, "is_alive", lambda p, timeout=0.5: started["alive"])

    cfg = type("C", (), {"port": 51999})()
    assert runtime.ensure_service(cfg) == 51999
    assert started["port"] == 51999


def test_ensure_service_times_out(monkeypatch):
    monkeypatch.setattr(runtime, "spawn_service", lambda p: None)
    monkeypatch.setattr(runtime, "is_alive", lambda p, timeout=0.5: False)
    monkeypatch.setattr(runtime, "STARTUP_TIMEOUT", 0.3)
    monkeypatch.setattr(runtime, "POLL_INTERVAL", 0.05)

    cfg = type("C", (), {"port": 52000})()
    with pytest.raises(RuntimeError, match="超时"):
        runtime.ensure_service(cfg)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/api/test_runtime.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.api.runtime'`

- [ ] **Step 3: 建包文件**

```bash
mkdir -p tests/api
touch tests/api/__init__.py src/kb/api/__init__.py
```

- [ ] **Step 4: 写 `src/kb/api/runtime.py`**

```python
"""运行时文件与服务的自动拉起（Q39 / Q49）。

服务启动后把端口写进 `runtime/service.json`，CLI 读它去探测：
通就直接投递；不通就后台拉起服务、等它就绪、再投递。

对用户是「按需启动」，对调用方是无感的（Q39）——不用管服务开没开，也不用开机常驻。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from kb.config import Config, PROJECT_ROOT

RUNTIME_DIR = PROJECT_ROOT / "runtime"
SERVICE_FILE = RUNTIME_DIR / "service.json"

STARTUP_TIMEOUT = 15.0
POLL_INTERVAL = 0.2


def find_free_port() -> int:
    """让操作系统分配一个空闲端口（Q40：自动寻找未占用的端口）。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def write_service_info(port: int, pid: int | None = None) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    SERVICE_FILE.write_text(
        json.dumps(
            {
                "port": port,
                "pid": pid if pid is not None else os.getpid(),
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return SERVICE_FILE


def read_service_info() -> dict | None:
    if not SERVICE_FILE.exists():
        return None
    try:
        return json.loads(SERVICE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def clear_service_info() -> None:
    SERVICE_FILE.unlink(missing_ok=True)


def is_alive(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def running_port() -> int | None:
    """读到端口、且端口真的通，才算在跑。服务崩了要能重新拉起。"""
    info = read_service_info()
    if not info:
        return None
    port = info.get("port")
    if isinstance(port, int) and is_alive(port):
        return port
    return None


def spawn_service(port: int) -> subprocess.Popen:
    """后台拉起服务，与当前进程解耦——关掉 CLI 后服务继续跑。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PROJECT_ROOT / "src"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    return subprocess.Popen(
        [sys.executable, "-m", "kb.api.http", "--port", str(port)],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=(sys.platform != "win32"),
    )


def ensure_service(cfg: Config) -> int:
    """返回可用服务的端口；没跑就拉起来并等它就绪。"""
    port = running_port()
    if port is not None:
        return port

    port = cfg.port or find_free_port()
    spawn_service(port)

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if is_alive(port):
            return port
        time.sleep(POLL_INTERVAL)

    raise RuntimeError(
        f"服务启动超时（{STARTUP_TIMEOUT} 秒）。查看 logs/ 排查。"
    )
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/api/test_runtime.py -v
```

预期：13 passed

- [ ] **Step 6: 提交**

```bash
git add src/kb/api/__init__.py src/kb/api/runtime.py tests/api
git commit -m "feat: 运行时文件与服务自动拉起"
```

---

## Task 11: HTTP 服务

**Files:**
- Create: `src/kb/api/http.py`
- Test: `tests/api/test_http.py`

**薄层**——只做协议转换，不含判断逻辑（Q33）。所有写入都经这里，所以写入天然串行（Q29）。

- [ ] **Step 1: 写失败的测试 `tests/api/test_http.py`**

```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kb.api.http import create_app
from kb.config import Config
from kb.core.vault import INBOX, KNOWLEDGE, list_drafts, read_draft
from kb.llm.base import FakeLLM


def _plan_json(**overrides) -> str:
    data = {
        "outcome": "create",
        "target_path": f"{KNOWLEDGE}/后端/并发写锁.md",
        "frontmatter": {"类型": "概念", "主题": ["后端"]},
        "content": "# 并发写锁\n\n见 [[后端]]\n",
        "pending_reason": None,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


@pytest.fixture
def client(tmp_path: Path):
    (tmp_path / KNOWLEDGE / "后端").mkdir(parents=True)
    cfg = Config(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        vault_path=tmp_path,
        port=None,
    )
    return TestClient(create_app(cfg, llm=FakeLLM(_plan_json())))


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_push_creates_draft(client, tmp_path):
    resp = client.post(
        "/push",
        json={"content": "并发写入会锁表", "project": "电商后台", "source": "会话"},
    )
    assert resp.status_code == 200
    draft_id = resp.json()["id"]

    drafts = list_drafts(tmp_path)
    assert len(drafts) == 1
    assert read_draft(drafts[0]).id == draft_id
    assert read_draft(drafts[0]).project == "电商后台"


def test_push_returns_immediately_without_organizing(client, tmp_path):
    """异步（Q55）：投递只落草稿，不做任何整理。"""
    client.post("/push", json={"content": "内容"})
    assert not (tmp_path / KNOWLEDGE / "后端" / "并发写锁.md").exists()
    assert (tmp_path / INBOX).exists()


def test_push_rejects_empty_content(client):
    resp = client.post("/push", json={"content": "   "})
    assert resp.status_code == 400
    assert "不能为空" in resp.json()["detail"]


def test_push_accepts_content_without_project(client):
    """Q30：允许没有项目——纯知识点场景。"""
    resp = client.post("/push", json={"content": "GIL 是怎么回事"})
    assert resp.status_code == 200


def test_inbox_lists_drafts(client):
    client.post("/push", json={"content": "第一条"})
    client.post("/push", json={"content": "第二条"})

    data = client.get("/inbox").json()
    assert data["count"] == 2
    assert {item["preview"] for item in data["items"]} == {"第一条", "第二条"}


def test_inbox_empty(client):
    assert client.get("/inbox").json() == {"count": 0, "items": []}


def test_organize_all(client, tmp_path):
    client.post("/push", json={"content": "并发写入会锁表"})
    resp = client.post("/organize", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["kind"] == "created"
    assert (tmp_path / KNOWLEDGE / "后端" / "并发写锁.md").exists()
    assert list_drafts(tmp_path) == []


def test_organize_single_by_id(client, tmp_path):
    first = client.post("/push", json={"content": "第一条"}).json()["id"]
    client.post("/push", json={"content": "第二条"})

    resp = client.post("/organize", json={"draft_id": first})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1
    assert len(list_drafts(tmp_path)) == 1        # 第二条还在


def test_organize_unknown_id_returns_404(client):
    resp = client.post("/organize", json={"draft_id": "不存在"})
    assert resp.status_code == 404


def test_organize_reports_failures(client, tmp_path):
    from kb.api.http import create_app
    from kb.llm.base import FakeLLM as F

    cfg = Config("k", "u", "m", tmp_path, None)
    bad = TestClient(create_app(cfg, llm=F("坏输出")))
    bad.post("/push", json={"content": "内容"})

    body = bad.post("/organize", json={}).json()
    assert body["results"][0]["kind"] == "failed"
    assert body["results"][0]["error"]
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/api/test_http.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.api.http'`

- [ ] **Step 3: 写 `src/kb/api/http.py`**

```python
"""HTTP 接口层——薄层，只做协议转换，不含判断逻辑（Q33）。

所有写入都经过这里：CLI 和 MCP 都调这个服务，不直接碰文件。
于是写入天然串行化，不会出现两份逻辑打架（Q29）。

直接运行即启动服务：

    python -m kb.api.http --port 51723
"""

from __future__ import annotations

import argparse
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from kb.api import runtime
from kb.config import Config, load_config
from kb.core import organize
from kb.core.models import Draft
from kb.core.vault import (
    PENDING,
    find_draft,
    list_drafts,
    new_draft_id,
    read_draft,
    write_draft,
)
from kb.llm.base import LLM
from kb.llm.providers.openai_compat import OpenAICompatLLM


class PushRequest(BaseModel):
    content: str
    project: str | None = None
    source: str | None = None


class OrganizeRequest(BaseModel):
    draft_id: str | None = None


def build_llm(cfg: Config) -> LLM:
    return OpenAICompatLLM(
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
    )


def _result_payload(result) -> dict:
    return {
        "draft_id": result.draft_id,
        "kind": result.kind.value,
        "detail": result.detail,
        "error": result.error,
    }


def create_app(cfg: Config | None = None, llm: LLM | None = None) -> FastAPI:
    cfg = cfg or load_config()
    cache: dict[str, LLM | None] = {"llm": llm}

    def get_llm() -> LLM:
        if cache["llm"] is None:
            cache["llm"] = build_llm(cfg)
        return cache["llm"]

    app = FastAPI(title="KN_Base 知识库服务")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/push")
    def push(req: PushRequest) -> dict:
        """投递一条草稿。异步——立刻返回，不做整理（Q55）。"""
        body = req.content.strip()
        if not body:
            raise HTTPException(status_code=400, detail="正文不能为空")

        draft = Draft(
            id=new_draft_id(),
            body=body + "\n",
            source=req.source,
            project=req.project,
            created_at=f"{datetime.now():%Y-%m-%d %H:%M}",
        )
        write_draft(cfg.vault_path, draft)
        return {"id": draft.id}

    @app.get("/inbox")
    def inbox() -> dict:
        items = []
        for path in list_drafts(cfg.vault_path):
            draft = read_draft(path)
            items.append(
                {
                    "id": draft.id,
                    "project": draft.project,
                    "source": draft.source,
                    "created_at": draft.created_at,
                    "preview": draft.body.strip().splitlines()[0][:80]
                    if draft.body.strip()
                    else "",
                    "pending": path.parent.name == PENDING,
                }
            )
        return {"count": len(items), "items": items}

    @app.post("/organize")
    def run_organize(req: OrganizeRequest) -> dict:
        if req.draft_id:
            path = find_draft(cfg.vault_path, req.draft_id)
            if path is None:
                raise HTTPException(
                    status_code=404, detail=f"找不到草稿 {req.draft_id}"
                )
            result, _ = organize.organize_draft(cfg.vault_path, path, get_llm())
            results = [result]
            touched = []
            journal = organize.append_results(cfg.vault_path, results, None)
            if journal is not None:
                touched.append(journal)
            organize.commit_changes(cfg.vault_path, touched, results, None)
        else:
            results = organize.organize_all(cfg.vault_path, get_llm())

        return {"count": len(results), "results": [_result_payload(r) for r in results]}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="KN_Base 知识库服务")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    import uvicorn

    cfg = load_config()
    port = args.port or cfg.port or runtime.find_free_port()

    runtime.write_service_info(port)
    try:
        uvicorn.run(create_app(cfg), host="127.0.0.1", port=port, log_level="info")
    finally:
        runtime.clear_service_info()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/api/test_http.py -v
```

预期：12 passed

- [ ] **Step 5: 提交**

```bash
git add src/kb/api/http.py tests/api/test_http.py
git commit -m "feat: HTTP 接口（投递、收件箱、整理）"
```

## Task 12: CLI

**Files:**
- Create: `src/kb/api/cli.py`
- Create: `kb.bat`（Windows 快捷入口）
- Test: `tests/api/test_cli.py`

CLI 是**最通用的一层**（Q28）——「能跑 shell」几乎是所有 agent harness 的底线能力。CLI 自己不碰文件，所有写入走 HTTP 打到服务进程（Q29）。

- [ ] **Step 1: 写失败的测试 `tests/api/test_cli.py`**

```python
import json
from pathlib import Path

import httpx
import pytest

from kb.api import cli
from kb.config import Config


class _Args:
    def __init__(self, **kw):
        self.content = kw.get("content")
        self.file = kw.get("file")
        self.project = kw.get("project")
        self.source = kw.get("source")
        self.draft_id = kw.get("draft_id")


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config("k", "u", "m", tmp_path, None)


@pytest.fixture
def fake_server(monkeypatch, cfg):
    """把 http 请求接到内存里的假服务上。"""
    import subprocess

    from fastapi.testclient import TestClient

    from kb.api.http import create_app
    from kb.core.vault import KNOWLEDGE
    from kb.llm.base import FakeLLM

    (cfg.vault_path / KNOWLEDGE / "后端").mkdir(parents=True, exist_ok=True)
    plan = json.dumps(
        {
            "outcome": "create",
            "target_path": f"{KNOWLEDGE}/后端/并发写锁.md",
            "frontmatter": {"类型": "概念", "主题": ["后端"]},
            "content": "# 并发写锁\n\n见 [[后端]]\n",
            "pending_reason": None,
        },
        ensure_ascii=False,
    )
    app = create_app(cfg, llm=FakeLLM(plan))
    transport = httpx.ASGITransport(app=app)

    def _make_client(_cfg):
        return httpx.Client(
            transport=transport, base_url="http://testserver", timeout=60.0
        )

    monkeypatch.setattr(cli, "make_client", _make_client)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    subprocess.run(["git", "init", "-b", "main"], cwd=cfg.vault_path,
                   capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@x", "commit",
         "--allow-empty", "-m", "init"],
        cwd=cfg.vault_path, capture_output=True,
    )
    return cfg


# ---------- 纯函数 ----------

def test_read_content_prefers_flag(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.read_content(_Args(content="直接给的")) == "直接给的"


def test_read_content_from_file(tmp_path):
    f = tmp_path / "content.txt"
    f.write_text("文件里的内容", encoding="utf-8")
    assert cli.read_content(_Args(file=str(f))) == "文件里的内容"


def test_read_content_from_stdin(monkeypatch):
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO("管道过来的内容"))
    assert cli.read_content(_Args()) == "管道过来的内容"


def test_read_content_empty_when_nothing(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "stdin", type("T", (), {"isatty": lambda self: True})())
    assert cli.read_content(_Args()) == ""


def test_default_project_uses_git_root(tmp_path, monkeypatch):
    """Q30：取 git 根的目录名，避免停在子目录时取到 core。"""
    subprocess_run = __import__("subprocess").run
    subprocess_run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
    deep = tmp_path / "src" / "kb" / "core"
    deep.mkdir(parents=True)

    from kb.core.vault import project_name_from_cwd

    assert project_name_from_cwd(deep) == tmp_path.name


# ---------- 端到端（假服务）----------

def test_push_then_inbox_then_organize(fake_server, capsys):
    assert cli.main(["push", "--content", "并发写入会锁表", "--project", "电商后台"]) == 0
    out = capsys.readouterr().out
    assert "已收，id=" in out

    assert cli.main(["inbox"]) == 0
    assert "并发写入会锁表" in capsys.readouterr().out

    assert cli.main(["organize"]) == 0
    assert "created" in capsys.readouterr().out

    note = fake_server.vault_path / "20_知识" / "后端" / "并发写锁.md"
    assert note.exists()


def test_push_rejects_empty(fake_server, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert cli.main(["push"]) == 2
    assert "正文为空" in capsys.readouterr().err


def test_inbox_empty_message(fake_server, capsys):
    assert cli.main(["inbox"]) == 0
    assert "收件箱是空的" in capsys.readouterr().out


def test_organize_reports_nothing_to_do(fake_server, capsys):
    assert cli.main(["organize"]) == 0
    assert "没有待整理的草稿" in capsys.readouterr().out


def test_status_shows_service(fake_server, capsys):
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "在运行" in out or "服务" in out
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/api/test_cli.py -v
```

预期：`ModuleNotFoundError: No module named 'kb.api.cli'`

- [ ] **Step 3: 写 `src/kb/api/cli.py`**

```python
"""命令行接口（Q28）。

**CLI 是最通用的一层**——「能跑 shell」几乎是所有 agent harness 的底线能力，
比 MCP 的覆盖面广得多。

CLI 自己不碰文件：所有写入都走 HTTP 打到服务进程，服务没跑就自动拉起（Q29/Q39）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from kb.api import runtime
from kb.config import Config, ConfigError, load_config

TIMEOUT = 600.0          # 整理要调 LLM，给足时间


def make_client(cfg: Config) -> httpx.Client:
    """建立到服务进程的连接。服务没跑就拉起来（Q39）。"""
    port = runtime.ensure_service(cfg)
    return httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=TIMEOUT)


def read_content(args) -> str:
    """正文来源优先级：--content > --file > stdin。"""
    if getattr(args, "content", None):
        return args.content
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def default_project() -> str | None:
    """Q30：默认取 **git 仓库根**的目录名，不是 cwd 的 basename。

    用 git 根是因为 agent 可能停在子目录（如 `src/kb/core/`），
    那样 basename 会取到 `core`，挂错项目。
    """
    from kb.core.vault import project_name_from_cwd

    return project_name_from_cwd(Path.cwd())


# ------------------------------------------------------------ 命令

def cmd_push(args) -> int:
    cfg = load_config()
    content = read_content(args).strip()
    if not content:
        print("正文为空。用 --content / --file 传入，或从 stdin 管道输入。", file=sys.stderr)
        return 2

    project = args.project if args.project is not None else default_project()

    with make_client(cfg) as client:
        resp = client.post(
            "/push",
            json={"content": content, "project": project, "source": args.source},
        )
        resp.raise_for_status()
        print(f"已收，id={resp.json()['id']}")
    return 0


def cmd_inbox(args) -> int:
    cfg = load_config()
    with make_client(cfg) as client:
        data = client.get("/inbox").raise_for_status().json()

    if not data["count"]:
        print("收件箱是空的。")
        return 0

    print(f"收件箱：{data['count']} 条待整理")
    for item in data["items"]:
        flags = []
        if item["pending"]:
            flags.append("待归类")
        if item["project"]:
            flags.append(item["project"])
        suffix = f"  [{'｜'.join(flags)}]" if flags else ""
        print(f"  {item['id']}  {item['preview']}{suffix}")
    return 0


def cmd_organize(args) -> int:
    cfg = load_config()
    with make_client(cfg) as client:
        resp = client.post("/organize", json={"draft_id": args.draft_id})
        if resp.status_code == 404:
            print(resp.json()["detail"], file=sys.stderr)
            return 1
        resp.raise_for_status()
        data = resp.json()

    if not data["count"]:
        print("没有待整理的草稿。")
        return 0

    # 报告：与工作日志同源（Q50），同一批 results 两个出口
    print(f"整理完成，{data['count']} 条：")
    for r in data["results"]:
        line = f"  [{r['kind']}] {r['detail']}"
        if r["error"]:
            line += f" —— {r['error']}"
        print(line)

    failed = sum(1 for r in data["results"] if r["kind"] == "failed")
    return 1 if failed and failed == data["count"] else 0


def cmd_status(args) -> int:
    cfg = load_config()
    port = runtime.running_port()
    if port is None:
        print("服务未在运行（下次调用会自动拉起）。")
    else:
        print(f"服务在运行：http://127.0.0.1:{port}")
    print(f"vault: {cfg.vault_path}")
    return 0


# ------------------------------------------------------------ 入口

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kb", description="KN_Base 知识库命令行"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_push = sub.add_parser("push", help="投递一条草稿到收件箱")
    p_push.add_argument("--content", help="正文")
    p_push.add_argument("--file", help="从文件读正文")
    p_push.add_argument("--project", help="项目名（默认取 git 根目录名）")
    p_push.add_argument("--source", help="来源：会话 / 书籍 / 网页 / 论文")
    p_push.set_defaults(func=cmd_push)

    p_org = sub.add_parser("organize", help="整理草稿（不填 id 则整理全部）")
    p_org.add_argument("draft_id", nargs="?", help="只整理这一条")
    p_org.set_defaults(func=cmd_organize)

    p_inbox = sub.add_parser("inbox", help="查看收件箱")
    p_inbox.set_defaults(func=cmd_inbox)

    p_status = sub.add_parser("status", help="查看服务状态")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:
        print(f"与服务通信失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 写 `kb.bat`（Windows 入口）**

```bat
@echo off
REM 在任何目录下调用都可——用绝对路径定位工程
setlocal
set KN_ROOT=%~dp0
set PYTHONPATH=%KN_ROOT%src;%PYTHONPATH%
python -m kb.api.cli %*
endlocal
```

用的时候把 `%KN_ROOT%`（即本目录）加进 PATH，之后在任意项目目录里敲 `kb push --content "..."` 即可。

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/api/test_cli.py -v
```

预期：12 passed

- [ ] **Step 6: 提交**

```bash
git add src/kb/api/cli.py kb.bat tests/api/test_cli.py
git commit -m "feat: CLI（投递、整理、收件箱、状态）"
```

---

## Task 13: 端到端验证

**Files:**
- 无新增代码。本任务是**手动验证**真实链路——自动化测试全部 mock 了 LLM（Q52），真实模型的效果必须人工过一遍。

- [ ] **Step 1: 跑全部自动化测试**

```bash
conda activate kn_base
pytest -v
```

预期：全绿。若有失败，先修完再往下。

- [ ] **Step 2: 建 vault**

```bash
python -c "from pathlib import Path; import sys; sys.path.insert(0,'src'); from scripts.init_vault import init_vault; print(init_vault(Path(r'E:\KB_Library')))"
```

预期：打印建了哪些目录。**再跑一次**应打印 `[]`（幂等）。

- [ ] **Step 3: 用 Obsidian 打开 vault**

打开 `E:\KB_Library` 作为仓库。确认目录结构正常。

- [ ] **Step 4: 配置密钥**

```bash
cp .env.example .env
```

编辑 `.env`，填入真实的 `KB_LLM_API_KEY`，并按供应商文档确认 `KB_LLM_BASE_URL` 与 `KB_LLM_MODEL` 的确切值。

- [ ] **Step 5: 手动建一个主题目录和项目目录**

第一条笔记需要有个落点。手动建 `20_知识/后端/` 和 `10_项目/工作/电商后台/`（**这一步是刻意的**——新主题由你决定，不由 AI 发明，Q11）。

- [ ] **Step 6: 投递一条**

```bash
kb.bat push --content "并发写入时会锁表，最后用队列串行化解决" --source 会话
```

预期：`已收，id=YYYYMMDD-xxxx`

- [ ] **Step 7: 看收件箱**

```bash
kb.bat inbox
```

预期：列出刚才那条。

- [ ] **Step 8: 用 Obsidian 检查草稿**

打开 `00_收件箱/<id>.md`，确认 frontmatter 有 `状态: 待整理`，正文原样未改。

- [ ] **Step 9: 触发整理**

```bash
kb.bat organize
```

预期：打印每条的结果（`created` / `folded` / `pending` / `failed`）。**这一步会真实调用 LLM。**

- [ ] **Step 10: 检查落盘结果**

在 Obsidian 里确认：
- `20_知识/后端/` 下出现了新笔记，有 `类型`、`主题`、`创建`、`更新` 字段
- 正文里有 `[[双向链接]]` 且能点开
- `40_索引/后端.md` 被自动创建（若此前不存在）
- `00_收件箱/` 已清空
- `40_索引/整理日志/<今天>.md` 里记了这次整理

- [ ] **Step 11: 检查 git**

```bash
cd /d E:\KB_Library
git log --oneline
git log -1 --format="%an <%ae>"
git show --stat HEAD
```

预期：**只有一个** commit；author 是 `kb-service`；只包含本次动过的文件。

- [ ] **Step 12: 验证「不允许孤儿笔记」**

打开新笔记，确认它的 `[[链接]]` 能解析到真实存在的笔记或索引页。

- [ ] **Step 13: 验证失败隔离**

故意投递一条含义模糊、难以归类的草稿：

```bash
kb.bat push --content "嗯……这个再想想"
kb.bat organize
```

预期：可能被判为 `pending` 并移入 `00_收件箱/待归类/`。确认**它不会阻塞其他草稿**，且报告里列出了原因。

- [ ] **Step 14: 验证提交信息可读**

```bash
git log -1
```

预期：message 是中文，列出了新建/合并/待归类/失败各多少条。

- [ ] **Step 15: 记录发现的问题**

把验证中发现的任何问题、设计缺陷、改进点**写进 `docs/问题记录.md`**（按既有格式：问题 → 结论；未决的标 🔴）。

**不要当场改代码。** 未经讨论的设计变更，先记下来（项目规则）。

---

## 计划自检

**规格覆盖：**

| 设计决策 | 落在哪个任务 |
|---|---|
| Q2 Python 环境 | Task 1 |
| Q24 类型枚举 | Task 2 |
| Q11/Q13/Q14 结构规则 | Task 4（目录）、Task 8（主题校验） |
| Q30 项目名映射 | Task 3（normalize/find/list）、Task 12（default_project） |
| Q30 投递接口 | Task 11（/push）、Task 12（CLI 参数） |
| Q56 索引页自动生成 | Task 3（`ensure_topic_index`）、Task 9（`_ensure_indexes`） |
| Q36 查重两段式 | Task 6（预筛）、Task 8（提示词含候选） |
| Q45 三段式 | Task 8（规划+校验）、Task 9（落盘+事务） |
| Q45 失败分级重试 | Task 9（`make_plan` 的退避与回喂） |
| Q45 按条隔离 | Task 9（`organize_all`） |
| Q46 git 提交策略 | Task 9（`commit_changes` + 服务 author） |
| Q49 端口发现 | Task 10 |
| Q39 按需拉起 | Task 10（`ensure_service`） |
| Q50 报告/日志同源 | Task 7、Task 9（同一批 results 两个出口） |
| Q51 运行日志 | Task 12 备注（uvicorn log + 后续接 logging） |
| Q52 全 mock LLM | 全部测试用 `FakeLLM` |
| Q53 .obsidian 部分入库 | Task 4（vault 的 .gitignore） |
| Q54 openai SDK | Task 5 |
| Q55 草稿格式与流转 | Task 3（写/读）、Task 9（PENDING 流转） |
| Q21 不允许孤儿 | Task 8（校验）、Task 3（索引页） |
| Q33 core 不依赖 api/web | 全程遵守 |

**未覆盖（明确不在最小闭环内）：** 运行日志接入标准 logging（Q51 完整版）、Web UI（Q31）、MCP 接口（Q28）、撤回界面（Q22）、Dataview 看板（Q31）、MOC 手工维护、阶段二 RAG。

**类型一致性检查：** `OrganizePlan` / `OrganizeResult` / `ResultKind` / `Outcome` 的字段名在 Task 2 定义，Task 7/8/9/11 使用一致；`journal_path` / `topic_index_path` / `find_draft` / `list_projects` 均在 Task 3 定义后被后续任务引用。

