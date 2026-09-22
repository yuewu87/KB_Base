"""忙的时候端点必须当场拒。**这是 `Busy` 存在的全部意义。**"""

import pytest
from fastapi.testclient import TestClient

from kb.api.http import create_app
from kb.config import Config
from kb.core.lifecycle import Busy
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


@pytest.mark.parametrize(
    "what,label", [("migrate", "迁移"), ("remove", "移除"), ("sweep", "巡检")]
)
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


@pytest.mark.parametrize(
    "what,label", [("migrate", "迁移"), ("remove", "移除"), ("sweep", "巡检")]
)
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


@pytest.mark.parametrize("what,label", [("organize", "整理"), ("migrate", "迁移")])
def test_sweep_endpoint_is_rejected_while_something_else_runs(client, what, label):
    """**`POST /sweep` 也要挂锁——它就是 `kb sweep` 走的那条路。**

    Task 10 给后台线程和网页那条 `/sweep/run` 都挂了锁，**偏偏漏了这个真正
    叫 `/sweep` 的端点**：`kb sweep`（`api/cli.py`）走的就是它，而终端里执行
    `kb sweep` 时正好服务在整理/迁移是常事。漏掉之后两轮巡检（或一轮巡检
    叠一轮整理）会各自重命名同一批标签目录、各自 git commit——正是这次要堵的
    「一半旧库一半新库、看起来一切正常」。

    根因是它那句 docstring 写着「`kb sweep` 与网页「巡检一次」走这里」，
    而网页其实走 `/sweep/run`——**那句错话**让人以为这个端点在锁外只有 CLI 用。
    """
    busy = client.app.state.busy
    assert busy.acquire(what) is True
    try:
        resp = client.post("/sweep")
        assert resp.status_code == 409
        assert label in resp.json()["detail"]
    finally:
        busy.release()


def test_a_background_sweep_stands_down_while_something_else_runs(tmp_path):
    """后台巡检**要占住锁**，占不到就不跑、也不占坑。

    它是服务进程里的一个 daemon 线程，跟请求处理是**并发**的——不占锁的话，
    启动后那一轮巡检跑到一半就可能被一轮整理劈开（`run_sweep` 的 docstring
    自己写着「它走的是和整理草稿同一条链」），而那个形状是「看起来一切正常」。
    """
    from kb.api.http import _sweep_in_background
    from kb.core import sweep_state

    data = tmp_path / "data"
    data.mkdir()
    busy = Busy()
    assert busy.acquire("organize") is True
    try:
        _sweep_in_background(tmp_path / "库", data, FakeLLM([]), busy)
    finally:
        busy.release()

    # **连坑都没占**：`mark_run` 是先用掉的「这次算跑过了」，留在锁外的话，
    # 拿不到锁反而先把坑占上——下一轮要再等一个 `KB_SWEEP_INTERVAL`
    # 才会重试，等于白丢一次巡检。
    state = sweep_state.load_state(data)
    assert state.get("last_sweep") is None
    assert "report" not in state


def test_a_background_sweep_never_raises(tmp_path, monkeypatch):
    """**「绝不抛异常」是它 docstring 里的承诺**——后台线程里抛了没人接。

    `mark_run` / `save_report` 都要写 `data/state.json`，而 `atomic_write`
    全程没有 try。盘写满、目录被设成只读时它们抛的 `OSError` 会直接逃出这个
    daemon 线程；`spawn_service` 传的是 `stderr=subprocess.DEVNULL`，于是运行
    日志里一个字都没有——那一轮巡检既没跑、也没留下「没跑成」的报告，
    巡检页上是一片空白，看起来一切正常。
    """
    from kb.api.http import _sweep_in_background
    from kb.core import sweep_state

    data = tmp_path / "data"
    data.mkdir()
    vault = tmp_path / "库"
    (vault / ".git").mkdir(parents=True)

    def boom(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(sweep_state, "mark_run", boom)
    busy = Busy()

    _sweep_in_background(vault, data, FakeLLM([]), busy)      # 不许抛

    assert busy.what is None                                   # 锁也得还回来
