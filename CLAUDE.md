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

- 使用 **conda** 管理环境，环境名统一为 `kn_base`。
- **conda 环境内一律使用 `pip` 安装依赖**，不用 `conda install`（避免与 pip 混装产生依赖冲突）。
- 环境**尚未创建**。方案定稿后按以下方式创建：

  ```bash
  conda create -n kn_base python=3.11 -y   # 版本号以方案定稿为准
  conda activate kn_base
  pip install -r requirements.txt
  ```

- 依赖统一记录在项目根目录的 `requirements.txt`。
- 运行任何 Python 命令前先确认已激活环境：`conda activate kn_base`。

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

## 待补充（方案定稿后回填）

- [ ] 技术选型：文档解析、切分策略、embedding 模型、向量库、检索与生成链路
- [ ] 目录结构与模块划分
- [ ] 常用命令（构建、运行、测试、跑单个测试）
- [ ] 配置文件与环境变量清单
