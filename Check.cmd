@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title WoWYap check
call "%~dp0Start.cmd" --check %*
set "ERR=%ERRORLEVEL%"
echo.
pause
exit /b %ERR%
