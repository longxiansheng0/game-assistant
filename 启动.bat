@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo 还没装依赖，先跑：
  echo    python -m venv .venv
  echo    .venv\Scripts\python -m pip install -r requirements.txt
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" run.py
