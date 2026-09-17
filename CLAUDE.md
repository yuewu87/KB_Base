# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目状态

**已实现并跑通，测试全绿。** 骨架：投递（CLI + Web）→ 整理（规划/校验/审核/落盘）
→ 落 vault + 一个 git commit → 报告；`--revise` 改已有笔记；每周巡检收拾标签与目录；
Web UI 六个入口（记一条 / ai对话 / 整理日志 / 工作日志 / 运行日志 / 巡检）。

- **细节以 `docs/` 为准**，别在本文件里复述设计——`README.md` 也只是入口
- **还缺什么、明确不做什么**，见 `docs/01_架构.md` 第十四节

## 语言约定

- 与用户交流、写文档、写代码注释、写提交信息，**一律使用中文**。
- 代码标识符（变量、函数、类名）保持英文，符合各自语言惯例。

## Python 环境约定

- 使用 **conda** 管理环境，环境名 `kn_base`，**Python 3.11**。
- 本机环境路径：`D:\Conda_base\envs\kn_base`。
- **conda 环境内一律使用 `pip` 安装依赖**，不用 `conda install`（避免与 pip 混装产生依赖冲突）。
- 依赖记录在项目根目录 `requirements.txt`（**版本未锁**）。`requirements.lock.txt` 是 `pip freeze` 的本机产物，**不入库**。

创建与安装：

```bash
conda create -n kn_base python=3.11 -y
conda activate kn_base
pip install -r requirements.txt
```

**在脚本或工具里调用环境内 Python 的两种可靠方式**（⚠️ 本机 `conda run` 会报内部错误，**不要用**）：

```bash
# 方式一：直接绝对路径（最省事，推荐）
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -v

# 方式二：先 source 再 activate
source "$(conda info --base)/etc/profile.d/conda.sh" && conda activate kn_base && pytest -v
```

## 平台陷阱

**调 `subprocess.run` 一律显式写 `encoding="utf-8", errors="replace"`，不要只写 `text=True`。**

Windows 下 `text=True` 按本地编码（GBK）解码，而 git 的输出（中文 commit message、含中文的路径）是 UTF-8。更糟的是解码异常抛在**子进程的读取线程**里，主流程只看到 `stdout=None`，症状与原因隔了十万八千里，极难排查。项目里所有调 git 的地方都遵守这条。

**解析 git 输出的路径时还要加 `-c core.quotepath=false`。** 否则 git 把中文路径转成八进制转义（`"20_\347\237\245\350\257\206/..."`），按字面比对全部对不上。

**`git add` 只要有一个 pathspec 不匹配就整体放弃**，一个文件都进不去。所以给 `git add` 传路径前必须先过滤掉 git 处理不了的（既不在磁盘上、也没被跟踪的）。

**`.bat` 文件必须写成纯 ASCII。** `cmd.exe` 按系统 OEM 代码页（中文 Windows 上是 GBK）逐字节读批处理文件，UTF-8 的中文注释会被误解码、`REM` 行提前断裂，**后半截当成命令执行**。要保留中文注释就得把文件存成 GBK——但那样用 UTF-8 编辑器一改又坏，所以本项目一律 ASCII，中文说明放文档里。

## 常用命令

```bash
# 跑全部测试
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -v

# 跑单个测试文件 / 单个测试
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_config.py -v
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_config.py::test_reads_required_values -v

# 风格检查
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts

# 真跑一遍（服务自己会拉起来）
PYTHONIOENCODING=utf-8 ./kb.bat push --content "..." --source 会话
PYTHONIOENCODING=utf-8 ./kb.bat organize
PYTHONIOENCODING=utf-8 ./kb.bat sweep
```

测试配置在 `pyproject.toml`（`pythonpath = ["src"]`），因此**无需安装包**即可 `from kb.config import ...`。

> **`pythonpath` 只对 pytest 生效。** 用 `python -c` 跑脚本时要自己加 `PYTHONPATH=src`。

> ⚠️ **改了 `src/` 下的代码，一定先 `./kb.bat stop`。** 服务是常驻进程，不停的话它仍执行
> 旧逻辑——**而且看起来一切正常**，能白排查半天。这个坑反复踩。

