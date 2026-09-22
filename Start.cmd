@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title WoWYap

set "QUIET=0"
echo %*| findstr /I /C:"--check" /C:"--install-addon" >nul && set "QUIET=1"

if "%QUIET%"=="0" (
  echo.
  echo  WoWYap
  echo  ------------
  echo  Syncs the WoW addon and starts hold-to-yap.
  echo  Leave this window open while you play. Ctrl+C stops it.
  echo.
)

rem Packaged build (from GitHub Actions artifact)
if exist "%~dp0WoWYap.exe" (
  "%~dp0WoWYap.exe" %*
  set "ERR=%ERRORLEVEL%"
  goto :done
)

rem Source checkout — no PowerShell required
set "HELPER=%~dp0helper"
if not exist "%HELPER%\gamepadspeak_helper.py" (
  echo Could not find WoWYap.exe or helper\gamepadspeak_helper.py
  echo Put Start.cmd next to the helper build, or run it from the repo root.
  set "ERR=1"
  goto :done
)

where uv >nul 2>&1
if %ERRORLEVEL%==0 (
  pushd "%HELPER%"
  uv run --quiet python gamepadspeak_helper.py %*
  set "ERR=%ERRORLEVEL%"
  popd
  goto :done
)

if not exist "%HELPER%\.venv\Scripts\python.exe" (
  echo First run: creating a local Python environment...
  where py >nul 2>&1
  if %ERRORLEVEL%==0 (
    py -3.12 -m venv "%HELPER%\.venv" 2>nul || py -3.13 -m venv "%HELPER%\.venv" 2>nul || py -3 -m venv "%HELPER%\.venv"
  ) else (
    python -m venv "%HELPER%\.venv"
  )
  if not exist "%HELPER%\.venv\Scripts\python.exe" (
    echo Python 3.12+ was not found. Install it from https://www.python.org/downloads/
    echo Or download the Windows build from GitHub Actions ^(no Python needed^).
    set "ERR=1"
    goto :done
  )
  "%HELPER%\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  "%HELPER%\.venv\Scripts\python.exe" -m pip install --quiet "%HELPER%"
)

"%HELPER%\.venv\Scripts\python.exe" "%HELPER%\gamepadspeak_helper.py" %*
set "ERR=%ERRORLEVEL%"

:done
if "%QUIET%"=="1" exit /b %ERR%
echo.
if not "%ERR%"=="0" (
  echo Helper exited with an error ^(%ERR%^).
  echo If WoW is not in the default folder, edit WoWYap.ini next to this file.
  pause
  exit /b %ERR%
)
echo Helper stopped.
pause
exit /b 0
