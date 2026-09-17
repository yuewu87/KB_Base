"""Web UI 路由。"""

import json

import pytest
from fastapi.testclient import TestClient

from kb.api.http import create_app
from kb.config import Config
from kb.core.vault import write_note
from kb.llm.base import FakeLLM

# 对话输出固定成「不做动作」的一句——Web 测试不该真连模型
CHAT_REPLY = '{"say": "好的", "action": null, "params": {}}'

# `/new` 现在投完直接整理（Q88），同一个假模型也要能回答整理那条链——
# 它按 outcome/target_path 解析，形状和对话完全不同。按系统提示分流。
PLAN_REPLY = json.dumps(
    {
        "outcome": "create",
        "target_path": "计算机/窗口缩放那个坑.md",
        "frontmatter": {"类型": "概念", "主题": ["计算机"]},
        "content": "# 窗口缩放那个坑\n\n见 [[计算机]]\n",
    },
    ensure_ascii=False,
)


class _TwoChainLLM:
    """对话给固定的一句，整理给一份合法计划。"""

    def complete(self, system: str, user: str) -> str:
        return CHAT_REPLY if "你能做的动作" in system else PLAN_REPLY


@pytest.fixture
def vault(tmp_path):
    """一个小 vault：一个领域、一篇笔记、一天的整理日志。"""
    write_note(
        tmp_path / "计算机" / "队列串行化.md",
        {"类型": "概念", "主题": ["计算机", "并发"]},
        "# 队列串行化\n\n并发写入会锁表。\n",
    )
    journal = tmp_path / "_索引" / "整理日志"
    journal.mkdir(parents=True)
    (journal / "2026-09-16.md").write_text(
        "## 23:20 整理 1 条草稿\n\n- 新建：[[队列串行化]]（计算机/队列串行化.md）\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def client(vault, tmp_path):
    cfg = Config(
        llm_api_key="k",
        llm_base_url="http://x",
        llm_model="m",
        vault_path=vault,
        port=None,
    )
    # **env_file 必须传**：`create_app` 的默认值是工程根目录那个真 `.env`，
    # 不传的话 `/settings` 一保存就把用户的配置改了。
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n",
        encoding="utf-8",
    )
    # data_dir 指到 vault（生产里是 data/）——会话落盘的预期位置要对得上
    return TestClient(
        create_app(cfg, llm=_TwoChainLLM(), data_dir=vault, env_file=env)
    )


