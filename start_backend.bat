@echo off
setlocal
title BSNL Portal - Backend (Django)
rem ---------------------------------------------------------------------------
rem Starts the Django REST API: backend\manage.py runserver, with the project's
rem existing Python virtual environment. Settings come from backend\.env (read
rem by backend\config\settings.py). Nothing is installed, created or changed.
rem ---------------------------------------------------------------------------

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
rem The frontend calls VITE_API_BASE_URL in frontend\.env (http://localhost:8000/api).
rem Change this only together with that value and CORS_ALLOWED_ORIGINS in backend\.env.
set "BACKEND_PORT=8000"

echo.
echo === BSNL Portal backend ===

if not exist "%BACKEND%\manage.py" (
    echo [ERROR] backend\manage.py was not found in "%BACKEND%".
    echo         Keep this script in the project root, next to the backend folder.
    goto :fail
)

rem --- Existing virtual environment (first match; never creates one) ---------
set "VENV="
for %%D in ("%ROOT%.venv" "%ROOT%venv" "%ROOT%env" "%BACKEND%\.venv" "%BACKEND%\venv" "%BACKEND%\env") do (
    if not defined VENV if exist "%%~D\Scripts\python.exe" set "VENV=%%~D"
)
if not defined VENV (
    echo [ERROR] No Python virtual environment was found.
    echo         Looked for .venv, venv and env in the project root and in backend.
    echo         Create one yourself, e.g. in the project root:
    echo             py -3.11 -m venv .venv
    echo             .venv\Scripts\python -m pip install -r backend\requirements.txt
    goto :fail
)
echo Virtual environment: %VENV%
call "%VENV%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Could not activate the virtual environment "%VENV%".
    goto :fail
)

python -c "import django, rest_framework, dotenv" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Django or another backend package is missing from the virtual environment.
    echo         Install the dependencies yourself:
    echo             "%VENV%\Scripts\python" -m pip install -r "%BACKEND%\requirements.txt"
    goto :fail
)

if not exist "%BACKEND%\.env" (
    echo [WARNING] backend\.env was not found. The settings need DB_ENGINE and the database values;
    echo           copy backend\.env.example to backend\.env and fill it in, unless they are set as
    echo           Windows environment variables.
)

rem --- Already running? (safe to run again) --------------------------------
netstat -ano | findstr /R /C:":%BACKEND_PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo [INFO] Port %BACKEND_PORT% is already in use: the backend is probably running already.
    echo        Check it with health_log.bat, or stop the other process before starting a new one.
    goto :done
)

cd /d "%BACKEND%"

rem Do not start against a stale schema: the API can fail when a new model's table is missing.
python manage.py migrate --check >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Migration check failed: migrations may be unapplied, or the database may be unreachable.
    echo         Run health_log.bat to diagnose the database, then apply migrations from backend:
    echo             python manage.py migrate
    goto :fail
)

echo Starting Django on http://localhost:%BACKEND_PORT%/  (API: http://localhost:%BACKEND_PORT%/api/)
echo Press Ctrl+C to stop.
echo.
python manage.py runserver %BACKEND_PORT%
if errorlevel 1 (
    echo.
    echo [ERROR] The backend stopped with an error. Read the messages above:
    echo         - ImproperlyConfigured: a setting is missing in backend\.env, e.g. DB_ENGINE or SECRET_KEY
    echo         - OperationalError: PostgreSQL is not running or the database values are wrong
    echo         - "port is already in use": another program uses port %BACKEND_PORT%
    goto :fail
)
goto :done

:fail
echo.
echo Backend not started.
pause
endlocal
exit /b 1

:done
endlocal
exit /b 0
