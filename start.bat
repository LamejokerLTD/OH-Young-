@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Installing Local Whisper for first use...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
  if errorlevel 1 (
    echo Installation failed. Please run install.bat to retry.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" launcher.py
if errorlevel 1 pause
