@echo off
setlocal
set "FATEGO_ROOT=%~dp0"
set "FATEGO_PYTHONW=%FATEGO_ROOT%.venv\Scripts\pythonw.exe"

if not exist "%FATEGO_PYTHONW%" (
  echo FateGo Agent is not installed yet.
  echo Follow the one-time setup steps in README.md, then run this file again.
  pause
  exit /b 1
)

start "" "%FATEGO_PYTHONW%" -m fgo_guardian.app --mode story
endlocal
