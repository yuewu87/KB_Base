# 与用户对接的 AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「与用户对接的 AI」落地——服务里的对话能力 + Web 的对话页 + 随手记（对话式 + 模板式）。

**Architecture:** **它是另一个入口，不是一层。** 对话能力放服务里（逻辑只有一份），Web / CLI / 以后的 qqbot 都是薄适配层。LLM 只负责「听懂人话、选一个动作」，**动作的执行由代码做**——和整理那条链一样，每个 LLM 调用点都有确定性校验兜着。

**Tech Stack:** Python 3.11、FastAPI、Jinja2、pytest（LLM 全 mock）、ruff。

**依据：** [`docs/03_问题记录.md`](../../03_问题记录.md) Q83–Q87、[`docs/01_架构.md`](../../01_架构.md)。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `src/kb/core/chat_store.py` | 会话的存与读 | **新建** |
| `src/kb/core/chat.py` | 对话能力：LLM 循环 + 动作执行 | **新建** |
| `src/kb/core/actions.py` | 动作清单（把已有能力包成统一形状） | **新建** |
| `src/kb/api/http.py` | 对话端点 | 加三个路由 |
| `src/kb/api/cli.py` | `kb chat` | 加子命令 |
| `src/kb/web/router.py` | 对话页、投递页 | 改 |
| `src/kb/web/templates/chat.html` | 真对话 | 重写 |
| `src/kb/web/templates/new.html` | 模板投递 | **新建** |
| `templates/投递模板/*.md` | 脚手架模板 | **新建** |
| `.gitignore` | `chats/` 不入库 | 加一行 |

**关键约束：`data/` 绝不能入库。** 代码仓库是 **public** 的，运行数据进去就等于公开发布。

---

## Task 0: 目录整理（前置）

**为什么要先做：** 运行数据散在顶层各处，而**「进不进 git」这条线是看不见的**——仓库是 public，切错就是公开发布。而且后面三个任务都要往这些地方放东西（会话历史、投递模板），**先把架子搭好，免得放一处改一处**。

### 判据

> **第一刀按「进不进 git」切**（最硬：public 仓库，切错就是发布）。
> **第二刀按「谁读」切**（机器读的骨架 vs 人读的脚手架）。

**不按「文件类型」切**——`log` 和 `模板` 看着都是文本，但一个绝不能进 git、一个必须进。放一起就把红线糊了。

### 目标

```
KN_Base/
├─ 代码与工程 ────────────── 进 git
│  ├── src/  tests/  scripts/
│  ├── templates/
│  │   ├── 笔记/            笔记骨架 —— 机器读
│  │   └── 投递/            随手记脚手架 —— 人读
│  ├── docs/
│  └── pyproject.toml · requirements.txt · CLAUDE.md · README.md
│      .env.example · .gitignore · .gitattributes · kb.bat
│
└─ data/ ──────────────────── 不进 git
    ├── logs/               运行日志
    ├── runtime/            service.json
    ├── chats/              会话历史（Task 1 建）
    └── cache/              pytest 与 ruff 的缓存
```

`.env` 留根上——它是**配置**不是运行数据，且是启动时的约定位置。

**Files:**
- Modify: `src/kb/logging_setup.py`、`src/kb/api/runtime.py`、`src/kb/core/planning.py`
- Modify: `.gitignore`、`pyproject.toml`
- Move: `logs/` `runtime/` → `data/`；`templates/*.md` → `templates/笔记/`
- Delete: `templates/日志.md`

- [ ] **Step 1: 停服务、挪运行数据**

```bash
cd "E:/Study_Projects/KN_Base" && ./kb.bat stop
mkdir -p data/cache
mv logs data/logs
mv runtime data/runtime
```

> **先停服务**——它正持有 `runtime/service.json`，不停就挪不动。

- [ ] **Step 2: 改三处路径常量**

| 文件 | 现在 | 改成 |
|---|---|---|
| `logging_setup.py:21` | `PROJECT_ROOT / "logs"` | `PROJECT_ROOT / "data" / "logs"` |
| `runtime.py:23` | `PROJECT_ROOT / "runtime"` | `PROJECT_ROOT / "data" / "runtime"` |
| `planning.py:34` | `PROJECT_ROOT / "templates"` | `PROJECT_ROOT / "templates" / "笔记"` |

- [ ] **Step 3: 改 `runtime.py:94` 的 mtime 扫描**

```python
    for folder in (
        PROJECT_ROOT / "src" / "kb",
        PROJECT_ROOT / "templates",
    ):
```

保持不变即可——`templates/` 整棵树的 mtime 仍然有效（子目录变动会冒泡到父目录）。**但 `data/` 不该进扫描**（服务自己写的日志会触发「代码变旧」的误报）——**确认它不在扫描范围内**。

- [ ] **Step 4: 重组 `templates/`**

```bash
mkdir -p templates/笔记 templates/投递
git mv templates/概念.md templates/踩坑.md templates/决策.md \
       templates/经验.md templates/清单.md templates/笔记/
git rm templates/日志.md          # 死文件：被排除列表跳过，从不使用
```

- [ ] **Step 5: 把缓存指到 `data/cache/`**

