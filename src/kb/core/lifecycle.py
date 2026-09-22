"""知识库的生命周期：有没有库、能不能搬、怎么扔干净。

**只碰磁盘与 `.env`，不含 HTTP 与模板**——端点与界面在 `web/router.py`。
分层规矩见 `docs/01_架构.md`：`core/` 不 import `web`/`api`。
"""

from __future__ import annotations

import threading

_BUSY_LABELS = {"organize": "整理", "migrate": "迁移", "remove": "移除"}


class Busy:
    """谁在动 vault。**同一时刻只允许一件事。**

    挡的是「半路迁移」那类事故：一轮整理会多次读库（每条草稿规划时
    `list_domains` + `find_candidates`，落盘时 `write_note`），迁移插在中间
    就把一次整理劈成两半——前一半落旧库、后一半落新库，而最后那个
    `commit_changes` 只在新库里提交，**旧库那半永远不进 git 却躺在磁盘上**，
    看起来一切正常。见 spec 5.3。

    `acquire` **不等待**：拿不到返回 `False`，由调用方回 409。
    排队等只会把一个「正在整理」变成一串排队请求。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._what: str | None = None

    def acquire(self, what: str) -> bool:
        with self._lock:
            if self._what is not None:
                return False
            self._what = what
            return True

    def release(self) -> None:
        with self._lock:
            self._what = None

    @property
    def what(self) -> str | None:
        with self._lock:
            return self._what

    @property
    def label(self) -> str:
        """409 文案里那个动词。写英文会变成「正在migrate，等它跑完再试」。"""
        what = self.what
        return _BUSY_LABELS.get(what, what or "")
