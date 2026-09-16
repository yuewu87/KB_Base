"""建 vault 骨架。幂等——可重复执行，不破坏已有内容。

这个脚本是**知识库结构的唯一真源**：实际目录是它的产物。
想调结构就改这里重跑，不要手工建目录。

直接运行：

    python scripts/init_vault.py [vault 路径]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 让脚本能直接跑：pytest 走 pyproject 里的 pythonpath，直接运行则没有，
# 于是 `from kb...` 会 ModuleNotFoundError。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kb.core.vault import (  # noqa: E402 —— 必须在 sys.path 自举之后
    ATTACHMENTS,
    INBOX,
    INDEX,
    JOURNAL_DIR,
    PENDING,
    SEED_DOMAINS,
)

VAULT_GITIGNORE = """\
# Obsidian 工作区状态——每次开关都变，入库会淹没历史（Q53）
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/cache

# 系统文件
.DS_Store
Thumbs.db
"""


def vault_dirs(vault_root: Path) -> list[Path]:
    """列出骨架包含的全部目录（顺序即创建顺序）。"""
    dirs = [
        vault_root / INBOX,
        vault_root / INBOX / PENDING,
        vault_root / INDEX,
        vault_root / INDEX / JOURNAL_DIR,
        vault_root / ATTACHMENTS,
    ]
    dirs += [vault_root / d for d in SEED_DOMAINS]
    return dirs


def _git(vault_root: Path, *args: str) -> subprocess.CompletedProcess:
    """调用 git。

    **必须显式指定 utf-8 与 errors="replace"。** Windows 下 `text=True` 会按
    本地编码（GBK）解码，而 git 输出（中文 commit message、路径）是 UTF-8——
    解码异常抛在子进程的读取线程里，主流程只看到 `stdout=None`，极难排查。
    """
    return subprocess.run(
        ["git", *args],
        cwd=vault_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _has_commits(vault_root: Path) -> bool:
    return _git(vault_root, "rev-parse", "HEAD").returncode == 0


def init_vault(vault_root: Path) -> list[str]:
    """建目录、写 .gitignore、初始化 git。返回本次实际执行的动作。

    只做缺失的部分，已有的东西一律不碰——包括用户自己改过的 `.gitignore`。
    """
    actions: list[str] = []

    for d in vault_dirs(vault_root):
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            actions.append(f"建目录 {d.relative_to(vault_root)}")

    gitignore = vault_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(VAULT_GITIGNORE, encoding="utf-8")
        actions.append("写 .gitignore")

    if not (vault_root / ".git").exists():
        _git(vault_root, "init", "-b", "main")
        actions.append("初始化 git 仓库")

    if not _has_commits(vault_root) and gitignore.exists():
        _git(vault_root, "add", ".gitignore")
        _git(vault_root, "commit", "-m", "chore: 初始化 vault 骨架")
        actions.append("首次提交")

    return actions


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"E:\KB_Library")
    done = init_vault(root)
    if done:
        print(f"初始化 {root}：")
        for line in done:
            print(f"  {line}")
    else:
        print(f"{root} 已是完整骨架，无需改动。")
