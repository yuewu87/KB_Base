"""子进程别闪控制台窗口（`kb.proc`）。

**这条测的是「有没有把标记传下去」，不是「窗口有没有真的不闪」。**
后者在测试里观察不到——它要一个没有控制台的父进程加一个真实的 Windows 桌面。
所以这里守两件事：常量按平台取值取对、三个起子进程的地方都带上了它。
漏传一处，症状是网页上多点一下就多闪一个黑框，而功能一切正常——
**没有任何东西会报错**，只有人眼看得见，所以更要在代码这一侧守住。
"""

import subprocess
import sys

import pytest

from kb import proc
from kb.api import runtime
from kb.core import organize, vault


def test_no_console_is_off_outside_windows():
    """非 Windows 上必须是 0。

    那个常量在别的平台上**根本不存在**，写成无条件引用会在 Linux 上
    `AttributeError`——而 CI 或别人的机器上正好就是 Linux。
    """
    if sys.platform == "win32":
        assert proc.NO_CONSOLE == subprocess.CREATE_NO_WINDOW
    else:
        assert proc.NO_CONSOLE == 0


def _capture_run(monkeypatch) -> list[dict]:
    """把 `subprocess.run` 换成只记调用的桩。"""
    calls: list[dict] = []

    def fake(*args, **kwargs):
        calls.append({"argv": args[0] if args else [], **kwargs})
        return subprocess.CompletedProcess(args[0] if args else [], 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    return calls


def test_git_run_suppresses_the_console(monkeypatch, tmp_path):
    """整理一次要跑好几次 git——**每跑一次闪一个**，所以这条最要紧。"""
    calls = _capture_run(monkeypatch)
    organize.git_run(tmp_path, "status")
    assert calls[0]["creationflags"] == proc.NO_CONSOLE


def test_project_name_lookup_suppresses_the_console(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch)
    vault.project_name_from_cwd(tmp_path)
    assert calls[0]["creationflags"] == proc.NO_CONSOLE


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill 那条只在 Windows 上走")
def test_taskkill_suppresses_the_console(monkeypatch, tmp_path):
    """网页上点「退出」走的是这条路。"""
    calls = _capture_run(monkeypatch)
    monkeypatch.setattr(runtime, "running_port", lambda: 12345)
    monkeypatch.setattr(runtime, "read_service_info", lambda: {"pid": 4242})

    runtime.stop_service()

    taskkills = [c for c in calls if "taskkill" in str(c["argv"])]
    assert len(taskkills) == 1
    assert taskkills[0]["creationflags"] == proc.NO_CONSOLE