@pytest.mark.parametrize("path", ["/", "/journal", "/flow", "/runtime"])
def test_pages_render(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_index_has_six_nav_buttons(client):
    """左栏六项。「巡检」是本次新加的那一项。"""
    body = client.get("/").text
    for label in ("记一条", "ai对话", "整理日志", "工作日志", "运行日志", "巡检"):
        assert label in body
    assert "巡检一次" not in body        # 它搬进巡检页了，不挂全局导航


# ---------- 对话 ----------

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
    # 表单 POST 落在 `/`：`/chat` 是服务端的 JSON 端点，两者同名会互相遮蔽
    resp = client.post("/", data={"message": "记一下 X"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/")


# ---------- 整理日志 ----------

def test_journal_shows_entries(client):
    body = client.get("/journal").text
    assert "2026-09-16" in body
    assert "23:20 整理 1 条草稿" in body
    assert "新建：[[队列串行化]]" in body


def test_journal_side_report_shows_the_latest_run(client, vault):
    """「报告」页签里是**最近一次整理**的文字记录，与箱子无关。

    不能直接断言那串文字在整页里——它在主区卡片里本来就有，改不改侧栏
    都过（这条测试的第一版就是这样，等于只测了「有个 sidebar 容器」）。
    把「报告」那个面板单独抠出来看。
    """
    import re

    from kb.core.flow import emit, set_run

    set_run("20260917-1400")
    emit("投递", "你在网页上投递了一条草稿")
    emit("落盘", "新建 计算机/队列串行化.md")

    body = client.get("/journal").text
    pane = re.search(r'data-pane="report">(.*?)data-pane="history"', body, re.S)
    assert pane, "「报告」面板不在"
    assert "你在网页上投递了一条草稿" in pane.group(1)
    assert "bubble assistant" in pane.group(1)          # 手机聊天式的气泡


def test_journal_empty_state(tmp_path):
    cfg = Config(
        llm_api_key="k", llm_base_url="http://x", llm_model="m",
        vault_path=tmp_path, port=None,
    )
    # `data_dir` 传了才隔离——默认是真实 `DATA_DIR`，不传就会往真库写流程日志
    body = TestClient(create_app(cfg, data_dir=tmp_path)).get("/journal").text
    assert "还没有整理记录" in body


# ---------- 工作日志 ----------

def test_flow_page_renders_chain(client, vault):
    from kb.core.flow import emit, set_run

    set_run("20260917-1400")
    emit("投递", "你在网页上投递了一条草稿")
    emit("规划", "模型决定放进「计算机/git」")
    body = client.get("/flow").text
    assert "你在网页上投递了一条草稿" in body
    assert "模型决定放进" in body
    assert "提交" in body            # 链上没走到的那几步也要画出来


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


def test_journal_sidebar_has_two_tabs(client):
    """整理日志的右侧栏是「报告 | 历史」两个竖排页签，默认开「报告」。"""
    body = client.get("/journal").text
    assert 'class="tabs"' in body
    assert ">报告<" in body
    assert ">历史<" in body
    assert 'class="tab active"' in body


# ---------- 模板随手记 ----------

def test_new_page_lists_templates(client):
    body = client.get("/new").text
    assert "踩了个坑" in body
    assert "学到一招" in body


def test_new_page_prefills_chosen_template(client):
    body = client.get("/new?t=踩了个坑").text
    assert "当时是怎么想的" in body


def test_push_from_web_organizes_immediately(client, vault):
    """模板投递也直接走完（Q88）。"""
    from kb.core.vault import list_drafts

    client.post("/new", data={"content": "窗口缩放那个坑"}, follow_redirects=False)
    assert list_drafts(vault) == []        # 不留草稿


def test_push_from_web_rejects_empty(client):
    resp = client.post("/new", data={"content": "   "}, follow_redirects=False)
    assert resp.status_code == 400


# ---------- 巡检页（报告 + 「我知道了」+ 一键巡检） ----------


def test_sweep_page_shows_the_report(client, vault):
    from kb.core.sweep_state import save_report

    save_report(vault, {"summary": "合并了 2 组近义标签", "tag_merges": [], "dir_merges": []})
    body = client.get("/sweep").text
    assert "合并了 2 组近义标签" in body


def test_flow_page_has_no_sweep_report(client, vault):
    """报告搬去巡检页了，工作日志页不该再挤着它（Q93）。"""
    from kb.core.sweep_state import save_report

    save_report(vault, {"summary": "合并了 2 组近义标签", "tag_merges": [], "dir_merges": []})
    assert "合并了 2 组近义标签" not in client.get("/flow").text


def test_sweep_page_has_the_acknowledge_button(client, vault):
    """报告下面**只有一个**「我知道了」——它就是个提醒，不做别的。"""
    from kb.core.sweep_state import save_report

    save_report(vault, {"summary": "x", "tag_merges": [], "dir_merges": []})
    body = client.get("/sweep").text
    assert "我知道了" in body
    assert "还需调整" not in body                 # 2026-09-17 删了，不留半截
    assert 'id="sweep-note"' not in body


def test_reply_known_marks_read(client, vault):
    from kb.core.sweep_state import load_state, save_report

    save_report(vault, {"summary": "合并了 2 组近义标签", "tag_merges": [], "dir_merges": []})
    # 真实表单是个不带 name 的普通提交按钮——这里也别塞死参数，
    # 否则测的不是真实的请求形状
    client.post("/sweep/reply", follow_redirects=False)
    assert load_state(vault)["report"]["read"] is True          # 记下了

    body = client.get("/sweep").text
    assert "合并了 2 组近义标签" in body                          # **读过了也还显示**
    assert "card sweep read" in body                            # 只是不再高亮


def test_sweep_run_button_lives_on_the_sweep_page(client):
    """「巡检一次」是巡检页自己的动作，不挂全局导航。"""
    assert "巡检一次" in client.get("/sweep").text
    assert "巡检一次" not in client.get("/flow").text


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


def test_sweep_run_reports_model_failure_instead_of_500(tmp_path):
    """模型输出坏了不能甩一张 500 页——要变成一句看得懂的提示。

    假模型给的不是 JSON，`run_sweep` 会抛 `SweepError`。
    """
    from kb.core.sweep_state import load_state

    cfg = Config(
        llm_api_key="k", llm_base_url="http://x", llm_model="m",
        vault_path=tmp_path, port=None,
    )
    c = TestClient(create_app(cfg, llm=FakeLLM("这不是 JSON"), data_dir=tmp_path))
    resp = c.post("/sweep/run", follow_redirects=False)
    assert resp.status_code == 303                              # 不是 500 页

    report = load_state(tmp_path)["report"]
    assert "没跑成" in report["summary"]
    assert report["read"] is False                              # 人还没看到


# ---------- 箱子与页签 ----------

def test_invalid_d_falls_back_to_latest(client):
    """非法 `d` 落回最新一天——手改 URL 不该看到错误页。

    **这条同时钉住参数名 `d`**：模板若写成 `?day=`，页面会永远停在最新一天
    而没人发现。
    """
    latest = client.get("/journal")
    for bad in ("1999-01-01", "../etc/passwd", "abc", ""):
        r = client.get(f"/journal?d={bad}")
        assert r.status_code == 200
        assert r.text == latest.text


def test_box_links_use_the_d_parameter(client):
    """箱子按钮的链接里带着 `?d=`——参数名不能悄悄改。"""
    r = client.get("/journal")
    assert "?d=2026-09-16" in r.text


def test_valid_d_actually_switches_the_day(client, vault):
    """`?d=` 指向**存在的更早一天**时，主区真的换成那天。

    这是「箱子」的核心用户故事——原来只测了非法 `d` 会落回最新一天，
    正向换天一次都没测过。

    （侧栏的箱子列表里**两天都在**，所以「某个箱子名出现」证明不了什么：
    得看主区那个 `<h2 class="day">` 和各天的条目。）
    """
    journal = vault / "_索引" / "整理日志"
    (journal / "2026-09-17.md").write_text(
        "## 09:00 整理 1 条草稿\n\n- 新建：[[今天那篇]]（计算机/今天那篇.md）\n",
        encoding="utf-8",
    )

    older = client.get("/journal?d=2026-09-16").text
    newer = client.get("/journal?d=2026-09-17").text

    assert older != newer
    assert '<h2 class="day">26_9_16箱子</h2>' in older       # 主区标题换了天
    assert '<h2 class="day">26_9_17箱子</h2>' in newer
    assert "今天那篇" in newer and "今天那篇" not in older    # 内容也跟着换
    assert "23:20 整理 1 条草稿" in older


def test_sweep_page_renders(client):
    r = client.get("/sweep")
    assert r.status_code == 200
    assert "巡检" in r.text


def test_sweep_page_is_html_not_json(client):
    """`/sweep` 必须是页面，不是那个 JSON 端点——先注册的赢，容易遮蔽。"""
    r = client.get("/sweep")
    assert r.headers["content-type"].startswith("text/html")


def test_flow_page_has_the_chain_tab(client, vault):
    """右侧栏是「流程图 | 历史」，流程图里画最近一次那条链。

    链要真走过才有——先记一条，否则 `latest` 是空的，页面画的是空态。
    """
    from kb.core.flow import emit, set_run

    set_run("20260917-1400")
    emit("投递", "投了")

    r = client.get("/flow")
    assert "流程图" in r.text
    assert "历史" in r.text
    assert ">投递<" in r.text          # 流程链上的一步


def test_runtime_page_has_no_tabs(client):
    """运行日志页没有页签，只有箱子。

    **断结构，别断内容。** 原先那条断的是 `"历史" not in r.text`——运行日志
    页显示的正是**本机真实的** `data/logs/kb/`（`LOG_DIR` 是模块常量，测试
    没隔离它），日志里一旦出现「历史」两个字就无故变红。
    """
    r = client.get("/runtime")
    assert 'class="tabs"' not in r.text          # 没有页签容器
    assert "data-pane=" not in r.text            # 也没有面板


# ---------- 测试隔离 ----------

def test_write_paths_do_not_touch_the_real_data_dir(client):
    """跑测试不该往真库写东西。

    **必须真的触发一条写路径。** 只 GET 什么都不会写——那种钉子是假的：
    实测故意用不带 `data_dir` 的 `create_app` 跑 GET，真库毫发无损。

    这里走 `POST /new`（投递 + 立即整理），它正是会 emit 流程记录的那条。
    """
    from kb.config import DATA_DIR

    real = DATA_DIR / "logs" / "flow"

    def sizes() -> dict[str, int]:
        if not real.is_dir():
            return {}
        return {p.name: p.stat().st_size for p in real.glob("*.jsonl")}

    before = sizes()

    resp = client.post(
        "/new", data={"content": "这条不该写进真库"}, follow_redirects=False
    )
    assert resp.status_code in (303, 200)

    assert sizes() == before, "测试往真实 data/ 写了流程记录——某条 create_app 调用忘了传 data_dir"


def test_settings_save_does_not_touch_the_real_env(client):
    """跑测试不该改工程根目录那个真 `.env`。

    **必须真的走一次保存**——只 GET `/settings` 什么都不写，那种钉子是假的
    （项目里栽过一条）。验证办法：临时把夹具的 `env_file=...` 去掉，
    这条必须变红。看完改回来。
    """
    from kb.config import PROJECT_ROOT

    real = PROJECT_ROOT / ".env"
    before = real.read_bytes() if real.is_file() else None

    client.post("/settings", json={"values": {"KB_LLM_MODEL": "测试不许改真文件"}})

    after = real.read_bytes() if real.is_file() else None
    assert after == before, "测试改了工程根目录的 .env——夹具忘了传 env_file"


# ---------- 配置热重载 ----------

def test_save_settings_writes_env_and_reloads(tmp_path):
    """保存 = 写 `.env` + 重载 + 让该失效的失效。

    **重载有没有生效，不靠看内部变量验**——保存完调一次 `/settings/test`，
    它的兜底值取自 `get_cfg()`，那边看到的就是重载后的配置。
    """
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=old\n", encoding="utf-8"
    )
    seen: list[str] = []

    def _build(c):
        seen.append(c.llm_model)
        return FakeLLM("{}")

    app = create_app(
        Config("k", "u", "old", tmp_path, None),
        data_dir=tmp_path, build_llm_fn=_build, env_file=env,
    )
    client = TestClient(app)

    resp = client.post("/settings", json={"values": {"KB_LLM_MODEL": "new"}})

    assert resp.status_code == 200
    assert "KB_LLM_MODEL=new" in env.read_text(encoding="utf-8")

    # 表单里没填模型名 → 兜底取当前配置 → 应当是 new
    client.post("/settings/test", json={"values": {}})
    assert seen[-1] == "new"


def test_reload_to_an_empty_shell_does_not_swap_in(tmp_path):
    """重载退化成空壳时**不许换进去**。

    `reload_config` 永不抛（读不回来就给一份空壳），所以调用方从返回值上
    分不清成功与降级。分不清就换，等于用手滑删掉一行 `.env` 的动作
    把正在跑的服务带崩。

    **「没换进去」得验实。** 只看 400 +「必填」是不够的：把 swap 挪到
    raise 之前，那两条断言照样绿。所以这里再用一个黑盒手段**读一次内存里
    那份配置**——`/settings/test` 不传模型名时兜底取 `get_cfg()`，
    记下它把哪个模型名递给了 build 函数。
    """
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=old\n", encoding="utf-8"
    )
    cfg = Config("k", "u", "old", tmp_path, None)
    built: list[str] = []

    def _build(c):
        built.append(c.llm_model)
        return FakeLLM("{}")

    app = create_app(cfg, data_dir=tmp_path, env_file=env, build_llm_fn=_build)
    client = TestClient(app)

    def current_model() -> str:
        """黑盒读「内存里那份配置」的模型名。"""
        client.post("/settings/test", json={"values": {}})
        return built[-1]

    assert current_model() == "old"          # 保存前

    # 手工把 .env 弄坏（模拟手滑删行），再走一次保存
    env.write_text("KB_LLM_MODEL=x\n", encoding="utf-8")
    resp = client.post("/settings", json={"values": {"KB_LOG_LEVEL": "DEBUG"}})

    assert resp.status_code == 400
    assert "必填" in resp.json()["detail"]
    # swap 真挪到 raise 之前时，这一行会看见「x」（或空壳的空串）——变红
    assert current_model() == "old"


def test_saving_after_a_hand_broken_log_level_does_not_500(tmp_path):
    """手改出 TRACE 之后，发一个不带该键的 POST 不该炸。

    原来的顺序是「换 cfg → setLevel」，setLevel 抛 ValueError 就成了
    「文件已写、cfg 已换、客户端拿 500」——改动其实生效了。
    """
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=m\nKB_LOG_LEVEL=TRACE\n",
        encoding="utf-8",
    )
    app = create_app(
        Config("k", "u", "m", tmp_path, None),
        data_dir=tmp_path, env_file=env, build_llm_fn=lambda c: FakeLLM("{}"),
    )
    resp = TestClient(app).post("/settings", json={"values": {"KB_LLM_MODEL": "x"}})

    assert resp.status_code == 200


