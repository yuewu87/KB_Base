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


def test_index_has_four_nav_buttons(client):
    body = client.get("/").text
    for label in ("ai对话", "整理日志", "工作日志", "运行日志"):
        assert label in body


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


def test_journal_has_side_summary(client):
    """右侧栏里发的**是整理总结**。

    不能直接断言那串文字在整页里——它在左侧卡片里本来就有，改不改右侧栏
    都过（这条测试的第一版就是这样，等于只测了「有个 sidebar 容器」）。
    把 `<aside>` 那段单独抠出来看。
    """
    import re

    body = client.get("/journal").text
    aside = re.search(
        r'<aside class="chat-history">(.*?)</aside>', body, re.S
    )
    assert aside, "右侧栏不在"
    assert "23:20 整理 1 条草稿" in aside.group(1)
    assert "bubble assistant" in aside.group(1)          # 手机聊天式的气泡


def test_journal_empty_state(tmp_path):
    cfg = Config(
        llm_api_key="k", llm_base_url="http://x", llm_model="m",
        vault_path=tmp_path, port=None,
    )
    body = TestClient(create_app(cfg)).get("/journal").text
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


def test_journal_sidebar_uses_bubbles(client):
    """整理日志的侧栏也是气泡流。"""
    import re

    body = client.get("/journal").text
    aside = re.search(r'<aside class="chat-history">(.*?)</aside>', body, re.S).group(1)
    assert 'class="bubble assistant"' in aside


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
