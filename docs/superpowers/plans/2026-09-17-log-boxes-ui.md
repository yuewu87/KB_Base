# 箱子与页签（UI 层）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 三个日志页各带一列按天的「箱子」，右侧栏加两个竖排页签；巡检单开一页；「还需调整」改成带着用户的话重跑一次。

**Architecture:** 右侧栏变成「页签 + 面板」结构，页签用几行 JS 切换（`base.html` 折叠侧栏已经在用 `onclick`，不引入框架）。箱子按钮复用现有的「会话按钮」样式。巡检页是新的第六个入口，原来挤在工作日志侧栏里的报告搬过去。

**Tech Stack:** Python 3.11、FastAPI、Jinja2、pytest、ruff、conda 环境 `kn_base`

**前置依赖：** **必须先做完 [`2026-09-17-log-boxes-storage.md`](2026-09-17-log-boxes-storage.md)。** 本计划用它的 `flow.list_days` / `flow.read_day` / `flow.latest_run_rows` / `data.journal_days` / `data.read_journal` / `data.runtime_days` / `data.read_runtime` / `data.box_label`。

**设计全文：** [`docs/superpowers/specs/2026-09-17-log-boxes-design.md`](../specs/2026-09-17-log-boxes-design.md)

---

## 文件结构

| 文件 | 职责 | 本计划动它什么 |
|---|---|---|
| `src/kb/core/sweep.py` | 巡检的规划 | `build_prompt`/`make_plan` 多收一个 `requirement` |
| `src/kb/api/http.py` | `run_sweep` 编排 | 透传 `requirement` |
| `src/kb/web/router.py` | 路由 | 新增 `/sweep`；`/sweep/reply` 改走重跑；`/sweep/run` 重定向改 `/sweep`；三个日志页传 `day`/`days`/`latest` |
| `src/kb/web/templates/_tabs.html` | **新增**，竖排页签 | |
| `src/kb/web/templates/_boxes.html` | **新增**，箱子列表 | |
| `src/kb/web/templates/journal.html` | 整理日志页 | 换骨架 |
| `src/kb/web/templates/flow.html` | 工作日志页 | 换骨架，报告那块搬走 |
| `src/kb/web/templates/runtime.html` | 运行日志页 | 换骨架，加右侧栏 |
| `src/kb/web/templates/sweep.html` | **新增**，巡检页 | |
| `src/kb/web/templates/base.html` | 左栏 | 加「巡检」，去掉「巡检一次」；加页签切换脚本 |
| `src/kb/web/static/style.css` | 样式 | 竖排页签、箱子、巡检页 |
| `tests/core/test_sweep.py` | | 带要求重跑 |
| `tests/api/test_sweep_api.py` | | `run_sweep` 透传 |
| `tests/web/test_router.py` | | 路由与页面 |
| `docs/01_架构.md`、`docs/03_问题记录.md`、`README.md` | | 补 `/sweep` 路由与页面清单 |

**测试总数基线：** 存储层计划跑完后的数字，以实跑为准。

**命令速查（本机 `conda run` 会报内部错误，勿用）：**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -v
```

---

## Task 1: 巡检带着用户的话重跑（规划层）

**先做后端。** 页面最后做——它依赖路由，路由依赖这里。

**Files:**
- Modify: `src/kb/core/sweep.py:74-150`
- Modify: `tests/core/test_sweep.py`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/core/test_sweep.py` 末尾：

```python
# ---------- 带用户要求重跑（Q96）----------

class _CaptureLLM:
    """把收到的提示词留下来，好断言要求进没进。"""

    def __init__(self, reply: str = '{"tag_merges": [], "dir_merges": [], "summary": "无"}'):
        self.reply = reply
        self.seen: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.seen.append((system, user))
        return self.reply


def test_prompt_is_byte_identical_without_requirement(vault):
    """不带要求时，提示词必须与加这个参数**之前逐字相同**——不许回归。"""
    from kb.core.sweep import build_prompt

    assert build_prompt(vault) == build_prompt(vault, None)


def test_prompt_carries_the_requirement(vault):
    from kb.core.sweep import build_prompt

    prompt = build_prompt(vault, "那两个分类不该合并，拆开")
    assert "那两个分类不该合并，拆开" in prompt
    assert "用户对上次结果的意见" in prompt


def test_requirement_goes_to_the_model(vault):
    """真的送到了模型手里——不只是拼进了字符串。"""
    from kb.core.sweep import make_plan

    llm = _CaptureLLM()
    make_plan(vault, llm, requirement="把 art 拆回来")

    system, user = llm.seen[0]
    assert "把 art 拆回来" in system
    assert "把 art 拆回来" in user


def test_no_requirement_leaves_user_message_alone(vault):
    """不带要求时，user 那句不许变——它是回归的锚点。"""
    from kb.core.sweep import make_plan

    llm = _CaptureLLM()
    make_plan(vault, llm)
    assert llm.seen[0][1] == "请给出合并方案。"
```

