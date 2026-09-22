"""建 vault 骨架。**薄壳**——实现住在 `kb.core.vault_setup`。

搬家的理由：服务要调它（设置窗那条龙），而 `src/` 与 `scripts/` 之间没有桥
（`pyproject.toml` 的 `pythonpath` 只有 `src`）。服务进程「恰好」能 import 它
是巧合不是设计——见 `kb/core/vault_setup.py` 开头那段。

直接运行（**路径必填**）：

    python scripts/init_vault.py <vault 的绝对路径>
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
    # **不给路径就报错，不回落。** 这里原来回落到写死的 `E:\KB_Library`：
    # 别人的机器上会凭空长出**作者**那个路径的骨架，而服务的 `.env` 指着别处，
    # 正是 `require_vault` 要消灭的「半截状态」——而它看起来是成功的。
    # 脚本**不读 `.env`**，所以也别假装 `.env` 里填了就能不传参。
    #
    # 相对路径一并挡掉，两个理由：填进 `.env` 后服务的启动目录和你的 shell
    # 不是同一个，库会绑到你没想到的地方；而且设置窗那条路也是这么挡的，
    # 两个入口不该有两套规矩。**挡在建目录之前**——失败了就不该留下东西。
    if len(sys.argv) < 2:
        print("用法：python scripts/init_vault.py <vault 的绝对路径>")
        raise SystemExit(2)
    root = Path(sys.argv[1])
    if not root.is_absolute():
        print(f"{root} 是相对路径，知识库要建在绝对路径上。")
        raise SystemExit(2)
    # 只建 DEFAULT_DOMAINS 的领域（当前「计算机」一个）。老脚本建的是
    # SEED_DOMAINS 的三个（计算机/艺术/文学），那三个已删——**领域数从 3 变 1**。
    done = init_vault(root, DEFAULT_DOMAINS)
    if done:
        print(f"初始化 {root}：")
        for line in done:
            print(f"  {line}")
    else:
        print(f"{root} 已是完整骨架，无需改动。")
