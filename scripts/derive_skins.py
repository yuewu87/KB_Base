"""把 `kb.web.skins` 渲染的皮肤块写进 `style.css`。

用法：

    python scripts/derive_skins.py            # 只检查两边是否一致
    python scripts/derive_skins.py --write    # 真的写
    python scripts/derive_skins.py --report   # 打印六套的对比度表

**`--write` 是幂等的**：连跑两次，第二次什么都不改。

改配色请改 `src/kb/web/skins.py` 里的规则或锚点，**不要手改 style.css 里那几块**
——`tests/web/test_skins.py` 会当场发现两边对不上。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kb.web import skins  # noqa: E402  （要先加好 sys.path）

STYLE_CSS = (
    Path(__file__).resolve().parents[1] / "src" / "kb" / "web" / "static" / "style.css"
)

BEGIN = "/* ===== 皮肤：由 scripts/derive_skins.py 生成，不要手改 ===== */"
END = "/* ===== 皮肤块结束 ===== */"

MARKED = f"{BEGIN}\n\n{skins.blocks()}\n{END}\n"


def current_region(text: str) -> str:
    """取出 style.css 里那段生成区（含首尾标记）。没有就返回空串。"""
    if BEGIN not in text or END not in text:
        return ""
    start = text.index(BEGIN)
    stop = text.index(END) + len(END) + 1
    return text[start:stop]


def apply(text: str) -> str:
    """把生成区换上最新内容。没有生成区就追加到文件末尾。"""
    region = current_region(text)
    if region:
        return text.replace(region, MARKED)
    return text.rstrip("\n") + "\n\n" + MARKED


def report() -> None:
    """六套的对比度一览。

    改完推导规则想确认「没把哪套改瞎」时看这张表——比翻 CSS 快，
    也比肉眼看截图准。`--accent-ink` 与「按钮字」两列**必须全部 ≥4.5**，
    它们各有测试守着（`tests/web/test_skins.py`）。
    """
    header = ("皮肤", "墨/底", "次级", "三级", "强调(填充)", "强调(文字)", "按钮字")
    print(f"{header[0]:<12}{header[1]:>9}{header[2]:>9}{header[3]:>9}"
          f"{header[4]:>12}{header[5]:>12}{header[6]:>9}")
    for skin in skins.SKINS:
        values = skins.derive(skin.id)
        cells = (
            skins.contrast(values["--ink"], values["--paper"]),
            skins.contrast(values["--muted"], values["--paper"]),
            skins.contrast(values["--faint"], values["--paper"]),
            skins.contrast(values["--accent"], values["--paper"]),
            skins.contrast(values["--accent-ink"], values["--paper"]),
            skins.contrast(values["--on-accent"], values["--accent"]),
        )
        print(f"{skin.id:<12}" + "".join(f"{c:>9.2f}" for c in cells[:3])
              + "".join(f"{c:>12.2f}" for c in cells[3:5]) + f"{cells[5]:>9.2f}")


def main() -> int:
    if "--report" in sys.argv:
        report()
        return 0

    text = STYLE_CSS.read_text(encoding="utf-8")
    updated = apply(text)

    if updated == text:
        print("style.css 已经是最新的")
        return 0

    if "--write" not in sys.argv:
        print("style.css 与 skins.py 不一致（加 --write 才会真的写）")
        return 1

    STYLE_CSS.write_text(updated, encoding="utf-8", newline="\n")
    print(f"已更新 {STYLE_CSS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
