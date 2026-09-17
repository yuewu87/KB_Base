"""Web UI 路由。"""

import json

import pytest
from fastapi.testclient import TestClient

from kb.api.http import create_app
from kb.config import Config
from kb.core.vault import write_note

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
def client(vault):
    cfg = Config(
        llm_api_key="k",
        llm_base_url="http://x",
        llm_model="m",
        vault_path=vault,
        port=None,
    )
    # data_dir 指到 vault（生产里是 data/）——会话落盘的预期位置要对得上
    return TestClient(create_app(cfg, llm=_TwoChainLLM(), data_dir=vault))


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


# ---------- 巡检页（报告 + 两个回复按钮 + 一键巡检） ----------


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


def test_sweep_page_has_two_reply_buttons(client, vault):
    from kb.core.sweep_state import save_report

    save_report(vault, {"summary": "x", "tag_merges": [], "dir_merges": []})
    body = client.get("/sweep").text
    assert "我知道了" in body
    assert "还需调整" in body


def test_reply_known_marks_read(client, vault):
    from kb.core.sweep_state import load_state, save_report

    save_report(vault, {"summary": "合并了 2 组近义标签", "tag_merges": [], "dir_merges": []})
    client.post("/sweep/reply", data={"reply": "知道了"}, follow_redirects=False)
    assert load_state(vault)["report"]["read"] is True          # 记下了

    body = client.get("/sweep").text
    assert "合并了 2 组近义标签" in body                          # **读过了也还显示**
    assert "card sweep read" in body                            # 只是不再高亮


def test_reply_adjust_reruns_the_sweep_with_the_note(vault, monkeypatch):
    """「还需调整」——带着你写的话把巡检**重跑一遍**（Q96）。

    旧行为是把你的意见当一条**草稿**投进收件箱，走整理那条链；可要改的
    往往是**上一次巡检刚做的事**，两边对不上（`apply_plan` 单向，也没留
    反演信息，所以「撤销」不是一条可走的路）。
    """
    from kb.core.sweep_state import load_state, save_report
    from kb.web import router as web_router

    seen: list[str] = []

    class _CaptureLLM:
        def complete(self, system: str, user: str) -> str:
            seen.append(system + user)
            return '{"tag_merges": [], "dir_merges": [], "summary": "无"}'

    sent: list[str] = []
    monkeypatch.setattr(
        web_router,
        "push_and_organize",
        lambda *a, **kw: sent.append(str(a)) or "",
    )

    cfg = Config(
        llm_api_key="k", llm_base_url="http://x", llm_model="m",
        vault_path=vault, port=None,
    )
    c = TestClient(create_app(cfg, llm=_CaptureLLM(), data_dir=vault))

    save_report(vault, {"summary": "x", "tag_merges": [], "dir_merges": []})
    resp = c.post(
        "/sweep/reply",
        data={"reply": "调整", "note": "别把 shell 并进命令行"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert any("别把 shell 并进命令行" in p for p in seen)       # 真的送到了模型手里
    assert sent == []                                          # 不再投草稿
    # 重跑出一份**新报告**，是未读的——页面会重新高亮它
    assert load_state(vault)["report"]["read"] is False


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
    from kb.llm.base import FakeLLM

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
    """运行日志页没有页签，只有箱子。"""
    r = client.get("/runtime")
    assert 'class="tabs"' not in r.text
    assert "历史" not in r.text


# ---------- 测试隔离 ----------

def test_tests_do_not_write_into_the_real_data_dir(client):
    """跑测试不该往真库写东西。

    `create_app` 的 `data_dir` 默认是真实 `DATA_DIR`——有一条路径忘了传
    `data_dir`，测试就会往 `data/logs/flow/` 里写记录（实测真库从 640 条
    被涨到 766 条）。这条钉住它。
    """
    from kb.config import DATA_DIR

    real = DATA_DIR / "logs" / "flow"
    before = sorted(p.name for p in real.glob("*.jsonl")) if real.is_dir() else []
    sizes = {p.name: p.stat().st_size for p in real.glob("*.jsonl")} if real.is_dir() else {}

    client.get("/journal")
    client.get("/flow")

    after = {p.name: p.stat().st_size for p in real.glob("*.jsonl")} if real.is_dir() else {}
    assert sorted(after) == before
    assert after == sizes