> 测试里的 `vault` 夹具是 `tests/core/test_sweep.py` 现成的，别另建。

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_sweep.py -k "requirement or prompt_carries or byte_identical" -v
```

**Expected:** `test_prompt_carries_the_requirement` 与 `test_requirement_goes_to_the_model` **FAIL**（要求没进提示词）。

**另外两个会 PASS**——`build_prompt(vault, None)` 现在会抛 `TypeError`，`test_prompt_is_byte_identical_without_requirement` 也 FAIL。以实跑为准，**只要红的是「要求没进提示词」那两个就对了**。

- [ ] **Step 3: 改实现**

`src/kb/core/sweep.py` 里 `build_prompt` 的签名与结尾改掉（第 74 行与第 113 行）：

```python
def build_prompt(vault_root: Path, requirement: str | None = None) -> str:
    """给模型的输入——**只有标签和目录，没有正文**。

    `requirement` 非空时是用户对**上次结果**的意见（Q96）：点「还需调整」
    写下的话。它说的往往是「上次那步做错了」，所以放在任务正下方、
    硬规矩之前——先按它调整，其余照旧。
    """
```

函数体最后那段 `return f"""..."""` 里的 `## 硬规矩` 前插入：

```python
    extra = ""
    if requirement:
        extra = f"""
## 用户对上次结果的意见

{requirement}

**先按这条意见调整。** 它说的是上次收拾里做得不对的地方（比如「那两个分类
不该合并」）；除此之外，下面的硬规矩一条都不放宽。
"""
```

然后在 `parse_plan` 之前补上 `extra`，并把**整段 `return` 语句**替换成下面这份
（`extra` 自带尾随换行，所以为空时那段文本**与现在逐字相同**——Step 1 那条
`test_prompt_is_byte_identical_without_requirement` 就是在守这个）：

```python
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
{extra}
## 硬规矩

1. **只合并明显重复的。** 拿不准就不动——宁可少合并，不要合并错。
   两个词意思相近但不是一回事（比如「编码」和「字符集」），不算重复。
2. **`to` 必须是上面列过的、已经存在的名字。** 不许新建标签或目录。
3. **`to` 不能同时出现在 `from` 里**（那会绕圈）。
4. **没得合并就返回空数组**，`summary` 里说「没什么要收拾的」。
   空计划是完全正常的结果——大多数时候都该是空的。"""
```

**`extra` 的定义必须紧挨着 `return` 之前**，且它**以换行开头**，这样为空时 `}}` 与 `## 硬规矩` 之间的关系和原来逐字一致。

`make_plan`（第 144 行）改成：

```python
def make_plan(vault_root: Path, llm: LLM, requirement: str | None = None) -> SweepPlan:
    """跑一次巡检的规划。只读——不碰文件。

    `requirement` 是用户对上次结果的意见（Q96）。**同时进 system 与 user**
    ——只说一遍模型容易漏，这不是「重复」是「强调」。
    """
    user = "请给出合并方案。"
    if requirement:
        user = f"请给出合并方案。用户对上次结果的意见：{requirement}"
    try:
        raw = llm.complete(build_prompt(vault_root, requirement), user)
    except LLMError as exc:
        raise SweepError(f"巡检失败：{exc}") from exc
    return parse_plan(raw)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_sweep.py -v
```

**Expected:** 全 PASS（含原有的）

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/sweep.py tests/core/test_sweep.py
git commit -m "feat: 巡检可以带着用户的要求重跑（Q96）"
```

---

## Task 2: `run_sweep` 透传要求

**Files:**
- Modify: `src/kb/api/http.py:210-244`
- Modify: `tests/api/test_sweep_api.py`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/api/test_sweep_api.py` 末尾：

```python
def test_run_sweep_passes_requirement_to_the_model(vault, tmp_path):
    """用户的要求要真的进到模型手里。"""
    from kb.api.http import run_sweep

    llm = _CaptureLLM()
    run_sweep(vault, tmp_path, llm, requirement="那两个分类不该合并")

    assert "那两个分类不该合并" in llm.seen[0][0]


def test_run_sweep_without_requirement_unchanged(vault, tmp_path):
    """不传要求时，prompt 与以前一样——不许回归。"""
    from kb.api.http import run_sweep

    llm = _CaptureLLM()
    run_sweep(vault, tmp_path, llm)
    assert "用户对上次结果的意见" not in llm.seen[0][0]
```

并在文件里补一个抓提示词的假模型（若已有类似的，改名复用即可）：

```python
class _CaptureLLM:
    """留下一份提示词，好断言要求进没进。空计划——不落盘。"""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.seen.append((system, user))
        return '{"tag_merges": [], "dir_merges": [], "summary": "无"}'
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/api/test_sweep_api.py -k "requirement" -v
```

