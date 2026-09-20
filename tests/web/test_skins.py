"""六套皮肤的取值、CSS 落地、以及「别再写死色值」的防回潮。"""

import re
from pathlib import Path

STYLE_CSS = (
    Path(__file__).resolve().parents[2] / "src" / "kb" / "web" / "static" / "style.css"
)

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def test_no_hardcoded_hex_outside_variable_blocks():
    """变量定义之外不许出现十六进制色值。

    **这条是防回潮的**：以后随手写一个 `color: #fff`，换皮就会在那处漏出
    上一套皮肤的颜色——而这种事在截图里不一定看得出来。

    变量定义的行（`--x: #abc;`）放过：那一处正是所有颜色的家。
    """
    text = STYLE_CSS.read_text(encoding="utf-8")
    leftovers = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if not line.strip().startswith("--") and HEX.search(line)
    ]
    assert leftovers == [], "变量定义之外还有写死的色值：\n" + "\n".join(leftovers)
