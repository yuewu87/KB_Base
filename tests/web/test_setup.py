"""知识库生命周期的端点。走真 `init_vault` 的库，不是手搓的半骨架。"""

import shutil

import pytest
from fastapi.testclient import TestClient

from kb.api.http import create_app

# **这里必须是 `reload_config` 而不是 `load_config`。**
# `load_config` 走 `load_dotenv(override=False)` + `os.environ`——环境变量
# **赢**，而它自己已经写进 `os.environ` 了。于是同一个进程里第二条用例
# 拿到的还是**第一条**那个临时库的路径（夹具每个用例换一个 `tmp_path`），
# 症状是「删/搬别人的库」：`PermissionError [WinError 5]` 打在另一个用例的
# `.git/objects/...` 上，或者 `/setup/state` 报出上一个库。
# `reload_config` 用 `dotenv_values` 直接解析文件（**文件赢**、不碰
# `os.environ`），正是这些用例要的语义：它们模拟的是**服务重读 `.env`**——
# 夹具刚把 `KB_VAULT_PATH` 写进去，读回来就得是它。
# （`load_config` 的 docstring 自己写着「同一个进程内只应调用一次」。）
from kb.config import Config, reload_config
from kb.core.vault_setup import init_vault
from kb.llm.base import FakeLLM


@pytest.fixture
def env(tmp_path):
    """一份配好模型、**没有 KB_VAULT_PATH** 的 `.env`——就是新用户那份。"""
    path = tmp_path / ".env"
    path.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def app(tmp_path, env):
    """未初始化状态的服务。`data_dir` 用临时目录，别碰真的 data/。"""
    data = tmp_path / "data"
    data.mkdir()
    cfg = Config(
        llm_api_key="k", llm_base_url="http://x", llm_model="m",
        vault_path=None, port=None,
    )
    return create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def initialized_vault(tmp_path, env):
    """一个走真 `init_vault` 的库——有 `.git`、有领域。"""
    path = tmp_path / "库"
    init_vault(path, ["计算机", "健康"])
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n"
        f"KB_VAULT_PATH={path}\n",
        encoding="utf-8",
    )
    return path


# ---------- 状态 ----------

def test_state_says_not_initialized(client):
    got = client.get("/setup/state").json()
    assert got["initialized"] is False
    assert got["vault_path"] == ""
    assert got["domains"] == []
    assert got["busy"] is None


def test_state_says_initialized(initialized_vault, env, tmp_path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    cfg = reload_config(env)
    client = TestClient(
        create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env)
    )
    got = client.get("/setup/state").json()
    assert got["initialized"] is True
    assert got["vault_path"] == str(initialized_vault)
    assert got["domains"] == ["健康", "计算机"]      # `list_domains` 排序


# ---------- 未初始化时挡住投递 ----------

@pytest.mark.parametrize("call", [
    lambda c: c.post("/push", json={"content": "x"}),
    lambda c: c.post("/organize", json={}),
    lambda c: c.get("/inbox"),
    lambda c: c.get("/search", params={"q": "x"}),
])
def test_vault_endpoints_409_before_init(client, call):
    """**端点必须自己拦**：`kb.bat push` 走 CLI、接入指南里的会话层 AI 走
    `/push`，它们都绕过界面，界面置灰拦不住它们。"""
    resp = call(client)
    assert resp.status_code == 409
    assert "初始化知识库" in resp.json()["detail"]


def test_pages_still_open_before_init(client):
    """页面**不能** 409——首屏那张引导卡得有个落脚的地方。"""
    for path in ("/", "/journal", "/settings", "/new"):
        assert client.get(path).status_code == 200, path


# ---------- 初始化 ----------

def test_init_creates_the_vault_and_writes_env(client, env, tmp_path):
    target = tmp_path / "新库"
    resp = client.post("/setup/init", json={
        "vault_path": str(target),
        "domains": ["计算机", "健康"],
        "values": {
            "KB_LLM_MODEL": "m",
            "KB_LLM_BASE_URL": "http://x",
            "KB_LLM_API_KEY": "k",
        },
    })
    assert resp.status_code == 200, resp.text
    assert (target / ".git").is_dir()
    assert (target / "计算机").is_dir()
    assert (target / "健康").is_dir()
    assert not (target / "艺术").exists()
    assert f"KB_VAULT_PATH={target}" in env.read_text(encoding="utf-8")
    assert client.get("/setup/state").json()["initialized"] is True


