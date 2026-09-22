"""知识库的生命周期：有没有库、能不能搬、怎么扔干净。

**只碰磁盘与 `.env`，不含 HTTP 与模板**——端点与界面在 `web/router.py`。
分层规矩见 `docs/01_架构.md`：`core/` 不 import `web`/`api`。
"""

from __future__ import annotations

import os
import shutil
import stat
import threading
from datetime import datetime
from pathlib import Path

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


class LifecycleError(RuntimeError):
    """搬家搬不成。消息直接给人看。"""


# ------------------------------------------------------------ 删树的公用件

def _rmtree(path: Path, *, ignore_errors: bool = False) -> None:
    """删一棵树，**删不掉的先摘只读位再删一次**。

    **git 的松散对象是只读的（实测 `0o100444`）**，而 Windows 上
    `shutil.rmtree` 碰到只读文件直接抛 `PermissionError [WinError 5] 拒绝访问`
    ——手工 `rm -rf .git` 在那个目录上同样删不掉。不管这一步，「移除知识库」
    与「搬家」在**真库**上必然失败（假 `.git` 目录的用例是绿的，所以这个坑
    只有拿真 git 跑才看得见），而且失败的样子像个权限问题，排查方向全错。
    实测：`os.chmod(p, stat.S_IWRITE)` 之后同一个 `rmtree` 就过了。

    **只用在库那棵树（含 `.git`）上**，`data/chats` / `data/logs` 不用：
    那里没有 git 对象，而真正会挡住的「文件正被服务打开」是**别的进程握着
    句柄**，摘只读位救不了——那种失败要的是如实汇报（见 `remove_vault`），
    不是换个删法再试。

    `ignore_errors=True` 时**照样先试摘只读位**再吞掉最终失败
    （`shutil.rmtree` 自带的 `ignore_errors` 是直接不调 `onerror` 的，
    那样回滚会留下一堆只读残留）。
    """
    def _on_error(func, target, _exc_info):
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        func(target)

    try:
        shutil.rmtree(path, onerror=_on_error)
    except OSError:
        if not ignore_errors:
            raise


# ------------------------------------------------------------ 体检

def _writable(path: Path) -> bool:
    """能不能在这儿建东西。**父目录存在就查父目录**——用户填的多半是
    一个还不存在的路径，而那个路径的父目录才是真正要写进去的地方。"""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def check_path(path: Path) -> dict:
    """顺手看一眼这个路径。**只回事实，不做判断。**

    这是「检查」按钮的全部实现——失败也不拦着初始化（`init_vault` 幂等，
    在一个有东西的目录上跑不会毁掉什么）。所以这里没有「行/不行」，
    只有「存在吗、能写吗、里面是不是已经有个库、有几个条目」。
    """
    entries: list[str] = []
    if path.is_dir():
        try:
            entries = sorted(p.name for p in path.iterdir())[:50]
        except OSError:
            entries = []
    return {
        "exists": path.exists(),
        "writable": _writable(path),
        "looks_like_vault": (path / ".git").exists(),
        "entries": entries,
    }


# ------------------------------------------------------------ 搬家

# **`data/` 不搬，一个字都不用动**（spec 5.4）。已核实过：`data/logs/flow/*.jsonl`
# 里记的路径**全是 vault 相对路径**（0 条绝对路径），`data/state.json` 只有巡检状态。
# 所以下面 `migrate_vault` 只碰 vault 目录，**别顺手把 `data/` 也拷过去**——
# 那是已经查过、确认不需要的，不是漏了。


def _tree_size(root: Path) -> tuple[int, int]:
    """数一棵树里的文件数与总字节数。

    **只比这两个，不逐文件哈希。** 这库按几千条设计（Q95）：727K 时哈希是
    零成本，但真到几千条、带附件时逐文件哈希会明显变慢；而**拷贝被截断几乎
    必然改变文件数和字节数**。这个取舍是有意的，别以为是漏了。
    """
    files = 0
    size = 0
    for p in root.rglob("*"):
        if p.is_file():
            files += 1
            size += p.stat().st_size
    return files, size