def test_saving_the_model_invalidates_the_llm_cache(tmp_path):
    """保存模型名之后，下一次拿 LLM 得是**新建的**。

    设计第十节点名要测的一条。缓存不失效的话，改完模型还得重启才生效——
    而「保存即生效」正是这次要做的。
    """
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=old\n", encoding="utf-8"
    )
    built: list[str] = []

    def _build(c):
        built.append(c.llm_model)
        return FakeLLM("{}")

    app = create_app(
        Config("k", "u", "old", tmp_path, None),
        data_dir=tmp_path, env_file=env, build_llm_fn=_build,
    )
    client = TestClient(app)

    # 先让它建一次（缓存有东西了）
    client.post("/settings/test", json={"values": {}})
    assert built == ["old"]

    client.post("/settings", json={"values": {"KB_LLM_MODEL": "new"}})

    # 再要一次——缓存该失效了
    client.post("/settings/test", json={"values": {}})
    assert built[-1] == "new"


def test_test_connection_requires_a_body(client):
    """body 必填——设计要的是「拿表单里当前填的值」。

    不带 body 的调用只能测已保存的配置，而用户刚改的正是表单里的值——
    让它响一声（422）比悄悄退化成「测旧配置」好。前端的 JS 必须传
    `{values: ...}`。
    """
    assert client.post("/settings/test").status_code == 422


