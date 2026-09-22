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
from kb.api.http import busy_guard, push_and_organize, run_sweep, vault_guard
from kb.config import NO_VAULT_MESSAGE, Config
from kb.core import settings, sweep, sweep_state
from kb.core.chat import handle
from kb.core.chat_store import list_chats, load_chat
from kb.core.flow import STEPS, latest_run_rows
from kb.core.flow import list_days as flow_days
from kb.core.flow import read_day as read_flow_day
from kb.core.lifecycle import (
    Busy,
    BusyError,
    LifecycleError,
    check_path,
    migrate_vault,
    remove_vault,
    vault_path_problem,
    vault_ready,
    vault_view,
)
from kb.core.vault import list_drafts, list_notes
from kb.core.vault_setup import DEFAULT_DOMAINS, DOMAIN_CANDIDATES, init_vault
from kb.llm.base import LLM, LLMError
from kb.logging_setup import LOG_DIR
from kb.web import skins
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


class SettingsBody(BaseModel):          # ← 现成的那个，别动
    values: dict[str, str] = {}


# **这两个必须住在模块级，不能挪进 `build_router` 函数体。**
# 本文件开头有 `from __future__ import annotations`（12 行），于是所有注解
# 都变成字符串；FastAPI 的 `get_typed_signature()` 是拿**函数所在模块的全局**
# 去 eval 这个注解的——`SetupBody` 要是成了函数体里的局部名，在那儿查不到，
# `create_app()` 会**当场 `NameError`**。
# `SettingsBody` 和 `api/http.py` 的 `PushRequest` / `DropRequest` 都在模块级，
# 跟它们是同一个规矩，别「顺手」挪回去。
class SetupBody(BaseModel):
    vault_path: str = ""
    domains: list[str] = []
    values: dict[str, str] = {}


class MigrateBody(BaseModel):
    target: str = ""


