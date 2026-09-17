import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import kb.api.http as http_mod
from kb.api.http import create_app
from kb.config import Config
from kb.core.vault import INBOX, list_drafts, read_draft
from kb.llm.base import FakeLLM


def _git(vault: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=vault,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _plan_json(**overrides) -> str:
    data = {
        "outcome": "create",
        "target_path": "计算机/并发写锁.md",
        "frontmatter": {"类型": "概念", "主题": ["计算机"]},
        "content": "# 并发写锁\n\n见 [[计算机]]\n",
        "pending_reason": None,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _chat_json(say: str = "好的，我记下了", action=None, params=None) -> str:
    return json.dumps(
        {"say": say, "action": action, "params": params or {}}, ensure_ascii=False
    )


class _ChatAwareLLM:
    """按系统提示分流的假模型。

    **一个夹具要同时供两条链用**，而它们的输出形状不同：对话要
    `{say, action, params}`，整理要 `{outcome, target_path, ...}`——传一个
    固定字符串满足不了两边。对话的系统提示里有动作清单，据此分流。
    """

    def __init__(self, chat_reply: str | None = None) -> None:
        self.chat_reply = chat_reply or _chat_json()

    def complete(self, system: str, user: str) -> str:
        if "你能做的动作" in system:
            return self.chat_reply
        return _plan_json()


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """带 git 的 vault。

    **会话目录也落在这里**（生产里是 `data/`）——落盘位置要能被测试指认，
    所以 `create_app` 收一个 `data_dir`。
    """
    (tmp_path / "计算机").mkdir(parents=True)
    _git(tmp_path, "init", "-b", "main")
    _git(
        tmp_path,
        "-c", "user.name=t", "-c", "user.email=t@x",
        "commit", "--allow-empty", "-m", "init",
    )
    return tmp_path


@pytest.fixture
def client(vault: Path) -> TestClient:
    """带 git 的 vault + 一个按提示分流的假模型。"""
    cfg = Config("k", "u", "m", vault, None)
    return TestClient(create_app(cfg, llm=_ChatAwareLLM(), data_dir=vault))


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---------- 投递 ----------

def test_push_creates_draft(client, tmp_path):
    resp = client.post(
        "/push",
        json={"content": "并发写入会锁表", "project": "电商后台", "source": "会话"},
    )
    assert resp.status_code == 200
    draft_id = resp.json()["id"]

    drafts = list_drafts(tmp_path)
    assert len(drafts) == 1
    stored = read_draft(drafts[0])
    assert stored.id == draft_id
    assert stored.project == "电商后台"


def test_push_returns_immediately_without_organizing(client, tmp_path):
    """异步（Q55）：投递只落草稿，不做任何整理。"""
    client.post("/push", json={"content": "内容"})
    assert not (tmp_path / "计算机" / "并发写锁.md").exists()
    assert (tmp_path / INBOX).exists()


def test_push_rejects_empty_content(client):
    resp = client.post("/push", json={"content": "   "})
    assert resp.status_code == 400
    assert "不能为空" in resp.json()["detail"]


def test_push_accepts_content_without_project(client):
    """没项目不是错误——`项目` 只是可选字段，不影响归到哪个领域。"""
    assert client.post("/push", json={"content": "GIL 是怎么回事"}).status_code == 200


def test_push_retries_on_id_collision(client, tmp_path, monkeypatch):
    """id 撞号时换一个重投，而不是覆盖已有草稿（那是数据丢失）。"""
    ids = iter(["撞号-id", "撞号-id", "另一个-id"])
    monkeypatch.setattr(http_mod, "new_draft_id", lambda: next(ids))

    first = client.post("/push", json={"content": "第一条"})
    second = client.post("/push", json={"content": "第二条"})

    assert first.json()["id"] == "撞号-id"
    assert second.json()["id"] == "另一个-id"
    assert len(list_drafts(tmp_path)) == 2


# ---------- 收件箱 ----------

def test_inbox_lists_drafts(client):
    client.post("/push", json={"content": "第一条"})
    client.post("/push", json={"content": "第二条"})

    data = client.get("/inbox").json()
    assert data["count"] == 2
    assert {item["preview"] for item in data["items"]} == {"第一条", "第二条"}


def test_inbox_empty(client):
    assert client.get("/inbox").json() == {"count": 0, "items": []}


# ---------- 整理 ----------

def test_organize_all(client, tmp_path):
    client.post("/push", json={"content": "并发写入会锁表"})
    resp = client.post("/organize", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["kind"] == "created"
    assert (tmp_path / "计算机" / "并发写锁.md").exists()
    assert list_drafts(tmp_path) == []


def test_organize_single_by_id(client, tmp_path):
    first = client.post("/push", json={"content": "第一条"}).json()["id"]
    client.post("/push", json={"content": "第二条"})

    resp = client.post("/organize", json={"draft_id": first})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1
    assert len(list_drafts(tmp_path)) == 1        # 第二条还在


def test_organize_single_commits_the_note(client, tmp_path):
    """单条整理的 commit 必须包含新建的笔记，而不只是整理日志。

    容易写错的地方：丢掉 organize_draft 返回的「动过的文件」，
    那样 commit 里只剩日志，笔记反而没入库。
    """
    draft_id = client.post("/push", json={"content": "并发写入会锁表"}).json()["id"]
    client.post("/organize", json={"draft_id": draft_id})

    committed = _git(tmp_path, "show", "--name-only", "--format=", "HEAD").stdout
    assert "并发写锁.md" in committed


def test_organize_unknown_id_returns_404(client):
    resp = client.post("/organize", json={"draft_id": "不存在"})
    assert resp.status_code == 404
    assert "找不到草稿" in resp.json()["detail"]


def test_organize_reports_failures(tmp_path):
    (tmp_path / "计算机").mkdir(parents=True)
    cfg = Config("k", "u", "m", tmp_path, None)
    bad = TestClient(create_app(cfg, llm=FakeLLM("坏输出")))
    bad.post("/push", json={"content": "内容"})

    body = bad.post("/organize", json={}).json()
    assert body["results"][0]["kind"] == "failed"
    assert body["results"][0]["error"]


def test_organize_empty_inbox_is_not_an_error(client):
    body = client.post("/organize", json={}).json()
    assert body == {"count": 0, "results": []}


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


def test_chat_persists_only_user_and_final_reply(vault):
    """落盘只留 [这一句用户消息] + [最终回复]——中间的全丢。

    两类都丢：
    - `tool` 是过程不是对话，存下去下次会当历史回喂，越堆越长
    - **中间几轮的 `say` 也丢**：模型每个动作轮都会说一句话，于是
      「记一下 X」会落成「我这就去记」+「记好了」两条回复——一问两答。
      （这条是端到端跑真实 LLM 时看出来的，计划里没有。）
    """
    from kb.core.chat_store import load_chat

    cfg = Config("k", "u", "m", vault, None)
    llm = FakeLLM([
        _chat_json("我记一下", action="push", params={"content": "记一下 X"}),
        _chat_json("记好了"),
    ])
    chat_client = TestClient(create_app(cfg, llm=llm, data_dir=vault))
    data = chat_client.post("/chat", json={"message": "记一下 X"}).json()

    chat = load_chat(vault, data["chat_id"])
    # 先确认动作真的跑过（否则下面那条断言会因为「没产生工具结果」而恒真）
    assert len(list_drafts(vault)) == 1
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][-1]["content"] == "记好了"
    assert all("工具结果" not in m["content"] for m in chat["messages"])
    assert all("我记一下" not in m["content"] for m in chat["messages"])
