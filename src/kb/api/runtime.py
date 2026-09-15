"""运行时文件与服务的自动拉起（Q39 / Q49）。

服务启动后把端口写进 `runtime/service.json`，CLI 读它去探测：
通就直接投递；不通就后台拉起服务、等它就绪、再投递。

对用户是「按需启动」，对调用方是无感的（Q39）——不用管服务开没开，
也不用开机常驻。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from kb.config import PROJECT_ROOT, Config

RUNTIME_DIR = PROJECT_ROOT / "runtime"
SERVICE_FILE = RUNTIME_DIR / "service.json"

STARTUP_TIMEOUT = 15.0
POLL_INTERVAL = 0.2


def find_free_port() -> int:
    """让操作系统分配一个空闲端口（Q40：自动寻找未占用的端口）。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def write_service_info(port: int, pid: int | None = None) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    SERVICE_FILE.write_text(
        json.dumps(
            {
                "port": port,
                "pid": pid if pid is not None else os.getpid(),
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return SERVICE_FILE


def read_service_info() -> dict | None:
    """读运行时文件。文件不在或内容坏掉都返回 None——调用方只关心「能用吗」。"""
    if not SERVICE_FILE.exists():
        return None
    try:
        return json.loads(SERVICE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def clear_service_info() -> None:
    SERVICE_FILE.unlink(missing_ok=True)


def is_alive(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def running_port() -> int | None:
    """读到端口、且端口真的通，才算在跑。

    只信文件不够——服务崩了之后文件会留在磁盘上，那时应当重新拉起。
    """
    info = read_service_info()
    if not info:
        return None
    port = info.get("port")
    if isinstance(port, int) and is_alive(port):
        return port
    return None


def spawn_service(port: int) -> subprocess.Popen:
    """后台拉起服务，与当前进程解耦——关掉 CLI 后服务继续跑。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PROJECT_ROOT / "src"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    return subprocess.Popen(
        [sys.executable, "-m", "kb.api.http", "--port", str(port)],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=(sys.platform != "win32"),
    )


def ensure_service(cfg: Config) -> int:
    """返回可用服务的端口；没跑就拉起来并等它就绪。"""
    port = running_port()
    if port is not None:
        return port

    port = cfg.port or find_free_port()
    spawn_service(port)

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if is_alive(port):
            return port
        time.sleep(POLL_INTERVAL)

    raise RuntimeError(f"服务启动超时（{STARTUP_TIMEOUT} 秒）。查看 logs/ 排查。")
