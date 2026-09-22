"""库的生命周期：状态推断、路径体检、搬家、移除。"""

import os
from pathlib import Path

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


def test_acquiring_an_unknown_name_is_an_error():
    """**没配中文标签的名目要当场炸，不能静默回落成英文。**

    `_BUSY_LABELS` 缺键时 `label` 走的是 `.get(what, what or "")`——直接
    把键名吐出来，于是文案变成中英夹杂的「正在reindex，等它跑完再试」。
    `sweep` 就是这么漏的（Task 10 才补上），而且**它不报错、测试全绿**，
    只能等用户来问。

    CLAUDE.md：「**机械约束归代码，判断题归模型。** 写一条规则之前先问：
    这条能不能落成一行 `if`？」——能，所以这条不靠 docstring 里那句
    「每加一个名目就要补一条」的承诺守着。
    """
    busy = Busy()
    with pytest.raises(ValueError, match="reindex"):
        busy.acquire("reindex")
    assert busy.what is None          # 炸了就不许占住


def test_refusal_survives_the_holder_releasing():
    """**拿不到锁之后持锁方才释放**，不能生成半截句子。

    走到「拒绝」这条分支的前提就是别人正持锁；而 `busy.what` 是在
    `acquire` 返回 `False` **之后**才读的，那中间持锁方可能已经
    `release()` 了。原先 `.get(None, None or "")` 会得到空串，409 的 detail
    和巡检页那份报告就会一起显示「正在，等它跑完再试」——照着这句话去等
    一个不存在的动作。
    """
    busy = Busy()
    assert busy.acquire("organize") is True
    busy.release()

    assert busy.refusal != "正在，等它跑完再试"
    assert "正在，" not in busy.refusal


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


def test_migrate_keeps_the_target_when_the_source_cannot_be_deleted(
        tmp_path, monkeypatch):
    """**删源失败绝不回滚目标，而且绝不抛裸 `OSError`。**

    走到删源这一步时，目标已经拷完并校验通过，它是**唯一完整的一份**；
    源正在被删、可能只剩一半。这时候回滚（`_rmtree(target)`）等于把好的
    那份也毁了——**方向反了**：上面那段 `except` 里的回滚只适用于**拷贝**
    阶段，那时源是完整的、目标是半截的。

    而 `_rmtree(source)` 失败在 Windows 上是常态（被 Obsidian、资源管理器
    预览、杀软占着），并且抛的是**裸 `OSError`**——端点那句
    `except LifecycleError` 接不住，用户拿到 500、`.env` 没改、旧库残着，
    重试又撞「目标非空」400，走进死胡同。所以这里按 `notes` 如实汇报，
    `.env` 照常指向新库。

    **`_rmtree` 的替身只对 source 生效。** 拷贝失败的回滚那一路也调
    `_rmtree(target)`，无差别抛错的话这条用例测的就是别的东西了。
    """
    source = _make_vault(tmp_path / "旧")
    target = tmp_path / "新"
    real = lifecycle._rmtree

    def refuse(path, **kwargs):
        if path == source:
            raise OSError(13, "占着")
        real(path, **kwargs)

    monkeypatch.setattr(lifecycle, "_rmtree", refuse)

    moved = migrate_vault(source, target)            # 不抛

    assert (target / "计算机" / "笔记0.md").is_file()  # 新库是齐的（没回滚）
    assert moved["notes"]
    assert str(source) in moved["notes"][0]           # 说清脏东西留在哪儿
    assert str(target) in moved["notes"][0]           # 并叮嘱别把新库删了


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

def test_remove_refuses_a_dir_that_is_not_a_vault(tmp_path):
    """**填错一个字母就删掉一个不相干的目录**——这个函数最严重的一种失败。

    端点拿到的是 `.env` 里那个字符串，一个字都不校验就交给 `remove_vault`，
    而后者**改名 + 递归删除**。用户把路径填成 `E:\\Documents` 这种手滑，
    一句 `POST /setup/remove` 就把那个目录整个端掉；界面上的确认框是
    **界面礼貌**，拦不住 `curl`、也拦不住接入指南里的会话层 AI。所以判据
    落在最里面这一层。

    **断言必须落到文件上**：只断言「抛了 `LifecycleError`」的话，一个
    「先删了再抛」的实现照样绿。
    """
    plain = tmp_path / "我的文档"
    plain.mkdir()
    (plain / "重要.txt").write_text("别删我", encoding="utf-8")

    with pytest.raises(LifecycleError, match="不是一个知识库"):
        remove_vault(plain, tmp_path / "data")

    assert plain.is_dir()                            # 目录还在
    assert (plain / "重要.txt").is_file()             # 里面那个文件也在


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