`pyproject.toml`：

```toml
[tool.pytest.ini_options]
cache_dir = "data/cache/pytest"

[tool.ruff]
cache-dir = "data/cache/ruff"
```

- [ ] **Step 6: 简化 `.gitignore`**

删掉 `logs/`、`runtime/` 两行（以及既有的 `data/` 那一段），换成一行：

```
# ---- 运行数据（日志 / 会话 / 缓存）—— 含个人内容，仓库是 public，绝不能入库 ----
data/
```

**保留** `.env`、`requirements.lock.txt`、`__pycache__/` 等条目。

- [ ] **Step 7: 跑测试**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**Expected:** 295 passed（不变），ruff 干净。

> **注意**：测试里的 `tmp_path` 是独立的，不受影响；但 `tests/test_init_vault.py` 里如有断言 `logs`/`runtime` 路径的要跟着改——**跑一遍就知道**。

- [ ] **Step 8: 手工验证服务仍能起**

```bash
./kb.bat inbox          # 拉起服务
./kb.bat status         # 看端口与 vault
cat data/runtime/service.json
ls data/logs/
```

**Expected:** 服务起得来，`service.json` 在 `data/runtime/`，日志在 `data/logs/`。

- [ ] **Step 9: 同步文档**

`CLAUDE.md` 的「常用命令」和 `docs/01_架构.md` 的「接口与工程」里的目录树，按新结构改。

- [ ] **Step 10: 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
git add -A && git commit -m "chore: 目录整理——运行数据归 data/，模板分笔记与投递"
```

---

## Task 1: 会话存储

**Files:**
- Create: `src/kb/core/chat_store.py`
- Create: `tests/core/test_chat_store.py`
- Modify: `.gitignore`

- [ ] **Step 1: 写失败测试**

`tests/core/test_chat_store.py`：

```python
"""会话存储。存服务侧，**不入库**——代码仓库是公开的。"""

from kb.core.chat_store import (
    append_message,
    chat_path,
    list_chats,
    load_chat,
    new_chat_id,
    save_chat,
)


def test_new_chat_id_shape():
    cid = new_chat_id()
    assert len(cid) == 13          # YYYYMMDD-xxxx
    assert cid[8] == "-"


def test_chat_path_under_chats_dir(tmp_path):
    assert chat_path(tmp_path, "20260917-a3f2").parent.name == "chats"


def test_save_then_load_roundtrip(tmp_path):
    cid = "20260917-a3f2"
    save_chat(tmp_path, cid, [{"role": "user", "content": "记一下 X"}])
    got = load_chat(tmp_path, cid)
    assert got["id"] == cid
    assert got["messages"][0]["content"] == "记一下 X"


def test_load_missing_chat_returns_none(tmp_path):
    assert load_chat(tmp_path, "不存在") is None


def test_append_message_keeps_order(tmp_path):
    cid = new_chat_id()
    append_message(tmp_path, cid, "user", "第一句")
    append_message(tmp_path, cid, "assistant", "第二句")
    chat = load_chat(tmp_path, cid)
    assert [m["content"] for m in chat["messages"]] == ["第一句", "第二句"]
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]


def test_list_chats_newest_first(tmp_path):
    append_message(tmp_path, "20260916-aaaa", "user", "旧")
    append_message(tmp_path, "20260917-bbbb", "user", "新")
    assert [c["id"] for c in list_chats(tmp_path)] == ["20260917-bbbb", "20260916-aaaa"]


def test_list_chats_empty_when_absent(tmp_path):
    assert list_chats(tmp_path) == []


def test_title_comes_from_first_user_message(tmp_path):
    cid = new_chat_id()
    append_message(tmp_path, cid, "user", "窗口缩放那个坑")
    assert load_chat(tmp_path, cid)["title"] == "窗口缩放那个坑"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_chat_store.py -q
