@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title WoWYap install addon
echo Installing / updating the WoWYap addon into WoW...
echo.
call "%~dp0Start.cmd" --install-addon %*
set "ERR=%ERRORLEVEL%"
echo.
if "%ERR%"=="0" (
  echo Done. In WoW: enable the addon if needed, then type /reload
) else (
  echo Install failed. Edit WoWYap.ini if your WoW path is non-default.
)
pause
exit /b %ERR%
