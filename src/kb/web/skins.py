"""六套皮肤的取值：从每套 6 个锚点推出其余 26 个变量。

## 为什么是「推导」而不是「手挑」

32 个变量 × 6 套 = 192 个十六进制数字。手挑的话，调一次「② 的紫再深一点」
就要跟着改二十个配套值，改漏一个就是一处对不上——而且看不出来。
所以除了用户定的 6 个锚点，其余**全部按固定比例算**，规则写在下面，
一个「看着调」都没有。

`scripts/derive_skins.py` 把 `render_block()` 的结果写进 `style.css`，
测试断言两边逐字相等。**CSS 里那几块不要手改。**

## 现有蓝不参与推导

用户要求「原样保留」，所以 `ARCHIVE` 把今天线上生效的 32 个值全部硬编码。
推导规则以后怎么改都不许波及它——`test_archive_is_verbatim_todays_values` 守着。

## 对比度

强调色有两个用途，对对比度的要求不一样：**当填充**（按钮底）只要上面的字看得清；
**当文字**（链接、选中项）它自己要 4.5:1。② 的紫、⑥ 的蓝当文字只有 2.85 / 2.60:1，
所以多出一档 `--accent-ink`（朝可读方向推到 4.5），**锚点不动**。

**可读性由测试守着**，不是靠这段注释：`tests/web/test_skins.py` 里六套皮肤
逐个参数化断言了正文、`--accent-ink`、按钮文字三处的对比度。
"""

from __future__ import annotations

from dataclasses import dataclass

# 深色皮要认，浏览器才会把滚动条、<select> 下拉、readonly 输入框跟着画深
_LIGHT = "light"
_DARK = "dark"


@dataclass(frozen=True)
class Skin:
    id: str
    name: str           # 面板上显示的名字
    paper: str
    surface: str
    ink: str
    line: str
    accent: str
    accent_soft: str
    second: str | None  # 撞色里的第二个颜色：只当「巡检金」用，不当第二个强调色
    tone: str           # _LIGHT / _DARK

    @property
    def dark(self) -> bool:
        return self.tone == _DARK


# ----------------------------------------------------------------- 颜色小工具

