# 接入指南

**给会话层的 AI 看的说明书**——它怎么知道该记什么、什么时候叫服务整理、怎么改已有笔记。

这是 [Q30②](../03_问题记录.md) 那份「挂着的文档」。它同时是 [Q62](../03_问题记录.md)「整理触发条件写在哪」的答案：**触发条件写在会话层能读到的地方**，不然只有人知道，机器不知道。

---

## 现在有什么

| 指南 | 给谁 | 状态 |
|---|---|---|
| [`kn-record/SKILL.md`](kn-record/SKILL.md) | **Claude Code** | ✅ 可用 |
| 同一份文件 | **DeepSeek Harness** + **Codex** | DSH ✅ 实测；Codex ⚠️ 未实测 |

三家读的是**同一套格式**（`<名字>/SKILL.md` + YAML frontmatter），所以**不需要单独的 `AGENTS.md` 版**——Codex 直接吃这份 `SKILL.md`。

---

## 怎么装

**仓库里那份是源**，改它；装的时候拷到两个 agent 的 skills 目录——**同一份文件，两个地方**：

```bash
# Claude Code
mkdir -p "C:/Users/wuyeu/.claude/skills/kn-record"
cp "E:/Study_Projects/KN_Base/docs/接入指南/kn-record/SKILL.md" \
   "C:/Users/wuyeu/.claude/skills/kn-record/SKILL.md"

# DeepSeek Harness + Codex（共用这一份）
mkdir -p "C:/Users/wuyeu/.agents/skills/kn-record"
cp "E:/Study_Projects/KN_Base/docs/接入指南/kn-record/SKILL.md" \
   "C:/Users/wuyeu/.agents/skills/kn-record/SKILL.md"
```

装在**用户级**而不是项目级，是因为用法是「**在别的项目里干活时，把东西记到这个知识库**」——项目级的话只有待在 `KN_Base` 目录下才生效，那就本末倒置了。

**为什么是两个目录、不是三个**：`~/.agents/skills/` 是 DSH 和 Codex **都认**的共享路径（DSH 按 rank 500 扫它，Codex 的用户级 skill 也在这里），所以它俩共用一份就够了。DSH 原先装在 `~/.dsh/skills/`，2026-09-28 挪过来合并的。

> ⚠️ **两份会漂移**（仓库源 + 两个安装位置）。同步顺序固定成三步：**改仓库源 → 拷到两个 skills 目录 → 核对一致**。
> 核对用 `Get-FileHash` 比 SHA256，两个 Hash 必须完全相同——**这是「没漂移」的凭据**，别靠印象。

---

## 写这份指南踩到的两个坑

**① 中文输出在管道里是乱码。**

`kb.bat` 在 Windows 上按 GBK 输出，agent 从管道读回来就是 `���գ�id=...`。**每条命令前面要加 `PYTHONIOENCODING=utf-8`**：

```bash
PYTHONIOENCODING=utf-8 "E:/Study_Projects/KN_Base/kb.bat" push --content "..." --source 会话
```

没写进 `kb.bat` 里，是因为那样**用户在自己的 cmd 窗口里会反过来看到乱码**（控制台是 GBK 的）。管道要 UTF-8、控制台要 GBK，两边掐着——所以让它待在调用侧。

**② `kb` 不在 PATH 里。**

指南里一律写完整路径 `"E:/Study_Projects/KN_Base/kb.bat"`。`kb.bat` 自己用 `%~dp0` 定位工程根，所以**从哪个目录调都行**。

---

## 怎么算写得好

**机械的事归代码，判断的事才写进指南。** 这条项目的中心结论（见 [`04_踩坑与经验.md`](../04_踩坑与经验.md) 第 10 条）在这里同样适用：

- 「不要填类型/标签」——**指南里写**。这拦的是 agent 的**冲动**（它总想帮你归好类），不是一条能落成 `if` 的规则
- 「目录最多 4 层」——**代码里写**（`planning.MAX_DIR_LEVELS`）。数得出来，就不该指望指南
- 「`--revise` 后面不带路径和 `.md`」——**代码里写**。服务自己会处理

**判断标准：这条能不能落成一行 `if`？** 能，就别写进指南。
