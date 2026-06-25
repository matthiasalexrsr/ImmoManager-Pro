param(
    [int]$Port = 8000,
    [string]$DataDir = "",
    [switch]$Seed,
    [switch]$NoBrowser,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
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
& $PythonCommand @PythonArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.11+ ist erforderlich."
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Step "Virtuelle Umgebung erstellen"
    & $PythonCommand @PythonArgs -m venv ".venv"
}

Write-Step "Backend-Abhaengigkeiten pruefen"
$stamp = Join-Path $Root ".venv\.immomanager-install-ok"
$needsInstall = -not (Test-Path $stamp)
if (-not $needsInstall) {
    $stampTime = (Get-Item $stamp).LastWriteTimeUtc
    foreach ($file in @("pyproject.toml", "requirements.txt")) {
        if ((Get-Item (Join-Path $Root $file)).LastWriteTimeUtc -gt $stampTime) {
            $needsInstall = $true
        }
    }
}

if ($needsInstall) {
    & $VenvPython -m pip install --upgrade pip setuptools wheel
    & $VenvPython -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) {
        throw "Backend-Installation fehlgeschlagen."
    }
    Set-Content -Path $stamp -Value (Get-Date).ToString("o") -Encoding UTF8
}

if (-not $SkipFrontendBuild) {
    $frontendDist = Join-Path $Root "frontend\dist\index.html"
    if (-not (Test-Path $frontendDist)) {
        Write-Step "Frontend bauen"
        $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if (-not $npm) {
            throw "frontend\dist fehlt und Node.js/npm wurde nicht gefunden. Installieren Sie Node.js oder fuehren Sie den Build auf einem anderen Rechner aus."
        }
        Push-Location (Join-Path $Root "frontend")
        try {
            if (Test-Path "package-lock.json") {
                & $npm.Source ci
            } else {
                & $npm.Source install
            }
            & $npm.Source run build
        } finally {
            Pop-Location
        }
    }
}

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
