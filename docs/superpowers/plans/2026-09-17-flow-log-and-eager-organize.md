# 流程日志 + Web 投递直接走完 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ① Web 投递后直接走完整理；② 补上流程日志——自然语言、一条一个动作，落到工作日志页。

**Architecture:** 流程日志复用现成的 logging 设施：单独一个 `kb.flow` logger + 独立 handler 写 `data/logs/flow.jsonl`。流水线各处只管把「发生了什么」用大白话说出来，**不看格式**——格式在 formatter 里。

**Tech Stack:** Python 3.11、FastAPI、Jinja2、pytest（LLM 全 mock）、ruff。

**依据：** [`docs/03_问题记录.md`](../../03_问题记录.md) Q88–Q90。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `src/kb/logging_setup.py` | 加 `kb.flow` 的 handler → `data/logs/flow.jsonl` | 改 |
| `src/kb/core/flow.py` | 流程日志的写入口 + 读入口 | **新建** |
| `src/kb/core/organize.py` | 三段式各处插桩 | 改 |
| `src/kb/api/http.py` | 投递走完整理；插桩 | 改 |
| `src/kb/api/cli.py` | 同上（CLI 投递也记流程） | 改 |
| `src/kb/web/data.py` | 读流程日志 | 改 |
| `src/kb/web/router.py` | 工作日志页接数据；整理日志页加右侧栏 | 改 |
| `src/kb/web/templates/flow.html` | 卡片流 + 右侧流程链 | 重写 |
| `src/kb/web/templates/journal.html` | 加右侧栏 | 改 |
| `src/kb/web/static/style.css` | 竖排流程链、聊天栏 | 改 |

---

## Task 1: Web 投递后直接走完

**Q88：** Web（你亲手写的）不等，会话层（agent 干的）攒着。

**Files:**
- Modify: `src/kb/api/http.py`
- Modify: `tests/api/test_http.py`、`tests/web/test_router.py`

- [ ] **Step 1: 写失败测试**

`tests/api/test_http.py` 追加：

```python
def test_chat_push_runs_organize_immediately(vault):
    """Web 投的不用等——投完直接整理（Q88）。"""
    from kb.core.vault import list_drafts, list_notes

    cfg = Config("k", "u", "m", vault, None)
    llm = _ChatAwareLLM(
        _chat_json("我记一下", action="push", params={"content": "记一下 X"})
    )
    client = TestClient(create_app(cfg, llm=llm, data_dir=vault))
    client.post("/chat", json={"message": "记一下 X"})

    assert list_drafts(vault) == []              # 草稿被消费掉了
    assert [p.stem for p in list_notes(vault)]   # 笔记建出来了
```

> **`_ChatAwareLLM` 和 `_chat_json` 都已存在**（Task 4 建在 `tests/api/test_http.py` 里）：
> `_ChatAwareLLM.complete` 看系统提示里有没有「你能做的动作」来分流——
> 有就是对话（返回构造时传的那串），没有就是整理（返回文件里那个 `_plan_json()`）。
>
> **`vault` 夹具那个 tmp_path 里必须有个领域目录**，否则整理计划的目标路径通不过校验。
> 现有的 `vault` 夹具已经建了 `计算机/`（Task 4 加的）——执行时确认一下，没有就补。

`tests/web/test_router.py` 的 `test_push_from_web_creates_draft` 要改——它断言草稿留在收件箱，那是旧行为：

```python
def test_push_from_web_organizes_immediately(client, vault):
    """模板投递也直接走完（Q88）。"""
    from kb.core.vault import list_drafts

    client.post("/new", data={"content": "窗口缩放那个坑"}, follow_redirects=False)
    assert list_drafts(vault) == []        # 不留草稿
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/api/test_http.py tests/web/test_router.py -q
```

**Expected:** 两条新断言 FAIL（草稿还在收件箱）

- [ ] **Step 3: 实现——抽一个「投完就走」的函数**

`src/kb/api/http.py`，在 `push_draft` 之后加：

