@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 먼저 build_windows.bat 를 실행하거나 아래 명령으로 라이브러리를 설치하세요:
  echo   py -3 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
