import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from kb.api import runtime
from kb.config import Config


def _ok():
    """`taskkill` 成功了的样子（`_kill_pid` 看的是返回码）。"""
    return SimpleNamespace(returncode=0)


def _failed():
    """对着一个已经没了的 pid——`taskkill` 会失败。"""
    return SimpleNamespace(returncode=1)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path: Path):
    """把运行时目录指到临时目录，避免污染真实工程。"""
    monkeypatch.setattr(runtime, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(runtime, "SERVICE_FILE", tmp_path / "runtime" / "service.json")


def _cfg(port: int | None = None) -> Config:
    return Config("k", "u", "m", Path("."), port)


def test_find_free_port_returns_bindable_port():
    port = runtime.find_free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))      # 不抛异常即可用
    assert 1024 < port < 65536


def test_find_free_port_varies():
    """连开两次应该是不同端口——否则「自动寻找」名不副实。"""
    assert runtime.find_free_port() != runtime.find_free_port()


# ---------- 运行时文件 ----------

def test_service_info_roundtrip():
    runtime.write_service_info(51723)
    info = runtime.read_service_info()
    assert info["port"] == 51723
    assert "pid" in info and "started" in info


def test_read_service_info_absent_returns_none():
    assert runtime.read_service_info() is None


def test_read_service_info_corrupt_returns_none():
    runtime.SERVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    runtime.SERVICE_FILE.write_text("不是 JSON", encoding="utf-8")
    assert runtime.read_service_info() is None


def test_clear_service_info_removes_file():
    runtime.write_service_info(1234)
    runtime.clear_service_info()
    assert runtime.read_service_info() is None


def test_clear_service_info_is_idempotent():
    runtime.clear_service_info()          # 不存在也不该抛


# ---------- 存活探测 ----------

def test_is_alive_false_for_unused_port():
    assert runtime.is_alive(runtime.find_free_port()) is False


def test_is_alive_true_for_listening_socket():
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        assert runtime.is_alive(srv.getsockname()[1]) is True


def test_running_port_none_without_file():
    assert runtime.running_port() is None


def test_running_port_ignores_dead_service():
    """文件在但端口不通（服务崩了）→ 视为没跑，触发重新拉起。"""
    runtime.write_service_info(runtime.find_free_port())
    assert runtime.running_port() is None


# ---------- 按需拉起 ----------

def test_ensure_service_reuses_running_one(monkeypatch):
    port = runtime.find_free_port()
    runtime.write_service_info(port)
    monkeypatch.setattr(runtime, "is_alive", lambda p, timeout=0.5: True)

    spawned = []
    monkeypatch.setattr(runtime, "spawn_service", lambda p: spawned.append(p))

    assert runtime.ensure_service(_cfg()) == port
    assert spawned == []                  # 已在跑，不该再拉起


def test_ensure_service_spawns_when_absent(monkeypatch):
    started = {"alive": False}

    def _spawn(port):
        started["alive"] = True
        started["port"] = port

    monkeypatch.setattr(runtime, "spawn_service", _spawn)
    monkeypatch.setattr(runtime, "is_alive", lambda p, timeout=0.5: started["alive"])

    assert runtime.ensure_service(_cfg(51999)) == 51999
    assert started["port"] == 51999


def test_ensure_service_honours_configured_port(monkeypatch):
    """配了 KB_PORT 就用它，不要另找一个。"""
    monkeypatch.setattr(runtime, "spawn_service", lambda p: None)
    monkeypatch.setattr(runtime, "is_alive", lambda p, timeout=0.5: True)

    assert runtime.ensure_service(_cfg(52123)) == 52123


# ---------- 服务跑的是不是旧代码 ----------

def test_service_info_records_start_timestamp():
    runtime.write_service_info(1234)
    info = runtime.read_service_info()
    assert isinstance(info["started_at"], float)


def test_is_stale_false_without_service():
    assert runtime.is_stale() is False