```

**Expected:** `ModuleNotFoundError: No module named 'kb.core.chat_store'`

- [ ] **Step 3: 实现**

`src/kb/core/chat_store.py`：

```python
"""会话的存与读。

**存服务侧，不入库。** 代码仓库是 public 的——会话历史进去就等于公开发布。
代价：换机器时它不跟着 git 走，得手动拷 `chats/`。

**它不是知识**，所以按 Q80 的分界（「是不是知识」）不进 vault。
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

CHATS = "chats"
_MSG_LIMIT = 200          # 一个会话最多留这么多条，防无限长


def chats_dir(project_root: Path) -> Path:
    return project_root / CHATS


def chat_path(project_root: Path, chat_id: str) -> Path:
    return chats_dir(project_root) / f"{chat_id}.json"


def new_chat_id(now: datetime | None = None) -> str:
    """`YYYYMMDD-` + 4 位随机十六进制。与草稿 id 同一套路。"""
    now = now or datetime.now()
    return f"{now:%Y%m%d}-{random.randrange(16 ** 4):04x}"


def load_chat(project_root: Path, chat_id: str) -> dict | None:
    path = chat_path(project_root, chat_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_chat(project_root: Path, chat_id: str, messages: list[dict]) -> dict:
    """整篇写入。返回落盘的会话对象。"""
    first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
    chat = {
        "id": chat_id,
        "title": first_user.splitlines()[0][:40] if first_user else "（空会话）",
        "updated": f"{datetime.now():%Y-%m-%d %H:%M}",
        "messages": messages[-_MSG_LIMIT:],
    }
    directory = chats_dir(project_root)
    directory.mkdir(parents=True, exist_ok=True)
    chat_path(project_root, chat_id).write_text(
        json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return chat


def append_message(project_root: Path, chat_id: str, role: str, content: str) -> dict:
    """追加一条消息。会话不存在就新建。"""
    chat = load_chat(project_root, chat_id)
    messages = chat["messages"] if chat else []
    messages.append({"role": role, "content": content})
    return save_chat(project_root, chat_id, messages)


def list_chats(project_root: Path) -> list[dict]:
    """全部会话，按 id 倒序（id 前缀是日期，所以等价于时间倒序）。"""
    directory = chats_dir(project_root)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({"id": data["id"], "title": data["title"], "updated": data["updated"]})
    return out
```

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_chat_store.py -q
```

**Expected:** 全 PASS

- [ ] **Step 5: 加 `.gitignore`**

`.gitignore` 的「运行时文件与日志」那一节加一行：

```
# ---- 会话历史（含个人对话，仓库是 public，绝不能入库）----
chats/
```

- [ ] **Step 6: 提交**

```bash
git add src/kb/core/chat_store.py tests/core/test_chat_store.py .gitignore
git commit -m "feat: 会话存储——服务侧、不入库（Q83）"
```

---

## Task 2: 动作清单

**把服务已有的能力包成统一形状**，让对话层只管「选哪个动作」，不关心底下怎么实现。

**Files:**
- Create: `src/kb/core/actions.py`
- Create: `tests/core/test_actions.py`

- [ ] **Step 1: 写失败测试**

`tests/core/test_actions.py`：

```python
"""动作清单：把已有能力包成对话层能用的形状。"""

from kb.core.actions import ACTIONS, describe_actions, run_action
from kb.llm.base import FakeLLM


def test_every_action_has_description_and_params():
    for name, spec in ACTIONS.items():
        assert spec["desc"], f"{name} 缺描述"
        assert isinstance(spec["params"], dict)


def test_describe_actions_lists_all():
    text = describe_actions()
    for name in ACTIONS:
        assert name in text


def test_run_search_returns_hits(tmp_path):
    from kb.core.vault import write_note

    write_note(tmp_path / "计算机" / "a.md", {"类型": "概念", "主题": ["计算机"]}, "锁表")
    result = run_action("search", {"query": "锁表"}, tmp_path, llm=None)
    assert "a.md" in result or "a" in result


def test_run_action_rejects_unknown_name(tmp_path):
    result = run_action("放火", {}, tmp_path, llm=None)
    assert "未知动作" in result


def test_run_action_reports_bad_params(tmp_path):
    result = run_action("search", {}, tmp_path, llm=None)
    assert "缺少参数" in result
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_actions.py -q
```

**Expected:** `ModuleNotFoundError: No module named 'kb.core.actions'`

- [ ] **Step 3: 实现**

`src/kb/core/actions.py`：

```python
"""动作清单——对话层能调用的东西。

**只有服务已有的能力**，不新增判断。每个动作都返回一段**给人看的文本**，
直接作为下一轮 LLM 的输入。

