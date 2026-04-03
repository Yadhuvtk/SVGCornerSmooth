@echo off
setlocal

set "ROOT=%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python launcher ^(`py`^) was not found in PATH.
  echo Install Python or add it to PATH, then run this file again.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm was not found in PATH.
  echo Install Node.js/npm or add it to PATH, then run this file again.
  pause
  exit /b 1
)

echo Starting SVGCornerSmooth backend...
start "SVGCornerSmooth Backend" cmd /k "cd /d ""%ROOT%"" && py api_server.py"

echo Starting SVGCornerSmooth frontend...
start "SVGCornerSmooth Frontend" cmd /k "cd /d ""%ROOT%frontend"" && npm run dev"

echo.
echo Started both services:
echo   Backend  : http://127.0.0.1:5050
echo   Frontend : http://localhost:5173
echo.
echo Close the two opened terminal windows to stop both services.

exit /b 0
