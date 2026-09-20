"""六套皮肤的取值、CSS 落地、以及「别再写死色值」的防回潮。"""

import re
from pathlib import Path

import pytest

from kb.web import skins

STYLE_CSS = (
    Path(__file__).resolve().parents[2] / "src" / "kb" / "web" / "static" / "style.css"
)

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")

# 每套皮肤该有的 32 个变量。顺序与 `skins.ORDER` 一致。
ALL_VARS = (
    "--paper", "--surface", "--ink", "--line", "--accent", "--accent-soft",
    "--muted", "--faint", "--ink-soft", "--faint-dim",
    "--line-soft", "--line-strong", "--divider",
    "--accent-mid", "--accent-tint", "--accent-line", "--accent-ring",
    "--accent-ink", "--on-accent", "--on-danger",
    "--journal-soft", "--journal-line",
    "--terminal-void", "--terminal-text", "--scrim",
    "--sweep-gold", "--sweep-gold-deep", "--sweep-gold-wash",
    "--danger", "--danger-hover",
    "--shadow", "--shadow-lift",
)

# 这俩**不是颜色**，是一整条 `0 1px 2px rgba(...), 0 4px 12px rgba(...)`。
COLOR_VARS = tuple(v for v in ALL_VARS if v not in ("--shadow", "--shadow-lift"))

HEX_OR_RGBA = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s,.]+\))$")


# ------------------------------------------------------------ 防回潮

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


def test_no_hardcoded_hex_in_templates():
    """模板里也不许写死颜色。

    **上面那条防不住这里，而且真漏过。** `flow.html` 的流程链勾写死过
    `stroke="#fff"`：它是画在 `fill="currentColor"`（= `--accent`）的实心圆
    上的，所以皮肤一切到 ④ 荧光绿，就成了白勾压荧光绿，≈1.2:1，看不见。
    扫 `style.css` 怎么扫都扫不到它。

    揪出它的办法记在这儿：拿无头浏览器把**每个元素的最终计算色**报出来，
    逐条核对是不是那 32 个变量解释得了的。六套 × 六页跑一遍，剩下的
    全是干净的就说明没漏。手改模板的人不会想到要跑那个，所以钉成测试。

    `style="--dot: {{ ... }}"` 那种把颜色**当数据传**的写法不受影响
    （模板源码里是 Jinja 表达式，不是字面量）。
    """
    bad = [
        f"{path.name}:{n}: {line.strip()}"
        for path in sorted((STYLE_CSS.parents[1] / "templates").glob("*.html"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if HEX.search(line)
    ]
    assert bad == [], "模板里有写死的色值（换皮肤会漏出上一套的颜色）：\n" + "\n".join(bad)


# ------------------------------------------------------------ 取值

def test_every_skin_defines_every_variable():
    """六套皮肤，每套 32 个变量一个不少，且都长得像颜色。"""
    for skin in skins.SKINS:
        values = skins.derive(skin.id)
        assert set(values) == set(ALL_VARS), (
            f"{skin.id} 缺或多：{set(ALL_VARS) ^ set(values)}"
        )
        for key in COLOR_VARS:
            assert HEX_OR_RGBA.match(values[key]), (
                f"{skin.id} 的 {key} 不是颜色字面量：{values[key]!r}"
            )
        for key in ("--shadow", "--shadow-lift"):
            assert "rgba(" in values[key], f"{skin.id} 的 {key} 不像一条阴影"


def test_unknown_skin_falls_back_to_archive():
    """认不出的 id 一律当现有蓝——`kb.config._skin()` 与这里用的是同一份语义。"""
    assert skins.derive("purple") == skins.derive("archive")
    assert skins.derive("") == skins.derive("archive")


@pytest.mark.parametrize("skin", skins.SKINS, ids=lambda s: s.id)
def test_color_scheme_follows_the_skin_tone(skin):
    """深色皮要带 `color-scheme: dark`，浅色皮带 `light`。

    否则滚动条、`<select>` 下拉、`readonly` 输入框这些**浏览器原生画的**
    东西会跟皮肤对不上，深色皮边上漏出一圈白。

    **按每套自己的 `tone` 断言，不写死 id**——哪个 id 属于哪一档是数据，
    不是常量（② 就从浅色改成了深色）。
    """
    block = skins.render_block(skin.id)
    assert block.startswith(f'[data-skin="{skin.id}"]')
    assert f"color-scheme: {'dark' if skin.dark else 'light'}" in block


def test_archive_is_verbatim_todays_values():
    """现有蓝是「原样保留」，几个关键值钉死——推导规则以后怎么改都不许波及它。"""
    values = skins.derive("archive")
    assert values["--paper"] == "#fbfcfe"
    assert values["--accent"] == "#2f5d8a"
    assert values["--journal-soft"] == "#fdf1f5"
    assert values["--sweep-gold"] == "#c9a86a"


@pytest.mark.parametrize("skin_id", [s.id for s in skins.SKINS])
def test_text_is_readable(skin_id):
    """正文与「强调色当文字」都要到 4.5:1。

    `--accent-ink` 这一档存在的全部理由就是这条：② 的紫、⑥ 的蓝直接当
    文字只有 2.85 / 2.60:1。这条测试是它的看门人——**推导规则改动、
    或将来有人换了锚点，可读性掉了当场变红**，不用等谁肉眼发现。
    """
    values = skins.derive(skin_id)
    assert skins.contrast(values["--ink"], values["--paper"]) >= 4.5
    assert skins.contrast(values["--accent-ink"], values["--paper"]) >= 4.5


@pytest.mark.parametrize("skin_id", [s.id for s in skins.SKINS])
def test_button_text_sits_readably_on_its_background(skin_id):
    """铺着色的按钮/标签上，字要是看得清的。

    `--on-accent` 是白或黑二选一。**这里不写死「白字」**——粉、紫、红、
    荧光绿上白字都不达标，规则是自动取高的那个。
    """
    values = skins.derive(skin_id)
    assert skins.contrast(values["--on-accent"], values["--accent"]) >= 4.5
    assert skins.contrast(values["--on-danger"], values["--danger"]) >= 4.5


# ------------------------------------------------------------ CSS 落地

# 生成块的首尾标记。测试靠它把「生成的」和「手写的」分开。
BEGIN = "/* ===== 皮肤：由 scripts/derive_skins.py 生成，不要手改 ===== */"
END = "/* ===== 皮肤块结束 ===== */"


def test_root_matches_generated_archive():
    """`:root` 里那 32 行必须逐字等于 `derive("archive")` 的渲染结果。

    现有蓝是「原样保留」，手改一下就会漂——而且漂了看不出来。
    """
    text = STYLE_CSS.read_text(encoding="utf-8")
    assert skins.render_vars("archive") in text, ":root 与 skins.derive('archive') 对不上"


def test_style_css_contains_generated_blocks():
    """另外五块逐字等于 `render_block()` 的输出。"""
    text = STYLE_CSS.read_text(encoding="utf-8")
    for skin_id in skins.SKIN_IDS:
        if skin_id == skins.DEFAULT_SKIN:
            continue
        assert skins.render_block(skin_id) in text, (
            f"style.css 里没有 {skin_id} 的块，或与生成结果不一致"
        )


def test_generated_region_is_delimited():
    """生成区有首尾标记——没有的话下一次 `--write` 会找不到地方插。"""
    text = STYLE_CSS.read_text(encoding="utf-8")
    assert BEGIN in text and END in text
    assert text.index(BEGIN) < text.index(END)
