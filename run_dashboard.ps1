<#
.SYNOPSIS
    Sets up everything the dashboard needs, then starts the server.

.DESCRIPTION
    Checks for Python 3.10 or later and git, removes a stale 'pylogkit' folder
    left over from the old bundled copy, creates a virtual environment in
    .venv, installs requirements.txt when anything is missing, and runs
    server.py. Every other argument is passed to server.py.

.PARAMETER SetupOnly
    Prepare the environment and stop without starting the server.

.PARAMETER WithMqtt
    Also install paho-mqtt, for the MQTT telemetry export.

.EXAMPLE
    .\run_dashboard.ps1 --port auto --record session.jsonl

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\run_dashboard.ps1 --port COM3
#>
param(
    [switch]$SetupOnly,
    [switch]$WithMqtt
)

# "Continue", not "Stop": Windows PowerShell turns anything a native command
# writes to stderr into a terminating error when it is redirected, which would
# stop the script on the import check below. Exit codes are checked explicitly.
$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot -ErrorAction Stop

function Fail([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Find-Python {
    # The "py" launcher is the usual way to reach Python on Windows.
    foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
        $exe = $candidate[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $extra = @($candidate | Select-Object -Skip 1)
        $ok = & $exe @extra -c "import sys; print(sys.version_info >= (3, 10))" 2>&1
        if ($LASTEXITCODE -eq 0 -and ("$ok".Trim() -eq "True")) { return ,(@($exe) + $extra) }
    }
    return $null
}

# 1. Python 3.10 or later and git (py-logkit is installed from GitHub).
$python = Find-Python
if (-not $python) {
    Fail "Python 3.10 or later was not found. Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git was not found, and py-logkit is installed from GitHub. Install it with: winget install --id Git.Git"
}

# 2. A folder called 'pylogkit' with no Python files is left over from the old
#    bundled copy and confuses the import. A real package folder is never touched.
$stale = Join-Path $PSScriptRoot "pylogkit"
if (Test-Path -LiteralPath $stale -PathType Container) {
    $code = Get-ChildItem -LiteralPath $stale -Recurse -Filter *.py -ErrorAction SilentlyContinue
    if (-not $code) {
        Write-Host "Removing the stale folder $stale (no code in it)."
        Remove-Item -LiteralPath $stale -Recurse -Force -ErrorAction Stop
    }
}

# 3. Virtual environment.
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating the virtual environment in .venv ..."
    $exe = $python[0]
    $extra = @($python | Select-Object -Skip 1)
    & $exe @extra -m venv (Join-Path $PSScriptRoot ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment." }
}

# 4. Packages: install only when an import fails.
$check = "import fastapi, uvicorn, serial, websockets, pydantic, pylogkit; pylogkit.setup_logging"
$null = & $venvPython -c $check 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing requirements.txt ..."
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { Fail "pip could not install the requirements. Check your network connection." }
    $null = & $venvPython -c $check 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "The packages are installed but pylogkit still cannot be imported." }
}
if ($WithMqtt) {
    & $venvPython -m pip install "paho-mqtt>=2.0"
    if ($LASTEXITCODE -ne 0) { Fail "Could not install paho-mqtt." }
}

Write-Host "Environment ready."
if ($SetupOnly) { exit 0 }

# 5. Start the server, passing every remaining argument through.
Write-Host "Starting the dashboard: server.py $($args -join ' ')"
& $venvPython (Join-Path $PSScriptRoot "server.py") @args
exit $LASTEXITCODE
