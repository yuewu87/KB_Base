---
name: KN_Base
description: 一个给 AI 用的个人知识库——管理界面
colors:
  # 主色
  archive-blue: "#2f5d8a"
  archive-blue-bright: "#3d7ab8"
  archive-blue-wash: "#eef4fb"
  archive-blue-tint: "#f7fafd"
  # 中性
  paper: "#fbfcfe"
  surface: "#ffffff"
  ink: "#1a2233"
  body-slate: "#37445a"
  muted-slate: "#5b6b7f"
  faint-slate: "#8a97a8"
  rule: "#e4e9f0"
  rule-soft: "#eff3f8"
  rule-strong: "#cfdeee"
  # 日志分类
  journal-pink: "#fdf1f5"
  journal-pink-rule: "#f2dbe4"
  sweep-gold: "#c9a86a"
  sweep-gold-deep: "#b8934f"
  sweep-gold-wash: "#fdf8ee"
  # 终端
  terminal-void: "#1b2430"
  terminal-text: "#c9d4e0"
  # 告警
  quit-red: "#8c3b3b"
  quit-red-hover: "#a24646"
  alert-red: "#aa3333"
typography:
  body:
    fontFamily: "Segoe UI, Microsoft YaHei, system-ui, -apple-system, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.65
  display:
    fontFamily: "Segoe UI, Microsoft YaHei, system-ui, -apple-system, sans-serif"
    fontSize: "21px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Segoe UI, Microsoft YaHei, system-ui, -apple-system, sans-serif"
    fontSize: "13.5px"
    fontWeight: 600
    lineHeight: 1.3
  label:
    fontFamily: "Segoe UI, Microsoft YaHei, system-ui, -apple-system, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    letterSpacing: "0.08em"
  mono:
    fontFamily: "Cascadia Mono, Consolas, Courier New, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.75
rounded:
  xs: "3px"
  sm: "5px"
  md: "6px"
  lg: "10px"
  xl: "14px"
  bubble: "12px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "9px"
  md: "15px"
  lg: "26px"
  xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.archive-blue}"
    rounded: "{rounded.sm}"
    padding: "6px 14px"
  button-primary-hover:
    backgroundColor: "{colors.archive-blue-wash}"
    textColor: "{colors.archive-blue}"
  button-secondary:
    backgroundColor: "{colors.archive-blue-tint}"
    textColor: "{colors.archive-blue}"
    rounded: "{rounded.pill}"
    padding: "6px 13px"
  button-secondary-hover:
    backgroundColor: "{colors.archive-blue-wash}"
    textColor: "{colors.archive-blue}"
  nav-item-active:
    backgroundColor: "{colors.archive-blue-wash}"
    textColor: "{colors.archive-blue}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "15px 17px"
  chip-active:
    backgroundColor: "{colors.archive-blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    padding: "5px 13px"
  input-search:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "11px 15px"
  input-search-focus:
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    # 全站唯一用 box-shadow 表达焦点的地方
  tab-vertical:
    backgroundColor: "{colors.rule-soft}"
    textColor: "{colors.faint-slate}"
    rounded: "{rounded.sm}"
    padding: "9px 3px"
  bubble-user:
    backgroundColor: "{colors.archive-blue-wash}"
    textColor: "{colors.body-slate}"
    rounded: "{rounded.bubble}"
    padding: "9px 12px"
  bubble-assistant:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.body-slate}"
    rounded: "{rounded.bubble}"
    padding: "9px 12px"
---

# Design System: KN_Base

## Overview

**Creative North Star: "安静的工作台"（The Quiet Workbench）**

> 这个名字是 **AI 起的描述性标签，不是用户定的**（2026-09-20 问过，用户答「不知道，只是想做得有设计感些，很酷的那种」）。它描述的是**现状**，不是目标。改它不用付代价。

