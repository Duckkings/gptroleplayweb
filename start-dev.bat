@echo off
setlocal ENABLEDELAYEDEXPANSION

set "ROOT=%~dp0"
set "LOG=%ROOT%start-dev.log"
set "BACKEND_VENV=.venv314"
set "PY_CMD="
set "PY_EXE="
set "PY_ARGS="

echo ==== start-dev %date% %time% ==== > "%LOG%"
echo [INFO] ROOT=%ROOT%>> "%LOG%"

if not defined PY_CMD (
  if exist "%LocalAppData%\Programs\Python\Python314\python.exe" (
    "%LocalAppData%\Programs\Python\Python314\python.exe" -V >nul 2>nul
    if %ERRORLEVEL%==0 (
      set "PY_CMD=%LocalAppData%\Programs\Python\Python314\python.exe"
      set "PY_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
      set "PY_ARGS="
    )
  )
)

if not defined PY_CMD (
  if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
    "%LocalAppData%\Programs\Python\Python313\python.exe" -V >nul 2>nul
    if %ERRORLEVEL%==0 (
      set "PY_CMD=%LocalAppData%\Programs\Python\Python313\python.exe"
      set "PY_EXE=%LocalAppData%\Programs\Python\Python313\python.exe"
      set "PY_ARGS="
    )
  )
)

if not defined PY_CMD (
  if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    "%LocalAppData%\Programs\Python\Python312\python.exe" -V >nul 2>nul
    if %ERRORLEVEL%==0 (
      set "PY_CMD=%LocalAppData%\Programs\Python\Python312\python.exe"
      set "PY_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
      set "PY_ARGS="
    )
  )
)

if not defined PY_CMD (
  if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    "%LocalAppData%\Programs\Python\Python311\python.exe" -V >nul 2>nul
    if %ERRORLEVEL%==0 (
      set "PY_CMD=%LocalAppData%\Programs\Python\Python311\python.exe"
      set "PY_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
      set "PY_ARGS="
    )
  )
)

if not defined PY_CMD (
  where py >nul 2>nul
  if %ERRORLEVEL%==0 (
    py -3 -V >nul 2>nul
    if %ERRORLEVEL%==0 (
      set "PY_CMD=py -3"
      set "PY_EXE=py"
      set "PY_ARGS=-3"
    )
  )
)

if not defined PY_CMD (
  where python >nul 2>nul
  if %ERRORLEVEL%==0 (
    python -c "import sys; print(sys.version)" >nul 2>nul
    if %ERRORLEVEL%==0 (
      set "PY_CMD=python"
      set "PY_EXE=python"
      set "PY_ARGS="
    )
  )
)

if not defined PY_CMD (
  echo [ERROR] Python not found. Install Python 3.11-3.14 stable and add it to PATH.
  echo [ERROR] Python not found>> "%LOG%"
  pause
  exit /b 1
)

where npm >nul 2>nul
if not %ERRORLEVEL%==0 (
  echo [ERROR] npm not found. Install Node.js 20+ and add it to PATH.
  echo [ERROR] npm not found>> "%LOG%"
  pause
  exit /b 1
)

echo [INFO] Using Python command: %PY_CMD%
echo [INFO] Using Python command: %PY_CMD%>> "%LOG%"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
  echo [INFO] Killing existing process on :8000 PID=%%P
  echo [INFO] Killing existing process on :8000 PID=%%P>> "%LOG%"
  taskkill /PID %%P /F >nul 2>nul
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5173 .*LISTENING"') do (
  echo [INFO] Killing existing process on :5173 PID=%%P
  echo [INFO] Killing existing process on :5173 PID=%%P>> "%LOG%"
  taskkill /PID %%P /F >nul 2>nul
)

if exist "%ROOT%backend\%BACKEND_VENV%\Scripts\python.exe" (
  "%ROOT%backend\%BACKEND_VENV%\Scripts\python.exe" -c "import sys; exit(0 if sys.version_info[:2] <= (3,14) else 1)" >nul 2>nul
  if not %ERRORLEVEL%==0 (
    echo [WARN] Existing backend .venv uses unsupported Python. Recreating...
    echo [WARN] Recreating backend .venv>> "%LOG%"
    rmdir /s /q "%ROOT%backend\%BACKEND_VENV%"
  )
)

echo [INFO] Preparing backend env...
cmd /c "cd /d ""%ROOT%backend"" && if not exist %BACKEND_VENV% (""%PY_EXE%"" %PY_ARGS% -m venv %BACKEND_VENV%) && call %BACKEND_VENV%\Scripts\activate.bat && python -m pip install -r requirements.txt"
if not %ERRORLEVEL%==0 (
  echo [ERROR] Backend environment prepare failed.
  echo [ERROR] Backend environment prepare failed.>> "%LOG%"
  pause
  exit /b 1
)

echo [INFO] Preparing frontend env...
cmd /c "cd /d ""%ROOT%frontend"" && if not exist node_modules call npm install"
if not %ERRORLEVEL%==0 (
  echo [ERROR] Frontend environment prepare failed.
  echo [ERROR] Frontend environment prepare failed.>> "%LOG%"
  pause
  exit /b 1
)

echo [INFO] Starting backend on http://127.0.0.1:8000
start "Roleplay Backend" cmd /k "cd /d ""%ROOT%backend"" && call %BACKEND_VENV%\Scripts\activate.bat && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

echo [INFO] Starting frontend on http://127.0.0.1:5173
start "Roleplay Frontend" cmd /k "cd /d ""%ROOT%frontend"" && call npm run dev"

echo [INFO] Opening browser in 2s...
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:5173
echo [INFO] Browser opened. If page is blank, wait a few seconds and refresh.
echo [INFO] Browser opened.>> "%LOG%"

echo [INFO] Started. Close the two terminal windows to stop services.
echo [INFO] Main launcher finished.>> "%LOG%"
echo [INFO] Log file: %LOG%
pause
endlocal
