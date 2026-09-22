"""库的生命周期：状态推断、路径体检、搬家、移除。"""

import pytest

from kb.core import lifecycle
from kb.core.lifecycle import (
    Busy,
    LifecycleError,
    check_path,
    migrate_vault,
    remove_vault,
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


def test_migrate_removes_the_source_only_after_verification(tmp_path):
    """校验没过就删源 = 数据没了。这条用「目标被占」间接验：
    copytree 到已存在的目录会抛，源必须还在。"""
    source = _make_vault(tmp_path / "旧")
    target = tmp_path / "新"
    target.mkdir()
    (target / "占位").write_text("x", encoding="utf-8")

    with pytest.raises(OSError):
        migrate_vault(source, target)

    assert (source / "计算机" / "笔记0.md").is_file()


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
