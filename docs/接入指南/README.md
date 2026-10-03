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

**第一步：让 `kb` 能调。** 指南里每条命令都用 `kb`，它是 `kb.bat` 包装出来的命令。
把 KN_Base 目录加进 PATH——**`kb.bat` 的注释里从头就是这么写的**：

```powershell
# 用户级 PATH，加一次就够；重开终端生效
[Environment]::SetEnvironmentVariable("PATH",
  [Environment]::GetEnvironmentVariable("PATH", "User") + ";<你 clone 的 KN_Base 目录>", "User")
```

**第二步：把 SKILL.md 拷到 agent 的 skills 目录**——同一份文件，两个地方：

```bash
# Claude Code
mkdir -p ~/.claude/skills/kn-record
cp "<KN_Base>/docs/接入指南/kn-record/SKILL.md" ~/.claude/skills/kn-record/SKILL.md

# DeepSeek Harness + Codex（共用这一份）
mkdir -p ~/.agents/skills/kn-record
cp "<KN_Base>/docs/接入指南/kn-record/SKILL.md" ~/.agents/skills/kn-record/SKILL.md
```

装在**用户级**而不是项目级，是因为用法是「**在别的项目里干活时，把东西记到这个知识库**」——项目级的话只有待在 `KN_Base` 目录下才生效，那就本末倒置了。

**为什么是两个目录、不是三个**：`~/.agents/skills/` 是 DSH 和 Codex **都认**的共享路径（DSH 按 rank 500 扫它，Codex 的用户级 skill 也在这里），所以它俩共用一份就够了。DSH 原先装在 `~/.dsh/skills/`，2026-09-28 挪过来合并的。

> ⚠️ **两份会漂移**（仓库源 + 两个安装位置）。同步顺序：**改仓库源 → 拷到两个 skills 目录 → 核对一致**。
> 核对用 `Get-FileHash` 比 SHA256，两个 Hash 必须完全相同——**这是「没漂移」的凭据**，别靠印象。

---

## 写这份指南踩到的两个坑

**① 中文输出在管道里是乱码。**

`kb` 在 Windows 上按 GBK 输出，agent 从管道读回来就是 `���գ�id=...`。**每条命令前面要加 `PYTHONIOENCODING=utf-8`**：

```bash
PYTHONIOENCODING=utf-8 kb push --content "..." --source 会话
```

没在 `kb` 里替调用方设，是因为那样**用户在自己的 cmd 窗口里会反过来看到乱码**（控制台是 GBK 的）。管道要 UTF-8、控制台要 GBK，两边掐着——所以让它待在调用侧。

**② 指南里的路径曾经全是死链。**

2026-09-28 之前，指南里每条命令都写成 `"E:/Study_Projects/KN_Base/kb.bat"`——**作者本机的绝对路径**。
别人 clone 到别处，13 条命令全是死链，报错还像「命令没找到」，看不出是路径问题。

现在改用 `kb`：把 KN_Base 目录加进 PATH 就有了（见上面「怎么装」的第一步），
**跟路径无关，谁 clone 到哪都一样**。

---

## 怎么算写得好

**机械的事归代码，判断的事才写进指南。** 这条项目的中心结论（见 [`04_踩坑与经验.md`](../04_踩坑与经验.md) 第 10 条）在这里同样适用：

- 「不要填类型/标签」——**指南里写**。这拦的是 agent 的**冲动**（它总想帮你归好类），不是一条能落成 `if` 的规则
- 「目录最多 4 层」——**代码里写**（`planning.MAX_DIR_LEVELS`）。数得出来，就不该指望指南
- 「`--revise` 后面不带路径和 `.md`」——**代码里写**。服务自己会处理

**判断标准：这条能不能落成一行 `if`？** 能，就别写进指南。
