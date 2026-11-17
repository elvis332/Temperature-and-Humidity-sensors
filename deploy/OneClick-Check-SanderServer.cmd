@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0Install-SanderServer.ps1"
set RESULT=%ERRORLEVEL%
echo.
if not "%RESULT%"=="0" echo Preflight FAILED. Nothing installed.
if "%RESULT%"=="0" echo Preflight PASSED. No changes made.
pause
exit /b %RESULT%
