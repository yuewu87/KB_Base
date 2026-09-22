"""运行时文件与服务的自动拉起（Q39 / Q49）。

服务启动后把端口写进 `runtime/service.json`，CLI 读它去探测：
通就直接投递；不通就后台拉起服务、等它就绪、再投递。

对用户是「按需启动」，对调用方是无感的（Q39）——不用管服务开没开，
也不用开机常驻。
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from kb import proc
from kb.config import PROJECT_ROOT, Config

RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
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
    now = time.time()
    SERVICE_FILE.write_text(
        json.dumps(
            {
                "port": port,
                "pid": pid if pid is not None else os.getpid(),
                "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                "started_at": now,
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


def source_mtime() -> float:
    """`src/kb/` 与 `templates/` 里最新的文件修改时间。"""
    newest = 0.0
    for folder in (PROJECT_ROOT / "src" / "kb", PROJECT_ROOT / "templates"):
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md"}:
                newest = max(newest, path.stat().st_mtime)
    return newest


def is_stale() -> bool:
    """在跑的服务是否比磁盘上的代码旧。

    Python 不会热重载：改了 `src/kb/` 下的代码后，已经在跑的服务仍然执行旧逻辑，
    而 CLI 探测端口只看到「活着」，于是继续用它——**改动看起来没生效**。
    （`templates/*.md` 是每次整理现读的，不受影响。）

    服务启动之后代码被改过就返回 True。
    """
    info = read_service_info()
    if not info:
        return False
    started = info.get("started_at")
    if not isinstance(started, int | float):
        return False
    return source_mtime() > started


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


def _kill_pid(pid: int) -> bool:
    """按 pid 停进程。返回是否**真的**停掉了。

    Windows 上 `taskkill` 对着一个已经没了的 pid 会失败（返回码非 0），
    正好用来分辨「真的停了一个」和「那条记录是陈的」。
    """
    if sys.platform == "win32":
        # 不用 text=True——taskkill 输出是 GBK，解码会在读取线程里炸
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            creationflags=proc.NO_CONSOLE,
        )
        return result.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def stop_service() -> bool:
    """停掉在跑的服务，返回是否真的停了一个。

    改了 `src/kb/` 下的代码之后要调它——否则旧进程会一直占着端口，
    后续调用继续用旧逻辑（见 `is_stale`）。

    **判据不看端口通不通，看文件里记没记 pid。** `running_port()` 要「文件里
    有端口 **且** 端口真通」两条都成立，而探不通有两种情况：服务真没在跑，
    或者它只是这一瞬间没应答（0.5 秒的连接超时、正在启动、机器卡了一下）。
    原先这里把两者当成同一件事，动作是 `clear_service_info()`——**把仅有的
    pid 线索一起删掉**，而进程还活着。之后 `kb stop` 永远报「本来就没在运行」
    （还顺手再删一次），`ensure_service` 又照样把旧端口还给你：那个进程
    **再也停不掉**，而它的症状是「测试全绿、开发机上的服务失控」
    （`04_踩坑与经验.md` 第 21 条）。

    ⚠️ **代价说清楚**：按 pid 停意味着「文件里那个 pid 此刻属于谁」这件事
    我们不再交叉验证。pid 被系统回收、派给了一个不相干的进程时，这条会把
    它误伤——窗口很窄（原进程早退出 + pid 被复用 + 文件还留着），而换来的是
    「孤儿服务不再无解」。`kb stop` 本来就是用户明确说「停掉它」。

    文件里连 pid 都没有（空的或坏的）时才只清文件——那种情况就算端口通也
    停不了，因为不知道该停谁。
    """
    info = read_service_info() or {}
    pid = info.get("pid")
    if not isinstance(pid, int):
        clear_service_info()
        return False

    stopped = _kill_pid(pid)
    clear_service_info()
    return stopped


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