def test_is_stale_false_when_code_older(monkeypatch):
    runtime.write_service_info(1234)
    monkeypatch.setattr(runtime, "source_mtime", lambda: 0.0)
    assert runtime.is_stale() is False


def test_is_stale_true_when_code_newer(monkeypatch):
    """改了 src/kb 下的代码后，在跑的服务仍执行旧逻辑——必须能看出来。"""
    runtime.write_service_info(1234)
    monkeypatch.setattr(runtime, "source_mtime", lambda: 9e12)
    assert runtime.is_stale() is True


def test_is_stale_false_for_old_format_file(monkeypatch):
    """兼容没有 started_at 的旧 service.json——不该因此报错或误报。"""
    runtime.SERVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    runtime.SERVICE_FILE.write_text('{"port": 1234}', encoding="utf-8")
    monkeypatch.setattr(runtime, "source_mtime", lambda: 9e12)
    assert runtime.is_stale() is False


def test_source_mtime_sees_repo_files():
    """真的去扫了源码目录，而不是永远返回 0。"""
    assert runtime.source_mtime() > 0


# ---------- 停服务 ----------

def test_stop_service_when_not_running(monkeypatch):
    assert runtime.stop_service() is False


def test_stop_service_kills_and_clears(monkeypatch):
    runtime.write_service_info(1234, pid=999999)

    killed = []
    monkeypatch.setattr(
        runtime.subprocess, "run",
        lambda args, **kw: killed.append(args) or _ok(),
    )

    assert runtime.stop_service() is True
    assert killed, "没有真的去停进程"
    assert runtime.read_service_info() is None


def test_stop_service_still_kills_when_the_port_does_not_answer(monkeypatch):
    """**端口探不通也要按 pid 停——那正是「孤儿服务」的形状。**

    `running_port()` 要「文件里有端口 **且** 端口真通」。探不通有两种情况：
    服务真没在跑，或者它只是这一瞬间没应答（0.5 秒超时、正在启动、机器卡了
    一下）。原先这里一律 `clear_service_info()`——**把仅有的 pid 线索一起
    删掉**，而进程还活着：此后 `kb stop` 永远报「本来就没在运行」，
    `ensure_service` 又照样把旧端口还给你，那个进程再也停不掉。

    实测撞上过（`04_踩坑与经验.md` 第 21 条）：一个旧进程占着端口、我在那
    之后改了 `router.py`，于是一整轮验证都在打旧代码——**看着像功能坏了**。
    """
    runtime.write_service_info(1234, pid=999999)
    monkeypatch.setattr(runtime, "running_port", lambda: None)   # 探不通

    killed = []
    monkeypatch.setattr(
        runtime.subprocess, "run",
        lambda args, **kw: killed.append(args) or _ok(),
    )

    assert runtime.stop_service() is True
    assert killed, "端口不通就放弃了——那正是孤儿服务的成因"
    assert runtime.read_service_info() is None


def test_stop_service_reports_failure_when_the_pid_is_gone(monkeypatch):
    """陈记录（进程早没了）如实说「没停成」，别报「服务已停止」。

    分辨靠 `taskkill` 的返回码——对着一个不存在的 pid 它是失败的。
    """
    runtime.write_service_info(1234, pid=999999)
    monkeypatch.setattr(
        runtime.subprocess, "run", lambda args, **kw: _failed()
    )

    assert runtime.stop_service() is False
    assert runtime.read_service_info() is None      # 陈记录照样清掉


def test_ensure_service_times_out(monkeypatch):
    monkeypatch.setattr(runtime, "spawn_service", lambda p: None)
    monkeypatch.setattr(runtime, "is_alive", lambda p, timeout=0.5: False)
    monkeypatch.setattr(runtime, "STARTUP_TIMEOUT", 0.3)
    monkeypatch.setattr(runtime, "POLL_INTERVAL", 0.05)

    with pytest.raises(RuntimeError, match="超时"):
        runtime.ensure_service(_cfg(52000))