def test_save_settings_rejects_bad_value(client):
    resp = client.post("/settings", json={"values": {"KB_LOG_LEVEL": "TRACE"}})
    assert resp.status_code == 400
    assert "日志级别" in resp.json()["detail"]


def test_save_settings_ignores_readonly(client):
    """后端不信前端——只读字段提交了也不改。"""
    resp = client.post(
        "/settings",
        json={"values": {"KB_VAULT_PATH": "E:\\别处", "KB_LLM_MODEL": "m"}},
    )
    assert resp.status_code == 200
    assert resp.json()["saved"] == {"KB_LLM_MODEL": "m"}


def test_settings_fragment_has_no_full_page(client):
    """模态是从任意页面 fetch 进来的——只要窗口那一段，不要整页骨架。"""
    body = client.get("/settings").text
    assert "<!doctype" not in body.lower()
    assert "模型配置" in body


def test_settings_has_the_about_group(client):
    """「关于」不在 `.env` 里，是拼出来的——但界面上得有这一组。"""
    body = client.get("/settings").text
    assert "关于" in body
    assert "服务状态" in body


def test_readonly_fields_show_the_effective_values(tmp_path):
    """只读两栏显示**生效值**，不是 `.env` 里的字面值。

    这份 `.env` 里没写 `KB_VAULT_PATH` / `KB_PORT`——按字面值两栏都是**空白**，
    尽管跑起来用的是配置里的 vault 路径、端口是自动找的空闲端口。
    空白看起来像坏了，而这一页的任务正是让人看清现在在用的是什么。
    """
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=m\n", encoding="utf-8"
    )
    cfg = Config("k", "u", "m", tmp_path / "我的库", None)

    body = TestClient(
        create_app(cfg, data_dir=tmp_path, env_file=env)
    ).get("/settings").text

    assert "我的库" in body          # vault 路径：生效值
    assert "自动" in body            # 端口没配 → 说清是自动找的，不是空白