def test_init_rejects_zero_domains(client, tmp_path):
    """一个领域都没有的话，投进来的每条都会掉进「待归类」。**理由要说清。**"""
    resp = client.post("/setup/init", json={
        "vault_path": str(tmp_path / "库"), "domains": [],
        "values": {"KB_LLM_MODEL": "m", "KB_LLM_BASE_URL": "x",
                   "KB_LLM_API_KEY": "k"},
    })
    assert resp.status_code == 400
    assert "待归类" in resp.json()["detail"]


def test_init_rejects_an_unknown_domain(client, tmp_path):
    """领域名不能随便起——候选清单之外的直接丢掉，丢掉后一个不剩就 400。"""
    resp = client.post("/setup/init", json={
        "vault_path": str(tmp_path / "库"), "domains": ["我自己编的"],
        "values": {"KB_LLM_MODEL": "m", "KB_LLM_BASE_URL": "x",
                   "KB_LLM_API_KEY": "k"},
    })
    assert resp.status_code == 400


def test_init_rejects_a_missing_model_config_before_creating_anything(
        tmp_path):
    """**模型没配齐就一个目录都别建。**

    `settings.validate` 只查「提交上来的键」，缺的键它不管；真正兜底的是
    `apply_settings` 重载之后那句复查（`api/http.py:362`）——可那时候库已经
    建好、`.env` 里的 `KB_VAULT_PATH` 也写下去了，留下「有库、没模型」的
    半截状态。本进程内还能靠「抛在换内存之前」歪打正着救回来，服务一重启
    就只剩「移除知识库」或手改 `.env` 两条路。所以检查必须在建库之前。

    `.env` 得是**连模型都没配**的那种，所以不用 `env` / `client` 夹具——
    它们那份 `.env` 三件套是齐的，走不到这条分支。
    """
    path = tmp_path / ".env"
    path.write_text("# 什么都还没填\n", encoding="utf-8")   # 刚解压出来那份
    data = tmp_path / "data"
    data.mkdir()
    cfg = Config(llm_api_key="", llm_base_url="", llm_model="",
                 vault_path=None, port=None)
    client = TestClient(
        create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=path)
    )

    target = tmp_path / "库"
    resp = client.post("/setup/init", json={
        "vault_path": str(target), "domains": ["计算机"], "values": {},
    })
    assert resp.status_code == 400
    assert "模型名" in resp.json()["detail"]
    assert not target.exists()                              # 一个目录都没建
    assert "KB_VAULT_PATH" not in path.read_text(encoding="utf-8")


def test_init_is_rejected_when_already_initialized(client, initialized_vault,
                                                   env, tmp_path):
    """已初始化时 400，文案指向两条正路——不是「先移除」一句打发。"""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    cfg = reload_config(env)
    c = TestClient(create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env))
    resp = c.post("/setup/init", json={
        "vault_path": str(tmp_path / "另一个"), "domains": ["计算机"],
        "values": {"KB_LLM_MODEL": "m", "KB_LLM_BASE_URL": "x",
                   "KB_LLM_API_KEY": "k"},
    })
    assert resp.status_code == 400
    assert "迁移到别处" in resp.json()["detail"]


# ---------- 迁移 ----------

def test_migrate_moves_and_repoints(initialized_vault, env, tmp_path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    cfg = reload_config(env)
    c = TestClient(create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env))
    (initialized_vault / "计算机" / "笔记.md").write_text("x", encoding="utf-8")

    target = tmp_path / "搬过去"
    resp = c.post("/setup/migrate", json={"target": str(target)})
    assert resp.status_code == 200, resp.text
    assert resp.json()["moved"]["files"] >= 1
    assert (target / "计算机" / "笔记.md").is_file()
    assert not initialized_vault.exists()
    assert f"KB_VAULT_PATH={target}" in env.read_text(encoding="utf-8")
    assert c.get("/setup/state").json()["vault_path"] == str(target)