# ---------- 修 ①：动手之前先自验这个路径 ----------
#
# 和上面 `test_remove_refuses_a_dir_that_is_not_a_vault` 同一类，补的是那个
# 判据（`.git` 在不在）盖不住的两条：**相对路径**，以及**源这一侧**。
# 两个函数最后都要 `_rmtree` 拿到手的那棵树，而拿到手的只是 `.env` 里那个
# 字符串——`config._build` 做的是 `Path(vault_raw)`，不 resolve、不判是不是库。


def test_migrate_refuses_a_source_that_is_not_a_vault(tmp_path):
    """搬走一个不相干的目录 = 把它删掉。

    原先这个闸只在端点的 `_check_migration` 里，而 `_rmtree(source)` 是在
    `migrate_vault` 里跑的。判据落两层照着「非空目标」那条既有做法来。
    """
    plain = tmp_path / "我的文档"
    plain.mkdir()
    (plain / "重要.txt").write_text("别搬我", encoding="utf-8")

    with pytest.raises(LifecycleError, match="不是一个知识库"):
        migrate_vault(plain, tmp_path / "新")

    assert (plain / "重要.txt").is_file()
    assert not (tmp_path / "新").exists()


def test_migrate_refuses_a_relative_source(tmp_path, monkeypatch):
    """**`.env` 里手填 `KB_VAULT_PATH=.` 会把整个 KN_Base 仓库删掉。**

    服务进程的 cwd 是 `PROJECT_ROOT`（`spawn_service` 传的 `cwd=`），那儿正好
    有 `.git`——于是 `.` 一路通过 `exists()` 和 `vault_ready()`，整个仓库被
    当成库拷到目标，紧接着 `_rmtree(source)` 把它清空，响应还是一句轻描淡写的
    「旧库没删干净」。`settings._vault_path_problem` 早就写明了这一手，只是
    `/setup/*` 从不走 `settings.validate`。
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "kb.py").write_text("x", encoding="utf-8")

    with pytest.raises(LifecycleError, match="相对路径"):
        migrate_vault(Path("."), tmp_path / "新")

    assert (tmp_path / ".git").is_dir()
    assert (tmp_path / "src" / "kb.py").is_file()
    assert not (tmp_path / "新").exists()


def test_remove_refuses_a_relative_path(tmp_path, monkeypatch):
    """同一个 `.` 打到移除这条路上，原先抛的是 `Path(".").with_name("")` 的
    裸 `ValueError`——端点接不住，用户拿到 500 而不是「你路径填错了」。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "重要.txt").write_text("别删我", encoding="utf-8")

    with pytest.raises(LifecycleError, match="相对路径"):
        remove_vault(Path("."), tmp_path / "data")

    assert (tmp_path / "重要.txt").is_file()
    assert (tmp_path / ".git").is_dir()


def test_migrate_refuses_a_target_that_is_a_file(tmp_path):
    """目标填成一个**已存在的文件**：`any(target.iterdir())` 抛的是
    `NotADirectoryError`，那是 `OSError` 不是 `LifecycleError`，端点的
    `except` 接不住 → 500。

    而界面正把用户往这条路上推：`/setup/check` 对同一个路径回的是
    「存在、能写、里面一个条目都没有」。
    """
    source = _make_vault(tmp_path / "旧")
    target = tmp_path / "notes.md"
    target.write_text("我是一个文件", encoding="utf-8")

    with pytest.raises(LifecycleError, match="文件"):
        migrate_vault(source, target)

    assert target.read_text(encoding="utf-8") == "我是一个文件"
    assert (source / "计算机" / "笔记0.md").is_file()


