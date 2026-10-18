@echo off
rem Build the Windows release zip (see packaging\build.ps1 for options).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build.ps1" %*
exit /b %ERRORLEVEL%
