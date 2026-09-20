"""起子进程：Windows 上不给它们开控制台窗口。

**服务自己是没有控制台的。** 它是 `runtime.spawn_service` 用 `DETACHED_PROCESS`
拉起来的——那正是为了「关掉终端它也别死」。Windows 上这种没有控制台的进程再
`subprocess.run` 一个控制台程序（`git`、`taskkill`），系统会给**子进程新分配一个
控制台**，于是你眼前闪一下黑框。

一次整理要跑好几次 git（add、commit，有时还有 rev-parse），所以网页上点一次
「记一条」，会**连闪好几个**——每个 git 调用闪一个。

`CREATE_NO_WINDOW` 就是「别开那个窗口」。它不改子进程的行为：照常跑、照常
拿得到 stdout/stderr、照常能写文件。省掉的只是那次控制台分配。

Windows 之外既没有这个常量、也没有这个问题，所以那个分支返回 `0`（子进程的
默认值）。
"""

from __future__ import annotations

import subprocess
import sys

# 传给 `subprocess.run(..., creationflags=NO_CONSOLE)`。
#
# 用条件表达式而不是 `getattr` 兜底：**非 Windows 上 `subprocess.CREATE_NO_WINDOW`
# 根本不存在**，`getattr` 会把「平台判断写错了」这件事一起吞掉。
NO_CONSOLE: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
