@echo off
REM app.bat - One-click headless launcher for YouTube Downloader (Windows).
REM Auto-setup on first run: if venv or PO provider is missing, it runs
REM deploy automatically so the user never types a command. Uses pythonw.exe
REM so NO console window stays open alongside the GUI.

setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV_PYW=%SCRIPT_DIR%venv\Scripts\pythonw.exe"
set "VENV_PY=%SCRIPT_DIR%venv\Scripts\python.exe"
set "POT_SCRIPT=%SCRIPT_DIR%pot-provider\server\build\generate_once.js"

if not exist "%VENV_PYW%" goto :NEED_SETUP
if not exist "%POT_SCRIPT%" goto :NEED_SETUP
goto :LAUNCH

:NEED_SETUP
echo.
echo   [INFO] First run detected - setting up environment...
echo   [INFO] This may take 2-5 minutes (installing deps + building PO provider).
echo   [INFO] Please keep this window open.
echo.
REM Prefer PowerShell deployer (winget + full stack), fallback to deploy.bat
if exist "%SCRIPT_DIR%deploy.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%deploy.ps1"
    if errorlevel 1 (
        echo   [WARN] deploy.ps1 failed, trying deploy.bat ...
        call "%SCRIPT_DIR%deploy.bat"
    )
) else (
    call "%SCRIPT_DIR%deploy.bat"
)
echo.
if not exist "%VENV_PYW%" (
    echo   [ERROR] Setup failed - venv still missing at:
    echo           %VENV_PYW%
    echo   [ERROR] Try running deploy.ps1 manually as Administrator.
    echo.
    pause
    exit /b 1
)

:LAUNCH
REM Launch the GUI with the windowed (no-console) interpreter, detached.
if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" "%SCRIPT_DIR%app.py" %*
) else (
    start "" "%VENV_PY%" "%SCRIPT_DIR%app.py" %*
)

endlocal
exit /b 0
