"""忙的时候端点必须当场拒。**这是 `Busy` 存在的全部意义。**"""

import pytest
from fastapi.testclient import TestClient

from kb.api.http import create_app
from kb.config import Config
from kb.llm.base import FakeLLM


@pytest.fixture
def client(tmp_path):
    vault = tmp_path / "库"
    vault.mkdir()
    (vault / ".git").mkdir()          # `settings.validate` 要的那个标记
    cfg = Config(
        llm_api_key="k", llm_base_url="http://x", llm_model="m",
        vault_path=vault, port=None,
    )
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n"
        f"KB_VAULT_PATH={vault}\n",
        encoding="utf-8",
    )
    data = tmp_path / "data"
    data.mkdir()
    return TestClient(create_app(cfg, llm=FakeLLM([]), data_dir=data,
                                 env_file=env))


@pytest.mark.parametrize("what,label", [("migrate", "迁移"), ("remove", "移除")])
def test_organize_is_rejected_while_something_else_runs(client, what, label):
    """别人在动库的时候 `/organize` 必须当场拒。

    不拒的话它会把半截笔记写进库——前一半落旧库、后一半落新库，
    而最后那个 `commit_changes` 只在新库里提交，**旧库那半永远不进 git
    却躺在磁盘上**。那是「看起来一切正常」的失败，最难发现。
    """
    busy = client.app.state.busy
    assert busy.acquire(what) is True
    try:
        resp = client.post("/organize", json={})
        assert resp.status_code == 409
        assert label in resp.json()["detail"]
    finally:
        busy.release()


@pytest.mark.parametrize("what,label", [("migrate", "迁移"), ("remove", "移除")])
def test_web_chat_form_is_rejected_while_something_else_runs(client, what, label):
    """网页对话表单（`POST /`）也要占锁——**它整轮都可能在写库**。

    对话层能触发「整理」动作（`api/http.py` 的 `_chat_organize_fn`），
    所以半路迁移期间放它进来，落盘的就是一个搬了一半的库。
    """
    busy = client.app.state.busy
    assert busy.acquire(what) is True
    try:
        resp = client.post("/", data={"message": "x"}, follow_redirects=False)
        assert resp.status_code == 409
        assert label in resp.json()["detail"]
    finally:
        busy.release()


def test_chat_endpoint_is_rejected_while_something_else_runs(client):
    """`/chat`（会话层 AI 走的 JSON 端点）同理。"""
    busy = client.app.state.busy
    assert busy.acquire("migrate") is True
    try:
        resp = client.post("/chat", json={"message": "x"})
        assert resp.status_code == 409
        assert "迁移" in resp.json()["detail"]
    finally:
        busy.release()


def test_web_push_shares_the_same_lock(client):
    """网页投递与服务端整理**必须是同一把锁**。

    `create_app` 各造一把的话，网页这边「正在迁移」挡住了投递，服务端
    `/organize` 却照样把半截笔记写进库——整把锁等于没上。这条就是钉
    `app.include_router(..., busy=busy, ...)` 传的是**那个实例**本身。
    """
    busy = client.app.state.busy
    assert busy.acquire("migrate") is True
    try:
        resp = client.post("/new", data={"content": "x"}, follow_redirects=False)
        assert resp.status_code == 409
        assert "迁移" in resp.json()["detail"]
    finally:
        busy.release()


@pytest.mark.parametrize("path,data", [
    ("/drop", {"ids": ["x"]}),
    ("/inbox", None),
    ("/search", None),
    ("/sweep", None),
])
def test_reads_are_not_blocked_by_busy(client, path, data):
    """**只有整理被拦，读操作照常。**

    迁移期间把 `/inbox` 也挡掉的话，用户连「库里现在有什么」都看不到，
    而那时候他正需要看一眼。读不会把库写到一半。
    """
    busy = client.app.state.busy
    assert busy.acquire("migrate") is True
    try:
        resp = client.get(path) if data is None else client.post(path, json=data)
        # **写死 200，不写「不是 409」**——后者对 500 也放行，
        # 而这个夹具下这几个端点都该正常返回：读照常才叫读照常。
        assert resp.status_code == 200
    finally:
        busy.release()