```python
def push_and_organize(
    cfg: Config,
    content: str,
    llm: LLM,
    *,
    source: str | None = None,
    revise_target: str | None = None,
) -> str:
    """投一条草稿，**立刻整理**，返回给人看的结果。

    Web 这条路不等（Q88）——人写完就想看到结果，留着等没有意义。
    会话层那条（`kb push` + 事后 `kb organize`）仍保留缓冲：
    agent 干活时投的东西要攒着，由会话 AI 判断时机（Q62）。
    """
    text, draft_id = push_draft(
        cfg, content, source=source, revise_target=revise_target
    )
    if not draft_id:
        return text

    results = organize.organize_selected(
        cfg.vault_path,
        [p for p in [find_draft(cfg.vault_path, draft_id)] if p],
        llm,
    )
    if not results:
        return text

    r = results[0]
    if r.kind.value == "failed":
        return f"{text}\n整理没成：{r.error}"
    if r.kind.value == "pending":
        return f"{text}\n归不了类，先搁在待归类：{r.detail}"
    return f"{text}\n已归到 {r.detail}"
```

`_chat_organize_fn` 的 `push` / `revise` 分支改成调它：

```python
        if kind == "push":
            return push_and_organize(cfg, content, get_llm(), source="Web")
        if kind == "revise":
            return push_and_organize(
                cfg, content, get_llm(), source="Web", revise_target=target
            )
```

`src/kb/web/router.py` 的 `POST /new` 也改成调它：

```python
    @router.post("/new")
    def new_note_post(content: str = Form(...)):
        """只填正文（Q87）——来源记成 Web，项目留空，其余归整理。"""
        if not content.strip():
            raise HTTPException(status_code=400, detail="正文不能为空")
        push_and_organize(cfg, content, build_llm(cfg), source="Web")
        return RedirectResponse("/journal", status_code=303)
```

> **`push_and_organize` 要公开**（不带下划线）——`web/router.py` 也调它，和 `push_draft` 同一个理由。

- [ ] **Step 4: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
git add -A && git commit -m "feat: Web 投递后直接走完整理（Q88）"
```

---

## Task 2: 流程日志的记录与存储

**Q89：** 自然语言，一条一个动作。存 `data/logs/flow.jsonl`，**不进 vault**。

**Files:**
- Modify: `src/kb/logging_setup.py`
- Create: `src/kb/core/flow.py`
- Create: `tests/core/test_flow.py`

- [ ] **Step 1: 写失败测试**

`tests/core/test_flow.py`：

```python
"""流程日志：自然语言，一条一个动作（Q89）。存服务侧，不进 vault。"""

from kb.core.flow import STEPS, emit, read_flow, set_run