**Expected:** `test_run_sweep_passes_requirement_to_the_model` **FAIL**——`TypeError: run_sweep() got an unexpected keyword argument 'requirement'`

- [ ] **Step 3: 改实现**

`src/kb/api/http.py` 的 `run_sweep` 签名（第 210 行）与 `make_plan` 调用（第 221 行）改成：

```python
def run_sweep(
    vault_root: Path,
    data_dir: Path,
    llm: LLM,
    requirement: str | None = None,
) -> dict:
    """跑一次巡检：规划 → 校验 → 落盘 → commit → 存报告。

    **它走的是和整理草稿同一条链**，只是输入换成了整个库的标签与目录。

    `requirement` 非空时是「还需调整」带上来的用户意见（Q96）——巡检**带着
    它重跑一次**，不是撤销上次的改动。重跑会产生**新的一个 commit**，
    上一个留着（与 Q46「一次整理 = 一个 commit」一致）。
    """
```

以及：

```python
    plan = sweep.make_plan(vault_root, llm, requirement)
```

`_sweep_in_background`（第 247 行）不用改——它调 `run_sweep` 时不给要求，走默认。

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/api/test_sweep_api.py -v
```

**Expected:** 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/kb/api/http.py tests/api/test_sweep_api.py
git commit -m "feat: run_sweep 透传用户要求"
```

---

## Task 3: 路由 —— 巡检页与三个日志页

**Files:**
- Modify: `src/kb/web/router.py`
- Modify: `tests/web/test_router.py`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/web/test_router.py` 末尾：

```python
# ---------- 箱子与页签（Q93）----------

def test_journal_page_shows_the_latest_day_by_default(client):
    """不带 d 参数 → 落在**最新一个有箱子的日子**，不是「今天」。"""
    r = client.get("/journal")
    assert r.status_code == 200
    assert "2026-09-16" in r.text          # 夹具里唯一的一天


def test_journal_page_unknown_day_is_empty_not_404(client):
    """指向没有日志的一天 → 空态，不 404。书签过期不该看到错误页。"""
    r = client.get("/journal?d=2020-01-01")
    assert r.status_code == 200
    assert "2020-01-01" not in r.text      # 没选中它


def test_journal_page_switches_day(client, vault):
    journal = vault / "_索引" / "整理日志"
    (journal / "2026-09-17.md").write_text(
        "## 09:27 整理 1 条草稿\n\n- 新建：[[窗边的花]]\n", encoding="utf-8"
    )

    r = client.get("/journal?d=2026-09-16")
    assert "队列串行化" in r.text


def test_journal_page_lists_boxes(client):
    """箱子按钮在右侧栏，名字是界面叫法。"""
    r = client.get("/journal")
    assert "26_9_16箱子" in r.text


def test_flow_page_has_both_tabs(client):
    r = client.get("/flow")
    assert r.status_code == 200
    assert "流程图" in r.text
    assert "历史" in r.text


def test_runtime_page_has_no_report_tab(client):
    """运行日志页没有「报告」页签，只有箱子。"""
    r = client.get("/runtime")
    assert r.status_code == 200
    assert ">报告<" not in r.text
    assert "历史" not in r.text


def test_sweep_page_renders(client):
    r = client.get("/sweep")
    assert r.status_code == 200
    assert "巡检" in r.text


def test_flow_page_no_longer_carries_the_sweep_report(client, vault, tmp_path):
    """巡检报告搬去巡检页了——工作日志页侧栏不再有那块。"""
    from kb.core import sweep_state

    sweep_state.save_report(
        tmp_path,
        {"summary": "合并了 2 处近义标签", "tag_merges": [], "dir_merges": []},
    )
    r = client.get("/flow")
    assert "合并了 2 处近义标签" not in r.text

    r = client.get("/sweep")
    assert "合并了 2 处近义标签" in r.text
```

> `client` 与 `vault` 是文件里现成的夹具。**注意 `client` 夹具用的 `data_dir` 是不是 `tmp_path`**——若不是，`test_flow_page_no_longer_carries_the_sweep_report` 里的 `tmp_path` 要换成夹具实际用的那个目录。**先读 `client` 夹具的定义再写这一步。**

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web/test_router.py -k "journal_page or flow_page or runtime_page or sweep_page" -v
```

**Expected:** `/sweep` 相关 404；页签相关断言失败。

- [ ] **Step 3: 改实现**

`src/kb/web/router.py`：

**(a)** `build_router` 里注册 Jinja 全局（第 35 行 `templates = Jinja2Templates(...)` 之后）：

```python
# 模板里现算箱子名——三个页面都要用，注册成全局比每个端点传一次干净
templates.env.globals["box_label"] = box_label
```

**(b)** 三个日志页端点改成带 `day` / `days` / `latest`（若存储层计划已改过签名，这里补的是 `latest` 与 `tabs`）：

`/journal`：

