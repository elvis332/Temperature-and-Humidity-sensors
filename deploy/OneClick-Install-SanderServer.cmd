@echo off
setlocal
echo SANDER ZIGBEE SERVER INSTALLATION
echo Requires approved deployment-approval.json, configured coordinator/MQTT and elevated IT permissions.
echo Does not modify EMS SQL or Zigbee pairing.
echo.
powershell.exe -NoProfile -File "%~dp0Install-SanderServer.ps1" -Install
set RESULT=%ERRORLEVEL%
echo.
if not "%RESULT%"=="0" echo Installation did not complete. Inspect messages and audit backups.
if "%RESULT%"=="0" echo Installation completed. EMS staging registration remains a separate Valen approval step.
pause
exit /b %RESULT%