这是一张每天开着的操作台，不是一件展示品。整个界面按**瑞士/国际主义**的底子建：严格的网格、大量留白、零装饰、颜色只用来承担信息。界面本身没有存在感——它退到内容后面，让人看见的是自己存下的那些结论。

材质上它模仿**纸与墨**：页面底不是纯白，而是极淡的蓝白（`#fbfcfe`），卡片是白纸，正文是墨色（`#1a2233`），分隔是极浅的灰蓝线。整个系统**不用纯黑、不用纯灰**——所有中性色都带一点蓝的色相。

**Key Characteristics:**

- 瑞士/编辑式极简：网格 + 留白 + 零装饰
- 纸墨质感：页面底是淡蓝白不是纯白；中性色全部带蓝色相，没有纯灰
- 颜色承担信息：蓝=可操作/当前，粉=工作日志，金=巡检报告，红=关机
- 阴影只做环境暗示，从不用来「抬起来」
- 反馈极轻：状态变化靠底色和边框微移，不靠位移、缩放或跳动

## Colors

整个色板是**一个主色 + 一群带蓝味的中性色**，另有三组只服务于特定页面的功能色。

### Primary

- **档案蓝**（`#2f5d8a`）：唯一的主色。**去饱和的藏蓝，不是亮蓝**——用户明确要求过「不要太亮」。用在：可点击文字、当前导航项、主按钮文字、流程链已走过的步骤、品牌方块。它是「这里可以动」的信号。
- **档案蓝·亮**（`#3d7ab8`）：只用于焦点环和 hover 态的边框。**从不做背景**。
- **档案蓝·洗**（`#eef4fb`）：当前项的底色。当前导航项、用户气泡、整理日志卡片都用它。**这是全站「被选中」的统一表达。**
- **档案蓝·淡**（`#f7fafd`）：比「洗」更淡一档，只用于次级按钮的底。

### Neutral

- **纸**（`#fbfcfe`）：页面底。**不是纯白**——它比卡片面更暗一点点，这才是卡片能「浮」起来的原因。
- **面**（`#ffffff`）：卡片、侧栏、输入框的底。
- **墨**（`#1a2233`）：正文与标题。**不是纯黑**，带蓝。
- **正文灰蓝**（`#37445a`）：卡片列表项、侧栏气泡的正文。比「墨」浅一档。
- **次要灰蓝**（`#5b6b7f`）：说明文字。对底色 5.9:1。
- **辅助灰蓝**（`#8a97a8`）：时间戳、提示。对底色 4.6:1——**已经贴到 4.5:1 的下限，不要再调淡**。
- **线**（`#e4e9f0`）：卡片与输入框的 1px 边框，分隔线。
- **浅线**（`#eff3f8`）：hover 底色、只读输入框的底。
- **深线**（`#cfdeee`）：次级按钮的边框。

### Tertiary（按页面分工，不混用）

- **日志粉**（`#fdf1f5` / 边框 `#f2dbe4`）：**只给「工作日志」的卡片**。这一页记的是过程，不是知识。
- **巡检金**（`#fdf8ee` / 边框 `#c9a86a` / 深 `#b8934f`）：**只给巡检报告卡**。金框是它在页面上唯一的样子；读过了也还显示，只是不再高亮。
- **终端黑**（`#1b2430` / 文字 `#c9d4e0`）：**只给「运行日志」的终端块**。
- **退出红**（`#8c3b3b` / hover `#a24646`）：**全站唯一的红底**，只给侧栏的「退出」。它跟别的入口不是一类东西：其余是「用功能」，这个是「关机」。用得比正红暗，与全站「不要太亮」的基调一致。

### Named Rules

**The One Accent Rule.** 主色只有档案蓝一个。除它之外的颜色都在表达**分类**（这一页是什么日志），不表达强调。想强调某样东西时，先问：是不是该换层级，而不是换颜色？

**The No-Pure-Gray Rule.** 中性色一律带蓝色相。`#808080` 这种纯灰在这个系统里不存在。