```python
    @router.get("/journal", response_class=HTMLResponse)
    def journal(request: Request, d: str = ""):
        days = journal_days(cfg.vault_path)
        day = d if d in days else (days[0] if days else "")
        return templates.TemplateResponse(
            request,
            "journal.html",
            _ctx(
                "journal",
                days=days,
                day=day,
                sections=read_journal(cfg.vault_path, day) if day else [],
                latest=latest_run_rows(data_dir),
            ),
        )
```

`/flow`：

```python
    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request, d: str = ""):
        days = flow_days(data_dir)
        day = d if d in days else (days[0] if days else "")
        return templates.TemplateResponse(
            request,
            "flow.html",
            _ctx(
                "flow",
                days=days,
                day=day,
                groups=group_flow(read_flow_day(data_dir, day), steps=STEPS),
                steps=STEPS,
                latest=latest_run_rows(data_dir),
            ),
        )
```

`/runtime`：

```python
    @router.get("/runtime", response_class=HTMLResponse)
    def runtime_page(request: Request, d: str = ""):
        days = runtime_days(LOG_DIR)
        day = d if d in days else (days[0] if days else "")
        return templates.TemplateResponse(
            request,
            "runtime.html",
            _ctx(
                "runtime",
                log_dir=str(LOG_DIR),
                days=days,
                day=day,
                log_text=read_runtime(LOG_DIR, day) if day else "",
            ),
        )
```

**(c)** 新增巡检页与改造两个动作端点（放在 `/runtime` 之前）：

```python
    def _run_sweep_or_report(requirement: str | None) -> RedirectResponse:
        """跑一次巡检，失败就落一份没读的报告——**人在这儿等着，不能甩 500**。

        写成报告的语义和后台那条失败路径一致（`_sweep_in_background` 也这么落），
        巡检页上看得见原因。
        """
        try:
            run_sweep(cfg.vault_path, data_dir, get_llm(), requirement=requirement)
        except sweep.SweepError as exc:
            sweep_state.save_report(
                data_dir,
                {
                    "summary": f"这次巡检没跑成：{exc}",
                    "tag_merges": [],
                    "dir_merges": [],
                },
            )
        return RedirectResponse("/sweep", status_code=303)

    @router.get("/sweep", response_class=HTMLResponse)
    def sweep_page(request: Request):
        """巡检页——报告与两个按钮的家（Q93）。

        **报告读过了也显示**，只是不再高亮：这一页就是它的家。原来那条
        「没读才冒出来」的逻辑是侧栏时代的（那块侧栏已经搬走了）。
        """
        state = sweep_state.load_state(data_dir)
        return templates.TemplateResponse(
            request,
            "sweep.html",
            _ctx(
                "sweep",
                report=state.get("report"),
                last_sweep=state.get("last_sweep"),
            ),
        )

    @router.post("/sweep/reply")
    def sweep_reply(reply: str = Form(...), note: str = Form("")):
        """报告下面那两个按钮。

        「我知道了」= 标记已读。
        「还需调整」= **带着用户的要求重跑一次巡检**（Q96）——不是把意见
        当一条草稿投出去。后者要改的往往是**上一次巡检刚做的事**，
        投一条新草稿跟它对不上。
        """
        if reply == "知道了":
            sweep_state.mark_read(data_dir)
            return RedirectResponse("/sweep", status_code=303)
        return _run_sweep_or_report(note.strip() or None)

    @router.post("/sweep/run")
    def sweep_run():
        """手动跑一次巡检，**不受 6 天限制**——是你主动要跑的。

        **同步跑**：巡检是低频动作，等一会儿可以接受，跑完直接看报告。
        """
        return _run_sweep_or_report(None)
```

**(d)** 删掉原来的 `/sweep/reply`（第 127-140 行）与 `/sweep/run`（第 142-166 行）——上面那三个替掉了它们。

**(e)** import 补 `latest_run_rows`：

