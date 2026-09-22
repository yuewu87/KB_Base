"""建 vault 骨架。这个模块是**知识库结构的唯一真源**。"""

import os
import subprocess
import sys
from pathlib import Path

from kb.core.vault import ATTACHMENTS, INBOX, INDEX, JOURNAL_DIR, PENDING
from kb.core.vault_setup import (
    DEFAULT_DOMAINS,
    DOMAIN_CANDIDATES,
    init_vault,
    vault_dirs,
)


def test_creates_machine_dirs_without_domains(tmp_path):
    """不给领域就只建机器目录——领域是可选的，不是骨架的必需品。"""
    init_vault(tmp_path)
    for rel in (INBOX, f"{INBOX}/{PENDING}", INDEX, f"{INDEX}/{JOURNAL_DIR}",
                ATTACHMENTS):
        assert (tmp_path / rel).is_dir(), f"缺少目录 {rel}"


def test_creates_only_the_domains_it_is_given(tmp_path):
    """勾了哪几个就建哪几个，**不多建**。

    多建的那天，「领域名让用户选」就名存实亡了。
    """
    init_vault(tmp_path, ["计算机", "健康"])
    assert (tmp_path / "计算机").is_dir()
    assert (tmp_path / "健康").is_dir()
    assert not (tmp_path / "艺术").exists()


def test_default_domains_are_a_subset_of_candidates():
    """两边会漂移——加候选时忘了默认、或反过来，界面上就是空勾或勾错。"""
    assert set(DEFAULT_DOMAINS) <= set(DOMAIN_CANDIDATES)
    assert DEFAULT_DOMAINS, "至少得默认勾一个，否则用户一进来就得自己找"


def test_domain_candidates_are_unique():
    """重复的名字在建目录时不报错（`exist_ok=True`），但界面上会出现两个
    一模一样的复选框——勾一个，另一个看起来没勾。"""
    assert len(DOMAIN_CANDIDATES) == len(set(DOMAIN_CANDIDATES))


def test_writes_gitignore_ignoring_workspace(tmp_path):
    """Q53：workspace.json 每次开关 Obsidian 都变，必须忽略。"""
    init_vault(tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".obsidian/workspace.json" in text


def test_initializes_git_repo_and_commits(tmp_path):
    """骨架要有首次提交，否则 .gitignore 一直悬着未跟踪。"""
    init_vault(tmp_path)
    assert (tmp_path / ".git").is_dir()
    out = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert out.returncode == 0
    assert "初始化 vault 骨架" in out.stdout


def test_does_not_touch_existing_gitignore(tmp_path):
    """幂等：已存在的 .gitignore 不能被覆盖——用户可能自己加过规则。"""
    (tmp_path / ".gitignore").write_text("# 我自己加的\n", encoding="utf-8")
    init_vault(tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "# 我自己加的\n"


def test_is_idempotent(tmp_path):
    """重复执行不报错，且第二次无事可做。**界面上那句「幂等」的底气。**"""
    init_vault(tmp_path, ["计算机"])
    assert init_vault(tmp_path, ["计算机"]) == []


def test_second_run_keeps_existing_notes(tmp_path):
    """幂等：不能删掉用户已经写进去的内容。"""
    # 领域由调用方给（骨架不再默认建 SEED_DOMAINS），所以这里显式点一个。
    init_vault(tmp_path, ["计算机"])
    note = tmp_path / "计算机" / "已有笔记.md"
    note.write_text("内容", encoding="utf-8")
    init_vault(tmp_path)
    assert note.read_text(encoding="utf-8") == "内容"


def test_reports_what_it_did(tmp_path):
    """返回动作清单，便于调用方展示——空清单表示什么都没做。"""
    actions = init_vault(tmp_path)
    assert actions
    assert any("git" in a for a in actions)


def test_vault_dirs_are_absolute_under_root(tmp_path):
    for d in vault_dirs(tmp_path, ["计算机"]):
        assert d.is_relative_to(tmp_path)


def test_script_is_a_thin_shell():
    """`scripts/init_vault.py` 必须是**同一份实现**，不是抄了一份。

    抄一份的那天开始两边就会漂移——改了一个忘了另一个，而 README 还指着
    脚本说「这是唯一真源」。
    """
    from kb.core import vault_setup
    from scripts import init_vault as script

    assert script.init_vault is vault_setup.init_vault


def _run_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """跑真脚本（`__main__` 那一段），拿 `CompletedProcess`。

    **必须给子进程塞 `PYTHONIOENCODING=utf-8`**：中文 Windows 下 stdout 接管道
    时按 locale（GBK）编码，父进程按 utf-8 解码就全是乱码——`kb.bat` 那条
    规矩的同一个坑，只是这次坑在测试自己身上。
    """
    root = Path(__file__).resolve().parents[2]
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "init_vault.py"), *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_script_refuses_to_guess_a_path():
    """不给路径必须报错退出，**不回落到任何写死的路径**。

    原来这里回落到 `E:\\KB_Library`：别人的机器上会凭空长出**作者**那个路径的
    骨架，而服务的 `.env` 指着别处。这是最坏的一种失败——看起来是成功的。
    """
    proc = _run_script()
    assert proc.returncode == 2
    assert "用法" in proc.stdout


def test_script_refuses_a_relative_path_before_creating_anything(tmp_path):
    """相对路径要挡掉，**而且挡在建目录之前**——失败了就不该留下东西。

    填进 `.env` 后服务的启动目录和用户的 shell 不是同一个，库会绑到他没想到
    的地方；设置窗那条路也是这么挡的，两个入口不该有两套规矩。
    """
    proc = _run_script("myvault", cwd=tmp_path)
    assert proc.returncode == 2
    assert "绝对路径" in proc.stdout
    assert not (tmp_path / "myvault").exists()
