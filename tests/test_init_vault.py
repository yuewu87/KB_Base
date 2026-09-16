import subprocess

from kb.core.vault import (
    ATTACHMENTS,
    INBOX,
    INDEX,
    JOURNAL_DIR,
    KNOWLEDGE,
    MATERIALS,
    PENDING,
    PROJECTS,
)
from scripts.init_vault import KNOWLEDGE_TOPICS, init_vault, vault_dirs


def test_creates_all_skeleton_dirs(tmp_path):
    init_vault(tmp_path)
    for rel in (
        INBOX,
        f"{INBOX}/{PENDING}",
        PROJECTS,
        KNOWLEDGE,
        MATERIALS,
        INDEX,
        f"{INDEX}/{JOURNAL_DIR}",
        ATTACHMENTS,
    ):
        assert (tmp_path / rel).is_dir(), f"缺少目录 {rel}"


def test_creates_topic_dirs(tmp_path):
    init_vault(tmp_path)
    for topic in KNOWLEDGE_TOPICS:
        assert (tmp_path / KNOWLEDGE / topic).is_dir()


def test_writes_gitignore_ignoring_workspace(tmp_path):
    """Q53：workspace.json 每次开关 Obsidian 都变，必须忽略。"""
    init_vault(tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".obsidian/workspace.json" in text


def test_initializes_git_repo(tmp_path):
    init_vault(tmp_path)
    assert (tmp_path / ".git").is_dir()


def test_makes_first_commit(tmp_path):
    """骨架要有首次提交，否则 .gitignore 一直悬着未跟踪。"""
    init_vault(tmp_path)
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
    """重复执行不报错，且第二次无事可做。"""
    init_vault(tmp_path)
    assert init_vault(tmp_path) == []


def test_second_run_keeps_existing_notes(tmp_path):
    """幂等：不能删掉用户已经写进去的内容。"""
    init_vault(tmp_path)
    note = tmp_path / KNOWLEDGE / "后端" / "已有笔记.md"
    note.write_text("内容", encoding="utf-8")
    init_vault(tmp_path)
    assert note.read_text(encoding="utf-8") == "内容"


def test_reports_what_it_did(tmp_path):
    """返回动作清单，便于调用方展示——空清单表示什么都没做。"""
    actions = init_vault(tmp_path)
    assert actions
    assert any("git" in a for a in actions)


def test_vault_dirs_are_absolute_under_root(tmp_path):
    for d in vault_dirs(tmp_path):
        assert d.is_relative_to(tmp_path)
