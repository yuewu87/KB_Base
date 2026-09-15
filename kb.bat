@echo off
REM KN_Base 知识库命令行入口（Windows）。
REM 把本目录加进 PATH 后，在任意项目目录里敲 `kb push --content "..."` 即可。
setlocal
set "KN_ROOT=%~dp0"
set "PYTHONPATH=%KN_ROOT%src;%PYTHONPATH%"

REM 用 conda 环境里的 python；没有就退回 PATH 上的 python
if exist "D:\Conda_base\envs\kn_base\python.exe" (
  "D:\Conda_base\envs\kn_base\python.exe" -m kb.api.cli %*
) else (
  python -m kb.api.cli %*
)
endlocal