**The 4.5 Floor.** 文字色对底色不得低于 4.5:1。`--faint`（`#8a97a8`）就是下限，不要再往下调。

## Typography

**Display / Body Font:** `"Segoe UI", "Microsoft YaHei", system-ui, -apple-system, sans-serif`（系统栈）
**Mono Font:** `"Cascadia Mono", Consolas, "Courier New", monospace`（系统栈）

**Character:** 因为它是**本地离线工具**，字体一律走系统栈，**不引外链字体**——断网不能废，首屏也不能等。代价是没有独特的字形个性；设计感全靠排版的间距、层级和留白来给，不靠字体。

### Hierarchy

- **Display**（600，21px，1.3，字距 -0.01em）：页面标题（`h1`）。一页只有一个。
- **Title**（600，13.5px，1.3）：卡片标题（`h3`）、导航项文字。比 body 还小——**层级靠粗细和位置区分，不靠字号堆叠**。
- **Body**（400，14px，1.65）：正文与输入框。全局行高 1.65，对话气泡 1.7，卡片列表 13px。
- **Label**（600，12px，字距 0.08em，大写）：右侧栏的小标题（「最近一次整理」「箱子」）。**只此一处**用大写+宽字距，用来把侧栏和主区区分开。
- **Mono**（400，11.5–12px，1.75）：时间戳、会话 id、终端输出、行内 `code`。

### Named Rules

**The System-Stack Rule.** 不引外链字体。要加字形个性就得自托管一个字体文件，不允许 CDN——这是离线工具的硬约束。

**The Small-Title Rule.** 卡片标题（13.5px）比正文（14px）小。层级由字重、颜色、和它周围的空间给，不由字号给。不要为了「看起来更重要」把标题调大。

## Layout

**网格：** 外壳是 `flex`——固定宽侧栏 + 弹性主区。主区内容一律 `max-width: 880px`（`--reading`）：超过这个宽度读起来累。

**日志页的右栏：** `.chat-layout` 是 `grid-template-columns: minmax(0,1fr) 250px`，间距 30px，`align-items: start`。右栏 `position: sticky; top: 34px`。

**页签：** 竖排（`writing-mode: vertical-rl`），贴右栏左边缘向外伸。**钉在顶上（`justify-content: flex-start`），不居中**——居中的话它会跟着当前面板的高度上下跳（实测跳 129px）。

**间距节奏：** 卡片之间 11px（密），主区上下留白 34px / 64px（松），页面标题到内容 26px。**成组的东西贴紧，不同组之间拉开**——这个对比就是这套排版全部的节奏来源。

**密度：** 偏密。列表项 4px 上下、导航项 38px 高、卡片内边距 15px/17px。一屏要能扫过很多条。

**响应式：** 900px 以下 `chat-layout` 收成单列、右栏取消 sticky；720px 以下侧栏变 fixed 抽屉。**但产品定位是只面向桌面浏览器**，这两条是保底不是目标。

## Elevation & Depth

**系统是平的，深度靠色调分层。** 页面底（纸 `#fbfcfe`）比卡片面（`#ffffff`）暗一档，卡片因此不需要重阴影就能读成「浮在上面」。

阴影只做**环境暗示**，只在两处出现：

### Shadow Vocabulary

- **`--shadow`**（`0 1px 2px rgba(26,34,51,.04), 0 4px 12px rgba(26,34,51,.045)`）：卡片 hover 时。极淡，几乎只让卡片看起来更「近」了一点。
- **`--shadow-lift`**（`0 2px 6px rgba(26,34,51,.07), 0 12px 28px rgba(26,34,51,.07)`）：模态窗，以及窄屏下的侧栏抽屉。**唯一一次用双层阴影把东西真的抬起来。**

两个阴影**都用双层**（一层近、一层远），这是这套系统里阴影看起来「柔」而不是「脏」的原因。单层会立刻显得廉价。

