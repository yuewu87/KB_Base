import socket
from pathlib import Path

import pytest

from kb.api import runtime
from kb.config import Config


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


def test_ensure_service_times_out(monkeypatch):
    monkeypatch.setattr(runtime, "spawn_service", lambda p: None)
    monkeypatch.setattr(runtime, "is_alive", lambda p, timeout=0.5: False)
    monkeypatch.setattr(runtime, "STARTUP_TIMEOUT", 0.3)
    monkeypatch.setattr(runtime, "POLL_INTERVAL", 0.05)

    with pytest.raises(RuntimeError, match="超时"):
        runtime.ensure_service(_cfg(52000))
