"""建 vault 骨架。**薄壳**——实现住在 `kb.core.vault_setup`。

搬家的理由：服务要调它（设置窗那条龙），而 `src/` 与 `scripts/` 之间没有桥
（`pyproject.toml` 的 `pythonpath` 只有 `src`）。服务进程「恰好」能 import 它
是巧合不是设计——见 `kb/core/vault_setup.py` 开头那段。

直接运行：

    python scripts/init_vault.py [vault 路径]
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让脚本能直接跑：pytest 走 pyproject 里的 pythonpath，直接运行则没有，
# 于是 `from kb...` 会 ModuleNotFoundError。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kb.core.vault_setup import (  # noqa: E402 —— 必须在 sys.path 自举之后
    DEFAULT_DOMAINS,
    DOMAIN_CANDIDATES,
    VAULT_GITIGNORE,
    init_vault,
    vault_dirs,
)

__all__ = [
    "DEFAULT_DOMAINS",
    "DOMAIN_CANDIDATES",
    "VAULT_GITIGNORE",
    "init_vault",
    "vault_dirs",
]


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"E:\KB_Library")
    # 只建 DEFAULT_DOMAINS 的领域（当前「计算机」一个）。老脚本建的是
    # SEED_DOMAINS 的三个（计算机/艺术/文学），那三个已删——**领域数从 3 变 1**。
    done = init_vault(root, DEFAULT_DOMAINS)
    if done:
        print(f"初始化 {root}：")
        for line in done:
            print(f"  {line}")
    else:
        print(f"{root} 已是完整骨架，无需改动。")