def test_emit_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.core.flow.FLOW_FILE", tmp_path / "flow.jsonl")
    emit("投递", "你在网页上投递了一条草稿")
    lines = (tmp_path / "flow.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json

    row = json.loads(lines[0])
    assert row["step"] == "投递"
    assert row["text"] == "你在网页上投递了一条草稿"
    assert row["at"]


def test_emit_never_raises(tmp_path, monkeypatch):
    """写日志失败不该让正事挂掉——日志是附属品。"""
    monkeypatch.setattr("kb.core.flow.FLOW_FILE", tmp_path / "不存在" / "x" / "f.jsonl")
    emit("投递", "x")          # 不抛


def test_set_run_tags_subsequent_entries(tmp_path, monkeypatch):
    monkeypatch.setattr("kb.core.flow.FLOW_FILE", tmp_path / "flow.jsonl")
    set_run("20260917-1400")
    emit("投递", "a")
    rows = read_flow(tmp_path)
    assert rows[0]["run"] == "20260917-1400"


def test_read_flow_missing_file(tmp_path):
    assert read_flow(tmp_path) == []


def test_steps_are_the_pipeline_order():
    """链上的顺序就是流水线的顺序——页面的流程图照它画。"""
    assert STEPS == ["投递", "规划", "校验", "审核", "落盘", "提交"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_flow.py -q
```

**Expected:** `ModuleNotFoundError: No module named 'kb.core.flow'`

- [ ] **Step 3: 实现**

`src/kb/logging_setup.py` 加 handler：

```python
FLOW_FILE = LOG_DIR / "flow.jsonl"

_FLOW_FORMAT = "%(message)s"          # 消息本身就是一行 JSON，见 core/flow.py
```

`setup_logging()` 里，在给根 logger 加 handler 之后加：

```python
    flow = logging.getLogger("kb.flow")
    flow.propagate = False            # 不再往根 logger 冒泡——否则流程会同时进运行日志
    if not any(isinstance(h, logging.handlers.RotatingFileHandler)
               and Path(h.baseFilename) == FLOW_FILE for h in flow.handlers):
        fh = logging.handlers.RotatingFileHandler(
            FLOW_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter(_FLOW_FORMAT))
        flow.addHandler(fh)
        flow.setLevel(logging.INFO)
```

`src/kb/core/flow.py`：

```python
"""流程日志——「从投递到落库，中间发生了什么」（Q89）。

**用自然语言写，一条就是一个动作。** 不是结构化字段：
读它的人想知道「模型决定放进 计算机/git」，不想看 `target_path=...`。

**存服务侧（`data/logs/flow.jsonl`），绝不进 vault**——它是过程记录不是知识
（Q80 的分界）。进去会被检索、被当知识。

写失败一律吞掉：**日志是附属品，不该让正事挂掉。**
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from kb.logging_setup import FLOW_FILE

_log = logging.getLogger("kb.flow")

# 链上的顺序就是流水线的顺序——工作日志页的流程图照它画
STEPS = ["投递", "规划", "校验", "审核", "落盘", "提交"]

_run: str | None = None


def set_run(run_id: str) -> None:
    """标记「这一批整理」的开始。之后记的流程都挂在这个 id 下。"""
    global _run
    _run = run_id


def emit(step: str, text: str) -> None:
    """记一条流程。`step` 取 `STEPS` 里的一个。"""
    row = {
        "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "run": _run or "",
        "step": step,
        "text": text,
    }
    try:
        _log.info(json.dumps(row, ensure_ascii=False))
    except Exception:      # noqa: BLE001 —— 日志失败不能拖垮正事
        pass


def read_flow(data_dir: Path, limit: int = 500) -> list[dict]:
    """读最近的流程记录，**按时间正序**。文件不存在返回空列表。"""
    path = data_dir / "logs" / FLOW_FILE.name
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue           # 半行（进程被杀）——跳过，别让整页挂掉
    return rows[-limit:]
```

> **`read_flow` 收 `data_dir` 而不是直接读模块常量**——和 `chat_store` 同一个理由：测试要能注入临时目录。

- [ ] **Step 4: 跑测试确认通过 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider tests/core/test_flow.py -q
git add -A && git commit -m "feat: 流程日志的存储——自然语言、一条一个动作（Q89）"
```

---

## Task 3: 流水线插桩

**在各处把「发生了什么」说出来。** 这一步只加 `flow.emit(...)`，不改逻辑。

**Files:**
- Modify: `src/kb/core/organize.py`、`src/kb/api/http.py`、`src/kb/api/cli.py`

- [ ] **Step 1: 写失败测试**

`tests/core/test_organize.py` 追加：

```python
def test_organize_emits_flow_steps(vault, monkeypatch):
    """整理会把每一步说进流程日志（Q89）。"""
    rows = []
    monkeypatch.setattr("kb.core.flow.emit", lambda step, text: rows.append((step, text)))

    _run(vault, FakeLLM([_plan_json()]))       # 复用文件里现有的辅助函数

    steps = [s for s, _ in rows]
    assert "规划" in steps
    assert "校验" in steps
    assert "落盘" in steps
```

- [ ] **Step 2: 跑测试确认失败** — 没有 `规划` 那些（emit 还没被调）

- [ ] **Step 3: 插桩**

`src/kb/core/organize.py`——三段的边界各说一句。**措辞用大白话**，别写 `target_path`：

```python
# make_plan 里，LLM 返回并校验通过之后
flow.emit("规划", f"模型决定放进「{plan.target_path}」，类型是{plan.frontmatter.get('类型') or '未定'}")

# validate_plan 通过之后
flow.emit("校验", "校验通过")

# review.review_plan 真的调了 LLM 时（改了路径）
flow.emit("审核", f"审核觉得和已有分类重了，改用「{plan.target_path}」")

# apply_plan 落盘之后
flow.emit("落盘", f"{'新建' if plan.outcome is Outcome.CREATE else '并入'} {plan.target_path}")

# commit_changes 之后
flow.emit("提交", f"提交了一个 commit：「{message.splitlines()[0]}」")
```

`src/kb/api/http.py` 的 `push_draft` 与 `/organize` 端点：

```python
# push_draft 成功落盘后
flow.emit("投递", f"你在网页上投递了一条草稿，编号 {draft.id}")

# /organize 端点开头
flow.set_run(f"{datetime.now():%Y%m%d-%H%M%S}")
flow.emit("投递", f"开始整理，共 {len(paths)} 条草稿")
```

> **`set_run` 在每个批次开头调一次**，之后这一批的流程都挂在同一个 `run` 下——工作日志页按它分组画流程图。

`src/kb/api/cli.py` 的 `cmd_push` 不用动（它走 HTTP，插桩在服务侧）。

- [ ] **Step 4: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
git add -A && git commit -m "feat: 流水线插桩——每一步都把话说进流程日志"
```

---

## Task 4: 工作日志页

**卡片流（粉色）+ 右侧栏的竖排流程链。**

**Files:**
- Modify: `src/kb/web/data.py`、`src/kb/web/router.py`
- Rewrite: `src/kb/web/templates/flow.html`
- Modify: `src/kb/web/static/style.css`
- Modify: `tests/web/test_router.py`、`tests/web/test_data.py`

- [ ] **Step 1: 写失败测试**

`tests/web/test_data.py` 追加：

```python
def test_group_flow_by_run():
    rows = [
        {"run": "a", "step": "投递", "text": "投了", "at": "t1"},
        {"run": "a", "step": "规划", "text": "规划了", "at": "t2"},
        {"run": "b", "step": "投递", "text": "又投了", "at": "t3"},
    ]
    got = group_flow(rows)
    assert [g["run"] for g in got] == ["b", "a"]        # 新的在前
    assert [r["step"] for r in got[1]["rows"]] == ["投递", "规划"]


def test_group_flow_marks_reached_steps():
    rows = [
        {"run": "a", "step": "投递", "text": "x", "at": "t"},
        {"run": "a", "step": "落盘", "text": "y", "at": "t"},
    ]
    got = group_flow(rows)
    assert got[0]["reached"] == {"投递", "落盘"}
```

`tests/web/test_router.py` 追加：

```python
def test_flow_page_renders_chain(client, vault):
    from kb.core.flow import emit, set_run

    set_run("20260917-1400")
    emit("投递", "你在网页上投递了一条草稿")
    emit("规划", "模型决定放进「计算机/git」")
    body = client.get("/flow").text
    assert "你在网页上投递了一条草稿" in body
    assert "模型决定放进" in body
    assert "提交" in body            # 链上没走到的那几步也要画出来
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 `web/data.py` 的分组**

```python
def group_flow(rows: list[dict]) -> list[dict]:
    """按 run 分组，**新的在前**。每组带上「走到了哪几步」。

    同一批整理的流程共用一个 run id；页面上一条流程链对应一组。
    """
    groups: dict[str, dict] = {}
    for row in rows:
        run = row.get("run") or "（未分组）"
        g = groups.setdefault(run, {"run": run, "rows": [], "reached": set(), "at": ""})
        g["rows"].append(row)
        g["reached"].add(row.get("step", ""))
        g["at"] = g["at"] or row.get("at", "")
    return list(reversed(list(groups.values())))
```

`web/router.py` 的 `flow` 路由：

```python
    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request):
        groups = group_flow(read_flow(data_dir))
        return templates.TemplateResponse(
            request, "flow.html", _ctx("flow", groups=groups, steps=STEPS)
        )
```

- [ ] **Step 4: 重写 `flow.html`**

```html
{% extends "base.html" %}
{% block title %}工作日志 · KN_Base{% endblock %}
{% block content %}
<div class="chat-layout">
  <section>
    <div class="page-head">
      <h1>工作日志</h1>
      <p>从投递到落库，中间每一步。这一份是过程记录，留在服务侧，不进 vault。</p>
    </div>

    {% if not groups %}
      <div class="empty">还没有流程记录。投一条、整理一次，这里就有了。</div>
    {% endif %}

    {% for g in groups %}
      <article class="card flow">
        <h3>{{ g.at }}</h3>
        <ul>
          {% for r in g.rows %}<li>{{ r.text }}</li>{% endfor %}
        </ul>
      </article>
    {% endfor %}
  </section>

  <aside class="chat-history">
    <h2>流程</h2>
    {% for g in groups %}
      <div class="chain">
        {% for step in steps %}
          <div class="chain-step {{ 'done' if step in g.reached else 'todo' }}">
            <span class="chain-mark">{{ '✓' if step in g.reached else '○' }}</span>
            <span>{{ step }}</span>
          </div>
          {% if not loop.last %}<div class="chain-line"></div>{% endif %}
        {% endfor %}
      </div>
    {% endfor %}
  </aside>
</div>
{% endblock %}
```

- [ ] **Step 5: 加样式**

竖排流程链——`.chain` 是 flex column，`.chain-step` 一行一个，`.done` 主蓝、`.todo` 灰；`.chain-line` 是那根竖线（`width: 1px; height: 12px; background: var(--line)`，居中）。

- [ ] **Step 6: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
git add -A && git commit -m "feat: 工作日志页——卡片流 + 竖排流程链（Q89）"
```

---

## Task 5: 整理日志页加右侧栏

**Q90：** 手机聊天式，发日志总结的文本。

**Files:**
- Modify: `src/kb/web/templates/journal.html`、`src/kb/web/static/style.css`
- Modify: `tests/web/test_router.py`

- [ ] **Step 1: 写失败测试**

```python
def test_journal_has_side_summary(client):
    body = client.get("/journal").text
    assert "chat-history" in body                    # 右侧栏在
    assert "23:20 整理 1 条草稿" in body             # 栏里发的是整理总结
```

- [ ] **Step 2: 改 `journal.html`** —— 套 `.chat-layout` 两栏，左卡片流、右聊天栏。右侧每条是「一节整理」，样式复用 `.bubble.assistant`。

- [ ] **Step 3: 跑测试 + 提交**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
git add -A && git commit -m "feat: 整理日志页加右侧栏（Q90）"
```

---

## Self-Review

**1. 规格覆盖：**

| 定案 | 落在哪 |
|---|---|
| Q88 Web 投递直接走完 | Task 1 |
| Q89 流程日志自然语言一条一动作 | Task 2（存）+ Task 3（写） |
| Q89 右侧栏竖排流程链 | Task 4 |
| Q90 整理日志右侧栏 | Task 5 |

**2. 占位符扫描：** 无 TBD / TODO / 无代码的代码步骤。

**3. 类型一致性：**

- `flow.emit(step: str, text: str) -> None`：Task 2 定义，Task 3 到处调
- `flow.set_run(run_id: str) -> None`：Task 2 定义，Task 3 在 `/organize` 开头调
- `flow.read_flow(data_dir, limit=500) -> list[dict]`：Task 2 定义，Task 4 用
- `group_flow(rows) -> list[dict]`，每项 `{run, rows, reached: set, at}`：Task 4 定义并测
- `push_and_organize(cfg, content, llm, *, source, revise_target) -> str`：Task 1 定义
- `flow.STEPS`：Task 2 定义，Task 4 的模板用它画链

**4. 已知风险：**

- **`flow.emit` 用 `monkeypatch` 替换**（Task 3 Step 1）——它是个模块级函数，替换后 `organize.py` 里的 `flow.emit(...)` 调用也会被换掉（因为是 `flow.emit` 属性访问）。**如果 `organize.py` 写成 `from kb.core.flow import emit`，替换就不生效**——**必须写 `from kb.core import flow` 然后 `flow.emit(...)`**。这条很容易漏。
- **`set_run` 是模块级可变状态**——并发整理会串。当前服务是单进程、整理是同步的，够用；真并发时得改成显式传参。**知道有这个边界。**
- **Task 3 的插桩会改动 `organize.py` 的多处**，而它是全项目测试最密的地方（30 个测试）。跑全量再提交。

---

## 验收

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -p no:cacheprovider -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**端到端（真实 LLM）：** 打开 `http://127.0.0.1:51823`

1. 说「记一下：今天的某个坑」→ 应回「已归到 计算机/…」**（不再只是收下）**
2. `kb.bat inbox` → **应该是空的**（Web 投的直接走完了）
3. 打开工作日志页 → 有卡片，右侧竖排链走得通的步骤高亮
4. 打开整理日志页 → 右侧栏有总结

**最后：`data/logs/flow.jsonl` 确认在 gitignore 覆盖范围内（`data/` 整棵）。**
