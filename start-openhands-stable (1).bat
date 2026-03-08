@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "WORKSPACE_PATH=%SCRIPT_DIR%"
set "WORKSPACE_PATH_UNIX=%WORKSPACE_PATH:\=/%"
set "WORKSPACE_PATH_DOCKER=/run/desktop/mnt/host/c/%WORKSPACE_PATH_UNIX:~3%"
set "OPENHANDS_HOME=%USERPROFILE%\.openhands"
set "OPENHANDS_VERSION=1.4.0"
set "APP_IMAGE=docker.openhands.dev/openhands/openhands:%OPENHANDS_VERSION%"
set "RUNTIME_IMAGE=docker.openhands.dev/openhands/runtime:%OPENHANDS_VERSION%-nikolaik"

echo [INFO] Workspace: %WORKSPACE_PATH%
echo [INFO] Sandbox mount: %WORKSPACE_PATH_DOCKER%:/workspace/project:rw

if not exist "%WORKSPACE_PATH%" (
  echo [ERROR] Workspace path does not exist: %WORKSPACE_PATH%
  goto :fail
)

where docker >nul 2>nul
if errorlevel 1 (
  echo [ERROR] docker.exe not found. Install Docker Desktop first.
  goto :fail
)

docker info >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Docker Desktop is not running or the current user cannot access Docker.
  echo [ERROR] Start Docker Desktop, wait until it shows "Engine running", then try again.
  goto :fail
)

if not exist "%OPENHANDS_HOME%" mkdir "%OPENHANDS_HOME%"

echo [INFO] Starting OpenHands on http://localhost:3000
docker run -it --rm ^
  --pull=always ^
  -e "SANDBOX_RUNTIME_CONTAINER_IMAGE=%RUNTIME_IMAGE%" ^
  -e "LOG_ALL_EVENTS=true" ^
  -v /var/run/docker.sock:/var/run/docker.sock ^
  -v "%OPENHANDS_HOME%:/.openhands" ^
  -e "SANDBOX_VOLUMES=%WORKSPACE_PATH_DOCKER%:/workspace/project:rw" ^
  -p 3000:3000 ^
  --add-host host.docker.internal:host-gateway ^
  --name openhands-app ^
  %APP_IMAGE%

if errorlevel 1 (
  echo [ERROR] OpenHands container failed to start.
  echo [ERROR] Common causes: Docker Desktop not running, image pull blocked, or port 3000 already in use.
  goto :fail
)

endlocal
exit /b 0

:fail
echo.
pause
endlocal
exit /b 1