为什么用「LLM 输出动作名 + 参数」而不是 SDK 的 tool calling：
- `llm/base.py` 的抽象只有 `complete(system, user) -> str`，加 tool 要动抽象层
- 结构化 JSON 和整理那条链是同一套路，解析与校验都能复用
"""

from __future__ import annotations

from pathlib import Path

from kb.core.search import search_notes
from kb.core.vault import read_note

ACTIONS: dict[str, dict] = {
    "search": {
        "desc": "在知识库里检索。用户问「X 是怎么说的」「有没有关于 X 的」时用。",
        "params": {"query": "关键词或一段描述"},
    },
    "push": {
        "desc": "投递一条新内容进收件箱。用户说「记一下 X」「帮我记着」时用。",
        "params": {"content": "正文，原样投递，不要改写"},
    },
    "revise": {
        "desc": "修改已有笔记。用户说「那条不对」「改成 X」时用。",
        "params": {"target": "目标笔记的文件名（不含 .md）", "content": "新内容"},
    },
    "organize": {
        "desc": "触发整理。用户说「可以整理了」「收拾一下」时用。",
        "params": {},
    },
}


def describe_actions() -> str:
    """给 LLM 看的动作清单。"""
    lines = []
    for name, spec in ACTIONS.items():
        params = "、".join(f"`{k}`（{v}）" for k, v in spec["params"].items()) or "无"
        lines.append(f"- `{name}`：{spec['desc']}\n  参数：{params}")
    return "\n".join(lines)


def run_action(
    name: str, params: dict, vault_root: Path, llm=None, *, organize_fn=None
) -> str:
    """执行一个动作，返回**给人看的文本**。

    **从不抛异常**——出错也返回文本，让对话能把它说给用户听。
    """
    if name not in ACTIONS:
        return f"未知动作：{name}"

    required = set(ACTIONS[name]["params"])
    missing = [k for k in required if not params.get(k)]
    if missing:
        return f"缺少参数：{'、'.join(missing)}"

    if name == "search":
        hits = search_notes(vault_root, params["query"])
        if not hits:
            return f"没找到关于「{params['query']}」的内容。"
        lines = [f"找到 {len(hits)} 篇："]
        for path in hits:
            meta, _ = read_note(path)
            tags = meta.get("主题") or []
            rel = path.relative_to(vault_root).as_posix()
            lines.append(f"- {path.stem}（{rel}）标签：{'、'.join(map(str, tags)) or '无'}")
        return "\n".join(lines)

    if name == "push":
        if organize_fn is None:
            return "投递通道没接上（调用方没传 push 回调）。"
        return organize_fn("push", params["content"], None)

    if name == "revise":
        if organize_fn is None:
            return "投递通道没接上（调用方没传 push 回调）。"
        return organize_fn("revise", params["content"], params["target"])

    if name == "organize":
        if organize_fn is None:
            return "整理通道没接上（调用方没传 organize 回调）。"
        return organize_fn("organize", "", None)

    return f"动作 {name} 没有实现。"
```

> **`organize_fn` 是回调解耦**：`actions.py` 不直接调 `organize` 模块——那样会引入循环依赖，而且投递/整理要经过服务进程（Q29）。**回调由 HTTP 层注入**，它才是真正落盘的那一层。

- [ ] **Step 4: 跑测试确认通过 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_actions.py -q
git add src/kb/core/actions.py tests/core/test_actions.py
git commit -m "feat: 动作清单——把已有能力包成对话层能用的形状"
```

---

## Task 3: 对话能力

**对话的实质：一个有界的「LLM 选动作 → 代码执行 → 结果回喂」循环。**

**Files:**
- Create: `src/kb/core/chat.py`
- Create: `tests/core/test_chat.py`

- [ ] **Step 1: 写失败测试**

`tests/core/test_chat.py`：

```python
"""对话能力：LLM 选动作，代码执行，结果回喂。"""

import json

from kb.core.chat import MAX_ROUNDS, parse_reply, run_turn
from kb.llm.base import FakeLLM


def _reply(say="收到", action=None, params=None, ask=None):
    return json.dumps(
        {"say": say, "action": action, "params": params or {}, "ask": ask},
        ensure_ascii=False,
    )


def test_parse_reply_plain_json():
    got = parse_reply(_reply("你好"))
    assert got["say"] == "你好"
    assert got["action"] is None


def test_parse_reply_strips_fence():
    got = parse_reply(f"```json\n{_reply('好')}\n```")
    assert got["say"] == "好"


def test_parse_reply_bad_json_raises():
    import pytest

    from kb.core.chat import ChatError

    with pytest.raises(ChatError):
        parse_reply("这不是 JSON")


def test_run_turn_no_action_ends_immediately(tmp_path):
    llm = FakeLLM([_reply("好的，我记下了")])
    messages, rounds = run_turn(tmp_path, [], "记一下 X", llm)
    assert rounds == 1
    assert messages[-1]["content"] == "好的，我记下了"


def test_run_turn_executes_action_then_reports(tmp_path):
    """第一轮选 search，第二轮总结。"""
    llm = FakeLLM([
        _reply("我先查查", action="search", params={"query": "锁表"}),
        _reply("查到了，没有相关笔记"),
    ])
    messages, rounds = run_turn(tmp_path, [], "锁表是怎么说的", llm)
    assert rounds == 2
    # 中间那轮的工具结果要进历史，模型才看得到
    assert any("工具结果" in m["content"] for m in messages)
    assert messages[-1]["content"] == "查到了，没有相关笔记"


def test_run_turn_stops_at_max_rounds(tmp_path):
    """模型一直要动作也不会转不完——有上限。"""
    llm = FakeLLM([
        _reply(action="search", params={"query": "x"}) for _ in range(MAX_ROUNDS + 3)
    ])
    _, rounds = run_turn(tmp_path, [], "一直查", llm)
    assert rounds == MAX_ROUNDS


def test_run_turn_reports_unknown_action_back_to_model(tmp_path):
    """模型给了个不存在的动作——不炸，把错误喂回去让它自己改。"""
    llm = FakeLLM([
        _reply(action="放火", params={}),
        _reply("我换个说法"),
    ])
    messages, _ = run_turn(tmp_path, [], "放火", llm)
    assert any("未知动作" in m["content"] for m in messages)


def test_run_turn_carries_prior_messages(tmp_path):
    llm = FakeLLM([_reply("接着上次说")])
    prior = [{"role": "user", "content": "上一轮的话"}, {"role": "assistant", "content": "上一轮的回"}]
    messages, _ = run_turn(tmp_path, prior, "继续", llm)
    assert messages[0]["content"] == "上一轮的话"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_chat.py -q
```

**Expected:** `ModuleNotFoundError: No module named 'kb.core.chat'`

- [ ] **Step 3: 实现**

`src/kb/core/chat.py`：

```python
"""对话能力——「与用户对接的 AI」的核心。