```python
from kb.core.flow import STEPS, latest_run_rows, list_days as flow_days, read_day as read_flow_day
```

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web -v
```

**Expected:** 路由层的用例全 PASS（模板还在改，个别断言可能还红——Task 4/5/6 处理）。

- [ ] **Step 5: 提交**

```bash
git add src/kb/web/router.py tests/web/test_router.py
git commit -m "feat: 巡检单开一页；三个日志页按天取数"
```

---

## Task 4: 两个模板片段

**Files:**
- Create: `src/kb/web/templates/_tabs.html`
- Create: `src/kb/web/templates/_boxes.html`
- Modify: `src/kb/web/templates/base.html`（页签切换脚本）

- [ ] **Step 1: 写 `_tabs.html`**

```jinja
{# 竖排页签。`tabs` 是 [(面板 id, 名字)]，空列表就不渲染（运行日志页）。

   点击靠 base.html 底部那几行脚本切换面板——不引入框架，
   和侧栏折叠用的是同一招（`onclick`）。 #}
{% if tabs %}
<div class="tabs">
  {% for panel, name in tabs %}
    <button type="button" class="tab {{ 'active' if loop.first }}"
            data-panel="{{ panel }}">{{ name }}</button>
  {% endfor %}
</div>
{% endif %}
```

- [ ] **Step 2: 写 `_boxes.html`**

```jinja
{# 箱子列表。`days` 是倒序的日期，`day` 是选中的那个。

   箱子名是**界面叫法**（`26_9_17箱子`），落盘还是 `2026-09-17.*`
   ——整理日志是 vault 里的笔记，文件名跟标题一致是现有约定。 #}
{% if days %}
  {% for d in days %}
    <a class="chat-item {{ 'active' if d == day }}" href="?d={{ d }}">
      {{ box_label(d) }}
    </a>
  {% endfor %}
{% else %}
  <p class="muted">这一天还没有日志。</p>
{% endif %}
```

> **`href="?d={{ d }}"` 用的是相对形式**——浏览器会保留当前路径，只换查询串。
> 写死 `/journal?d=` 的话，三个页面就得各传一个 `base` 参数进来。

- [ ] **Step 3: 加页签切换脚本**

`base.html` 的 `</body>` 之前插入：

```html
  <script>
    // 竖排页签：点哪个，就只显示它对应的面板。
    // 只有几行——为这个拖一个框架进来不划算（和侧栏折叠同一个路子）。
    document.querySelectorAll('.tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        const aside = tab.closest('.tabbed');
        aside.querySelectorAll('.tab').forEach(function (t) {
          t.classList.toggle('active', t === tab);
        });
        aside.querySelectorAll('.pane').forEach(function (p) {
          p.hidden = p.dataset.pane !== tab.dataset.panel;
        });
      });
    });
  </script>
```

- [ ] **Step 4: 提交**

```bash
git add src/kb/web/templates/_tabs.html src/kb/web/templates/_boxes.html src/kb/web/templates/base.html
git commit -m "feat: 竖排页签与箱子列表的模板片段"
```

---

## Task 5: 三个日志页换骨架

**Files:**
- Modify: `src/kb/web/templates/journal.html`
- Modify: `src/kb/web/templates/flow.html`
- Modify: `src/kb/web/templates/runtime.html`

- [ ] **Step 1: 改写 `journal.html`**

整份替换：

```jinja
{% extends "base.html" %}
{% block title %}整理日志 · KN_Base{% endblock %}
{% block content %}
<div class="chat-layout">
  <section>
    <div class="page-head">
      <h1>整理日志</h1>
      <p>按天聚合，一次整理一张卡片。这一份是知识，进 vault，可被检索。</p>
    </div>

    {% if not day %}
      <div class="empty">
        还没有整理记录。<br>
        投一条草稿（<code>kb push</code>），再 <code>kb organize</code>。
      </div>
    {% else %}
      <h2 class="day">{{ box_label(day) }}</h2>
      {% for title, items in sections %}
        <article class="card journal">
          <h3>{{ title }}</h3>
          {% if items %}
            <ul>
              {% for item in items %}<li>{{ item }}</li>{% endfor %}
            </ul>
          {% else %}
            <p class="muted">（这一节没有条目）</p>
          {% endif %}
        </article>
      {% endfor %}
    {% endif %}
  </section>

  <aside class="chat-history tabbed">
    {% set tabs = [("report", "报告"), ("history", "历史")] %}
    {% include "_tabs.html" %}

    <div class="pane" data-pane="report">
      <h2>最近一次整理</h2>
      {% if latest %}
        {% for r in latest %}
          <div class="bubble assistant">
            <span class="bubble-at">{{ r.at[-8:] }}</span>{{ r.text }}
          </div>
        {% endfor %}
      {% else %}
        <p class="muted">还没有整理过。</p>
      {% endif %}
    </div>

    <div class="pane" data-pane="history" hidden>
      <h2>箱子</h2>
      {% include "_boxes.html" %}
    </div>
  </aside>