def test_migrate_into_an_existing_empty_target(initialized_vault, env, tmp_path):
    """目标**存在但是空的**也是合法目标（spec 5.1）——正是界面「检查」会
    建议的那种：`entries: []`，看着正合适。

    `copytree` 默认 `dirs_exist_ok=False`，撞上已存在的目录**一律**抛
    `FileExistsError`（哪怕它是空的），而那是 `OSError` 不是 `LifecycleError`，
    端点那句 `except LifecycleError` 接不住 → 500，重试还是 500。
    """
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    cfg = reload_config(env)
    c = TestClient(create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env))
    (initialized_vault / "计算机" / "笔记.md").write_text("x", encoding="utf-8")

    target = tmp_path / "已经建好的空目录"
    target.mkdir()

    resp = c.post("/setup/migrate", json={"target": str(target)})
    assert resp.status_code == 200, resp.text
    assert (target / "计算机" / "笔记.md").is_file()
    assert not initialized_vault.exists()


def test_migrate_refuses_a_non_empty_target(initialized_vault, env, tmp_path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    cfg = reload_config(env)
    c = TestClient(create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env))

    target = tmp_path / "有东西"
    target.mkdir()
    (target / "占位").write_text("x", encoding="utf-8")

    resp = c.post("/setup/migrate", json={"target": str(target)})
    assert resp.status_code == 400
    assert "非空" in resp.json()["detail"]
    assert initialized_vault.exists()          # 源没动


def test_migrate_refuses_a_target_inside_the_source(initialized_vault, env, tmp_path):
    """`D:\\a` 搬到 `D:\\a\\b` 会把库搬进自己肚子里。"""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    cfg = reload_config(env)
    c = TestClient(create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env))

    resp = c.post("/setup/migrate",
                  json={"target": str(initialized_vault / "子目录")})
    assert resp.status_code == 400
    assert initialized_vault.exists()


def test_migrate_409_while_busy(initialized_vault, env, tmp_path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    cfg = reload_config(env)
    app = create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env)
    c = TestClient(app)

    assert app.state.busy.acquire("organize") is True
    try:
        resp = c.post("/setup/migrate", json={"target": str(tmp_path / "新")})
        assert resp.status_code == 409
        assert "整理" in resp.json()["detail"]
    finally:
        app.state.busy.release()


# ---------- 移除 ----------

def test_remove_deletes_everything_and_unbinds(initialized_vault, env, tmp_path):
    data = tmp_path / "data"
    (data / "chats").mkdir(parents=True)
    (data / "chats" / "c.json").write_text("{}", encoding="utf-8")
    cfg = reload_config(env)
    c = TestClient(create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env))

    resp = c.post("/setup/remove")
    assert resp.status_code == 200, resp.text
    assert not initialized_vault.exists()
    assert not (data / "chats").exists()

    got = c.get("/setup/state").json()
    assert got["initialized"] is False
    assert got["vault_path"] == ""


def test_remove_keeps_service_json(initialized_vault, env, tmp_path):
    """**端点这一层也不许顺手把 `data/` 整个端掉。**

    删的只有 `chats` / `logs` / `state.json` 三处。`data/runtime/service.json`
    是 `kb stop` 唯一的线索，删了就是「停不掉的孤儿进程」——那个 bug 的症状是
    **测试全绿、开发机上服务失控**（`04_踩坑与经验.md` 第 21 条）。

    同样造一个无关文件一起验：`remove_vault` 根本不碰 `data/runtime`，
    只断言 `service.json` 还在的话，删不删都绿，等于没测。
    """
    data = tmp_path / "data"
    (data / "runtime").mkdir(parents=True)
    (data / "runtime" / "service.json").write_text("{}", encoding="utf-8")
    (data / "unrelated.txt").write_text("x", encoding="utf-8")
    cfg = reload_config(env)
    c = TestClient(create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env))

    # **不看响应的话这条是弱断言**：端点整个坏掉（500）也照样绿，
    # 因为「没删掉」和「压根没跑」在文件系统上长得一模一样。
    resp = c.post("/setup/remove")
    assert resp.status_code == 200, resp.text

    assert (data / "runtime" / "service.json").is_file()
    assert (data / "unrelated.txt").is_file()