def test_migrate_wraps_a_source_it_cannot_measure(tmp_path, monkeypatch):
    """量源（`_tree_size`）那一步原先在 `try` **外面**：`rglob` 与 `p.stat()`
    之间文件正好没了（被整理、被编辑器重写）抛的就是裸 `OSError` → 500，
    而那时源和目标都一根汗毛没动。包进 `try` 之后它和「拷贝失败」同路。
    """
    source = _make_vault(tmp_path / "旧")

    def boom(path):
        raise OSError(2, "量到一半文件没了")

    monkeypatch.setattr(lifecycle, "_tree_size", boom)

    with pytest.raises(LifecycleError, match="量到一半文件没了"):
        migrate_vault(source, tmp_path / "新")

    assert (source / "计算机" / "笔记0.md").is_file()


# ---------- 修 ①：移除失败时如实汇报 ----------

def test_remove_reports_a_partially_deleted_vault_honestly(tmp_path, monkeypatch):
    """改名改回去成功 ≠「什么都没少」。

    `_rmtree` 是**边走边删**的：`scandir` 顺序里前几个条目可能已经删掉了，
    它才在某个被占着句柄的文件上失败。「改回去」恢复的是名字，不是内容。
    """
    vault = _make_vault(tmp_path / "库")

    def refuse(*a, **k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(lifecycle.shutil, "rmtree", refuse)

    result = remove_vault(vault, tmp_path / "data")

    assert result["vault_removed"] is False
    assert any("删了一部分" in f for f in result["failed"])


def test_remove_survives_a_rename_back_that_also_fails(tmp_path, monkeypatch):
    """改名改回去这一步自己也会失败——那个进程既然占着库里的文件，Windows
    上连目录改名都不会放行（实测 `WinError 5`）。

    原先它是 `except OSError` 块里一句裸调，一抛就从 `remove_vault` 里逃出去，
    端点的 `except LifecycleError` 接不住 → 500；而库已经躺在那个
    `.库.deleting-<时间戳>` 的残骸里，谁都没被告知。
    """
    vault = _make_vault(tmp_path / "库")

    def refuse_rmtree(*a, **k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(lifecycle.shutil, "rmtree", refuse_rmtree)

    real_rename = lifecycle.os.rename

    def rename_fails_back(src, dst):
        if Path(dst) == vault:
            raise OSError(5, "拒绝访问")
        real_rename(src, dst)

    monkeypatch.setattr(lifecycle.os, "rename", rename_fails_back)

    result = remove_vault(vault, tmp_path / "data")      # 不许抛

    assert result["vault_removed"] is False
    assert any("deleting-" in f for f in result["failed"])
    assert any("删了一部分" in f for f in result["failed"])


def test_remove_says_what_it_deleted_when_the_vault_survives(tmp_path, monkeypatch):
    """库没删掉，`data/chats` / `data/logs` / `state.json` 照样删了——
    **那是本来的设计**（逐项独立删，spec §6.2 / §9.4），但汇报里得说。

    `data/chats` 是这份数据里唯一不可从 git 恢复的（会话历史），而端点补的
    那句「笔记目录没删掉，所以还指着它」读起来是「删除失败、什么都没少」。
    """
    vault = _make_vault(tmp_path / "库")
    data = tmp_path / "data"
    (data / "chats").mkdir(parents=True)
    (data / "chats" / "c.json").write_text("{}", encoding="utf-8")

    # **只让库那棵树删不掉**（那个待删的改名目录），`data/chats` 照常删得掉
    # ——无差别地让 `rmtree` 一律抛，测的就是「chats 也删不掉」那条路了。
    real = lifecycle.shutil.rmtree

    def refuse_only_the_graveyard(path, *a, **k):
        if ".deleting-" in Path(path).name:
            raise OSError(13, "Permission denied")
        real(path, *a, **k)

    monkeypatch.setattr(lifecycle.shutil, "rmtree", refuse_only_the_graveyard)

    result = remove_vault(vault, data)

    assert result["vault_removed"] is False
    assert not (data / "chats").exists()            # 确实删了
    assert any("chats" in n for n in result["notes"])   # 也确实说了
