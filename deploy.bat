@echo off
REM deploy.bat — One-shot deployment for YouTube Playlist Downloader (Windows cmd fallback)
REM Usage: deploy.bat

setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%venv"
set "REQ=%SCRIPT_DIR%requirements.txt"

echo.
echo   [YouTube Playlist Downloader - Deploy]
echo.

REM ── 1. Find Python ──────────────────────────────────────────────────────
set "PYTHON_EXE="
for %%c in (python python3 py) do (
    if not defined PYTHON_EXE (
        %%c --version >nul 2>&1 && set "PYTHON_EXE=%%c"
    )
)
if not defined PYTHON_EXE (
    echo   [ERROR] Python not found. Install from https://python.org
    exit /b 1
)
echo   [OK]    Found Python: %PYTHON_EXE%

REM ── 2. Install FFmpeg (merge video+audio / audio conversion) ─────────────
where ffmpeg >nul 2>&1
if %errorlevel%==0 (
    echo   [OK]    FFmpeg found.
) else (
    where winget >nul 2>&1
    if errorlevel 1 (
        echo   [WARN]  FFmpeg + winget unavailable. Install FFmpeg from https://ffmpeg.org
    ) else (
        echo   [INFO]  Installing FFmpeg via winget ...
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements --disable-interactivity
        echo   [OK]    FFmpeg install attempted.
    )
)

REM ── 2b. Install Deno (nsig solver) ───────────────────────────────────────
where deno >nul 2>&1
if %errorlevel%==0 (
    echo   [OK]    Deno found.
) else if exist "%USERPROFILE%\.deno\bin\deno.exe" (
    echo   [OK]    Deno found.
) else (
    echo   [INFO]  Installing Deno ...
    powershell -ExecutionPolicy Bypass -Command "irm https://deno.land/install.ps1 | iex"
    echo   [OK]    Deno install attempted.
)

REM ── 2c. Install Node.js LTS (PO token runtime, >= 20.19) ─────────────────
where node >nul 2>&1
if %errorlevel%==0 (
    echo   [OK]    Node.js found.
) else (
    where winget >nul 2>&1
    if errorlevel 1 (
        echo   [WARN]  Node + winget unavailable. Install Node 20.19+ from https://nodejs.org
    ) else (
        echo   [INFO]  Installing Node.js LTS via winget ...
        winget install OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements --disable-interactivity
        echo   [OK]    Node.js install attempted.
    )
)

REM ── 2d. Build local PO Token provider (bgutil script mode) ───────────────
REM Put a freshly winget-installed Node on PATH for this session.
if exist "%ProgramFiles%\nodejs\node.exe" set "PATH=%ProgramFiles%\nodejs;%PATH%"
set "POT_DIR=%SCRIPT_DIR%pot-provider\server"
set "POT_SCRIPT=%POT_DIR%\build\generate_once.js"
if exist "%POT_SCRIPT%" (
    echo   [OK]    PO Token provider already built.
) else (
    where node >nul 2>&1 && where git >nul 2>&1
    if errorlevel 1 (
        echo   [WARN]  Node/git unavailable - skipping PO provider build.
        echo   [WARN]  Bot-gated videos may fail. Re-run deploy after installing them.
    ) else (
        echo   [INFO]  Building local PO Token provider ^(bgutil script mode^) ...
        set "POT_TMP=%TEMP%\bgutil_build"
        if exist "!POT_TMP!" rmdir /s /q "!POT_TMP!"
        git clone --depth 1 --branch 1.3.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "!POT_TMP!" 2>nul
        pushd "!POT_TMP!\server"
        call npm install --no-audit --no-fund --silent
        call npx --yes tsc
        popd
        if exist "%POT_DIR%" rmdir /s /q "%POT_DIR%"
        mkdir "%POT_DIR%"
        for %%d in (build node_modules) do if exist "!POT_TMP!\server\%%d" move "!POT_TMP!\server\%%d" "%POT_DIR%\" >nul
        for %%f in (package.json package-lock.json) do if exist "!POT_TMP!\server\%%f" move "!POT_TMP!\server\%%f" "%POT_DIR%\" >nul
        rmdir /s /q "!POT_TMP!" 2>nul
        if exist "%POT_SCRIPT%" ( echo   [OK]    PO Token provider built. ) else ( echo   [WARN]  PO provider build failed - check Node/npm. )
    )
)

REM ── 3. Create venv ───────────────────────────────────────────────────────
echo   [INFO]  Creating virtual environment ...
if exist "%VENV_DIR%" (
    echo   [WARN]  Removing existing venv ...
    rmdir /s /q "%VENV_DIR%"
)
%PYTHON_EXE% -m venv "%VENV_DIR%"
echo   [OK]    Virtual environment created.

REM ── 4. Install deps ──────────────────────────────────────────────────────
REM Use 'python -m pip' so pip can upgrade itself on Windows (pip.exe self-upgrade fails)
echo   [INFO]  Installing dependencies ...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip --quiet
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%REQ%" --quiet
echo   [OK]    Dependencies installed.

REM ── 5. Directories ───────────────────────────────────────────────────────
if not exist "%SCRIPT_DIR%downloads" mkdir "%SCRIPT_DIR%downloads"
if not exist "%SCRIPT_DIR%logs"      mkdir "%SCRIPT_DIR%logs"
if not exist "%SCRIPT_DIR%debug"     mkdir "%SCRIPT_DIR%debug"
echo   [OK]    Directories ready.

echo.
echo   Deployment complete!
echo   Activate:  %VENV_DIR%\Scripts\activate.bat
echo   Run:       python app.py
echo.
endlocal
