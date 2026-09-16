"""Web UI 路由。"""

import pytest
from fastapi.testclient import TestClient

from kb.api.http import create_app
from kb.config import Config
from kb.core.vault import write_note


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


# ---------- 检索 ----------

def test_search_lists_hits(client):
    body = client.get("/?q=锁表").text
    assert "队列串行化" in body
    assert "并发写入会锁表" not in body      # 只列标题与路径，不贴正文


def test_search_reports_no_hits(client):
    body = client.get("/?q=绝不可能命中的词").text
    assert "没找到" in body


def test_search_empty_query_shows_hint(client):
    assert "输入关键词" in client.get("/").text


# ---------- 整理日志 ----------

def test_journal_shows_entries(client):
    body = client.get("/journal").text
    assert "2026-09-16" in body
    assert "23:20 整理 1 条草稿" in body
    assert "新建：[[队列串行化]]" in body


def test_journal_empty_state(tmp_path):
    cfg = Config(
        llm_api_key="k", llm_base_url="http://x", llm_model="m",
        vault_path=tmp_path, port=None,
    )
    body = TestClient(create_app(cfg)).get("/journal").text
    assert "还没有整理记录" in body


# ---------- 工作日志 ----------

def test_flow_says_not_implemented(client):
    """流程日志的字段清单还没定，页面要如实说明，不能装作有数据。"""
    body = client.get("/flow").text
    assert "还没实现" in body
    assert "字段清单还没定" in body