def test_service_status_shows_the_start_time(client, monkeypatch):
    """设计第四节那栏的样例是 `已连接 · 启动于 18:31`——启动时间要在。"""
    from kb.api import runtime

    monkeypatch.setattr(runtime, "running_port", lambda: 51723)
    monkeypatch.setattr(
        runtime, "read_service_info", lambda: {"started": "2026-09-17 18:31:22"}
    )
    monkeypatch.setattr(runtime, "is_stale", lambda: False)

    assert "启动于 18:31" in client.get("/settings").text


def test_settings_never_echoes_the_api_key(client, tmp_path):
    """**API Key 不回显原文。** 只给掩码。

    **掩码算的是夹具注入的那份 `.env`**（`tmp_path` 里的临时文件），
    不是工程根目录那个真的——原来这条靠 `monkeypatch.setenv` 顶，而
    `read_env` 根本不看 `os.environ`，真正决定掩码出不出得来的是开发机上
    恰好存在、且那行非空的真 `.env`。**新克隆的仓库没有它，这条必红。**
    """
    (tmp_path / ".env").write_text(
        "KB_LLM_API_KEY=sk-super-secret-value\n"
        "KB_LLM_BASE_URL=http://x\n"
        "KB_LLM_MODEL=m\n",
        encoding="utf-8",
    )

    body = client.get("/settings").text
    assert "sk-super-secret-value" not in body
    assert "••" in body


def test_quit_calls_the_injected_function(tmp_path):
    """**退出要能注入**——不然跑一次测试就把 pytest 自己杀了。"""
    quit_calls = []
    app = create_app(
        Config("k", "u", "m", tmp_path, None),
        llm=FakeLLM("{}"),
        data_dir=tmp_path,
        quit_fn=lambda: quit_calls.append(1),
    )
    resp = TestClient(app).post("/quit")

    assert resp.status_code == 200
    assert quit_calls == [1]
