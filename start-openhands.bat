@echo off
setlocal enabledelayedexpansion

REM ===== 强制切到 bat 所在目录（关键！）=====
cd /d "%~dp0"

echo ==========================================
echo Starting OpenHands...
echo Host workspace directory:
echo %cd%
echo This will be mounted to /workspace
echo ==========================================

set CONTAINER_NAME=openhands-app
set IMAGE=docker.openhands.dev/openhands/openhands:latest
set PORT=3000

echo.
echo [1/5] Removing old container (if exists)...
docker rm -f %CONTAINER_NAME% >nul 2>&1

echo.
echo [2/5] Pulling latest image...
docker pull %IMAGE%
if errorlevel 1 goto :error

echo.
echo [3/5] Starting container...
docker run -d ^
  -v //var/run/docker.sock:/var/run/docker.sock ^
  -v "%USERPROFILE%\.openhands:/.openhands" ^
  -v "%cd%:/workspace" ^
  -p %PORT%:3000 ^
  --name %CONTAINER_NAME% ^
  %IMAGE%

if errorlevel 1 goto :error

echo.
echo [4/5] Waiting for server to boot...
timeout /t 3 >nul

echo.
echo [5/5] Opening browser...
start "" "http://localhost:%PORT%"

echo.
echo ==========================================
echo OpenHands started successfully.
echo In WebUI, open /workspace to access repo.
echo ==========================================

exit /b 0


:error
echo.
echo ==========================================
echo ERROR: Failed to start OpenHands.
echo.
echo Possible causes:
echo - Docker Desktop not running
echo - Port 3000 already in use
echo - Drive not shared in Docker settings
echo.
echo Try:
echo docker ps
echo docker logs %CONTAINER_NAME%
echo ==========================================
pause
exit /b 1