def test_remove_then_init_again_keeps_the_model_config(initialized_vault, env,
                                                       tmp_path):
    """**移除后能重新初始化，模型配置保留**——那是给模型的钥匙，跟库没关系。"""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    cfg = reload_config(env)
    c = TestClient(create_app(cfg, llm=FakeLLM([]), data_dir=data, env_file=env))

    c.post("/setup/remove")
    text = env.read_text(encoding="utf-8")
    assert "KB_LLM_API_KEY=k" in text          # 钥匙还在
    assert "KB_VAULT_PATH=" in text            # 只是解绑了

    again = tmp_path / "再来一个"
    resp = c.post("/setup/init", json={
        "vault_path": str(again), "domains": ["计算机"],
        "values": {},                          # 不重填模型三件套
    })
    assert resp.status_code == 200, resp.text
    assert (again / ".git").is_dir()
    assert c.get("/setup/state").json()["initialized"] is True


def test_remove_refuses_a_path_that_is_not_a_vault(env, tmp_path):
    """**填错一个字母就删掉一个不相干的目录**——端点这一层也得拦住。

    `/setup/state` 和 `/setup/init` 的闸都判 `.git`（用 `lifecycle.vault_ready`），
    只有删除这条原来是「拿到路径就删」。界面上的确认框拦不住 `curl`，
    也拦不住接入指南里的会话层 AI，所以这里必须回 400。

    **断言要落到文件上**，并且要验 `.env` 没被解绑——闸得在**真动手之前**，
    不是删完了才回 400。
    """
    data = tmp_path / "data"
    data.mkdir()
    plain = tmp_path / "我的文档"
    plain.mkdir()
    (plain / "重要.txt").write_text("别删我", encoding="utf-8")
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n"
        f"KB_VAULT_PATH={plain}\n",
        encoding="utf-8",
    )
    c = TestClient(create_app(reload_config(env), llm=FakeLLM([]),
                              data_dir=data, env_file=env))

    resp = c.post("/setup/remove")

    assert resp.status_code == 400, resp.text
    assert "不是一个知识库" in resp.json()["detail"]
    assert plain.is_dir()                             # 目录还在
    assert (plain / "重要.txt").is_file()              # 里面那个文件也在
    assert f"KB_VAULT_PATH={plain}" in env.read_text(encoding="utf-8")


def test_remove_still_reports_a_missing_vault_dir(env, tmp_path):
    """反向：**目录本来就不在了是合法的**，不能因为上面那道闸把这条也拦成 400。

    `vault_ready` 对不存在的路径同样返回 `False`，所以闸必须自己判
    `exists()`——不然「库被人手工删掉了，回来点一下移除清干净」这件事
    就永远做不成，用户只剩手改 `.env` 一条路。
    """
    data = tmp_path / "data"
    data.mkdir()
    gone = tmp_path / "早就没了"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n"
        f"KB_VAULT_PATH={gone}\n",
        encoding="utf-8",
    )
    c = TestClient(create_app(reload_config(env), llm=FakeLLM([]),
                              data_dir=data, env_file=env))

    resp = c.post("/setup/remove")

    assert resp.status_code == 200, resp.text
    assert resp.json()["vault_removed"] is True
    assert any("本来就不在了" in n for n in resp.json()["notes"])
    assert "KB_VAULT_PATH=" in env.read_text(encoding="utf-8")   # 解绑了


def test_migrate_refuses_when_the_current_vault_is_not_a_vault(env, tmp_path):
    """`_check_migration` 原先只判 `source.exists()`，不判它是不是库。

    路径填歪了、那儿是个普通目录时，搬家的结果是「把一个不相干的目录当成
    库搬走」。挡在拷贝之前，一个字节都不动。
    """
    data = tmp_path / "data"
    data.mkdir()
    plain = tmp_path / "我的文档"
    plain.mkdir()
    (plain / "重要.txt").write_text("别搬我", encoding="utf-8")
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n"
        f"KB_VAULT_PATH={plain}\n",
        encoding="utf-8",
    )
    c = TestClient(create_app(reload_config(env), llm=FakeLLM([]),
                              data_dir=data, env_file=env))

    target = tmp_path / "新"
    resp = c.post("/setup/migrate", json={"target": str(target)})

    assert resp.status_code == 400, resp.text
    assert "不是一个知识库" in resp.json()["detail"]
    assert not target.exists()
    assert (plain / "重要.txt").is_file()


# ---------- 路径体检 ----------

def test_check_reports_a_missing_path(client, tmp_path):
    got = client.get("/setup/check",
                     params={"path": str(tmp_path / "还没有")}).json()
    assert got["exists"] is False
    assert got["looks_like_vault"] is False