def migrate_vault(source: Path, target: Path) -> dict:
    """把整棵库从 `source` 搬到 `target`。成功返回 `{files, bytes}`。

    **失败时回滚目标，源库一根汗毛不动。** 这条是铁律：数据有两份的时候，
    永远让**旧的那份先活着**，新的可以再造。
    """
    files, size = _tree_size(source)

    shutil.copytree(source, target)
    try:
        got_files, got_size = _tree_size(target)
        if (got_files, got_size) != (files, size):
            raise LifecycleError(
                f"拷完对不上：拷了 {got_files} 个文件 / {got_size} 字节，"
                f"源有 {files} 个 / {size} 字节。目标目录已清掉，源库没动。"
            )
    except LifecycleError:
        # `ignore_errors=True`：这一步是**回滚**，删不干净也不能盖掉上面那个
        # `LifecycleError`——用户要看见的是「拷完对不上」，不是「回滚没删掉」。
        _rmtree(target, ignore_errors=True)
        raise

    _rmtree(source)
    return {"files": files, "bytes": size}


# ------------------------------------------------------------ 移除

def remove_vault(vault_root: Path | None, data_dir: Path) -> dict:
    """把库和它在服务侧留下的痕迹一起删掉。

    返回 `{removed, failed, notes, vault_removed}`——**逐项汇报**，因为这里
    做不到「全部成功」：Windows 上正被服务打开的文件删不掉（今天的日志就在
    其中），所以「一点痕迹都不留」物理上不成立。界面上得说实话，否则用户
    下次在 `data/logs/` 里看见文件会以为移除没生效。

    **`data/runtime/service.json` 绝不能删**：那份文件是 `kb stop` 唯一的线索，
    删了就是「停不掉的孤儿进程」——而那个 bug 的症状是测试全绿、开发机上服务
    失控（`04_踩坑与经验.md` 第 21 条）。所以下面的删除清单里**没有它**，
    这是刻意的，不是漏了。

    **`data/cache/` 也不在清单里，理由跟上面那条不一样**：里面装的是 pytest
    与 ruff 的缓存（`pyproject.toml` 把 `cache_dir` 指过去的），**跟这个 vault
    一点关系都没有**，删了只是让下次跑测试慢一点。判据是「这份文件记的**是不是
    这个库**」，不是「它在不在 `data/` 底下」——照后者去加，`data/` 下迟早会
    长出一堆不相干的东西被误伤。

    `vault_removed` 是给调用方的信号：**库还在的时候不要解绑 `.env`**，
    否则界面上显示「还没有知识库」而笔记还躺在原地。
    """
    removed: list[str] = []
    failed: list[str] = []
    notes: list[str] = []
    vault_removed = True

    if vault_root is None:
        pass
    elif not vault_root.exists():
        notes.append(f"笔记目录本来就不在了：{vault_root}")
    else:
        # **先改名再删。** 改名在同盘内是原子的、瞬间完成，所以「删了一半」
        # 那个窗口从一开始就不存在——要么库还在原地，要么它整个变成了一个
        # 待删的目录。第三步改回去保证失败可逆。
        graveyard = vault_root.with_name(
            f".{vault_root.name}.deleting-{datetime.now():%Y%m%d%H%M%S}"
        )
        try:
            os.rename(vault_root, graveyard)
        except OSError as exc:
            vault_removed = False
            failed.append(
                f"{vault_root}（{exc.strerror or exc}）——"
                "先关掉 Obsidian、停在库里的资源管理器、正在扫这个目录的杀软，再试"
            )
        else:
            try:
                _rmtree(graveyard)
                removed.append(str(vault_root))
            except OSError as exc:
                os.rename(graveyard, vault_root)      # 改回去，失败可逆
                vault_removed = False
                failed.append(f"{vault_root}（{exc.strerror or exc}）")

    for name in ("chats", "logs"):
        item = data_dir / name
        if not item.exists():
            continue
        try:
            shutil.rmtree(item)
            removed.append(str(item))
        except OSError:
            # 今天的日志文件正被服务自己打开着。**不抛错、不中断**，
            # 但**照实记下来**——`failed` 的语义是「这份没删掉」，不是
            # 「出 bug 了」，两者混起来用户会在 `data/logs/` 里看见文件
            # 却什么都没被告知。`notes` 里那句是给人看的原因。
            notes.append(f"{item} 里有文件正被服务打开，删不掉")
            failed.append(str(item))

    state = data_dir / "state.json"
    if state.is_file():
        try:
            state.unlink()
            removed.append(str(state))
        except OSError as exc:
            failed.append(f"{state}（{exc.strerror or exc}）")

    return {
        "removed": removed,
        "failed": failed,
        "notes": notes,
        "vault_removed": vault_removed,
    }
