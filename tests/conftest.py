"""全测试共用的护栏。

**只放「不这么写就有人会误伤」的东西。** 各测试自己的夹具仍然留在各自的
文件里——这里不是夹具的垃圾场。
"""

from __future__ import annotations

import pytest

from kb.api import runtime


@pytest.fixture(autouse=True)
def _never_touch_the_real_service_file(tmp_path, monkeypatch):
    """**任何测试都不许碰真实的 `data/runtime/service.json`。**

    这个文件是「在跑的服务是哪个 pid」的唯一记录，`kb stop` 与 `is_stale()`
    都只认它。测试把它删掉，症状不在测试里，全在开发机上：

    | 现象（都在开发机上，不在测试里） | 原因 |
    |---|---|
    | `kb stop` 报「没在运行」，进程还活着 | 文件没了，pid 就没了；这次 stop 还会再删一次 |
    | `kb status` 说代码是最新的 | `is_stale()` 缺文件时返回 `False`——**假的全绿** |
    | 重启验证过了，跑的还是旧进程 | `ensure_service` 只会把旧端口原样还回来 |

    **2026-09-20 真踩到**：`tests/test_proc.py` 为了验 taskkill 那条
    `creationflags`，调了真的 `runtime.stop_service()`——它结尾那句
    `clear_service_info()` 把**开发机上正跑着的那个服务的记录删了**。
    之后一整轮验证都在打旧代码（`?new=1` 死活不生效，看着像功能写坏了），
    **而测试 571 条全绿**。

    所以用 autouse：**不靠每个人记得给这条打补丁**。第三个人写「顺手调一下
    stop_service」的时候，不会再踩一遍。
    """
    monkeypatch.setattr(runtime, "SERVICE_FILE", tmp_path / "service.json")