def test_check_reports_an_existing_vault(client, initialized_vault):
    got = client.get("/setup/check",
                     params={"path": str(initialized_vault)}).json()
    assert got["exists"] is True
    assert got["looks_like_vault"] is True
    assert got["writable"] is True


def test_check_with_an_empty_path_is_not_an_error(client):
    """空输入不该 422——用户刚清空输入框就会打一次。"""
    assert client.get("/setup/check", params={"path": ""}).status_code == 200


# ---------- 修 ①：`.env` 填歪了也要有下文，不许 500 ----------

def _client_for(env, tmp_path):
    """按 `.env` 现读造一个客户端。

    这几条验的是**服务重读 `.env`** 之后的行为，所以不能用 `app` 夹具里那份
    固定的 `cfg`——它写死了 `vault_path=None`。
    """
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return TestClient(
        create_app(reload_config(env), llm=FakeLLM([]), data_dir=data,
                   env_file=env)
    )


def test_state_survives_a_vault_path_that_points_at_a_file(env, tmp_path):
    """`KB_VAULT_PATH` 指到一个**文件**（手滑打错一个字符）。

    `/setup/state` 是每个页面首屏、还有 busy 轮询都要打的端点。`list_domains`
    只判了 `exists()`，紧跟的 `iterdir()` 当场抛 `NotADirectoryError` → 500，
    于是整块界面死掉，而唯一的出路是再去手改 `.env`——正是这次改动要消灭的
    那种状态。
    """
    notes = tmp_path / "notes.md"
    notes.write_text("x", encoding="utf-8")
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n"
        f"KB_VAULT_PATH={notes}\n",
        encoding="utf-8",
    )

    resp = _client_for(env, tmp_path).get("/setup/state")

    assert resp.status_code == 200
    got = resp.json()
    assert got["initialized"] is False            # 一个文件不是库
    assert got["domains"] == []
    assert got["counts"]["notes"] == 0


def test_migrate_refuses_a_relative_vault_path(env, tmp_path, monkeypatch):
    """**`.env` 手填 `KB_VAULT_PATH=.` 时，一句 `curl -X POST /setup/migrate`
    就能把整个 KN_Base 仓库删掉。**

    端点拿到的「源」是 `vault()` 给的，也就是 `.env` 里那个字符串——
    **从不走 `settings.validate`**，所以闸只能设在 core 里。而服务进程的 cwd
    是 `PROJECT_ROOT`（`spawn_service` 传的），那儿正好有 `.git`，于是
    `exists()` 与 `vault_ready()` 两道判据全过。
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "重要.txt").write_text("别搬我", encoding="utf-8")
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n"
        "KB_VAULT_PATH=.\n",
        encoding="utf-8",
    )
    # 目标放在**源外面**：闸要是漏了（RED 那一轮），`copytree` 会在源里面
    # 造一个目标目录，源又正在被拷——那就递归了。
    target = tmp_path.parent / "新库"
    shutil.rmtree(target, ignore_errors=True)      # 上一轮 RED 跑剩的

    resp = _client_for(env, tmp_path).post(
        "/setup/migrate", json={"target": str(target)}
    )

    assert resp.status_code == 400
    assert "相对路径" in resp.json()["detail"]
    assert (tmp_path / "重要.txt").is_file()
    assert (tmp_path / ".git").is_dir()


def test_remove_reports_when_the_env_cannot_be_rewritten(
        initialized_vault, env, tmp_path, monkeypatch):
    """库删干净了，`unbind_vault()` 写 `.env` 却失败（编辑器或杀软占着文件、
    文件只读）——它原先裸在 `try` 外面，用户拿到 500，而库已经没了、`.env`
    还指着那个不存在的路径，连「去手改 `.env`」这句话都没有。

    对照 `setup_migrate`：它专门兜住了同样的失败，给的是「库已经搬到 X 了，
    但写 `.env` 没过校验」这种能照着做的 400。
    """
    def refuse(*a, **k):
        raise PermissionError(13, "拒绝访问")

    monkeypatch.setattr("kb.core.settings.write_env", refuse)

    resp = _client_for(env, tmp_path).post("/setup/remove")

    assert resp.status_code == 400
    assert "手工" in resp.json()["detail"]
    assert str(initialized_vault) in resp.json()["detail"]
