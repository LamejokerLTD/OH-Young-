@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Local Whisper Desktop cannot start.
  echo Missing Python environment: .venv\Scripts\python.exe
  echo Please run install.bat first.
  echo.
  pause
  exit /b 1
)

if not exist "desktop_launcher.py" (
  echo.
  echo Local Whisper Desktop cannot start.
  echo Missing launcher: desktop_launcher.py
  echo.
  pause
  exit /b 1
)

if "%LOCAL_WHISPER_DESKTOP_DEBUG%"=="1" (
  ".venv\Scripts\python.exe" "desktop_launcher.py"
  if errorlevel 1 (
    pause
    exit /b 1
  )
  exit /b 0
)

if not exist ".venv\Scripts\pythonw.exe" (
  echo.
  echo Local Whisper Desktop cannot start.
  echo Missing windowed Python: .venv\Scripts\pythonw.exe
  echo Please run install.bat first.
  echo.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "desktop_launcher.py"
