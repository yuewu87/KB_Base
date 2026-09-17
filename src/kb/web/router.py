"""Web UI 路由。布局见 `docs/02_需求.md` 第五节。

**薄层**——只做「取数据 + 渲染」，判断逻辑全在 `core/`。

**对话不在这里实现**（Q84）：跑一轮对话的是 `core.chat.handle`，能做的动作
由服务侧的闭包给。Web 只是调用方——两份实现迟早会分叉。

会话历史的落点（`data_dir`）同样由 `create_app` 传进来：Web 层自己拼路径
迟早会拼成仓库根的 `chats/`，那条路径没被 gitignore 覆盖（见 `chat_store`）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from kb.api import runtime
from kb.api.http import push_and_organize, run_sweep
from kb.config import Config
from kb.core import settings, sweep, sweep_state
from kb.core.chat import handle
from kb.core.chat_store import list_chats, load_chat
from kb.core.flow import STEPS, latest_run_rows
from kb.core.flow import list_days as flow_days
from kb.core.flow import read_day as read_flow_day
from kb.llm.base import LLM, LLMError
from kb.logging_setup import LOG_DIR
from kb.web.data import (
    box_label,
    group_flow,
    journal_days,
    load_push_templates,
    read_journal,
    read_runtime,
    runtime_days,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 模板里现算箱子名——三个页面都要用，注册成全局比每个端点传一次干净
templates.env.globals["box_label"] = box_label


class SettingsBody(BaseModel):
    values: dict[str, str] = {}


def settings_context(env_path: Path, cfg: Config) -> dict:
    """给模板的：四组字段 + 它们当前的值（密钥掩码）。

    **「关于」那一组不在 `.env` 里**——它显示的是运行时的东西（服务状态、
    版本），所以在这里拼出来。这样模板仍然只是一个循环，不用为一组开特例。

    **`env_path` 由 `create_app` 传进来**，不许自己拼 `PROJECT_ROOT / ".env"`：
    这一页该显示的是**这个 app 实际在用的那份配置**，不是「工程根目录下恰好
    存在的那个文件」。生产里两者一样，测试里不该一样——写死真 `.env` 的话，
    新克隆的仓库没有那个文件，掩码那条用例必红。

    **`cfg` 是当前那份生效配置**（`create_app` 里那个盒子里的），只读字段
    显示它、其余字段显示 `.env` 里的字面值。理由见 `_value`。
    """
    values = settings.read_env(env_path)

    def _value(f) -> str:
        """只读字段显示**生效值**，可改字段显示 `.env` 里的字面值。

        只读两栏不能按字面值显示：`.env` 里没写 `KB_VAULT_PATH` / `KB_PORT`
        的人（默认值就是给这种 `.env` 准备的），那两栏会是**空白**——
        尽管跑起来用的是 `DEFAULT_VAULT_PATH`、端口是自动找的空闲端口。
        一栏空白看起来像坏了，而这一页的任务正是让人看清楚现在在用的是什么。

        可改字段反过来，**必须**是 `.env` 的字面值：留空 = 不改是它们的语义
        （密钥尤其），显示生效值就等于让人一保存把 key 覆盖成掩码。

        **`choice` 是唯一的例外：先 `upper()` 再显示。** 与 `config._log_level`
        的 `upper()` 口径一致——`.env` 里手写小写 `debug` 时，大写选项列表里
        匹配不上，下拉框会**落到第一个 option**（画面上是 INFO），而 `data-init`
        还是 `debug`：用户「什么都不改点保存」，`debug` 就被静默写成 `INFO`。
        归一之后，显示的就是**实际生效**的那个值，`data-init` 也跟着对得上。
        """
        if f.kind == "readonly":
            if f.key == "KB_VAULT_PATH":
                return str(cfg.vault_path)
            if f.key == "KB_PORT":
                return str(cfg.port) if cfg.port else "自动"
        raw = values.get(f.key, f.default)
        if f.kind == "choice":
            raw = raw.upper()
        return _display(f, raw)

    groups = [
        {
            "name": group.name,
            "fields": [
                {
                    "key": f.key,
                    "label": f.label,
                    "kind": f.kind,
                    "help": f.help,
                    "choices": f.choices,
                    "value": _value(f),
                }
                for f in group.fields
            ],
        }
        for group in settings.GROUPS
    ]

    groups.append({
        "name": "关于",
        "fields": [
            {
                "key": "_service", "label": "服务状态", "kind": "readonly",
                "choices": (), "value": _service_status(),
                "help": "「改了 src/ 下的代码要 kb stop」那条坑摆在这儿——"
                        "双击 web.bat 进来的人不会去查 kb status",
            },
            {
                "key": "_repo", "label": "版本 / 仓库", "kind": "readonly",
                "choices": (), "help": "",
                "value": "KN_Base · github.com/yuewu87/KB_Base",
            },
        ],
    })
    return {"groups": groups}


def _service_status() -> str:
    """一行说清服务在不在、跑了多久、跑的是不是旧代码。

    「启动于」是**给人对表用的**（设计第四节那栏的样例就是它）：改了代码重启
    没有、日志里那一串要不要重新看，看一眼这个时间就够。
    """
    port = runtime.running_port()
    if port is None:
        return "未在运行"

    text = f"已连接（:{port}）"
    info = runtime.read_service_info() or {}
    started = info.get("started")
    if isinstance(started, str) and " " in started:
        # `2026-09-17 18:31:22` → `18:31`。文件里的形状由 runtime 决定，
        # 对不上就当没有这一项——一栏状态不该为此变成异常页。
        text += f" · 启动于 {started.split(' ', 1)[1][:5]}"
    if runtime.is_stale():
        text += " · 代码比进程新，建议重启"
    return text


def _display(field, value: str) -> str:
    """密钥只给掩码——**原文一个字都不进 HTML**。"""
    if field.kind != "secret" or not value:
        return value
    return "•" * 12 + value[-4:] if len(value) > 4 else "•" * 8


def build_router(
    get_cfg: Callable[[], Config],
    data_dir: Path,
    organize_fn: Callable[[str, str, str | None], str],
    get_llm: Callable[[], LLM],
    apply_settings: Callable[[dict[str, str]], dict[str, str]],
    quit_fn: Callable[[], None],
    env_path: Path,
    build_llm_fn: Callable[[Config], LLM],
) -> APIRouter:
    """`data_dir`、`organize_fn`、`get_llm` 都由 `create_app` 传进来。

    三者都是**服务侧的东西**：会话历史落哪、对话能调哪些动作、模型是谁。
    Web 层自己知道这三件事，就意味着多出第二份实现——
    尤其是 `get_llm`：自己 `build_llm(cfg)` 会绕过注入的模型（测试里就是假模型）。

    `get_cfg` 同理，而且是**回调不是值**：配置在网页上能改，改完 `create_app`
    里那个盒子会换一份新的——把 `cfg` 当值收下来的话，这里拿到的永远是旧的。

    `env_path` 是**这个 app 实际在用的**那份 `.env`（`create_app` 决定，
    测试里是临时文件）。设置页显示它，不显示「工程根目录下恰好存在的那个」。
    """
    router = APIRouter()

    def _ctx(name: str, **extra) -> dict:
        return {"active": name, "vault": str(get_cfg().vault_path), **extra}

    def _pick_day(d: str, days: list[str]) -> str:
        """选哪一天：`d` 在列表里就用它，否则落到**最新一天**。

        **非法 `d` 不 404**——手改 URL 或书签过期不该看到错误页，
        当「没有这一天」处理即可。
        """
        return d if d in days else (days[0] if days else "")

    @router.get("/", response_class=HTMLResponse)
    def chat_page(request: Request, cid: str = ""):
        """对话页。不带 `cid` 就落到最近一次会话。"""
        chats = list_chats(data_dir)
        if not cid and chats:
            cid = chats[0]["id"]
        current = load_chat(data_dir, cid) if cid else None
        return templates.TemplateResponse(
            request,
            "chat.html",
            _ctx("chat", chats=chats, current=current, cid=cid),
        )

    # 表单 POST 落在 `/` 上，**不能也叫 `/chat`**——那条路径已经被服务端的
    # JSON 端点占了（`api/http.py`）。同一个路径注册两次，先注册的那个
    # 会把另一个的请求全吃掉（表单进 JSON 端点 = 422，反之亦然）。
    @router.post("/")
    def chat_post(message: str = Form(...), cid: str = Form("")):
        chat_id, _ = handle(
            data_dir,
            get_cfg().vault_path,
            cid or None,
            message,
            get_llm(),
            organize_fn=organize_fn,
        )
        return RedirectResponse(f"/?cid={chat_id}", status_code=303)

    @router.get("/new", response_class=HTMLResponse)
    def new_note(request: Request, t: str = ""):
        """模板随手记（Q85）。模板只是脚手架，**不逼人先做分类判断**（Q86）。"""
        templates_ = load_push_templates()
        chosen = templates_.get(t, "")
        return templates.TemplateResponse(
            request,
            "new.html",
            _ctx("new", templates=list(templates_), chosen=t, body=chosen),
        )

    @router.post("/new")
    def new_note_post(content: str = Form(...)):
        """只填正文（Q87）——`source` 记成 Web，项目留空，其余归整理。"""
        if not content.strip():
            raise HTTPException(status_code=400, detail="正文不能为空")
        push_and_organize(get_cfg(), content, get_llm(), source="Web")
        return RedirectResponse("/journal", status_code=303)

    @router.get("/journal", response_class=HTMLResponse)
    def journal(request: Request, d: str = ""):
        days = journal_days(get_cfg().vault_path)
        day = _pick_day(d, days)
        return templates.TemplateResponse(
            request,
            "journal.html",
            _ctx(
                "journal",
                days=days,
                day=day,
                sections=read_journal(get_cfg().vault_path, day) if day else [],
                latest=latest_run_rows(data_dir),
            ),
        )

    @router.get("/flow", response_class=HTMLResponse)
    def flow(request: Request, d: str = ""):
        days = flow_days(data_dir)
        day = _pick_day(d, days)
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

    def _run_sweep_or_report() -> RedirectResponse:
        """跑一次巡检，失败就落一份没读的报告——**人在这儿等着，不能甩 500**。

        写成报告的语义和后台那条失败路径一致（`_sweep_in_background` 也这么落），
        巡检页上看得见原因。
        """
        try:
            run_sweep(get_cfg().vault_path, data_dir, get_llm())
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

    @router.post("/sweep/reply")
    def sweep_reply():
        """报告下面那个按钮。

        **「我知道了」= 把报告标成已读。** 它就只做这件事——是不再高亮的提醒，
        不是审批，也不触发任何动作。

        （原来这里还有个「还需调整」，点了会带着用户写的话把巡检重跑一遍。
        2026-09-17 删了：巡检只会合并、且刻意不看笔记正文，所以「拆开某个分类」
        这类调整在结构上无法表达——后端能力与用户预期对不上，不留半截。）
        """
        sweep_state.mark_read(data_dir)
        return RedirectResponse("/sweep", status_code=303)

    @router.post("/sweep/run")
    def sweep_run():
        """手动跑一次巡检，**不受 6 天限制**——是你主动要跑的。

        跑完 `run_sweep` 自己会写 `last_sweep`（Task 1 的 `save_report`），
        所以自动那条也跟着顺延，这里不用额外记。

        **同步跑**，和 `/new` 一个路子：点完等它跑完，页面转到巡检页看报告。
        巡检比单条投递慢（全库过一遍 + 一次 LLM），但它是低频动作。
        """
        return _run_sweep_or_report()

    @router.get("/sweep", response_class=HTMLResponse)
    def sweep_page(request: Request):
        """巡检页——报告与「我知道了」的家（Q93）。

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

    @router.get("/settings", response_class=HTMLResponse)
    def settings_fragment(request: Request):
        """模态窗的内容。**只有窗口那一段**，不带整页骨架。

        模态是从任意页面 fetch 进来的，跳页会把用户的位置弄丢。
        """
        return templates.TemplateResponse(
            request,
            "_settings.html",
            # `get_cfg()` 而不是某个存下来的值：这一页要显示的是**此刻**在用的
            # 那份配置（保存过一次之后就是新的那份）。
            _ctx("settings", **settings_context(env_path, get_cfg())),
        )

    @router.post("/settings")
    def settings_save(body: SettingsBody):
        """保存 + 重载。模型与日志级别**当场生效**，不用重启。

        **不是每个字段都当场生效**：`KB_SWEEP_INTERVAL` / `KB_LOG_KEEP_DAYS`
        只在服务启动那一刻用一次（`main()` 里判一次 `due`、清一次旧日志），
        改完要等下次启动——所以那两个字段的 `help` 里写明「下次启动服务时生效」，
        前端的成功提示也不再笼统地说「立刻生效」。见
        `core.settings.GROUPS` 与 `docs/03_问题记录.md` Q98。

        `saved` 里是**真变了的**那些，不是提交上来的全部——表单会把所有
        pane 的字段都送过来（隐藏的也在），照单全收的话，只改一个日志级别
        也会提示「已保存 5 项」。详见 `apply_settings`。

        写失败（磁盘满、没权限）会把异常抛出去 → 500，**不重载**——
        文件没写成，内存里跟着变就成了两套真相。
        """
        try:
            saved = apply_settings(body.values)
        except settings.SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"saved": saved}

    @router.post("/settings/test")
    def settings_test(body: SettingsBody):
        """拿**表单里当前填的值**新建一个客户端发一次最小请求。

        **不落盘、不动现有的客户端**——所以「先测试再保存」走得通，
        不用为了测一次就把坏配置先写进 `.env`。

        （失败路径的用例在 `tests/web/test_router.py` 里——
        保存后的重载要靠它验：兜底值走的是 `get_cfg()`。）

        **它要花钱**（一次极小的调用）。这是刻意的：换模型/换 key 时，
        这是唯一能立刻知道对不对的办法。

        ## body 必填——这不是疏忽，是定下来的约定

        设计要的是「拿**表单里当前填的值**」去测。不带 body 的调用没有意义：
        它只能测**已保存的配置**，而用户刚改的正是表单里的值——测了个寂寞，
        界面还会显示「通了」。所以这里收的是必填的 `SettingsBody`，**不带 body
        的调用拿 422**。让它响一声，比悄悄退化成「测的是旧配置」好。

        **下一个批次写 JS 时别漏 body**：

        ```javascript
        const r = await fetch('/settings/test', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({values: Object.fromEntries(new FormData(form))}),
        });
        ```

        （计划 Task 5 那段 JS 只写了 `{method: 'POST'}`，照抄下去「测试连接」
        会**永远**显示不通。另外前端显示失败原因时要**带上 HTTP 状态**——
        不然 422 会被显示成「不通：未知原因」，谁也查不出来。
        用例见 `tests/web/test_router.py::test_test_connection_requires_a_body`。）
        """
        cfg = get_cfg()
        # 表单里的值优先；没填的（比如密钥留空）沿用当前的
        merged = {
            "KB_LLM_MODEL": body.values.get("KB_LLM_MODEL") or cfg.llm_model,
            "KB_LLM_BASE_URL": body.values.get("KB_LLM_BASE_URL") or cfg.llm_base_url,
            "KB_LLM_API_KEY": body.values.get("KB_LLM_API_KEY") or cfg.llm_api_key,
        }
        probe = build_llm_fn(Config(
            llm_api_key=merged["KB_LLM_API_KEY"],
            llm_base_url=merged["KB_LLM_BASE_URL"],
            llm_model=merged["KB_LLM_MODEL"],
            vault_path=cfg.vault_path,
            port=cfg.port,
        ))

        started = time.monotonic()
        try:
            probe.complete("你是连通性测试。", "回复 ok 两个字就行。")
        except LLMError as exc:
            return {"ok": False, "detail": str(exc)}
        return {"ok": True, "seconds": round(time.monotonic() - started, 1)}

    @router.post("/quit")
    def quit_service():
        """停掉服务。实现见 `api/http.py` 的 `_default_quit`——**先答应，再退出**。"""
        quit_fn()
        return {"ok": True}

    @router.get("/runtime", response_class=HTMLResponse)
    def runtime_page(request: Request, d: str = ""):
        days = runtime_days(LOG_DIR)
        day = _pick_day(d, days)
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

    return router