</div>
{% endblock %}
```

- [ ] **Step 2: 改写 `flow.html`**

整份替换：

```jinja
{% extends "base.html" %}
{% block title %}工作日志 · KN_Base{% endblock %}
{% block content %}
<div class="chat-layout">
  <section>
    <div class="page-head">
      <h1>工作日志</h1>
      <p>从投递到落库，中间每一步。这一份是过程记录，留在服务侧，不进 vault。</p>
    </div>

    {% if not day %}
      <div class="empty">还没有流程记录。投一条、整理一次，这里就有了。</div>
    {% else %}
      <h2 class="day">{{ box_label(day) }}</h2>
      {% for g in groups %}
        <article class="card flow">
          <h3>{{ g.at }}</h3>
          <ul>
            {% for r in g.rows %}<li>{{ r.text }}</li>{% endfor %}
          </ul>
        </article>
      {% endfor %}
    {% endif %}
  </section>

  <aside class="chat-history tabbed">
    {% set tabs = [("chart", "流程图"), ("history", "历史")] %}
    {% include "_tabs.html" %}

    <div class="pane" data-pane="chart">
      <h2>最近一次</h2>
      {% if latest %}
        {% set reached = latest | map(attribute="step") | list %}
        <div class="chain">
          {% for step in steps %}
            {% set state = 'done' if step in reached else 'todo' %}
            <div class="chain-step {{ state }}">
              {% if state == 'done' %}
                <svg class="mark" viewBox="0 0 16 16" role="img">
                  <title>{{ step }}：走过</title>
                  <circle cx="8" cy="8" r="7" fill="currentColor"/>
                  <path d="M4.8 8.3l2.1 2.1 4.3-4.5" fill="none" stroke="#fff"
                        stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              {% else %}
                <svg class="mark" viewBox="0 0 16 16" role="img">
                  <title>{{ step }}：还没走到</title>
                  <circle cx="8" cy="8" r="6.3" fill="none" stroke="currentColor" stroke-width="1.4"/>
                </svg>
              {% endif %}
              <span>{{ step }}</span>
            </div>
            {% if not loop.last %}<div class="chain-line"></div>{% endif %}
          {% endfor %}
        </div>
      {% else %}
        <p class="muted">还没有记录。</p>
      {% endif %}
    </div>

    <div class="pane" data-pane="history" hidden>
      <h2>箱子</h2>
      {% include "_boxes.html" %}
    </div>
  </aside>
</div>
{% endblock %}
```

> **流程图那一栏只画「走过 / 没走到」两态。** 原来的 `skipped`（没触发，比如审核）
> 要用 `group_flow` 才能算出来，而「最近一次」这一份走的是 `latest_run_rows`，
> 没有那层加工。**这是刻意的简化**——「审核 ○ 分不清没触发还是没走到」本来
> 就记在 `02_需求.md` 的待办里，这次不动它，保持两态。

- [ ] **Step 3: 改写 `runtime.html`**

整份替换：

```jinja
{% extends "base.html" %}
{% block title %}运行日志 · KN_Base{% endblock %}
{% block content %}
<div class="chat-layout">
  <section>
    <div class="page-head">
      <h1>运行日志</h1>
      <p>代码级输出，原样显示。留在服务侧，不进 vault——技术日志是噪音。</p>
    </div>

    {% if not day %}
      <div class="empty">
        日志还是空的。做一次整理（<code>kb organize</code>）就会写进来。
      </div>
    {% else %}
      <p class="mono">{{ box_label(day) }}　·　{{ log_dir }}</p>
      <pre class="term">{{ log_text }}</pre>
    {% endif %}
  </section>

  <aside class="chat-history">
    <h2>箱子</h2>
    {% include "_boxes.html" %}
  </aside>
</div>
{% endblock %}
```

> **注意这份 `<aside>` 没有 `tabbed` 类**——运行日志页没有页签（Q93）。

- [ ] **Step 4: 跑测试**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web -v
```

**Expected:** 页签与箱子的用例全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/kb/web/templates/journal.html src/kb/web/templates/flow.html src/kb/web/templates/runtime.html
git commit -m "feat: 三个日志页改成箱子 + 页签的骨架"
```

---

## Task 6: 巡检页与左侧导航

**Files:**
- Create: `src/kb/web/templates/sweep.html`
- Modify: `src/kb/web/templates/base.html`

- [ ] **Step 1: 写 `sweep.html`**

```jinja
{% extends "base.html" %}
{% block title %}巡检 · KN_Base{% endblock %}
{% block content %}
<div class="page-head">
  <h1>巡检</h1>
  <p>定期收拾**标签和目录**——合并近义、更新索引。不看正文。每 6 天自动跑一次，也可以随时手动跑。</p>
</div>

{% if report %}
  <article class="card sweep {{ '' if not report.read else 'read' }}">
    <h3>最近一次巡检</h3>
    {% if report.tag_merges or report.dir_merges %}
      <ul>
        {% for m in report.tag_merges or [] %}<li>标签：{{ m.from }} → {{ m.to }}</li>{% endfor %}
        {% for m in report.dir_merges or [] %}<li>目录：{{ m.from }} → {{ m.to }}</li>{% endfor %}
      </ul>
    {% endif %}
    <p>{{ report.summary }}</p>
    <p class="muted mono">{{ report.at }}</p>
  </article>

  <form class="sweep-reply" method="post" action="/sweep/reply">
    <button name="reply" value="知道了">我知道了</button>
    <button name="reply" value="调整" formnovalidate
            onclick="document.getElementById('sweep-note').hidden = false">
      还需调整
    </button>
    <input id="sweep-note" name="note" placeholder="要改哪里？比如「那两个分类不该合并，拆开」" hidden>
  </form>
{% else %}
  <div class="empty">还没巡检过。点下面的按钮跑一次，或等服务自己触发（超过 6 天会跑）。</div>
{% endif %}

