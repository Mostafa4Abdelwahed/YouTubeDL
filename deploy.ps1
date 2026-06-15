# deploy.ps1 - One-shot deployment for YouTube Playlist Downloader
# Windows (PowerShell 5.1+)
# Usage: Set-ExecutionPolicy -Scope Process Bypass; .\deploy.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir   = Join-Path $ScriptDir "venv"
$Req       = Join-Path $ScriptDir "requirements.txt"

function Write-Step { param($msg) Write-Host "  [INFO]  $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "  [OK]    $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [WARN]  $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [ERROR] $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  +----------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |  YouTube Playlist Downloader -- Deploy       |" -ForegroundColor Cyan
Write-Host "  +----------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

# -- 1. Locate Python 3.10+ --------------------------------------------------
Write-Step "Locating Python interpreter ..."
$PythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))" 2>$null
        if ($ver) {
            $parts = $ver.Trim().Split(".")
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
                $PythonExe = $candidate
                Write-Ok "Found $candidate ($ver)"
                break
            }
        }
    } catch {}
}

if (-not $PythonExe) {
    Write-Fail "Python 3.10+ not found. Install from https://python.org and re-run."
}

# -- 2. Install FFmpeg (REQUIRED for merging video+audio / audio conversion) --
Write-Step "Checking FFmpeg ..."
$ffmpegOk = ($null -ne (Get-Command ffmpeg -ErrorAction SilentlyContinue))
$wingetFf = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
if (-not $ffmpegOk -and (Test-Path $wingetFf)) {
    $ffExe = Get-ChildItem -Path $wingetFf -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ffExe) { $ffmpegOk = $true }
}
if ($ffmpegOk) {
    Write-Ok "FFmpeg is available."
} elseif ($null -ne (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Step "Installing FFmpeg via winget ..."
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements --disable-interactivity
    Write-Ok "FFmpeg installed (restart your shell so it is on PATH; the app finds it automatically)."
} else {
    Write-Warn "FFmpeg not found and winget unavailable."
    Write-Warn "Download from https://ffmpeg.org and add the bin\ folder to your PATH."
    Write-Warn "Video merging and audio conversion WILL NOT WORK without FFmpeg."
}

# -- 2b. Install Deno (solves YouTube's 'n' signature challenge) --------------
Write-Step "Checking Deno (nsig challenge solver) ..."
$denoExe = Join-Path $env:USERPROFILE ".deno\bin\deno.exe"
if (($null -ne (Get-Command deno -ErrorAction SilentlyContinue)) -or (Test-Path $denoExe)) {
    Write-Ok "Deno is available."
} else {
    Write-Step "Installing Deno ..."
    try { irm https://deno.land/install.ps1 | iex; Write-Ok "Deno installed." }
    catch { Write-Warn "Deno install failed. Install manually from https://deno.land" }
}

# -- 2c. Install Node.js LTS (runs the local PO Token script) -----------------
Write-Step "Checking Node.js (>= 20.19, for PO tokens) ..."
$nodeOk = $false
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    try {
        $nv = (& node --version).TrimStart('v').Split('.')
        if ([int]$nv[0] -gt 20 -or ([int]$nv[0] -eq 20 -and [int]$nv[1] -ge 19)) { $nodeOk = $true }
    } catch {}
}
if ($nodeOk) {
    Write-Ok "Node.js is available ($(& node --version))."
} elseif ($null -ne (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Step "Installing Node.js LTS via winget ..."
    winget install OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements --disable-interactivity
    Write-Ok "Node.js LTS installed (restart your shell so it is on PATH)."
} else {
    Write-Warn "Node.js 20.19+ not found and winget unavailable. Install from https://nodejs.org"
}

# -- 2d. Build the local PO Token provider (bgutil 'script mode') -------------
Write-Step "Setting up local PO Token provider ..."
$PotDir    = Join-Path $ScriptDir "pot-provider\server"
$PotScript = Join-Path $PotDir "build\generate_once.js"
$PotVersion = "1.3.1"   # keep in sync with bgutil-ytdlp-pot-provider in requirements.txt
if (Test-Path $PotScript) {
    Write-Ok "PO Token provider already built."
} else {
    $nodePath = "$env:ProgramFiles\nodejs"
    if (Test-Path "$nodePath\node.exe") { $env:PATH = "$nodePath;$env:PATH" }
    if (($null -eq (Get-Command node -ErrorAction SilentlyContinue)) -or ($null -eq (Get-Command git -ErrorAction SilentlyContinue))) {
        Write-Warn "Node.js and/or git unavailable - skipping PO provider build."
        Write-Warn "Bot-gated/age-restricted videos may fail. Re-run deploy after installing them."
    } else {
        $tmp = Join-Path $env:TEMP "bgutil_build"
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Write-Step "  Cloning bgutil provider v$PotVersion ..."
        git clone --depth 1 --branch $PotVersion https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git $tmp 2>$null
        Push-Location (Join-Path $tmp "server")
        Write-Step "  Installing npm dependencies ..."
        & npm install --no-audit --no-fund --silent
        Write-Step "  Building (tsc) ..."
        & npx --yes tsc
        Pop-Location
        # Keep only build/ + node_modules/ + package files; drop src/ so the
        # Node provider is selected over the Deno one (which needs src/*.ts).
        if (Test-Path $PotDir) { Remove-Item -Recurse -Force $PotDir }
        New-Item -ItemType Directory -Path $PotDir -Force | Out-Null
        foreach ($item in @("build", "node_modules", "package.json", "package-lock.json")) {
            $srcItem = Join-Path $tmp "server\$item"
            if (Test-Path $srcItem) { Move-Item $srcItem $PotDir }
        }
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
        if (Test-Path $PotScript) { Write-Ok "PO Token provider built (pot-provider\server)." }
        else { Write-Warn "PO Token provider build failed - check Node/npm and re-run." }
    }
}

# -- 3. Create virtual environment --------------------------------------------
Write-Step "Creating virtual environment at $VenvDir ..."
if (Test-Path $VenvDir) {
    Write-Warn "Existing venv found - removing and recreating."
    Remove-Item -Recurse -Force $VenvDir
}
& $PythonExe -m venv $VenvDir
Write-Ok "Virtual environment created."

# -- 4. Install dependencies --------------------------------------------------
Write-Step "Installing dependencies from requirements.txt ..."
$venvPy = Join-Path $VenvDir "Scripts\python.exe"
# Use 'python -m pip' (not pip.exe) so pip can upgrade itself on Windows.
# Tolerate a failed self-upgrade - it is optional and must not abort the deploy.
try { & $venvPy -m pip install --upgrade pip --quiet } catch { Write-Warn "pip self-upgrade skipped." }
& $venvPy -m pip install -r $Req --quiet
if ($LASTEXITCODE -ne 0) { Write-Fail "Dependency install failed (exit $LASTEXITCODE)." }
Write-Ok "Dependencies installed."

# -- 5. Project directories ---------------------------------------------------
Write-Step "Creating project directories ..."
foreach ($dir in @("downloads", "logs", "debug")) {
    $path = Join-Path $ScriptDir $dir
    if (-not (Test-Path $path)) { New-Item -ItemType Directory -Path $path | Out-Null }
}
Write-Ok "Directories ready."

# -- Done ---------------------------------------------------------------------
Write-Host ""
Write-Host "  +----------------------------------------------+" -ForegroundColor Green
Write-Host "  |         Deployment complete!                 |" -ForegroundColor Green
Write-Host "  +----------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Activate venv:  .\venv\Scripts\Activate.ps1"
Write-Host "  Run the app:    python app.py"
Write-Host "  Or directly:    .\venv\Scripts\python.exe app.py"
Write-Host ""