**它是另一个入口，不是一层。** 能力和会话层 AI 相同，只是走 Web 不走 CLI。

## 形态：有界的动作循环

    用户说话
      → LLM 看 [系统提示 + 历史 + 动作清单] → 输出 {say, action, params}
      → 有 action → 代码执行 → 结果回喂 → 再问一轮
      → 没 action → 结束，say 就是回复

**上限 `MAX_ROUNDS` 轮**——模型一直要动作也不会转不完。

**动作的执行归代码**（`actions.run_action`），LLM 只负责「听懂人话、选一个」。
这和整理那条链是同一条原则：每个 LLM 调用点都有确定性校验兜着。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kb.core.actions import describe_actions, run_action
from kb.llm.base import LLM, LLMError

MAX_ROUNDS = 4

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class ChatError(ValueError):
    """模型输出不可用。"""


def build_system_prompt() -> str:
    return f"""你是知识库助手，替用户处理他的个人知识库。

**只输出 JSON，不要输出任何其他文字，不要用代码块包裹。**

{{
  "say": "对用户说的话",
  "action": "要执行的动作名，不需要就填 null",
  "params": {{"参数名": "值"}}
}}

## 你能做的动作

{describe_actions()}

## 怎么用

- 用户想**记东西** → `push`，正文**原样传他说的内容**，不要改写、不要补标题
- 用户想**查东西** → `search`
- 用户想**改东西** → `revise`，target 填笔记文件名（不含 .md）
- 用户说**可以整理了** → `organize`
- 只是闲聊或问你已经知道的事 → `action` 填 null

## 硬规矩

1. **不要替用户写他没说过的内容。** `push` 的 content 只能是他的原话。
2. **一次只做一个动作。** 需要多步（比如先查再改）就先做第一个，
   看到工具结果后再决定下一步。
3. **不要编造检索结果。** 没查就别说得像查过。
4. 动作失败时，把失败原因如实告诉用户，别装作成功。"""