<form method="post" action="/sweep/run">
  <button class="primary" type="submit">巡检一次</button>
</form>

<p class="muted">
  {% if last_sweep %}上次巡检：{{ last_sweep }}{% else %}还没跑过。{% endif %}
</p>
{% endblock %}
```

> **「还需调整」那个输入框用的是 `hidden` 属性切换**，和原来工作日志页侧栏里那块一个写法——表单还是同一个，点按钮才把它露出来。

- [ ] **Step 2: 改左栏**

`base.html` 里把 `<form method="post" action="/sweep/run">…巡检一次…</form>` 那一段（第 36-45 行）**整段删掉**，并在「运行日志」那条之后加：

```html
      <a href="/sweep" class="side-btn {{ 'active' if active == 'sweep' }}">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20 11a8 8 0 1 0-2.3 5.7"/>
          <path d="M20 5v6h-6"/>
        </svg>
        <span class="side-label">巡检</span>
      </a>
```

> 图标沿用原来那个「巡检一次」的——含义一样，不用另找。

- [ ] **Step 3: 跑测试**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web -v
```

**Expected:** 全 PASS

- [ ] **Step 4: 提交**

```bash
git add src/kb/web/templates/sweep.html src/kb/web/templates/base.html
git commit -m "feat: 巡检单开一页，左栏加第六项"
```

---

## Task 7: 样式

**Files:**
- Modify: `src/kb/web/static/style.css`

- [ ] **Step 1: 加样式**

追加到 `style.css` 末尾：

```css
/* ---- 竖排页签（Q93）----
   贴着侧栏的**左边缘**向外伸，点哪个哪个高亮。窄栏里横排挤不下，
   所以用 writing-mode 竖着写。 */
.chat-history.tabbed {
  display: flex;
  gap: 0;
  padding-left: 0;
}

.tabs {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  flex: 0 0 22px;
}

.tab {
  writing-mode: vertical-rl;
  text-orientation: upright;
  letter-spacing: 2px;
  padding: 9px 3px;
  border: 1px solid var(--line);
  border-right: none;
  border-radius: 5px 0 0 5px;
  background: var(--line-soft);
  color: var(--faint);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.tab.active {
  background: #fff;
  color: var(--fg);
  font-weight: 600;
  box-shadow: -1px 0 0 var(--blue) inset;
  border-color: #b9c6d6;
}

.pane { flex: 1; min-width: 0; }

/* ---- 箱子按钮（Q93）----
   复用会话按钮的 .chat-item，这里只补日期那行的字形。 */
.chat-item { font-variant-numeric: tabular-nums; }

/* 主区顶上的箱子名 */
h2.day {
  font-size: 13px;
  font-weight: 600;
  color: var(--faint);
  margin: 0 0 10px;
  letter-spacing: 1px;
}

/* ---- 巡检页 ---- */
.card.sweep {
  border-color: #c9a86a;
  background: #fdf8ee;
}

.card.sweep.read {
  border-color: var(--line);
  background: #fff;
}

.card.sweep.read h3 { color: var(--faint); }

button.primary,
.sweep-reply button {
  border: 1px solid var(--blue);
  color: var(--blue);
  background: #fff;
  border-radius: 5px;
  padding: 6px 14px;
  font: inherit;
  cursor: pointer;
}

button.primary:hover,
.sweep-reply button:hover { background: var(--blue-soft); }

.sweep-reply { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }

.sweep-reply input {
  flex: 1 0 100%;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: 5px;
  font: inherit;
}
```

> **变量名要对得上。** 先扫一眼 `style.css` 顶部的 `:root`，把 `--line` / `--line-soft` / `--blue` / `--blue-soft` / `--faint` / `--fg` 换成实际存在的名字。**对不上的话样式会静默失效**——不报错，只是没效果。

- [ ] **Step 2: 起服务肉眼过一遍**

```bash
./kb.bat stop && ./kb.bat status
```

然后打开 `http://127.0.0.1:51823`，逐个走：

1. 左栏六项都在，「巡检一次」不在左栏了
2. 整理日志页：右侧栏两个竖排页签，点「历史」出箱子列表，点箱子主区换天
3. 工作日志页：页签是「流程图 / 历史」，「流程图」里是竖排的 ✓/○ 链，**没有巡检报告那块**
4. 运行日志页：右侧栏只有箱子，**没有页签**，主区是终端样式
5. 巡检页：报告 + 两个按钮 + 「巡检一次」+ 上次巡检时间
6. 手改 URL 成 `?d=2020-01-01` → 空态，不是错误页

- [ ] **Step 3: 跑全量测试与风格检查**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**Expected:** 全绿、`All checks passed!`

- [ ] **Step 4: 提交**

```bash
git add src/kb/web/static/style.css
git commit -m "feat: 竖排页签、箱子、巡检页的样式"
```

---