def _rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def mix(a: str, b: str, t: float) -> str:
    """`a` 朝 `b` 线性插值 `t`（在 gamma 编码的 sRGB 上，与 CSS `color-mix` 一致）。"""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def _luminance(color: str) -> float:
    def channel(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG 对比度。"""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _rgba(color: str, alpha: float) -> str:
    r, g, b = _rgb(color)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _pick_ink(bg: str) -> str:
    """压在 `bg` 上的字用白还是用黑。

    **白字达标（≥4.5:1）就用白，否则才用黑**——不是简单地「谁高选谁」。
    ③ 白 4.32 / 黑 4.58，差 0.26，纯粹比大小会翻成黑字，但「白字压红底」
    是更强的视觉习惯，0.26 的差别也谈不上更好读。定成阈值就没这个摇摆。

    ⚠️ 这**不保证**结果一定 ≥4.5：当 `bg` 的亮度落在 0.183–0.233 那段窄带里，
    黑白两边都够不着（黑最高只能到 4.40）。现有六套锚点没有落进去的
    （最紧的是 ③，黑字 4.58），但**将来换锚点可能踩进去**——
    `test_button_text_sits_readably_on_its_background` 会当场发现。
    """
    return "#ffffff" if contrast("#ffffff", bg) >= 4.5 else "#0a0a0c"


def _to_contrast(accent: str, paper: str, target: float, toward: str) -> str:
    """把 `accent` 朝 `toward` 推，直到对 `paper` 的对比度达标。"""
    if contrast(accent, paper) >= target:
        return accent
    for step in range(1, 256):
        candidate = mix(accent, toward, step / 256)
        if contrast(candidate, paper) >= target:
            return candidate
    return toward


# --------------------------------------------------------------- ②③ 的底色
#
# 用户给的参考图里**只有那两个色**（左半右半各铺一块，另一色当字色），没有任何
# 第三个「底」。所以底色不能自己配一个看着顺眼的——**必须从这两个色里调和出来**，
# 落在它们连成的那条线上。2026-09-20 用户的原话：「我的意思是调和其他俩个配色的
# 那种，而且你这个颜色色号不对吧」——我一开始配的那个亮薰衣草不在线上，是凭空
# 配的，所以「色号不对」。
#
# 规则（`_HARMONY` 是唯一的旋钮）：
#
#     调和色 = mix(主色, 另一个色, _HARMONY)     # 以谁为主，看这套该走哪个色
#     --paper       = 调和色往白提亮 .50          # 提到能当整页底
#     --surface     = 调和色往白提亮 .78          # 卡片再亮一档
#     --line        = --paper 掺 .10 的墨
#     --accent-soft = 强调色往 surface 提亮 .92   # 与其它浅色皮同一条规则
#
# **改比例只改 `_HARMONY` 一个数**，别去手改下面那两行色号——那样又回到
# 「凭手感配一个」，下次换配色还得再猜一遍。
_HARMONY = 0.20


def _harmonized(main: str, other: str, ink: str, accent: str) -> dict[str, str]:
    """按上面那条规则算出 ②③ 底色的四个锚点。

    **刻意让代码算，而不是把结果抄成字面量**——抄一遍就多出一个「改比例时
    要跟着手改」的地方，而那种地方漏一个，色号就悄悄偏一两个数位（实测过：
    手抄的四行里有三行和规则差 1，肉眼看不出来）。
    """
    blend = mix(main, other, _HARMONY)
    paper = mix(blend, "#ffffff", 0.50)
    surface = mix(blend, "#ffffff", 0.78)
    return {
        "paper": paper,
        "surface": surface,
        "line": mix(paper, ink, 0.10),
        "accent_soft": mix(accent, surface, 0.92),
    }


# ②③ 的底色锚点 = 调和规则算出来的；它们的强调色仍是用户定稿值
_AURORA = _harmonized("#9f82fd", "#fbea03", "#2a2440", "#9f82fd")
_GARNET = _harmonized("#f1dddf", "#e72d48", "#33191e", "#e72d48")


# 六个锚点：①④⑤⑥ 由用户定稿（`.superpowers/brainstorm/.../palettes.html`），
# ②③ 的底色按上面那条规则调和（其余四个色仍是定稿值）。
SKINS: tuple[Skin, ...] = (
    Skin("archive", "现有蓝", "#fbfcfe", "#ffffff", "#1a2233", "#e4e9f0",
         "#2f5d8a", "#eef4fb", None, _LIGHT),
    Skin("dark-pink", "炭黑甜酷粉", "#1a1a1d", "#242429", "#f0f0f3", "#35353d",
         "#e6397c", "#3b1b2b", None, _DARK),
    # ②③ 的底色是**两个色调和出来的**，四个锚点由 `_harmonized` 算，别手改。
    # ② 以极光紫为主掺蜜柚黄；③ 以雾粉桃为主掺石榴红。
    Skin("aurora", "极光紫蜜柚黄", _AURORA["paper"], _AURORA["surface"],
         "#2a2440", _AURORA["line"], "#9f82fd", _AURORA["accent_soft"],
         "#fbea03", _LIGHT),
    Skin("garnet", "石榴红雾粉桃", _GARNET["paper"], _GARNET["surface"],
         "#33191e", _GARNET["line"], "#e72d48", _GARNET["accent_soft"],
         None, _LIGHT),
    Skin("neon", "极光紫荧光绿", "#241c3a", "#2e2549", "#efeafb", "#3e3462",
         "#bcfe1a", "#3a3457", "#9f82fd", _DARK),
    Skin("mono", "黑皮", "#16171b", "#1f2025", "#e9ebef", "#2e3037",
         "#2f5d8a", "#23303f", None, _DARK),
)

SKIN_IDS: tuple[str, ...] = tuple(s.id for s in SKINS)
DEFAULT_SKIN = "archive"
_BY_ID = {s.id: s for s in SKINS}

# 展示顺序：用户定的 ①-⑥ 顺序，不是上面的定义顺序
_DISPLAY_ORDER = ("dark-pink", "aurora", "garnet", "neon", "archive", "mono")


# ----------------------------------------------------------------- 推导

def _derive(skin: Skin) -> dict[str, str]:
    paper, surface = skin.paper, skin.surface
    ink, line = skin.ink, skin.line
    accent, accent_soft = skin.accent, skin.accent_soft
    dark = skin.dark

    values = {
        "--paper": paper,
        "--surface": surface,
        "--ink": ink,
        "--line": line,
        "--accent": accent,
        "--accent-soft": accent_soft,

        "--muted": mix(ink, paper, 0.29),
        "--faint": mix(ink, paper, 0.50),
        "--ink-soft": mix(ink, paper, 0.16),
        "--faint-dim": mix(ink, paper, 0.62),
        "--line-soft": mix(line, surface, 0.45),
        "--line-strong": mix(line, ink, 0.12),
        # 侧栏那根分隔线。**比例是拿现有蓝反推的**：`#3d4753` 正是
        # `mix(#ffffff, #1a2233, .84)`（差 1-2 个色阶），不是随便挑的一档。
        # 一开始写成 .22 是个错——那样出来是近白的 `#cdced2`，跟现有蓝那根
        # 深色线完全两码事；现有蓝是硬编码的，错了也看不出来。
        "--divider": mix(surface, ink, 0.84),
        "--accent-mid": mix(accent, "#ffffff", 0.22 if dark else 0.14),
        "--accent-tint": mix(accent, paper, 0.98),
        "--accent-line": mix(accent_soft, accent, 0.10),
        "--accent-ring": _rgba(mix(accent, "#ffffff", 0.22 if dark else 0.14),
                               .28 if dark else .12),
        # 强调色当「文字」用：推到 4.5:1。浅色皮往墨推、深色皮往白推。
        "--accent-ink": _to_contrast(accent, paper, 4.5,
                                     ink if not dark else "#ffffff"),
    }

    if dark:
        values["--shadow"] = "0 1px 2px rgba(0, 0, 0, .40), 0 4px 12px rgba(0, 0, 0, .32)"
        values["--shadow-lift"] = "0 2px 6px rgba(0, 0, 0, .48), 0 12px 28px rgba(0, 0, 0, .42)"
        values["--scrim"] = "rgba(0, 0, 0, .62)"
        values["--terminal-void"] = mix(paper, "#000000", 0.45)
        values["--terminal-text"] = mix(values["--muted"], "#ffffff", 0.55)
        # 工作日志：从面往强调色兑。**方向别写反**——反了会得到一块饱和的
        # 强调色（④ 出来是 #a8e021 荧光绿，当卡片底太吵）。
        # 两档也必须拉开：早先用 0.30 / 0.05，出来只差 3 个色阶，分层白做。
        values["--journal-soft"] = mix(surface, accent, 0.14)
        values["--journal-line"] = mix(surface, accent, 0.42)
        values["--danger"] = "#d4736f"
        values["--danger-hover"] = "#e08a86"
    else:
        values["--shadow"] = f"0 1px 2px {_rgba(ink, .04)}, 0 4px 12px {_rgba(ink, .045)}"
        values["--shadow-lift"] = f"0 2px 6px {_rgba(ink, .07)}, 0 12px 28px {_rgba(ink, .07)}"
        values["--scrim"] = _rgba(ink, .38)
        values["--terminal-void"] = mix(ink, "#000000", 0.22)
        values["--terminal-text"] = mix(ink, "#ffffff", 0.78)
        # 工作日志卡片一律比面**亮**一档，所以底色的粉桃铺到页面上之后，
        # 卡片反而浮起来了。（③ 原来有一条「粉桃就是卡片底色本身」的特例，
        # 粉桃改当页面底色之后那条自然作废——两者不可能同时是同一个颜色。）
        values["--journal-soft"] = mix(accent, surface, 0.92)
        values["--journal-line"] = mix(accent, surface, 0.72)
        values["--danger"] = "#8c3b3b"
        values["--danger-hover"] = "#a24646"

    # 巡检金：撞色的第二个颜色优先（② 的黄、④ 的紫），否则由强调色与现有金混出来
    if skin.id == "aurora":
        gold = "#fbea03"
        deep = mix(gold, "#000000", 0.18)
    elif skin.id == "neon":
        gold = "#9f82fd"
        deep = mix(gold, "#ffffff", 0.10)
    elif dark:
        gold = accent
        deep = mix(accent, "#ffffff", 0.12)
    else:
        gold = mix(accent, "#c9a86a", 0.5)
        deep = mix(gold, "#000000", 0.16)
    values["--sweep-gold"] = gold
    values["--sweep-gold-deep"] = deep
    values["--sweep-gold-wash"] = mix(gold, surface, 0.86 if dark else 0.90)

    values["--on-accent"] = _pick_ink(accent)
    values["--on-danger"] = _pick_ink(values["--danger"])
    return values


# 「现有蓝」是「原样保留」：今天线上生效的 32 个值，一字不改。
#
# ⚠️ 其中 `--line-strong` / `--accent-line` 各自**合并了原来 2-3 个手挑的近色**
#    （见 spec 8.1，用户已确认），所以有 5 个选择器的 1px 边框动 1-2 个色阶。
ARCHIVE: dict[str, str] = {
    "--paper": "#fbfcfe", "--surface": "#ffffff", "--ink": "#1a2233",
    "--line": "#e4e9f0", "--accent": "#2f5d8a", "--accent-soft": "#eef4fb",
    "--muted": "#5b6b7f", "--faint": "#8a97a8",
    "--ink-soft": "#37445a", "--faint-dim": "#b9c3d0",
    "--line-soft": "#eff3f8", "--line-strong": "#d3dce7", "--divider": "#3d4753",
    "--accent-mid": "#3d7ab8", "--accent-tint": "#f7fafd",
    "--accent-line": "#dbe7f4", "--accent-ring": "rgba(61, 122, 184, .12)",
    "--accent-ink": "#2f5d8a", "--on-accent": "#ffffff", "--on-danger": "#ffffff",
    "--journal-soft": "#fdf1f5", "--journal-line": "#f2dbe4",
    "--terminal-void": "#1b2430", "--terminal-text": "#c9d4e0",
    "--scrim": "rgba(26, 34, 51, .38)",
    "--sweep-gold": "#c9a86a", "--sweep-gold-deep": "#b8934f",
    "--sweep-gold-wash": "#fdf8ee",
    "--danger": "#8c3b3b", "--danger-hover": "#a24646",
    "--shadow": "0 1px 2px rgba(26, 34, 51, .04), 0 4px 12px rgba(26, 34, 51, .045)",
    "--shadow-lift": "0 2px 6px rgba(26, 34, 51, .07), 0 12px 28px rgba(26, 34, 51, .07)",
}

# 输出顺序：先纸墨、再强调、再零件，读 CSS 的人好找
ORDER: tuple[str, ...] = (
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


def derive(skin_id: str) -> dict[str, str]:
    """取一套皮肤的 32 个变量。**认不出的 id 一律当现有蓝。**

    这个回落和 `kb.config._skin()` 是同一份语义：手改 `.env` 写错值不能让
    服务崩，界面上显示默认值，人一看就知道不对。
    """
    if skin_id == DEFAULT_SKIN:
        return dict(ARCHIVE)
    skin = _BY_ID.get(skin_id)
    if skin is None:
        return dict(ARCHIVE)
    return _derive(skin)


# ----------------------------------------------------------------- 渲染

def render_vars(skin_id: str, indent: str = "  ") -> str:
    """把 32 个变量渲染成 `--x: y;` 的行，用于 `:root` 里面。"""
    values = derive(skin_id)
    return "\n".join(f"{indent}{key}: {values[key]};" for key in ORDER)


def render_block(skin_id: str) -> str:
    """渲染一整块 `[data-skin="x"] { ... }`。现有蓝不走这里（它在 `:root`）。"""
    skin = _BY_ID[skin_id]
    tone = _DARK if skin.dark else _LIGHT
    return (
        f'[data-skin="{skin_id}"] {{   /* {skin.name} */\n'
        f"  color-scheme: {tone};\n"
        f"{render_vars(skin_id)}\n"
        f"}}\n"
    )


def blocks() -> str:
    """除现有蓝之外那五套，整段拼好——`scripts/derive_skins.py` 写进 CSS 用。"""
    return "".join(
        render_block(sid) for sid in SKIN_IDS if sid != DEFAULT_SKIN
    )


def options() -> tuple[dict[str, str], ...]:
    """给模板的：六行面板选项，顺序是用户定的 ①-⑥。"""
    return tuple(
        {"id": sid, "name": _BY_ID[sid].name, "dot": derive(sid)["--accent"]}
        for sid in _DISPLAY_ORDER
    )
