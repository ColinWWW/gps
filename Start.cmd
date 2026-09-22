@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title WoWYap
set "QUIET=0"
for %%A in (%*) do if /I "%%~A"=="--check" set "QUIET=1"
for %%A in (%*) do if /I "%%~A"=="--install-addon" set "QUIET=1"
if "%QUIET%"=="0" (
  echo.
  echo WoWYap - leave this window open while you play. Ctrl+C stops it.
)
if exist "%~dp0WoWYap.exe" goto :exe
set "HELPER=%~dp0helper"
if not exist "%HELPER%\gamepadspeak_helper.py" goto :missing
where uv >nul 2>&1
if not errorlevel 1 goto :uv
if exist "%HELPER%\.venv\Scripts\python.exe" goto :dependencies
where py >nul 2>&1
if errorlevel 1 goto :plain_python
py -3.12 -m venv "%HELPER%\.venv" 2>nul || py -3.13 -m venv "%HELPER%\.venv" 2>nul || py -3 -m venv "%HELPER%\.venv"
goto :install
:plain_python
python -m venv "%HELPER%\.venv"
:install
if not exist "%HELPER%\.venv\Scripts\python.exe" goto :missing_python
:dependencies
if exist "%HELPER%\.venv\.wowyap-deps-ready" goto :python
"%HELPER%\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
if errorlevel 1 goto :failed
"%HELPER%\.venv\Scripts\python.exe" -m pip install --quiet "%HELPER%"
if errorlevel 1 goto :failed
type nul > "%HELPER%\.venv\.wowyap-deps-ready"
:python
"%HELPER%\.venv\Scripts\python.exe" "%HELPER%\gamepadspeak_helper.py" %*
set "ERR=%ERRORLEVEL%"
goto :done
:exe
"%~dp0WoWYap.exe" %*
set "ERR=%ERRORLEVEL%"
goto :done
:uv
pushd "%HELPER%"
uv run --quiet python gamepadspeak_helper.py %*
set "ERR=%ERRORLEVEL%"
popd
goto :done
:missing
echo Could not find WoWYap.exe or helper\gamepadspeak_helper.py next to Start.cmd.
set "ERR=1"
goto :done
:missing_python
echo Install Python 3.12+ or download the Windows build from GitHub Actions.
set "ERR=1"
goto :done
:failed
set "ERR=%ERRORLEVEL%"
:done
if "%QUIET%"=="1" exit /b %ERR%
if not "%ERR%"=="0" (
  echo Helper exited with error %ERR%. Check the output above and WoWYap.ini.
) else (
  echo Helper stopped.
)
pause
exit /b %ERR%