### Named Rules

**The Flat-By-Default Rule.** 表面静止时是平的。阴影只作为**状态的回应**出现（hover、模态、抽屉），从不作为默认外观。

**The Two-Layer Rule.** 阴影一律两层。改阴影时两层一起改。

## Shapes

**圆角分四档，按元素大小递增**——小东西小圆角，大东西大圆角：

| 档 | 值 | 用在哪 |
|---|---|---|
| xs | 3px | 焦点环 |
| sm | 5px | 主按钮、页签（只有左侧有角） |
| md | 6px | 导航项、次级按钮、输入框 |
| lg | 10px | 卡片 |
| xl | 14px | 模态窗 |
| bubble | 12px | 对话气泡（助手气泡左上角是 4px，做出一个「小尾巴」） |
| pill | 999px | 标签、chip、次级按钮 |

**边框一律 1px。** 全站没有第二档线宽——唯一的例外是 `.chat-item.active` 的 `border-left: 2px`，那是「当前项」的标记，不是边框。

**圆与方的分工是语义的：** 胶囊（`999px`）属于**次级**动作（「测试连接」「我知道了」）；方角+实边框属于**主要**动作（「保存」「巡检一次」）。一眼分得出主次，不靠颜色深浅。

### Named Rules

**The Semantic Radius Rule.** 胶囊 = 次级动作，方角 = 主要动作。不要因为「好看」把主按钮改成胶囊。

## Components

### Buttons

- **Shape:** 主按钮方角（5px）+ 1px 实边框；次级按钮胶囊（999px）+ 1px 浅边框。
- **Primary**（`button.primary`：白底 + 档案蓝边框 + 档案蓝字，`6px 14px`）：方角、实边框。用于「保存」「巡检一次」「我知道了」。**白底**——它靠边框和字色立住，不靠填充。
- **Secondary**（`button.secondary` / `.sweep-reply button`：`--blue-tint` 底 + `#cfdeee` 边框 + 档案蓝字，`6px 13px`）：胶囊。用于「测试连接」「我知道了」这类附随动作。
- **实心按钮**（搜索、发送、投递：`--blue` 底 + 白字，`min-height 40–44px`）：**只在「主区里推进一件事」时用**。全站实心按钮不超过一只手数得过来。
- **Hover / Focus:** 底色变化（`--blue-tint` → `--blue-soft`）+ 边框转 `--blue-mid`，180ms。**不位移、不缩放。** 键盘焦点环是 `2px solid --blue-mid`，`outline-offset: 2px`——**不能只有鼠标能看见焦点**。
- **Disabled:** `opacity: .6` + `cursor: default`。**两颗按钮都要写**（`.primary` 和 `.secondary`），否则灰下去时光标还是小手。

> **这个系统里「像按钮」靠的是底色，不是边框。** 这是踩过两次坑的结论：「开始新会话」先用了近乎不可见的 `--blue-tint` 底，读成一行蓝字；改成白底+实蓝边，还是读成「描了框的链接」。最终用 `--blue-soft` 铺底才对。

### Cards / Containers

- **Corner Style:** 10px。
- **Background:** `--surface`（白）。**分类色只染特定页面的卡片**：整理日志 `--blue-soft`，工作日志 `--pink-soft`，巡检报告 `#fdf8ee`。
- **Shadow Strategy:** 静止时无阴影，只有 1px 边框。hover 时边框转深 + 上 `--shadow`。
- **Internal Padding:** `15px 17px`；卡片间距 `11px`（紧）。
- **入场:** 依次弹出——`card-in` 260ms，每个错开 40ms（第 6 个之后统一 200ms）。`prefers-reduced-motion` 时全部关掉。

### Inputs / Fields

