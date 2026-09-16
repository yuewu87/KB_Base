# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目状态

**知识库项目，技术方案尚未确定。** 当前仓库只有约定与脚手架，没有业务代码。
在方案定稿前，不要假设技术栈（向量库、LLM SDK、Web 框架等均未选型）。
选型确定后，需要回到本文件补充「架构」和「常用命令」两节。

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
```

测试配置在 `pyproject.toml`（`pythonpath = ["src"]`），因此**无需安装包**即可 `from kb.config import ...`。

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

代理地址在 CLAUDE.md 中**不写死到代码或脚本**里；运行时需要的场景通过环境变量传入：

```bash
export http_proxy=http://127.0.0.1:5408
export https_proxy=http://127.0.0.1:5408
```

## Git 约定

- 本地仓库，默认分支 `main`。
- 提交信息使用中文，格式：`<类型>: <简述>`，类型取 `feat` / `fix` / `docs` / `refactor` / `chore` / `test`。
- **提交前先 `/code-review` 或自查 diff**；不要提交 `data/` 下的原始数据与向量库产物（已在 `.gitignore` 中排除）。
- 除非用户明确要求，不要执行 `git push` 或创建 PR。

## 工作方式约定

- 新增功能、改动行为前先走 `superpowers:brainstorming` 明确需求，再进入实现。
- 涉及 3 个以上步骤的任务，先写计划再动手。

## 相关文档

| 文档 | 作用 |
|---|---|
| `README.md` | 系统最终形态的架构总览 |
| `docs/03_问题记录.md` | **全部设计决策与理由**，设计状态的唯一真源 |
| `docs/superpowers/plans/` | 实施计划 |

**过程规矩：没有讨论出结果的问题，不先动手实现。** 新问题记入 `docs/03_问题记录.md`，格式为「问题 → 结论」，未决的标 🔴。

## 待补充（方案定稿后回填）

- [ ] 技术选型：文档解析、切分策略、embedding 模型、向量库、检索与生成链路（阶段二 RAG）
