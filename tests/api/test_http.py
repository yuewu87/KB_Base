import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import kb.api.http as http_mod
from kb.api.http import create_app
from kb.config import Config
from kb.core.vault import KNOWLEDGE, list_drafts, read_draft
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
        "target_path": f"{KNOWLEDGE}/后端/并发写锁.md",
        "frontmatter": {"类型": "概念", "主题": ["后端"]},
        "content": "# 并发写锁\n\n见 [[后端]]\n",
        "pending_reason": None,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """带 git 的 vault + 一个返回固定计划的假模型。"""
    (tmp_path / KNOWLEDGE / "后端").mkdir(parents=True)
    _git(tmp_path, "init", "-b", "main")
    _git(
        tmp_path,
        "-c", "user.name=t", "-c", "user.email=t@x",
        "commit", "--allow-empty", "-m", "init",
    )
    cfg = Config("k", "u", "m", tmp_path, None)
    return TestClient(create_app(cfg, llm=FakeLLM(_plan_json())))


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
    assert not (tmp_path / KNOWLEDGE / "后端" / "并发写锁.md").exists()
    assert (tmp_path / "00_收件箱").exists()


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
    assert (tmp_path / KNOWLEDGE / "后端" / "并发写锁.md").exists()
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
    (tmp_path / KNOWLEDGE / "后端").mkdir(parents=True)
    cfg = Config("k", "u", "m", tmp_path, None)
    bad = TestClient(create_app(cfg, llm=FakeLLM("坏输出")))
    bad.post("/push", json={"content": "内容"})

    body = bad.post("/organize", json={}).json()
    assert body["results"][0]["kind"] == "failed"
    assert body["results"][0]["error"]


def test_organize_empty_inbox_is_not_an_error(client):
    body = client.post("/organize", json={}).json()
    assert body == {"count": 0, "results": []}
