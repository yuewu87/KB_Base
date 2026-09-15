@echo off
REM KN_Base knowledge-base CLI entry point (Windows).
REM
REM NOTE: this file is intentionally ASCII-only. cmd.exe reads .bat files
REM byte-by-byte using the OEM code page (GBK on zh-CN Windows), so UTF-8
REM Chinese in comments gets mis-decoded and splits the REM line -- the
REM remainder is then executed as a command. Keep it ASCII, or save as GBK.
REM
REM Usage: add this directory to PATH, then from any project directory:
REM     kb push --content "..."
setlocal
set "KN_ROOT=%~dp0"
set "PYTHONPATH=%KN_ROOT%src;%PYTHONPATH%"

if exist "D:\Conda_base\envs\kn_base\python.exe" (
  "D:\Conda_base\envs\kn_base\python.exe" -m kb.api.cli %*
) else (
  python -m kb.api.cli %*
)
endlocal