- **Style:** 白底、1px `--line` 边框、10px 圆角（搜索/正文）或 6px（设置窗内）。字号 14px，行高 1.75（正文域）。
- **Focus:** 边框转 `--blue-mid` + `box-shadow: 0 0 0 3px rgba(61,122,184,.12)`——**一圈极淡的蓝色光晕**。这是全站唯一用 box-shadow 做焦点表达的地方。
- **Placeholder:** `--faint`（4.6:1，贴下限）。
- **Readonly:** `--line-soft` 底 + `--faint` 字（设置窗里的 vault 路径、端口）。

### Navigation

- **侧栏**（224px，白底，右侧 1px 线）：导航项 38px 高、6px 圆角、13.5px 字。当前项 `--blue-soft` 底 + 档案蓝字 + 600 字重。hover 是 `--line-soft` 底。
- **图标** 18px，默认 `--faint`，hover 和当前项转档案蓝。
- **折叠态**（60px）：只留图标，标签隐藏。
- **`icon` 宽度固定 18px、不缩**——否则折叠时图标会被挤扁。

### Chat Bubbles

- **Shape:** 12px；助手气泡左上角 4px 做出「小尾巴」。侧栏气泡 12.5px 字、`9px 12px` 内边距。
- **User:** `--blue-soft` 底 + `#dbe7f4` 边框，靠右。**Assistant:** `#f6f8fb` 底（侧栏）或白底（主区），靠左。
- **`white-space` 分两处：** 主区气泡必须 `pre-wrap`（用户输入的换行是内容），**侧栏气泡必须 `normal`**（模板里的缩进会被原样画出来，凭空多一行空白）。
- **Thinking:** `--faint` 字 + 1.4s 呼吸（opacity 1 → .55）。它要像「还没到的话」，不能让人以为这就是回答。

### Tags & Chips

- **Tag**（`11.5px`，胶囊，`#e9f0f9` 底 + `#dae6f3` 边框 + `#3c5878` 字）：只读的知识标签。
- **Chip**（`12.5px`，胶囊，白底 1px `--line`）：可点。选中时**整个翻转**成档案蓝底白字。

### Tabs

- **Style:** 竖排（`writing-mode: vertical-rl`），只有左侧有圆角（`5px 0 0 5px`），右侧无边（与面板相接）。`--line-soft` 底、`--faint` 字。
- **Active:** 白底 + 墨色字 + 左侧 2px 档案蓝内阴影。
- **必须钉顶**（`flex-start`）——居中会跟着面板高度跳。

## Do's and Don'ts

### Do:

- **Do** 用 `var(--token)`。全站颜色、圆角、时长都过变量；写死十六进制是这套系统最大的债（目前 `:root` 之外还有 40 处写死的色值）。
- **Do** 保持 1px 线宽。要更重的线，用颜色而不是宽度。
- **Do** 让文字对比度守 4.5:1。`--faint` 就是下限。
- **Do** 焦点环用 `:focus-visible`，`2px` 档案蓝·亮，`offset 2px`。
- **Do** 阴影用双层。
- **Do** 关掉动效时真的关掉——`prefers-reduced-motion` 那条规则要覆盖全部动画和过渡。

### Don't:

- **Don't** 用纯黑、纯白、纯灰。中性色一律带蓝的色相。
- **Don't** 把主色晾成亮蓝。档案蓝是去饱和的藏蓝，这是用户明确要求过的。
- **Don't** 为了强调换颜色。先考虑换层级或换空间。
- **Don't** 给静止的表面加阴影。
- **Don't** 把卡片标题调大。它比正文小是故意的。
- **Don't** 让主按钮变胶囊，或让次级按钮变方角。
- **Don't** 在同一个选择器上写两份规则。这个文件里已经栽过三次（`.chain-step.todo`、`.day`、`.sweep-reply button` / `button.secondary`）——特异度相同、后写的赢，改先写的那份完全没反应。
- **Don't** 让 `.overlay` 忘了写 `[hidden] { display: none }`。作者规则的 `display: flex` 稳压浏览器默认，遮罩层会把整页盖死。