def _model_group() -> settings.Group:
    """「模型配置」那一组。**它的 key 只在这里写一次。**

    一条龙的段①靠它渲染——键名手抄四份的那条记档就是从这里收掉的。
    """
    return next(g for g in settings.GROUPS if g.key == "model")


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

        只读栏不能按字面值显示：`.env` 里没写 `KB_PORT` 的人（默认值就是给
        这种 `.env` 准备的），那一栏会是**空白**——尽管跑起来是个自动找的
        空闲端口。一栏空白看起来像坏了，而这一页的任务正是让人看清楚现在在
        用的是什么。

        （`KB_VAULT_PATH` 2026-09-22 从 `readonly` 改成了 `text`，而且「知识库」
        那一组从 Task 6 起整个换成 `_vault_pane.html`、根本不走字段循环，
        这里原先为它留的那条分支是**死代码**，已删。）

        可改字段反过来，**必须**是 `.env` 的字面值：留空 = 不改是它们的语义
        （密钥尤其），显示生效值就等于让人一保存把 key 覆盖成掩码。

        **`choice` 是唯一的例外：先对回选项列表里的那一个。** 与
        `config._log_level` 的 `upper()` 同一条理由——`.env` 里手写小写
        `debug` 时，选项表里匹配不上，下拉框会**落到第一个 option**
        （画面上是 INFO），而 `data-init` 还是 `debug`：用户「什么都不改点
        保存」，那个 `debug` 就被静默写成 `INFO`。归一之后，显示的就是
        **实际生效**的那个值，`data-init` 也跟着对得上。
        """
        if f.kind == "readonly" and f.key == "KB_PORT":
            return str(cfg.port) if cfg.port else "自动"
        raw = values.get(f.key, f.default)
        if f.kind == "choice":
            raw = _normalize_choice(raw, f.choices)
        return _display(f, raw)

    groups = [
        {
            # 稳定标识：模板拿它认组（`{% if g.key == 'vault' %}`）、JS 拿它
            # 定位导航按钮。**别拿 `g.name` 当标识**——那是给人看的，改一次
            # 名字就会有一处悄悄失灵，而故障长成「这一组不见了」。
            "key": group.key,
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
        "key": "about",
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
    # 「知识库」那一组要**一屏两态**，模板得知道现在是哪一态。
    # ⚠️ 局部变量**不要再叫 `vault_ready`**——那会遮住 `lifecycle.vault_ready`
    # 这个函数，同一个名字在这里指两样东西。判据本身在它那儿，只有那一份。
    return {
        "groups": groups,
        # **这里不返回 `vault_ready`。** 它由 `_ctx` 一处提供——这个函数的结果
        # 是**摊在 `_ctx` 之上**的（`_ctx("settings", **settings_context(...))`），
        # 两边都带这个键的话 `**extra` 会把先算的那份静默顶掉：同一次请求算
        # 两遍，哪份生效取决于字典展开顺序，分岔时不会有任何东西报错。
        #
        # 路径字符串与领域**从磁盘读，不从配置读**——领域的唯一真源始终是
        # 磁盘（Q95 那条）。判据与防 500 的那道守卫都在 `lifecycle.vault_view`。
        **vault_view(cfg.vault_path),
        # 一条龙的段①**由 `settings.GROUPS` 里那一组渲染**，不是模板手抄
        # 三个 `id="w-KB_LLM_*"`。手抄的话，往「模型配置」加第四个字段时
        # 设置窗那栏会有、**段①不会有**——向导问的和服务实际要的成了两份
        # 清单；改键名更静默（`getElementById('w-' + k)` 返回 `null`，
        # `.value` 当场 TypeError，被 catch 包成「初始化失败：TypeError…」，
        # 看着像后端的问题）。
        "model_fields": [
            {
                "key": f.key,
                "label": f.label,
                "kind": f.kind,
                # **密钥不预填**（掩码都不给）：「留空 = 不改」是它的语义，
                # 预填成掩码等于让人一保存把 key 覆盖掉。
                "value": "" if f.kind == "secret" else values.get(f.key, ""),
            }
            for f in _model_group().fields
        ],
        # 段③那九个复选框。清单是常量、不进 `.env`——勾选的作用只是建出目录，
        # 建完就不再被读第二次（见 `DOMAIN_CANDIDATES` 那段注释）。
        "domain_candidates": DOMAIN_CANDIDATES,
        "default_domains": DEFAULT_DOMAINS,
    }


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


def _normalize_choice(raw: str, choices: tuple[str, ...]) -> str:
    """把 `.env` 里手写的值对到选项列表里的那一个——**不区分大小写**。

    **不能一律 `upper()`。** 那是为 `INFO` / `DEBUG` 那种全大写选项写的，
    而皮肤名是小写带连字符的（`neon`、`dark-pink`）：`upper()` 成 `NEON`
    之后**谁都匹配不上**，`<option>` 一个都不 `selected`，浏览器静默落到
    第一项——画面上写着「现有蓝」，实际存的是 neon。这类「显示的和生效的
    不是一回事」正是这个模块上面那段注释要拦的东西。

    对不上就原样返回：下拉框照样落到第一项，但 `data-init` 是真值，
    `saveSettings` 不会把它当「没动过」而漏掉。
    """
    for choice in choices:
        if choice.lower() == raw.lower():
            return choice
    return raw


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
    *,
    busy: Busy,
    unbind_vault: Callable[[], None],
) -> APIRouter:
    """`data_dir`、`organize_fn`、`get_llm` 都由 `create_app` 传进来。

    三者都是**服务侧的东西**：会话历史落哪、对话能调哪些动作、模型是谁。
    Web 层自己知道这三件事，就意味着多出第二份实现——
    尤其是 `get_llm`：自己 `build_llm(cfg)` 会绕过注入的模型（测试里就是假模型）。

    `get_cfg` 同理，而且是**回调不是值**：配置在网页上能改，改完 `create_app`
    里那个盒子会换一份新的——把 `cfg` 当值收下来的话，这里拿到的永远是旧的。

    `env_path` 是**这个 app 实际在用的**那份 `.env`（`create_app` 决定，
    测试里是临时文件）。设置页显示它，不显示「工程根目录下恰好存在的那个」。

    `busy` 由 `create_app` 造了传进来——**锁必须是同一把**。各造一把的话，
    网页这边「正在整理」挡住了投递，服务端 `/organize` 却照样跑，
    等于没锁。

    `unbind_vault` 是移除专用的一条路（直接写空 `KB_VAULT_PATH` 再重载），
    **故意绕开 `apply_settings`**——那条路会走 `settings.validate`，
    而那里「空值 = 400」。
    """
    router = APIRouter()

    vault = vault_guard(get_cfg)

    # **锁与那套 409 文案只有一份实现**（`api/http.py` 的 `busy_guard`）——
    # 两边各抄一遍的话，改文案、加 `Retry-After` 都得记得改两处。
    organizing = busy_guard(busy)

    def _ctx(name: str, **extra) -> dict:
        # `get_cfg()` 每请求现读，所以换皮肤**下一个请求就生效**，不用重启。
        # **皮肤只在这一处注入**：六个页面 + 设置片段都走这个函数，
        # 每个端点各传一次迟早漏一个——而漏掉的那页正是「切了皮肤没反应」
        # 的那一页，而且多半是你没点开的那页。
        vault_path = get_cfg().vault_path
        return {
            "active": name,
            # 首屏那张引导卡看它，侧栏两处「未初始化就置灰」也看它。
            # 判据用 `lifecycle.vault_ready`——全仓唯一那一份（`/setup/state`、
            # `/setup/init` 的闸、设置窗都调它）。**路径字符串与领域不在这里**：
            # 那两样只有 `/settings` 和 `/setup/state` 要，走
            # `lifecycle.vault_view`——每个请求都去扫一遍目录没必要。
            "vault_ready": vault_ready(vault_path),
            "skin": get_cfg().skin,
            "skins": skins.options(),
            **extra,
        }

    def _pick_day(d: str, days: list[str]) -> str:
        """选哪一天：`d` 在列表里就用它，否则落到**最新一天**。

        **非法 `d` 不 404**——手改 URL 或书签过期不该看到错误页，
        当「没有这一天」处理即可。
        """
        return d if d in days else (days[0] if days else "")

    @router.get("/", response_class=HTMLResponse)
    def chat_page(request: Request, cid: str = "", new: str = ""):
        """对话页。不带 `cid` 就落到最近一次会话——**除非点了「开始新会话」**。

        `new=1` 是「就是不要那一次」：没有它的话，空白会话没法表达（`cid` 空
        和不传长得一样，都会回落到最近一次），点了按钮的人会发现自己又回到
        上一轮对话里。

        **`new` 收字符串不收 `int`**，理由同 `_pick_day`：`?new=abc` 该当成
        「要新会话」而不是 422——手改 URL 不该看到错误页。写了 `int` 的话，
        `?new=abc` 会被 FastAPI 直接拒掉。
        """
        chats = list_chats(data_dir)
        if not cid and not new and chats:
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
        # 对话层能触发整理（`organize_fn` 里那个 `organize` 动作），
        # 所以**整轮对话都要占锁**——见 `api/http.py` 的 `/chat`。
        with organizing():
            chat_id, _ = handle(
                data_dir,
                vault(),
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
        vault()                     # 没库就 409，别等写了一半才发现
        # 这条会整理，所以占锁——迁移期间投进来的东西会落进半截库。
        with organizing():
            push_and_organize(get_cfg(), content, get_llm(), source="Web")
        return RedirectResponse("/journal", status_code=303)

    @router.get("/journal", response_class=HTMLResponse)
    def journal(request: Request, d: str = ""):
        # **未初始化时这一页照样打得开**，只是空的。首屏那张引导卡得有个
        # 落脚的地方——页面上甩一坨 409 JSON 不成样子。
        vault_path = get_cfg().vault_path
        days = journal_days(vault_path) if vault_path else []
        day = _pick_day(d, days)
        return templates.TemplateResponse(
            request,
            "journal.html",
            _ctx(
                "journal",
                days=days,
                day=day,
                sections=(
                    read_journal(vault_path, day)
                    if (vault_path and day) else []
                ),
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
        巡检页上看得见原因。**没有知识库也走这条路**：`/sweep` 是个页面表单，
        回 409 JSON 很难看，而且用户看不出下一步该干什么。

        **正在整理/迁移/移除时不跑，但也不回 409**——理由同上，这还是个页面
        表单，用户是在巡检页上点了个按钮。挡它的理由和 Task 4 挡整理一样：
        `run_sweep` 走的是和整理草稿同一条链（同样改 vault 里的笔记、同样落
        一个 git commit），插进一轮迁移里会写成「一半旧库一半新库」，而那个
        样子是**看起来一切正常**。
        """
        # **先问一句「现在忙不忙」**（只读，不占锁）——忙就落一份报告。
        # 被挡的理由拿 `Busy.refusal`，和 409 的 detail 是同一句话。
        # 真正的互斥在 `run_sweep` 动文件那一段，理由见它的 docstring。
        if busy.what is not None:
            sweep_state.save_failure(data_dir, busy.refusal)
            return RedirectResponse("/sweep", status_code=303)

        vault_path = get_cfg().vault_path
        if vault_path is None:
            sweep_state.save_failure(data_dir, NO_VAULT_MESSAGE)
            return RedirectResponse("/sweep", status_code=303)

        try:
            run_sweep(vault_path, data_dir, get_llm(), busy)
        except (sweep.SweepError, BusyError) as exc:
            # 「被挡住」和「巡检自己坏了」在这里落成同一种东西——都是
            # 「这次巡检没跑成」的一份报告，原因原样给出去。用户看报告
            # 就知道该等一会儿还是该去查日志。
            sweep_state.save_failure(data_dir, str(exc))
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

    # ---------------------------------------------------------- 知识库生命周期
    #
    # `SetupBody` / `MigrateBody` 在**模块级**（见 (a-2)）——写在这个函数体里
    # 的话 FastAPI 解析不到注解，`create_app()` 会当场 NameError。

    def _counts(vault_path: Path | None) -> dict:
        """移除确认页要的「将要删掉多少」——数量让人看一眼就知道删的是不是
        他以为的那个库。一句「确定要删除吗」在删 3 篇和删 3000 篇时长得
        一模一样。"""
        notes = 0
        drafts = 0
        # **`vault_ready` 为假时一个都不数。** 原先判的是 `exists()`：`.env`
        # 填成一个文件时（手滑打错一个字符）`list_notes` 的 `iterdir()` 当场抛
        # `NotADirectoryError`，而 `/setup/state` 是每个页面首屏、还有 busy
        # 轮询都要打的端点——它 500 就是整块界面死掉，唯一的出路是再去手改
        # `.env`。也不能只把 `exists()` 换成 `is_dir()`：一个普通目录会被数出
        # 一堆「笔记」吓用户，而 `remove_vault` 根本不会碰它。
        if vault_ready(vault_path):
            notes = len(list_notes(vault_path))
            drafts = len(list_drafts(vault_path))
        chats = 0
        chats_dir = data_dir / "chats"
        if chats_dir.is_dir():
            chats = len(list(chats_dir.glob("*.json")))
        return {"notes": notes, "drafts": drafts, "chats": chats}

    @router.get("/setup/state")
    def setup_state() -> dict:
        """四个状态里的「未初始化 / 已初始化」，加「谁正忙着」。

        判据是 **`.git` 存在**，不是「目录存在」——理由见
        `settings._vault_path_problem`。**判据本身在 `lifecycle.vault_ready`**，
        这里别再手写一遍。
        """
        vault_path = get_cfg().vault_path
        # 路径字符串、磁盘上的领域、以及「不 ready 就别去读」那道守卫都在
        # `lifecycle.vault_view` 里——和设置窗共用同一份。原先这里和
        # `settings_context` 逐行同构，连注释都要写「理由和那条一样」。
        return {
            "initialized": vault_ready(vault_path),
            **vault_view(vault_path),
            "counts": _counts(vault_path),
            "busy": busy.what,
        }

    @router.get("/setup/check")
    def setup_check(path: str = "") -> dict:
        """顺手验一下用户填的路径——**失败也不拦着初始化**。

        它只回事实，不做判断：存在吗、能写吗、里面是不是已经有个库、有几个条目。
        """
        text = path.strip()
        if not text:
            return {"exists": False, "writable": False,
                    "looks_like_vault": False, "entries": []}
        return check_path(Path(text))

    @router.post("/setup/init")
    def setup_init(body: SetupBody) -> dict:
        """一条龙：**建骨架 → 写配置 → 重载**。

        **这个顺序不能反**，理由见下面那段注释：反过来的话
        `settings.validate` 会因为「目标还没有 `.git`」把用户自己的初始化
        请求拒掉，而那句文案还是「想搬过去用『迁移到别处』」。

        **只在「未初始化」时允许**（已初始化时 400）。它**不加 busy 锁**——
        那个状态下没有别的事在跑，加了是空转。
        """
        cfg = get_cfg()
        if vault_ready(cfg.vault_path):
            raise HTTPException(
                status_code=400,
                detail="已经有知识库了。要改配置去对应的设置，要搬家用「迁移到别处」",
            )

        target = body.vault_path.strip()
        if not target:
            raise HTTPException(status_code=400, detail="知识库目录不能留空")
        # **相对路径必须挡在建库之前。** 下面那句 `init_vault` 是**真建**：
        # 相对路径会按**服务进程的 cwd**（生产里 `spawn_service` 传的是
        # `PROJECT_ROOT`）建出一整棵带 `.git` 和首次 commit 的库，紧接着
        # `apply_settings` 才被 `settings.validate` 拒成 400——用户只看到
        # 「失败了」，磁盘上却多了一个嵌在项目仓库里的**未跟踪的嵌套 git
        # 仓库**，一次 `git add -A` 就带进去了。
        #
        # 顺序不能倒（「先建库、再写配置」的理由见下面那段），所以这个检查
        # 只能在这儿、只能提前。判据和 `/setup/migrate` 第一句同款。
        if not Path(target).is_absolute():
            raise HTTPException(status_code=400, detail="知识库目录要填绝对路径")

        # 领域名不能随便起：候选清单之外的直接丢掉
        domains = [d for d in dict.fromkeys(body.domains) if d in DOMAIN_CANDIDATES]
        if not domains:
            raise HTTPException(
                status_code=400,
                detail="至少勾一个领域——一个都没有的话，投进来的每一条都会掉进「待归类」",
            )

        # **模型三件套要在这里查，必须在建库之前。**
        #
        # `settings.validate` 只检查「提交上来的键」，**缺的键它不管**；真正兜底的
        # 是 `apply_settings` 重载之后那句复查（`api/http.py:362`）。可那时候库
        # 已经建好、`.env` 里的 `KB_VAULT_PATH` 也已经写下去了——留下一个
        # 「有库、没模型」的半截状态。
        #
        # 本进程内它歪打正着还能救：`apply_settings` 是在换内存**之前**抛的
        # （`http.py:362` 早于 374 行的 `state["cfg"] = new_cfg`），所以
        # `get_cfg()` 拿到的还是旧的、`vault_path` 仍是 `None`，上面那道
        # 「已初始化」的闸门关不上，用户补上那几项再点一次能过。
        # **但那只是运气**——服务一重启，`reload_config` 就从 `.env` 里读到刚
        # 写下的 `KB_VAULT_PATH`，闸门关上，用户只剩「移除知识库」或手改 `.env`
        # 两条路。所以这个检查既不能省，也不能挪到建库之后。
        #
        # 留空的键**沿用现在的配置**（上面 2714 行那个 `cfg`，别再读一遍
        # `.env`）。判据要和兄弟端点 `/settings/test`（`router.py:481-486`）
        # 用同一套：**两边都是 `get_cfg()` 兜底**。不一致的话，用户会看见
        # 「测试连接：通了」紧接着「初始化：还差 API Key」——同一个
        # 「留空 = 不改」的语义，两个端点给出两种答案，而他还得自己猜哪个对。
        known = {
            "KB_LLM_MODEL": cfg.llm_model,
            "KB_LLM_BASE_URL": cfg.llm_base_url,
            "KB_LLM_API_KEY": cfg.llm_api_key,
        }
        known.update({k: v for k, v in body.values.items() if v})
        missing = [
            label
            for key, label in (
                ("KB_LLM_MODEL", "模型名"),
                ("KB_LLM_BASE_URL", "API 地址"),
                ("KB_LLM_API_KEY", "API Key"),
            )
            if not known.get(key)
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=(
                    "还差 " + "、".join(missing) + "，模型没配齐之前不建库。"
                    "（留空的那些，`.env` 里本来有就沿用；这次是那儿也没有。）"
                ),
            )

        # **先建库、再写配置。反过来是死锁。**
        #
        # `settings.validate` 现在要求 `KB_VAULT_PATH` 指向一个含 `.git` 的目录
        # （Task 3 加的路径校验），而这一刻那个库当然还不存在——先写配置的话，
        # 用户会被自己的初始化请求拒掉，文案还是「想搬过去用『迁移到别处』」。
        # 建在前就没这个问题：写配置那一刻库已经在了。
        #
        # 反过来的风险（库建好了、写配置失败）靠上面那道检查兜着：模型三件套
        # 已经确认齐了，`apply_settings` 到这一步不会因为「必填项是空的」而抛。
        # 剩下的失败（磁盘满、目标只读）由 `except OSError` 接。
        try:
            actions = init_vault(Path(target), domains)
        except OSError as exc:
            raise HTTPException(
                status_code=400, detail=f"建不了 {target}：{exc}"
            ) from exc

        values = dict(body.values)
        values["KB_VAULT_PATH"] = target
        try:
            apply_settings(values)
        except settings.SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"actions": actions, "vault_path": target, "domains": domains}

    def _check_migration(source: Path, target: Path) -> None:
        """迁移的前置检查。不过就抛 400，一句一条。"""
        if not target.is_absolute():
            raise HTTPException(status_code=400, detail="目标要填绝对路径")
        # **判据和 `/setup/state` 一致**（都在 `lifecycle.vault_ready`）：路径
        # 填歪了、那儿是个普通目录时，只判 `exists()` 的话会把一个不相干的
        # 目录当成库搬走。（`migrate_vault` 里另有一道，那边拦的是「绕过这个
        # 端点直接调它」。）
        #
        # **必须过 `vault_path_problem`，不能只判 `vault_ready`。** 判据本身
        # 是同一份，`vault_ready` 对相对路径也回 False，但文案是「不是一个
        # 知识库」——那儿明明有 `.git`（服务 cwd 底下那份），用户照着查会查错
        # 方向；而且这一步得排在下面「在不在」之前，否则 `.env` 里写个不存在
        # 的相对路径时，先甩出来的是一句「当前库不在了」，同样引错方向。
        problem = vault_path_problem(source)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        if not source.exists():
            raise HTTPException(
                status_code=400,
                detail=f"当前库不在了：{source}。这本身就不正常，先查一下",
            )
        if target == source:
            raise HTTPException(status_code=400, detail="目标就是当前库，不用搬")
        if source in target.parents:
            raise HTTPException(
                status_code=400,
                detail=f"{target} 在当前库里面——搬进去会把库搬进自己肚子里",
            )
        if target.exists() and not target.is_dir():
            # **目标是文件**要单独判：`any(target.iterdir())` 对它抛的是
            # `NotADirectoryError`，那是 `OSError` 不是 `LifecycleError`，
            # 这句 `except` 接不住 → 500。而 `/setup/check` 对同一个路径回的是
            # 「存在、能写、里面一个条目都没有」，正把用户往这条路上推。
            raise HTTPException(
                status_code=400,
                detail=f"{target} 是一个文件，不是目录——搬家的目标得是个空目录",
            )
        if target.is_dir() and any(target.iterdir()):
            # **「非空」= 有任何一个条目**，不区分是不是库。迁移做完就把目标
            # 当成新库了，里面原有的任何东西都会混进笔记树——连一个
            # `.DS_Store` 都算。
            raise HTTPException(
                status_code=400,
                detail=f"目标非空（有 {len(list(target.iterdir()))} 个条目）。换一个空的目录",
            )

    @router.post("/setup/migrate")
    def setup_migrate(body: MigrateBody) -> dict:
        """整目录搬家：拷 → 校验 → 删源 → 改指向。

        **同步做**（和 `/new` 一个路子）。库这个量级拷贝是秒级，不值得为它
        再开一套进度协议；期间 busy 是 `"migrate"`，前端拿它做轮询。
        """
        # ⚠️ **下面整块比原稿少四格缩进**——头尾换成了 `with busy_guard(...)`，
        # 中间一字不改。409 的文案与状态码只有 `busy_guard` 那一份。
        #
        # ⚠️ **末尾那个 `()` 不能省。** `busy_guard(busy, what)` 返回的是
        # **工厂**（内层那个 `@contextmanager` 的 `organizing` 函数），不是
        # 上下文管理器本身——现成的用法就是 `organizing = busy_guard(busy)`
        # 之后 `with organizing():`。漏了 `()` 报的是
        # `TypeError: 'function' object does not support the context manager protocol`，
        # 而且只在**跑到这个端点**时才炸，导入期一切正常。
        with busy_guard(busy, "migrate")():
            source = vault()
            target = Path(body.target.strip())
            _check_migration(source, target)
            try:
                moved = migrate_vault(source, target)
            except LifecycleError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            # **这里必须和 `setup_init` 一样兜住 `SettingsError`，而且更要兜。**
            # 走到这一行时库已经搬完、源已经删了；`apply_settings` 要是以 500
            # 抛出去，`.env` 仍指着那个不存在的旧路径——服务显示「还没有知识库」，
            # 笔记却躺在 `target` 里，用户只能手工改 `.env` 才走得出来。
            # 校验没法提前做：`validate` 要求目标已经有 `.git`，而迁移前它必然
            # 是个空目录，提前校验会把合法的迁移目标全部拒掉。所以顺序是死的，
            # 只能把失败说清楚——把该填什么直接写进消息里。
            try:
                apply_settings({"KB_VAULT_PATH": str(target)})
            except settings.SettingsError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"库已经搬到 {target} 了，但写 `.env` 没过校验（{exc}）。"
                        f"请把 `.env` 里的 KB_VAULT_PATH 手工改成 {target}"
                    ),
                ) from exc
            return {"moved": moved, "vault_path": str(target)}

    @router.post("/setup/remove")
    def setup_remove() -> dict:
        """移除知识库：**全部删除，一点痕迹不留**——用户的原话。

        逐项汇报是因为这里做不到「全部成功」：Windows 上正被服务打开的文件
        （今天的日志）删不掉，那是操作系统的边界，不是设计妥协。
        """
        # 同 `setup_migrate`：整块少四格缩进，409 只有 `busy_guard` 那一份。
        # 末尾那个 `()` 同样不能省（理由见 `setup_migrate` 里那段）。
        with busy_guard(busy, "remove")():
            vault_root = get_cfg().vault_path
            # **`remove_vault` 的闸抛 `LifecycleError`，这里必须接住。** 那句
            # 是「这个路径不是库，我不删」，得变成 400 给用户看——接不住的话
            # 一个「`.env` 填歪了」会以 500 的样子出现，而用户多半会当成
            # 服务坏了，不去看自己填的路径。写法照抄上面 `setup_migrate`。
            try:
                result = remove_vault(vault_root, data_dir)
            except LifecycleError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if result["vault_removed"]:
                # **写 `.env` 也会失败**：编辑器或杀软占着那个文件、文件只读。
                # 它原先裸在这儿，抛出去就是 500——而库已经删干净了、`.env`
                # 还指着那个不存在的路径，用户连「去手改 `.env`」这句话都拿不到。
                # 写法照抄上面 `setup_migrate` 那段。
                try:
                    unbind_vault()
                except settings.SettingsError as exc:
                    # 库已经没了、`.env` 也写空了，但读回来三件套是空的
                    # （它们只在进程环境里）。`unbind_vault` 的 docstring 里
                    # 写着为什么这条复查不能省。
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"库已经删干净了（{vault_root}），但 {exc}。"
                            "另外请确认 `.env` 里的 KB_VAULT_PATH 已经清空"
                        ),
                    ) from exc
                except OSError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"库已经删干净了（{vault_root}），但写 `.env` 没成功"
                            f"（{exc.strerror or exc}）。请把 `.env` 里的 "
                            "KB_VAULT_PATH 手工清空——不清的话服务还指着那个"
                            "已经不存在的路径"
                        ),
                    ) from exc
            else:
                # **库还在就别解绑。** 否则界面上显示「还没有知识库」而笔记
                # 还躺在原地——正是本设计要消灭的那种状态。
                result["notes"].append(
                    "笔记目录没删掉，所以还指着它。处理完再点一次「移除」"
                )
            return result

    return router
