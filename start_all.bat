@echo off
setlocal
rem ---------------------------------------------------------------------------
rem Opens the backend and the frontend in two separate command windows. Each
rem window stays open (cmd /k) so its output and errors remain visible.
rem Paths are relative to this file, so the project folder can be moved.
rem ---------------------------------------------------------------------------

set "ROOT=%~dp0"

if not exist "%ROOT%start_backend.bat" (
    echo [ERROR] start_backend.bat is missing next to start_all.bat.
    pause
    exit /b 1
)
if not exist "%ROOT%start_frontend.bat" (
    echo [ERROR] start_frontend.bat is missing next to start_all.bat.
    pause
    exit /b 1
)

echo Starting the BSNL Portal...
start "BSNL Portal - Backend" /D "%ROOT%" cmd /k call "%ROOT%start_backend.bat"
rem A short pause so the API is listening first (the frontend works either way).
timeout /t 3 /nobreak >nul
start "BSNL Portal - Frontend" /D "%ROOT%" cmd /k call "%ROOT%start_frontend.bat"

echo.
echo Two windows were opened:
echo   Backend   http://localhost:8000/api/
echo   Frontend  http://localhost:5173/
echo Close a window, or press Ctrl+C in it, to stop that server.
echo Run health_log.bat to check that everything responds.
echo.
endlocal
timeout /t 8