## Task 8: 文档同步与端到端验证

**Files:**
- Modify: `docs/01_架构.md`（第十一节接口、第十三节实现步骤）
- Modify: `docs/03_问题记录.md`（Q80/Q89/Q90/Q93 补注）
- Modify: `README.md`

- [ ] **Step 1: 改 `01_架构.md` 第十一节**

接口表下面补：

```markdown
**页面路由（2026-09-17）：** 三个日志页收 `?d=YYYY-MM-DD`（省略 → 最新一个有日志的日子，
非法值 → 空态**不 404**）；新增 `GET /sweep` 巡检页与 `POST /sweep/run` 手动跑。
`/sweep/reply` 的「还需调整」不再是「把意见当草稿投」，而是**带着这句重跑一次巡检**
（Q96）。
```

- [ ] **Step 2: 改 `01_架构.md` 第十三节**

实现步骤表里第 11 条「日志箱子 + 巡检页」的状态从 ⬜ 改成 ✅。

- [ ] **Step 3: 改 `03_问题记录.md`**

给 Q80 / Q89 / Q90 各补一条注：

```markdown
> **2026-09-17 补注（Q93）：** <这条说的是什么，现在落到哪了>
```

- **Q80**：补「三个落点现在都是按天一个文件，这就是箱子」
- **Q89**：补「右侧栏的流程图页签固定显示最近一次（`flow.latest_run_rows`），与箱子无关；`skipped` 与 `todo` 的区分**这次没做**——那需要 `group_flow` 那层加工，见 `02_需求.md` 的待办」
- **Q90**：补「整理日志页的右侧栏改成报告/历史两个页签」

- [ ] **Step 4: 改 `README.md`**

「使用方式」一节的页面清单加巡检页，并说明三个日志页可以按天翻。

- [ ] **Step 5: 端到端验证**

```bash
# 停服务（改了 src/ 下的代码，在跑的服务仍是旧逻辑）
./kb.bat stop

# 投一条，看它进今天的箱子
./kb.bat push --content "日志箱子的端到端验证：三个日志页各带一列按天的箱子。" --source 会话
./kb.bat organize

# 手工跑一次巡检，看报告落在巡检页上
./kb.bat sweep

# 起来看页面
./kb.bat status
```

打开 `http://127.0.0.1:51823` 逐项确认：

1. **整理日志页** `26_9_17箱子` 里有刚才那条的记录
2. **工作日志页** 那天的箱子里有 `投递/规划/校验/落盘` 四步；右侧栏「流程图」画的是最近一次
3. **运行日志页** 那天的箱子里有 `kb.push` / `kb.organize` 那几行
4. **巡检页** 有报告、有时间、「巡检一次」能跑
5. 在巡检页点「还需调整」，写一句「没什么要改的，只是试试」→ 提交后**巡检带着这句重跑了一遍**，「流程图」页签上能看到新的一次

- [ ] **Step 6: 跑全量测试与风格检查**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**Expected:** 全绿

- [ ] **Step 7: 提交**

```bash
git add docs/01_架构.md docs/03_问题记录.md README.md
git commit -m "docs: 箱子、页签、巡检页同步"
```

---

## Self-Review

**1. 规格覆盖：** 设计文档的每一条都对应到任务——页签表（Task 5/6）、箱子按钮（Task 4/5）、巡检页（Task 6）、「还需调整」带要求重跑（Task 1/2/3）、`?d=` 与不 404（Task 3）、保留策略之外的都覆盖了。样式（Task 7）与文档（Task 8）收尾。

**2. 占位符扫描：** 无 TBD / TODO / 「类似 Task N」。

**3. 类型一致性：**
- `sweep.build_prompt(vault_root, requirement=None)` / `sweep.make_plan(vault_root, llm, requirement=None)`
- `run_sweep(vault_root, data_dir, llm, requirement=None)`
- 模板上下文：`days` / `day` / `latest` / `sections` / `groups` / `steps` / `log_dir` / `log_text` / `report` / `last_sweep`
- `_tabs.html` 收 `tabs`（`[(面板 id, 名字)]`），`_boxes.html` 收 `days` / `day`
- 页签 `data-panel` 与面板 `data-pane` **是同一个值**——脚本靠它对上

**4. 一处刻意的不对称：** 运行日志页的 `<aside>` **没有 `tabbed` 类、也不 include `_tabs.html`**。这是对的（Q93：那一页没有页签），但容易在后续改动中被「顺手统一」掉——Task 5 Step 3 的注释里写明了。

**5. 已知会碰到的两处：** ① `client` 夹具的 `data_dir` 若不是 `tmp_path`，Task 3 Step 1 那个用例要改（已在步骤里提示先读夹具）；② `style.css` 的 CSS 变量名要核（已在 Task 7 Step 1 提示）。

---

## 收尾

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

全绿即本计划完成。**两份计划都做完后**，「日志箱子」这条线就走完了。
