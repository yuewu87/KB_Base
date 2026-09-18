@echo off
REM KN_Base Web UI launcher (Windows).
REM
REM Double-click this file: it starts the knowledge-base service if it is not
REM already running, then opens the web UI in your default browser.
REM
REM Equivalent command line: kb web
REM
REM NOTE: this file is intentionally ASCII-only. cmd.exe reads .bat files
REM byte-by-byte using the OEM code page (GBK on zh-CN Windows), so UTF-8
REM Chinese in comments gets mis-decoded and splits the REM line -- the
REM remainder is then executed as a command. Keep it ASCII. See CLAUDE.md.
setlocal
set "KN_ROOT=%~dp0"
set "PYTHONPATH=%KN_ROOT%src;%PYTHONPATH%"

if exist "D:\Conda_base\envs\kn_base\python.exe" (
  "D:\Conda_base\envs\kn_base\python.exe" -m kb.api.cli web
) else (
  python -m kb.api.cli web
)

set "KN_RC=%ERRORLEVEL%"

REM Keep the window on failure. A double-clicked console window closes the
REM instant the command exits, so the error would be gone before you read it.
if not "%KN_RC%"=="0" pause

REM endlocal resets ERRORLEVEL to 0 -- capture it first (above), exit with it.
endlocal & exit /b %KN_RC%
