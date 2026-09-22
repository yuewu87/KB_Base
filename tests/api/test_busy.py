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
        assert resp.status_code != 409
    finally:
        busy.release()
