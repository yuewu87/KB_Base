"""库的生命周期：状态推断、路径体检、搬家、移除。"""

import os

import pytest

from kb.core import lifecycle
from kb.core.lifecycle import (
    Busy,
    LifecycleError,
    check_path,
    migrate_vault,
    remove_vault,
    vault_ready,
)


def test_acquire_succeeds_when_idle():
    busy = Busy()
    assert busy.what is None
    assert busy.acquire("organize") is True
    assert busy.what == "organize"


def test_acquire_fails_while_held():
    """**不等待，直接返回 False。** 排队等只会把一个「正在整理」变成
    一串排队请求，而调用方要的是「现在不行，等会儿再来」。"""
    busy = Busy()
    busy.acquire("organize")
    assert busy.acquire("migrate") is False
    assert busy.what == "organize"       # 先来的那个不被顶掉


def test_release_frees_it():
    busy = Busy()
    busy.acquire("organize")
    busy.release()
    assert busy.what is None
    assert busy.acquire("migrate") is True


def test_label_is_chinese():
    """409 的文案要给人看，不能写 `正在migrate`。"""
    busy = Busy()
    busy.acquire("migrate")
    assert busy.label == "迁移"


def _make_vault(root):
    """一个有三篇笔记、两个领域的真库。"""
    (root / ".git").mkdir(parents=True)
    (root / "计算机").mkdir()
    (root / "艺术").mkdir()
    for i in range(3):
        (root / "计算机" / f"笔记{i}.md").write_text("x" * 100, encoding="utf-8")
    return root


# ---------- vault_ready ----------

def test_vault_ready_is_false_when_no_path_is_configured():
    """没配库 = 没库。`None` 进来不能炸。"""
    assert vault_ready(None) is False


def test_vault_ready_is_false_for_a_dir_without_dot_git(tmp_path):
    """**目录存在不算数。**

    路径配了、目录也在，但那儿没库——这是最容易骗过界面的一种状态：界面
    说「已初始化」，用户点进去发现 `list_notes` 空空的。判据认 `.git`，
    理由见 `settings._vault_path_problem`。
    """
    plain = tmp_path / "普通目录"
    plain.mkdir()
    assert vault_ready(plain) is False


def test_vault_ready_is_true_when_dot_git_exists(tmp_path):
    vault = _make_vault(tmp_path / "库")
    assert vault_ready(vault) is True


# ---------- check_path ----------

def test_check_path_on_a_missing_dir(tmp_path):
    got = check_path(tmp_path / "还没有")
    assert got["exists"] is False
    assert got["looks_like_vault"] is False
    assert got["entries"] == []


def test_check_path_on_an_initialized_vault(tmp_path):
    vault = _make_vault(tmp_path / "库")
    got = check_path(vault)
    assert got["exists"] is True
    assert got["looks_like_vault"] is True
    assert got["writable"] is True
    # `check_path` 用的是 `sorted()`，按 **Unicode 码点**排，不是按拼音：
    # `艺` 是 U+827A、`计` 是 U+8BA1，所以 `艺` 在前。**看着别扭别改回去。**
    assert got["entries"] == [".git", "艺术", "计算机"]


def test_check_path_on_a_plain_dir(tmp_path):
    plain = tmp_path / "普通目录"
    plain.mkdir()
    got = check_path(plain)
    assert got["exists"] is True
    assert got["looks_like_vault"] is False


# ---------- migrate_vault ----------

def test_migrate_moves_everything_and_removes_the_source(tmp_path):
    source = _make_vault(tmp_path / "旧")
    target = tmp_path / "新"

    moved = migrate_vault(source, target)

    assert moved["files"] == 3          # `_tree_size` 只数 `is_file()`；`.git`
    assert moved["bytes"] == 300        # 与两个领域目录都是空目录，不算文件
    assert not source.exists()
    assert (target / "计算机" / "笔记0.md").is_file()


def test_migrate_rolls_back_the_target_when_verification_fails(tmp_path, monkeypatch):
    """**源库一根汗毛不动。** 数据有两份的时候，永远让旧的那份先活着——
    新的可以再造。"""
    source = _make_vault(tmp_path / "旧")
    target = tmp_path / "新"

    real = lifecycle._tree_size

    def lying(path):
        # 第一次量源（真话），第二次量目标（谎报少一个文件）
        if path == target:
            return (1, 1)
        return real(path)

    monkeypatch.setattr(lifecycle, "_tree_size", lying)

    with pytest.raises(LifecycleError, match="对不上"):
        migrate_vault(source, target)

    assert not target.exists()                       # 目标回滚了
    assert (source / "计算机" / "笔记0.md").is_file()  # 源完好


