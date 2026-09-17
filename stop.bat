@echo off
REM KN_Base service stopper (Windows).
REM
REM Double-click to stop the knowledge-base service. Equivalent to: kb stop
REM
REM Why you would want this: the service is a long-running process that keeps
REM running the code it was started with. After editing anything under src/,
REM stop it -- the next kb command starts a fresh one with the current code.
REM The web UI can do it too (sidebar, red button at the bottom).
REM
REM NOTE: this file is intentionally ASCII-only. cmd.exe reads .bat files
REM byte-by-byte using the OEM code page (GBK on zh-CN Windows), so UTF-8
REM Chinese in comments gets mis-decoded and splits the REM line -- the
REM remainder is then executed as a command. Keep it ASCII. See CLAUDE.md.
setlocal
set "KN_ROOT=%~dp0"
set "PYTHONPATH=%KN_ROOT%src;%PYTHONPATH%"

if exist "D:\Conda_base\envs\kn_base\python.exe" (
  "D:\Conda_base\envs\kn_base\python.exe" -m kb.api.cli stop
) else (
  python -m kb.api.cli stop
)

REM Always pause. Unlike web.bat (which opens a browser, so you get visible
REM feedback either way), this one only prints a line -- double-clicked from
REM Explorer the window would close before you could read it. Scripts should
REM call the kb CLI directly instead.
pause
endlocal
