@echo off
setlocal
title BSNL Portal - Health and logs
rem ---------------------------------------------------------------------------
rem Read-only status check: frontend, backend API, database connection (from
rem backend\.env through the Django settings; no credentials are printed) and
rem the most recent application log lines. Changes nothing; safe to run anytime.
rem ---------------------------------------------------------------------------

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
rem Same values as start_frontend.bat / start_backend.bat (see the notes there).
set "FRONTEND_PORT=5173"
set "BACKEND_PORT=8000"
set "LOG_LINES=20"

echo.
echo ==================== BSNL Portal health  %DATE% %TIME:~0,8% ====================

set "HAVE_CURL=1"
where curl >nul 2>&1
if errorlevel 1 set "HAVE_CURL="

rem --- 1. Frontend ----------------------------------------------------------
echo.
echo [1] Frontend  http://localhost:%FRONTEND_PORT%/
call :listening %FRONTEND_PORT%
call :http_code "http://localhost:%FRONTEND_PORT%/"
if "%CODE%"=="200" (
    echo     [OK]   Responding ^(HTTP 200^).
) else (
    echo     [DOWN] Not responding ^(HTTP %CODE%^). Start it with start_frontend.bat or start_all.bat.
)

rem --- 2. Backend -----------------------------------------------------------
echo.
echo [2] Backend   http://localhost:%BACKEND_PORT%/api/health/
call :listening %BACKEND_PORT%
call :http_code "http://localhost:%BACKEND_PORT%/api/health/"
if "%CODE%"=="200" (
    echo     [OK]   API responding ^(HTTP 200^):
    if defined HAVE_CURL (
        for /f "delims=" %%B in ('curl -s --max-time 5 "http://localhost:%BACKEND_PORT%/api/health/"') do echo            %%B
    )
) else (
    echo     [DOWN] Not responding ^(HTTP %CODE%^). Start it with start_backend.bat or start_all.bat.
)

rem --- 3. Database ----------------------------------------------------------
echo.
echo [3] Database  (settings from backend\.env; credentials are never shown)
set "VENV="
for %%D in ("%ROOT%.venv" "%ROOT%venv" "%ROOT%env" "%BACKEND%\.venv" "%BACKEND%\venv" "%BACKEND%\env") do (
    if not defined VENV if exist "%%~D\Scripts\python.exe" set "VENV=%%~D"
)
if not defined VENV goto :no_venv
if not exist "%BACKEND%\manage.py" goto :no_manage
pushd "%BACKEND%"
"%VENV%\Scripts\python.exe" manage.py shell -c "exec('from django.db import connection as c\nfrom django.db.migrations.executor import MigrationExecutor\ns = c.settings_dict\ndef mask(t):\n    for k in (\"PASSWORD\", \"USER\"):\n        if s.get(k): t = t.replace(str(s[k]), \"[hidden]\")\n    return t\ntry:\n    c.ensure_connection()\n    print(\"    [OK]   Connected:\", c.vendor, \"database\", s[\"NAME\"], \"on\", s.get(\"HOST\") or \"local\", \"port\", s.get(\"PORT\") or \"default\")\n    ex = MigrationExecutor(c)\n    plan = ex.migration_plan(ex.loader.graph.leaf_nodes())\n    print(\"    [OK]   All migrations applied.\" if not plan else \"    [WARN] \" + str(len(plan)) + \" unapplied migration(s): python manage.py migrate\")\nexcept Exception as e:\n    print(\"    [FAIL]\", type(e).__name__ + \":\", (mask(str(e)).strip().splitlines() or [\"\"])[0])\n    print(\"           Check that PostgreSQL is running and the DB_ values in backend\\\\.env.\")')" 2>"%TEMP%\bsnl_health_db.txt"
if errorlevel 1 call :db_error
popd
goto :logs

:no_venv
echo     [SKIP] No Python virtual environment found (.venv, venv or env); the database could not be checked.
goto :logs

:no_manage
echo     [SKIP] backend\manage.py not found.
goto :logs

rem --- 4. Logs --------------------------------------------------------------
:logs
echo.
echo [4] Application logs
set "AUDIT_LOG=%BACKEND%\logs\audit.log"
if exist "%BACKEND%\.env" (
    for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"AUDIT_LOG_FILE=" "%BACKEND%\.env"') do set "AUDIT_LOG=%%B"
)
if exist "%AUDIT_LOG%" (
    echo     Audit log ^(sign-ins and account administration^): %AUDIT_LOG%
    echo     Last %LOG_LINES% lines:
    powershell -NoProfile -Command "Get-Content -LiteralPath $env:AUDIT_LOG -Tail $env:LOG_LINES | ForEach-Object { '      ' + $_ }"
) else (
    echo     No audit log yet ^(it is created at the first sign-in^): %AUDIT_LOG%
)
echo.
echo     Everything else is not written to a file; it is printed in the console windows:
echo       - Django requests, errors and warnings: the backend window ^(start_backend.bat^)
echo       - Test-mode emails ^(console email backend^): the backend window
echo       - Vite build errors and page reloads: the frontend window ^(start_frontend.bat^)
echo       - Alert worker, when started with: python manage.py run_alerts ^(in its own window^)
echo.
echo ==============================================================================
endlocal
pause
exit /b 0

rem --- Helpers --------------------------------------------------------------
:listening
netstat -ano | findstr /R /C:":%1 .*LISTENING" >nul
if errorlevel 1 (
    echo     [INFO] Nothing is listening on port %1.
) else (
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%1 .*LISTENING"') do (
        echo     [INFO] Port %1 is open ^(process id %%P^).
        goto :eof
    )
)
goto :eof

:http_code
set "CODE=000"
if defined HAVE_CURL (
    for /f %%S in ('curl -s -o NUL -w "%%{http_code}" --max-time 5 %1') do set "CODE=%%S"
) else (
    for /f %%S in ('powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri '%~1').StatusCode } catch { if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { '000' } }"') do set "CODE=%%S"
)
goto :eof

:db_error
echo     [FAIL] The Django settings could not be loaded:
for /f "usebackq delims=" %%L in (`powershell -NoProfile -Command "Get-Content -LiteralPath (Join-Path $env:TEMP 'bsnl_health_db.txt') -Tail 1"`) do echo            %%L
echo            Check backend\.env ^(DB_ENGINE and the DB_ values^) and the virtual environment.
goto :eof