> ⚠️ **`PYTHONIOENCODING=utf-8` 不能省。** Windows 上 `kb.bat` 按 GBK 输出，从管道读回来
> 全是乱码（`���գ�id=...`）。**没写进 `kb.bat`**，是因为那样用户在自己的 cmd 窗口里会反过来
> 看到乱码——管道要 UTF-8、控制台要 GBK，只能待在调用侧。

## 网络与代理

本地代理为 `http://127.0.0.1:5408`，**已全局配置**：

- pip：`C:\Users\wuyeu\AppData\Roaming\pip\pip.ini` 中的 `global.proxy`
- git：`git config --global http.proxy` / `https.proxy`

因此 `pip install` 和 `git clone/pull` 会自动走代理，无需手动设置。
若代理未启动，上述命令会因连接失败而挂起或报错，此时临时关闭代理：

```bash
# 临时禁用（针对性排查用）
pip install <pkg> --proxy ""
git -c http.proxy= -c https.proxy= clone <url>

# 彻底移除全局配置
pip config unset global.proxy
git config --global --unset http.proxy
git config --global --unset https.proxy
```

代理地址**不要写死到代码或脚本里**；运行时需要的场景通过环境变量传入：

```bash
export http_proxy=http://127.0.0.1:5408
export https_proxy=http://127.0.0.1:5408
```

## Git 约定

- 本地仓库，默认分支 `main`。
- 提交信息使用中文，格式：`<类型>: <简述>`，类型取 `feat` / `fix` / `docs` / `refactor` / `chore` / `test`。
- **提交前先 `/code-review` 或自查 diff**；不要提交 `data/` 下的任何东西——运行日志、会话历史、缓存全在里头。**仓库是 public 的，会话历史进去就是公开发布。**
- 除非用户明确要求，不要执行 `git push` 或创建 PR。

## 工作方式约定

- 新增功能、改动行为前先走 `superpowers:brainstorming` 明确需求，再进入实现。
- 涉及 3 个以上步骤的任务，先写计划再动手。
- **机械约束归代码，判断题归模型。** 写一条规则之前先问：**这条能不能落成一行 `if`？**
  能，就别写进提示词或文档里。同一个坑踩了三次才总结出来（见 `docs/04_踩坑与经验.md` 第 10 条），
  已经落地的两条是「兜底分类名」和「目录最多 4 层」。
- **设计状态的唯一真源是 `docs/03_问题记录.md`。** 结论变了改那里，别另开文档；
  **作废的条目直接删掉**，不留存根。

## 相关文档

**先看这张表再动手：**

| 文档 | 作用 |
|---|---|
| `docs/01_架构.md` | **目标架构**——做成什么样。只写「是什么」 |
| `docs/02_需求.md` | **要什么** |
| `docs/03_问题记录.md` | **全部设计决策与理由**——设计状态的唯一真源，只写「为什么」 |
| `docs/04_踩坑与经验.md` | **踩过什么、学到了什么**——动手前扫一眼，多半能少踩一次 |
| `docs/接入指南/` | **会话层 AI 怎么用这个库**——装成 skill 用的，不是给人读的说明 |
| `docs/superpowers/plans/` | 实施计划 |
| `README.md` | **入口**——背景 / 架构 / 使用方式。适合先读；细节以 `01_架构.md` 为准 |

**过程规矩：没有讨论出结果的问题，不先动手实现。** 新问题记入 `docs/03_问题记录.md`，格式为「问题 → 结论」，未决的标 🔴。

## 两处容易忘的

**① skill 有两份，会漂移。**

`docs/接入指南/kn-record/SKILL.md` 是**源**，装在 `~/.claude/skills/kn-record/SKILL.md`。
改了源，记得拷过去：

```bash
cp "E:/Study_Projects/KN_Base/docs/接入指南/kn-record/SKILL.md" \
   "C:/Users/wuyeu/.claude/skills/kn-record/SKILL.md"
```

**② vault 是另一个仓库，且刻意没有远端。**

知识数据在 `E:\KB_Library`，独立 git 管理。**不要给它配 GitHub 远端**——2026-09-15 误推过一次，
已撤回。推之前先确认两件事：**推到哪个仓库**、**谁能看见**。
