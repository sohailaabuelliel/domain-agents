@echo off
rem Stop Domain Agents (Windows). Same as: py stop.py
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 stop.py %*
) else (
  python stop.py %*
)
pause
