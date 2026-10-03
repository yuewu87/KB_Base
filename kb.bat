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

REM Which Python: set KB_PYTHON to yours (e.g. the conda env's python.exe);
REM otherwise the "python" on PATH is used. Either way the deps must be
REM installed -- see README "install". Keep this file ASCII (CLAUDE.md).
if defined KB_PYTHON (
  "%KB_PYTHON%" -m kb.api.cli %*
) else (
  python -m kb.api.cli %*
)

REM endlocal resets ERRORLEVEL to 0, so without this every failure (empty
REM content, a drop target that does not exist) still looks like success to
REM whoever called us. Capture the code first, then exit with it.
set "KN_RC=%ERRORLEVEL%"
endlocal & exit /b %KN_RC%