def test_migrate_rolls_back_the_target_when_the_copy_fails(tmp_path, monkeypatch):
    """**拷贝自己失败（磁盘满、权限）也要回滚目标，源不动。**

    `copytree` 抛的是 `OSError`，不是 `LifecycleError`。只接住后者的话，
    错误会冒到 `router.py` 那句 `except LifecycleError` 外面变成 500，而
    **目标留着半截**——用户按提示重试，又撞上「目标非空」400，走进死胡同。
    spec 9.3「拷贝中途失败 → 回滚目标目录，源不动，报错」说的就是这条。
    """
    source = _make_vault(tmp_path / "旧")
    target = tmp_path / "新"

    def boom(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(lifecycle.shutil, "copytree", boom)

    with pytest.raises(LifecycleError, match="No space left"):
        migrate_vault(source, target)

    assert not target.exists()                       # 目标回滚了
    assert (source / "计算机" / "笔记0.md").is_file()  # 源完好


def test_migrate_refuses_a_non_empty_target_before_copying(tmp_path):
    """**非空目标必须被挡在拷贝之前**——一旦进了回滚分支，目标里原有的
    东西会被一起删掉。

    这条闸在 `migrate_vault` 里再兜一道（端点上 `_check_migration` 已经先
    400 了），因为 `dirs_exist_ok=True` 对非空目标是**静默合并**：拷完文件数
    4≠3，校验挂掉 → 回滚 → `_rmtree(target)` 连用户那个 `占位` 一起删。
    所以这里断言的不只是「源还在」，还有**目标里原有的东西也没被碰**。

    （修 ① 之前这条靠 `copytree` 撞上已存在目录抛 `FileExistsError` 来验，
    现在那个异常不存在了；docstring 里原来那句「copytree 到已存在的目录会抛」
    已经不作数。）
    """
    source = _make_vault(tmp_path / "旧")
    target = tmp_path / "新"
    target.mkdir()
    (target / "占位").write_text("x", encoding="utf-8")

    with pytest.raises(LifecycleError, match="非空"):
        migrate_vault(source, target)

    assert (source / "计算机" / "笔记0.md").is_file()   # 源一根汗毛没动
    assert (target / "占位").is_file()                  # 目标原有的东西也没被删


def test_rmtree_deletes_a_read_only_file(tmp_path):
    """**只读文件也删得掉**——`_rmtree` 存在的全部理由。

    git 的松散对象是只读的（实测 `0o100444`），Windows 上 `shutil.rmtree`
    撞上它直接抛 `PermissionError [WinError 5]`。上面那条
    `test_remove_reports_a_locked_vault_instead_of_pretending` 看着也走
    `_rmtree`，其实它把 `shutil.rmtree` 整个换成了「一律抛 OSError」，
    chmod-重试那条路**一步都走不到**，所以这条得单独写。
    """
    tree = tmp_path / "树"
    obj = tree / "objects" / "ab" / "cdef"
    obj.parent.mkdir(parents=True)
    obj.write_text("x", encoding="utf-8")
    os.chmod(obj, 0o444)                     # 跟 git 的松散对象一样：只读

    lifecycle._rmtree(tree)

    assert not tree.exists()


# ---------- remove_vault ----------

def test_remove_deletes_vault_chats_logs_and_state(tmp_path):
    vault = _make_vault(tmp_path / "库")
    data = tmp_path / "data"
    (data / "chats").mkdir(parents=True)
    (data / "chats" / "c.json").write_text("{}", encoding="utf-8")
    (data / "logs" / "kb").mkdir(parents=True)
    (data / "logs" / "kb" / "2026-01-01.log").write_text("x", encoding="utf-8")
    (data / "state.json").write_text("{}", encoding="utf-8")

    result = remove_vault(vault, data)

    assert result["vault_removed"] is True
    assert not vault.exists()
    assert not (data / "chats").exists()
    assert not (data / "logs").exists()
    assert not (data / "state.json").exists()
    assert result["failed"] == []


def test_remove_leaves_the_rest_of_data_alone(tmp_path):
    """**删除清单只有三项**：`data/chats`、`data/logs`、`data/state.json`。

    最要紧的是 `data/runtime/service.json` 不在里面——那是 `kb stop` 唯一的
    线索，探活失败时 `stop_service` 还会顺手把它清掉；删了就是「停不掉的
    孤儿进程」，而那个 bug 的症状是**测试全绿、开发机上服务失控**
    （`04_踩坑与经验.md` 第 21 条）。

    **这条测试得真的会咬，所以多造一个无关文件一起验。** 只断言
    `service.json` 还在的话它是**恒真**的——`remove_vault` 压根不碰
    `data/runtime`，那条断言一条路径都走不到。（「一点痕迹都不留」这个说法
    压过来的时候，最省事的改法就是 `rmtree(data_dir)`，那正是要拦的。）
    """
    vault = _make_vault(tmp_path / "库")
    data = tmp_path / "data"
    (data / "runtime").mkdir(parents=True)
    (data / "runtime" / "service.json").write_text("{}", encoding="utf-8")
    (data / "unrelated.txt").write_text("x", encoding="utf-8")

    remove_vault(vault, data)

    assert (data / "runtime" / "service.json").is_file()
    assert (data / "unrelated.txt").is_file()
    assert data.is_dir()          # `data/` 本身也得留着


def test_remove_survives_a_missing_vault_dir(tmp_path):
    """库本来就不在了 → 照删其余部分，最后说明一句。**不算错。**"""
    data = tmp_path / "data"
    (data / "chats").mkdir(parents=True)

    result = remove_vault(tmp_path / "根本没有", data)

    assert result["vault_removed"] is True
    assert result["failed"] == []
    assert any("本来就不在了" in n for n in result["notes"])


def test_remove_with_no_vault_configured(tmp_path):
    """没配过库就点移除——不该炸。"""
    result = remove_vault(None, tmp_path / "data")
    assert result["vault_removed"] is True
    assert result["failed"] == []


def test_remove_reports_a_locked_vault_instead_of_pretending(tmp_path, monkeypatch):
    """被占着删不掉时**如实汇报**，并且**不解绑**——库还在，界面就不能说
    「还没有知识库」。"""
    vault = _make_vault(tmp_path / "库")

    def refuse(*a, **k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(lifecycle.shutil, "rmtree", refuse)

    result = remove_vault(vault, tmp_path / "data")

    assert result["vault_removed"] is False
    assert result["failed"]
    assert vault.exists()                # 名字被改回去了