def parse_reply(raw: str) -> dict:
    """解析模型输出。容忍代码块包裹。"""
    text = _FENCE.sub("", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ChatError(f"模型输出不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ChatError("模型输出不是 JSON 对象")
    data.setdefault("say", "")
    data.setdefault("action", None)
    data.setdefault("params", {})
    if not isinstance(data["params"], dict):
        raise ChatError("params 必须是对象")
    return data


def _render_history(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        who = "用户" if m["role"] == "user" else "助手"
        lines.append(f"**{who}**：{m['content']}")
    return "\n\n".join(lines)


def run_turn(
    vault_root: Path,
    history: list[dict],
    user_message: str,
    llm: LLM,
    *,
    organize_fn=None,
) -> tuple[list[dict], int]:
    """跑一轮对话。

    返回 `(新的完整消息列表, 实际跑了几轮)`。调用方负责落盘。
    """
    messages = list(history)
    messages.append({"role": "user", "content": user_message})
    system = build_system_prompt()

    for round_no in range(1, MAX_ROUNDS + 1):
        try:
            raw = llm.complete(system, _render_history(messages))
        except LLMError as exc:
            messages.append({"role": "assistant", "content": f"我这边出错了：{exc}"})
            return messages, round_no

        try:
            reply = parse_reply(raw)
        except ChatError as exc:
            messages.append({"role": "assistant", "content": f"我输出的格式不对：{exc}"})
            return messages, round_no

        say = reply["say"]
        action = reply["action"]

        if not action:
            messages.append({"role": "assistant", "content": say})
            return messages, round_no

        result = run_action(action, reply["params"], vault_root, llm, organize_fn=organize_fn)
        messages.append({"role": "assistant", "content": say})
        messages.append({"role": "tool", "content": f"工具结果（{action}）：\n{result}"})

    # 到达上限——把最后一轮的 say 作为收尾
    messages.append({"role": "assistant", "content": "我转的圈数太多了，先停下。你再说一句我接着办。"})
    return messages, MAX_ROUNDS
```

- [ ] **Step 4: 跑测试确认通过 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_chat.py -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests
git add src/kb/core/chat.py tests/core/test_chat.py
git commit -m "feat: 对话能力——有界的动作循环（Q83/Q84）"
```

---

## Task 4: HTTP 端点

**对话要走服务进程**（Q29：所有写入必须经过服务）。动作的执行由 HTTP 层注入回调。

**Files:**
- Modify: `src/kb/api/http.py`
- Modify: `tests/api/test_http.py`

- [ ] **Step 1: 写失败测试**

`tests/api/test_http.py` 追加：

```python
# ---------- 对话 ----------

def test_chat_returns_reply_and_creates_session(client, vault):
    """一轮对话落一个会话文件。"""
    from kb.core.chat_store import list_chats

    resp = client.post("/chat", json={"message": "你好"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"]
    assert data["chat_id"]
    assert [c["id"] for c in list_chats(vault)] == [data["chat_id"]]


def test_chat_continues_existing_session(client, vault):
    from kb.core.chat_store import load_chat

    first = client.post("/chat", json={"message": "第一句"}).json()
    client.post("/chat", json={"chat_id": first["chat_id"], "message": "第二句"})
    chat = load_chat(vault, first["chat_id"])
    contents = [m["content"] for m in chat["messages"] if m["role"] == "user"]
    assert contents == ["第一句", "第二句"]


def test_chats_lists_sessions(client, vault):
    client.post("/chat", json={"message": "一句话"})
    resp = client.get("/chats")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_chat_404_on_unknown_session(client, vault):
    resp = client.post("/chat", json={"chat_id": "不存在", "message": "x"})
    assert resp.status_code == 404
```

> `client` 夹具要能注入 `FakeLLM`——`create_app(cfg, llm)` 已经支持（第二个参数）。夹具改成 `create_app(cfg, FakeLLM([...]))`，让对话返回固定 JSON。

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/api/test_http.py -k chat -q
```

**Expected:** `404 Not Found`（端点还不存在）

- [ ] **Step 3: 把投递逻辑抽成函数**

`/push` 的处理体已经在，把它抽出来给对话复用：

```python
def _push_draft(
    cfg: Config, content: str, *, project: str | None = None,
    source: str | None = None, revise_target: str | None = None,
) -> str:
    """落一条草稿，返回**给人看的文本**。撞 id 就重试（见 PUSH_ATTEMPTS）。"""
    created_at = f"{datetime.now():%Y-%m-%d %H:%M}"
    for _ in range(PUSH_ATTEMPTS):
        draft = Draft(
            id=new_draft_id(), body=content.strip() + "\n", source=source,
            project=project, created_at=created_at, revise_target=revise_target,
        )
        try:
            write_draft(cfg.vault_path, draft)
        except FileExistsError:
            continue
        logging.getLogger("kb.push").info("收到草稿 id=%s 来源=%s", draft.id, source or "未说明")
        return f"已记下，编号 {draft.id}。"
    return f"连续 {PUSH_ATTEMPTS} 次撞上已存在的草稿 id，没记成。"
```

`/push` 端点改成调它（返回值是文本，端点仍返回 `{"id": ...}`——所以 `_push_draft` 再返回草稿 id 更好，**改成 `tuple[str, str]`：`(给人看的文本, 草稿 id)`**）。

- [ ] **Step 4: 加对话端点**

`src/kb/api/http.py` 的 `create_app` 里加：

```python
    def _chat_organize_fn(kind: str, content: str, target: str | None) -> str:
        """对话层能调的动作——**只有服务已有的能力**，不新增判断。"""
        if kind == "push":
            _, text = _push_draft(cfg, content, source="Web")
            return text
        if kind == "revise":
            _, text = _push_draft(cfg, content, source="Web", revise_target=target)
            return text
        if kind == "organize":
            results = organize.organize_selected(cfg.vault_path, list_drafts(cfg.vault_path), get_llm())
            ok = sum(1 for r in results if not r.error)
            return f"整理了 {len(results)} 条，成功 {ok} 条。"
        return f"未知动作：{kind}"

    @app.post("/chat")
    def chat_endpoint(req: ChatRequest) -> dict:
        if req.chat_id:
            chat = load_chat(PROJECT_ROOT, req.chat_id)
            if chat is None:
                raise HTTPException(status_code=404, detail=f"找不到会话 {req.chat_id}")
            history = chat["messages"]
            chat_id = req.chat_id
        else:
            history, chat_id = [], new_chat_id()

        messages, _ = run_turn(
            cfg.vault_path, history, req.message, get_llm(), organize_fn=_chat_organize_fn
        )
        save_chat(PROJECT_ROOT, chat_id, messages)
        reply = next(
            (m["content"] for m in reversed(messages) if m["role"] == "assistant"), ""
        )
        return {"chat_id": chat_id, "reply": reply}

    @app.get("/chats")
    def chats() -> dict:
        items = list_chats(PROJECT_ROOT)
        return {"count": len(items), "items": items}
```

配套：`ChatRequest(BaseModel)` 加 `chat_id: str | None = None` 和 `message: str`；import 补 `chat_store` 的四个名字 + `chat.run_turn`。

> **`tool` 角色的消息不能回喂给模型当对话历史**——`run_turn` 里已经把它们渲染成「工具结果」，但**落盘的 `messages` 含 `role="tool"`**。下次对话会把它当历史传进去，`_render_history` 会把它当「助手」渲染。**修法**：`_render_history` 里把 `tool` 也标成「工具」，或在落盘前过滤。**选后者更简单：落盘时只存 `user` / `assistant`。**

- [ ] **Step 5: 跑测试确认通过 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/api/test_http.py -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests
git add src/kb/api/http.py tests/api/test_http.py
git commit -m "feat: 对话端点 /chat 与会话管理 /chats"
```

---

## Task 5: Web 对话页

**Files:**
- Modify: `src/kb/web/router.py`
- Rewrite: `src/kb/web/templates/chat.html`
- Modify: `tests/web/test_router.py`

- [ ] **Step 1: 写失败测试**

`tests/web/test_router.py` 追加：

```python
def test_chat_page_has_input(client):
    body = client.get("/").text
    assert "输入关键词" not in body          # 旧的搜索框占位没了
    assert 'name="message"' in body           # 换成对话输入


def test_chat_page_shows_history(client, vault):
    from kb.core.chat_store import append_message

    append_message(vault, "20260917-aaaa", "user", "我问了一句")
    append_message(vault, "20260917-aaaa", "assistant", "我答了一句")
    body = client.get("/").text
    assert "我问了一句" in body
    assert "我答了一句" in body


def test_chat_post_redirects_back(client, vault):
    resp = client.post("/chat", data={"message": "记一下 X"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/")
```

> Web 层调 `core` 的函数是允许的（`core` 不许 import `web`，反过来可以）。但**对话要走服务进程落盘**——这里直接用 `run_turn` 落盘，和 HTTP 端点重复了一份逻辑。

> **更好的做法：Web 层不自己实现，转发给同一份 action。** 本 Task 里，Web 的 `/chat` POST 直接调 `run_turn` + `save_chat`（和 HTTP 端点一样的两行），**把这两行抽到 `chat_store` 旁边的一个函数里**，两边共用：

```python
# src/kb/core/chat.py 追加
def handle(project_root: Path, vault_root: Path, chat_id: str | None,
           message: str, llm, *, organize_fn=None) -> tuple[str, str]:
    """一轮对话的完整处理：读历史 → 跑 → 落盘。返回 (chat_id, reply)。"""
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/web/test_router.py -k chat -q
```

**Expected:** FAIL

- [ ] **Step 3: 改路由**

`src/kb/web/router.py` 的 `/` 改成显示对话，加 `POST /chat`：

```python
    @router.get("/", response_class=HTMLResponse)
    def chat_page(request: Request, cid: str = ""):
        chats = list_chats(PROJECT_ROOT)
        current = None
        if cid:
            current = load_chat(PROJECT_ROOT, cid)
        return templates.TemplateResponse(
            request, "chat.html",
            _ctx("chat", chats=chats, current=current, cid=cid),
        )

    @router.post("/chat")
    def chat_post(message: str = Form(...), cid: str = Form("")):
        chat_id, _ = handle(
            PROJECT_ROOT, cfg.vault_path, cid or None, message,
            build_llm(cfg), organize_fn=make_organize_fn(cfg),
        )
        return RedirectResponse(f"/?cid={chat_id}", status_code=303)
```

> `handle` 与 `make_organize_fn` 都要能在 Web 层拿到——**它们属于服务侧**。把 `make_organize_fn` 从 `http.py` 提到一个共用位置（`src/kb/api/actions_bridge.py`），两边 import。

- [ ] **Step 4: 重写 `chat.html`**

对话流 + 输入框 + 右侧会话历史（点历史切换 `?cid=`）：

```html
{% extends "base.html" %}
{% block title %}ai对话 · KN_Base{% endblock %}
{% block content %}
<div class="chat-layout">
  <section>
    <div class="page-head">
      <h1>ai对话</h1>
      <p>说一句就行——记东西、查东西、改东西都可以。</p>
    </div>

    <div class="thread">
      {% for m in (current.messages if current else []) %}
        {% if m.role != "tool" %}
          <div class="bubble {{ m.role }}">{{ m.content }}</div>
        {% endif %}
      {% endfor %}
      {% if not current %}
        <div class="empty">新会话。试试「记一下……」「……是怎么说的」。</div>
      {% endif %}
    </div>

    <form class="searchbar" method="post" action="/chat">
      <input type="hidden" name="cid" value="{{ cid }}">
      <label for="message" class="sr-only">要说的话</label>
      <input id="message" name="message" placeholder="说点什么……" autofocus autocomplete="off">
      <button type="submit">发送</button>
    </form>
  </section>

  <aside class="chat-history">
    <h2>会话历史</h2>
    {% if not chats %}<p class="muted">还没有会话。</p>{% endif %}
    {% for c in chats %}
      <a class="chat-item {{ 'active' if c.id == cid }}" href="/?cid={{ c.id }}">
        <span class="chat-title">{{ c.title }}</span>
        <span class="mono">{{ c.updated }}</span>
      </a>
    {% endfor %}
  </aside>
</div>
{% endblock %}
```

- [ ] **Step 5: 加样式**

`.thread`（消息流）、`.bubble`（用户靠右淡蓝、助手靠左白）、`.chat-item`（历史项）。

- [ ] **Step 6: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/web/ -q
git add src/kb/web/ tests/web/ src/kb/api/
git commit -m "feat: Web 对话页——真对话 + 会话历史"
```

---

## Task 6: 模板随手记

**Files:**
- Create: `templates/投递模板/*.md`
- Create: `src/kb/web/templates/new.html`
- Modify: `src/kb/web/router.py`、`base.html`（侧栏加按钮）、`style.css`
- Modify: `tests/web/test_router.py`

- [ ] **Step 1: 写三个脚手架模板**

`templates/投递模板/踩了个坑.md`：

```markdown
发生了什么？一句话说清。

当时是怎么想的？

后来怎么解决的？
```

`templates/投递模板/学到一招.md`：

```markdown
学会了什么？

在什么情况下用得上？

有没有踩过坑才知道的地方？
```

`templates/投递模板/随手一记.md`：

```markdown
（想到什么写什么，几句话就行）
```

> **它们是脚手架，不是骨架。** 只帮人把话说清，**不逼人先做分类判断**——是什么类型、放哪、起什么标题，全归整理阶段（Q86）。

- [ ] **Step 2: 写失败测试**

```python
def test_new_page_lists_templates(client):
    body = client.get("/new").text
    assert "踩了个坑" in body
    assert "学到一招" in body


def test_new_page_prefills_chosen_template(client):
    body = client.get("/new?t=踩了个坑").text
    assert "当时是怎么想的" in body


def test_push_from_web_creates_draft(client, vault):
    from kb.core.vault import list_drafts

    client.post("/new", data={"content": "窗口缩放那个坑"}, follow_redirects=False)
    assert len(list_drafts(vault)) == 1


def test_push_from_web_rejects_empty(client):
    resp = client.post("/new", data={"content": "   "}, follow_redirects=False)
    assert resp.status_code == 400
```

- [ ] **Step 3: 跑测试确认失败**

- [ ] **Step 4: 实现路由**

```python
    @router.get("/new", response_class=HTMLResponse)
    def new_note(request: Request, t: str = ""):
        templates_ = load_push_templates()
        chosen = templates_.get(t, "")
        return templates.TemplateResponse(
            request, "new.html", _ctx("new", templates=list(templates_), chosen=t, body=chosen)
        )

    @router.post("/new")
    def new_note_post(content: str = Form(...)):
        if not content.strip():
            raise HTTPException(status_code=400, detail="正文不能为空")
        _push(cfg, content, source="Web")     # 复用 Task 4 抽出来的那个
        return RedirectResponse("/journal", status_code=303)
```

`load_push_templates()` 放 `src/kb/web/data.py`：读 `templates/投递模板/*.md`，返回 `{名字: 内容}`。

- [ ] **Step 5: 侧栏加按钮**

`base.html` 在品牌区和四个导航项之间加：

```html
<a href="/new" class="side-action {{ 'active' if active == 'new' }}">
  <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
    <path d="M12 5v14M5 12h14"/>
  </svg>
  <span class="side-label">记一条</span>
</a>
```

样式：`.side-action` 用主蓝描边强调——**它是动作，不是页面**，视觉上和数据要分开。

- [ ] **Step 6: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
git add -A && git commit -m "feat: 模板随手记——侧栏「记一条」+ 脚手架模板（Q85/Q86）"
```

---

## Self-Review

**1. 规格覆盖：**

| Q83–Q87 | 落在哪 |
|---|---|
| Q83 是另一个入口 | Task 2/3：对话能力放 `core/`，不绑 Web |
| Q84 逻辑放服务里 | Task 3 `core/chat.py` + Task 4 端点；Web 只是 `handle()` 的调用方 |
| Q85 两种随手记 | Task 5（对话式）+ Task 6（模板式） |
| Q86 模板是脚手架 | Task 6 Step 1 的三个模板——只有问题，没有分类字段 |
| Q87 只填正文 | Task 6 Step 4 的表单只有 `content`；`source` 默认 `Web`，`project` 留空 |

**2. 占位符扫描：** 无 TBD / TODO / 无代码的代码步骤。

**3. 类型一致性：**

- `run_turn(vault_root, history, user_message, llm, *, organize_fn) -> (list[dict], int)`：Task 3 定义，Task 4/5 一致使用
- `run_action(name, params, vault_root, llm, *, organize_fn) -> str`：Task 2 定义
- `organize_fn(kind: str, content: str, target: str | None) -> str`：Task 2 调用，Task 4 实现
- `handle(project_root, vault_root, chat_id, message, llm, *, organize_fn) -> (str, str)`：Task 5 Step 1 提出，Task 4 与 Web 共用
- `_push_draft(...) -> tuple[str, str]`：Task 4 Step 3 改成返回 `(文本, 草稿 id)`

**4. 已知风险：**

- **Task 4 Step 4 那个 `tool` 角色落盘问题**——计划里给了修法（只存 `user`/`assistant`），但**它是这条链上最容易漏的地方**，Step 5 的测试没覆盖它。执行时要么补一条测试，要么明确记下没测。
- **Task 5 Step 3 提到 `make_organize_fn` 要提到共用位置**——那是一次重构，会同时改 `http.py`。如果执行时发现牵动面比预期大，**停下来报告**，别硬塞。
- **对话的 LLM 调用会花钱**：每一轮用户消息至少一次调用，带动作的两三次。这是设计如此（和整理一样），不是问题。

---

## 验收

代码侧：

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**端到端（真实 LLM）：**

1. `kb stop`（改了 `src/` 必须重启）
2. 打开 `http://127.0.0.1:51823/`
3. 说「记一下：IE 缩放那个坑记得先看视口边界」→ 应回「已记下，编号 …」
4. `kb inbox` 确认草稿在
5. 说「IE 缩放是怎么说的」→ 应列出已有笔记
6. 点侧栏「记一条」→ 选「踩了个坑」→ 填三个空 → 投递 → `kb inbox` 确认
7. `kb organize` → 内容落进 `计算机/` 对应分类

**最后：`chats/` 确认在 `.gitignore` 里，`git status` 看不到它。**

