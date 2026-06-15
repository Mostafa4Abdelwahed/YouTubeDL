@echo off
REM app.bat - Headless one-click launcher for the YouTube Downloader (Windows).
REM Uses pythonw.exe so NO console window stays open alongside the GUI.
REM The app is launched detached; this script exits immediately. The GUI
REM process ends when you close the window (clean shutdown handled in app.py).

setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV_PYW=%SCRIPT_DIR%venv\Scripts\pythonw.exe"

if not exist "%VENV_PYW%" (
    echo.
    echo   [ERROR] Virtual environment not found at:
    echo           %VENV_PYW%
    echo.
    echo   Run deploy.bat ^(or deploy.ps1^) first to set up the app.
    echo.
    pause
    exit /b 1
)

REM Launch the GUI with the windowed (no-console) interpreter, detached.
start "" "%VENV_PYW%" "%SCRIPT_DIR%app.py" %*

endlocal
exit /b 0
