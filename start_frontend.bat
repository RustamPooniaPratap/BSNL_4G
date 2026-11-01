@echo off
setlocal
title BSNL Portal - Frontend (Vite)
rem ---------------------------------------------------------------------------
rem Starts the React + Vite development server with the existing "dev" script
rem of frontend\package.json (npm run dev). Nothing is installed or changed.
rem ---------------------------------------------------------------------------

set "ROOT=%~dp0"
set "FRONTEND=%ROOT%frontend"
rem Vite's default port (vite.config.ts sets none). The backend allows this origin
rem in CORS_ALLOWED_ORIGINS (backend\.env).
set "FRONTEND_PORT=5173"

echo.
echo === BSNL Portal frontend ===

if not exist "%FRONTEND%\package.json" (
    echo [ERROR] frontend\package.json was not found in "%FRONTEND%".
    echo         Keep this script in the project root, next to the frontend folder.
    goto :fail
)

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js is not installed or not on PATH. Install Node.js LTS from https://nodejs.org
    goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm is not on PATH. It comes with Node.js; reinstall Node.js LTS.
    goto :fail
)

if not exist "%FRONTEND%\node_modules" (
    echo [ERROR] frontend\node_modules is missing: the dependencies are not installed.
    echo         Install them yourself, once:
    echo             cd /d "%FRONTEND%"
    echo             npm install
    goto :fail
)

if not exist "%FRONTEND%\.env" (
    echo [WARNING] frontend\.env was not found; the API address defaults to http://localhost:8000/api.
)

rem --- Already running? (safe to run again) --------------------------------
netstat -ano | findstr /R /C:":%FRONTEND_PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo [INFO] Port %FRONTEND_PORT% is already in use: the frontend is probably running already.
    echo        Open http://localhost:%FRONTEND_PORT%/ or check it with health_log.bat.
    goto :done
)

cd /d "%FRONTEND%"
echo Starting Vite on http://localhost:%FRONTEND_PORT%/
echo Press Ctrl+C to stop.
echo.
call npm run dev
if errorlevel 1 (
    echo.
    echo [ERROR] The frontend stopped with an error. Read the messages above:
    echo         - "Cannot find module" / missing package: run npm install in the frontend folder
    echo         - port errors: another program uses port %FRONTEND_PORT%
    goto :fail
)
goto :done

:fail
echo.
echo Frontend not started.
pause
endlocal
exit /b 1

:done
endlocal
exit /b 0
