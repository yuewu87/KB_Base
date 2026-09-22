"""建 vault 骨架。幂等——可重复执行，不破坏已有内容。

**这个模块是知识库结构的唯一真源**：实际目录是它的产物。
想调结构就改这里重跑，不要手工建目录。

**为什么住在 `core/` 而不是 `scripts/`**：服务要调它（设置窗那条龙）。
`src/` 与 `scripts/` 之间没有桥——`pyproject.toml` 的 `pythonpath` 只有 `src`，
`src/` 下也没有任何文件 import `scripts`。服务进程「恰好」能 import 是因为
`spawn_service` 用 `-m kb.api.http` 且 `cwd=PROJECT_ROOT`，`python -m` 把 cwd
放进了 `sys.path[0]`——**那是巧合不是设计**，换个人从别的 cwd 起服务就断。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from kb.core.vault import ATTACHMENTS, INBOX, INDEX, JOURNAL_DIR, PENDING

# 开库时可勾的领域清单。**九个候选**——界面把它们画成复选框。
#
# **清单不进 `.env`，设置里也没有这一栏。** 领域的唯一真源始终是磁盘
# （`vault.list_domains` 直接读目录），勾选的作用只是建出对应的目录，
# 建完就不再被读第二次。要加领域 = 建文件夹，不走配置。
DOMAIN_CANDIDATES = [
    "计算机", "科学", "艺术", "文学", "历史", "哲学", "生活", "工作", "健康",
]

# 界面上默认勾上的那几个。
DEFAULT_DOMAINS = ["计算机"]

VAULT_GITIGNORE = """\
# Obsidian 工作区状态——每次开关都变，入库会淹没历史（Q53）
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/cache

# 系统文件
.DS_Store
Thumbs.db
"""


def vault_dirs(vault_root: Path, domains: list[str] | None = None) -> list[Path]:
    """列出骨架包含的全部目录（顺序即创建顺序）。

    `domains` 不给就只建机器目录——领域是**可选的**，不是骨架的必需品。
    """
    dirs = [
        vault_root / INBOX,
        vault_root / INBOX / PENDING,
        vault_root / INDEX,
        vault_root / INDEX / JOURNAL_DIR,
        vault_root / ATTACHMENTS,
    ]
    dirs += [vault_root / d for d in (domains or [])]
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


def init_vault(vault_root: Path, domains: list[str] | None = None) -> list[str]:
    """建目录、写 .gitignore、初始化 git。返回本次实际执行的动作。

    只做缺失的部分，已有的东西一律不碰——包括用户自己改过的 `.gitignore`。
    **幂等**：重复点不会毁掉已有的东西，这是界面上那句提示的底气。

    `domains` 是这次要建的领域目录，**不给就只建机器目录**——领域是调用方的事。

    ⚠️ **命令行入口不属于「不给」**：`scripts/init_vault.py` 传的是
    `DEFAULT_DOMAINS`，只有「计算机」**一个**。老脚本走 `SEED_DOMAINS`
    （计算机 / 艺术 / 文学 **三个**）。所以 CLI 建出的领域目录从 3 个变成
    1 个——这是有意的改动（领域改由用户勾），**不是「行为不变」**。
    """
    actions: list[str] = []

    for d in vault_dirs(vault_root, domains):
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
