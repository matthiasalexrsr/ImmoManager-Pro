param(
    [int]$Port = 8000,
    [string]$DataDir = "",
    [switch]$Seed,
    [switch]$NoBrowser,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
if (-not $env:PYTHONUTF8) { $env:PYTHONUTF8 = "1" }
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-CheckedCommand([string]$Command, [string[]]$Arguments, [string]$FailureMessage) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (Exit $LASTEXITCODE)."
    }
}

function Get-DependencyFingerprint([string]$ProjectRoot, [string]$Interpreter) {
    $version = & $Interpreter -c "import sys; print(sys.version)"
    if ($LASTEXITCODE -ne 0) {
        throw "Die virtuelle Python-Umgebung konnte nicht geprueft werden."
    }
    $inputs = @("immomanager-backend-v1", "$version")
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        foreach ($name in @("pyproject.toml", "requirements.txt", "backend/requirements.txt")) {
            $path = Join-Path $ProjectRoot $name
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
                throw "Abhaengigkeitsdatei fehlt: $name"
            }
            $stream = [IO.File]::OpenRead($path)
            try { $fileHash = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "") }
            finally { $stream.Dispose() }
            $inputs += "$name=$fileHash"
        }
        $hash = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($inputs -join "`n")))
        return ([BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Resolve-Python {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Command = $python.Source; Args = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Command = $py.Source; Args = @("-3.11") }
    }

    throw "Python 3.11+ wurde nicht gefunden. Installieren Sie Python von https://www.python.org und aktivieren Sie 'Add Python to PATH'."
}

function Test-PortOpen([int]$PortToCheck) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $PortToCheck, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(300, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    $DataDir = Join-Path $localAppData "ImmoManagerPro"
}

$DataDir = [IO.Path]::GetFullPath($DataDir)
$UploadsDir = Join-Path $DataDir "uploads"
$BackupsDir = Join-Path $DataDir "backups"
$LogsDir = Join-Path $DataDir "logs"
New-Item -ItemType Directory -Force -Path $DataDir, $UploadsDir, $BackupsDir, $LogsDir | Out-Null

if (Test-PortOpen $Port) {
    Write-Host "Port $Port ist bereits belegt. Oeffnen Sie http://127.0.0.1:$Port oder starten Sie mit: start.bat -Port 9000" -ForegroundColor Yellow
    exit 1
}

Write-Step "Python pruefen"
$py = Resolve-Python
$PythonCommand = $py.Command
$PythonArgs = @($py.Args)
Invoke-CheckedCommand $PythonCommand (@($PythonArgs) + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")) "Python 3.11+ ist erforderlich"

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Step "Virtuelle Umgebung erstellen"
    Invoke-CheckedCommand $PythonCommand (@($PythonArgs) + @("-m", "venv", ".venv")) "Erstellen der virtuellen Umgebung fehlgeschlagen"
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw "Die virtuelle Umgebung enthaelt keinen Python-Interpreter."
    }
}

Write-Step "Backend-Abhaengigkeiten pruefen"
$stamp = Join-Path $Root ".venv\.immomanager-install-ok"
$dependencyFingerprint = Get-DependencyFingerprint "$Root" $VenvPython
$needsInstall = -not (Test-Path -LiteralPath $stamp -PathType Leaf)
if (-not $needsInstall) {
    $needsInstall = (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $dependencyFingerprint
}

if ($needsInstall) {
    Invoke-CheckedCommand $VenvPython @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel") "pip-Vorbereitung fehlgeschlagen"
    Invoke-CheckedCommand $VenvPython @("-m", "pip", "install", "-r", "requirements.txt") "Backend-Abhaengigkeiten konnten nicht installiert werden"
    Invoke-CheckedCommand $VenvPython @("-m", "pip", "install", "-e", ".[dev]") "Backend-Installation fehlgeschlagen"
    Invoke-CheckedCommand $VenvPython @("-m", "pip", "check") "Backend-Abhaengigkeiten sind inkonsistent"
    # Only a fully successful install may authorize an offline restart.
    Set-Content -LiteralPath $stamp -Value $dependencyFingerprint -Encoding UTF8
}

Write-Step "Frontend pruefen"
$frontendArgs = @("-m", "backend.frontend_build", "--root", "$Root")
if ($SkipFrontendBuild) { $frontendArgs += "--skip-build" }
Invoke-CheckedCommand $VenvPython $frontendArgs "Frontend-Vorbereitung fehlgeschlagen; vorhandene Assets wurden erhalten"

$env:DATA_DIR = $DataDir
$env:UPLOADS_DIR = $UploadsDir
$env:BACKUP_DIR = $BackupsDir
$env:ENVIRONMENT = "production"
$env:ALLOW_INMEMORY_FALLBACK = "false"
$env:SQLITE_PERSISTENT_STORE = "true"
$env:CONTRACT_WIZARD_REQUIRED = "true"
$env:CORS_ORIGINS = "http://127.0.0.1:$Port,http://localhost:$Port,http://localhost:5173"

Write-Step "ImmoManager Pro starten"
Write-Host "Daten:   $DataDir"
Write-Host "Backups: $BackupsDir"
Write-Host "URL:     http://127.0.0.1:$Port"

$backendArgs = @("-m", "backend", "--host", "127.0.0.1", "--port", "$Port", "--data-dir", "$DataDir")
if ($Seed) {
    $backendArgs += "--seed"
}
if ($NoBrowser) {
    $backendArgs += "--no-browser"
}

& $VenvPython @backendArgs
exit $LASTEXITCODE
