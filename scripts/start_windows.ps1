param(
    [int]$Port = 8000,
    [string]$DataDir = "",
    [switch]$Demo,
    [switch]$Seed,
    [switch]$NoBrowser,
    [switch]$SkipFrontendBuild,
    [ValidateSet("standalone", "browser")]
    [string]$Mode = "standalone",
    [switch]$Console
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

function Test-DesktopDependenciesRequired([switch]$Console, [string]$Mode = "standalone") {
    return (-not $Console) -and ($Mode -eq "standalone")
}

function Test-DependencyInstallNeeded([string]$Stamp, [string[]]$Files) {
    if (-not (Test-Path -LiteralPath $Stamp -PathType Leaf)) { return $true }
    $stampTime = (Get-Item -LiteralPath $Stamp).LastWriteTimeUtc
    foreach ($file in $Files) {
        if ((Get-Item -LiteralPath $file).LastWriteTimeUtc -gt $stampTime) { return $true }
    }
    return $false
}

function Get-BackendArguments([int]$Port, [string]$DataDir, [switch]$Console, [switch]$Demo,
                              [string]$Mode = "standalone", [switch]$Seed, [switch]$NoBrowser) {
    $entryModule = if ($Console) { "backend" } else { "backend.desktop_entry" }
    $arguments = @("-m", $entryModule, "--host", "127.0.0.1", "--port", "$Port", "--data-dir", "$DataDir")
    if (-not $Console) { $arguments += @("--mode", $Mode.ToLowerInvariant()) }
    if ($Demo) { $arguments += "--demo" }
    if ($Seed) { $arguments += "--seed" }
    if ($NoBrowser) { $arguments += "--no-browser" }
    return $arguments
}

$Demo = $Demo -or (([string]$env:IMMO_DEMO).Trim().ToLowerInvariant() -in @("1", "true", "yes", "ja"))
if ($Demo -and $Seed) { throw "-Demo und -Seed können nicht kombiniert werden." }
if ($Demo -and -not $PSBoundParameters.ContainsKey("Port")) { $Port = 8766 }

if (-not $Demo) {
    if ([string]::IsNullOrWhiteSpace($DataDir)) {
        $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
        $DataDir = Join-Path $localAppData "ImmoManagerPro"
    }
    $DataDir = [IO.Path]::GetFullPath($DataDir)
    $UploadsDir = Join-Path $DataDir "uploads"
    $BackupsDir = Join-Path $DataDir "backups"
    $LogsDir = Join-Path $DataDir "logs"
    New-Item -ItemType Directory -Force -Path $DataDir, $UploadsDir, $BackupsDir, $LogsDir | Out-Null
}

if ($Console -and (Test-PortOpen $Port)) {
    Write-Host "Port $Port ist bereits belegt. Starten Sie mit einem freien Port, zum Beispiel: start.bat -Console -Port 9000" -ForegroundColor Yellow
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
    foreach ($file in @("pyproject.toml", "requirements.txt", "requirements-runtime.txt", "requirements-pip.txt", "constraints.txt")) {
        if ((Get-Item (Join-Path $Root $file)).LastWriteTimeUtc -gt $stampTime) {
            $needsInstall = $true
        }
    }
}

if ($needsInstall) {
    & $VenvPython -m pip install -r requirements-pip.txt
    if ($LASTEXITCODE -ne 0) { throw "Vorbereitung der Python-Installation fehlgeschlagen." }
    # exact versions of the whole dependency tree, then the project itself without resolving again
    & $VenvPython -m pip install -r requirements.txt -c constraints.txt
    if ($LASTEXITCODE -eq 0) {
        & $VenvPython -m pip install -e . --no-deps
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Backend-Installation fehlgeschlagen."
    }
    Set-Content -Path $stamp -Value (Get-Date).ToString("o") -Encoding UTF8
}

if ($Demo) {
    Write-Step "Demoverwaltung vorbereiten"
    # Validate the separate location before creating any data/upload folders.
    $demoDirectory = & $VenvPython -c "import sys; from backend.demo import configure_environment; print(configure_environment(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None))" $DataDir
    if ($LASTEXITCODE -ne 0) { throw "Der Datenordner der Demoverwaltung konnte nicht vorbereitet werden." }
    $DataDir = [IO.Path]::GetFullPath([string]($demoDirectory | Select-Object -Last 1))
    $UploadsDir = Join-Path $DataDir "uploads"
    $BackupsDir = Join-Path $DataDir "backups"
    $LogsDir = Join-Path $DataDir "logs"
    New-Item -ItemType Directory -Force -Path $DataDir, $UploadsDir, $BackupsDir, $LogsDir | Out-Null
}

if (Test-DesktopDependenciesRequired -Console:$Console -Mode $Mode) {
    Write-Step "Desktop-Abhaengigkeiten pruefen"
    $desktopStamp = Join-Path $Root ".venv\.immomanager-desktop-install-ok"
    $desktopInputs = @("requirements-desktop.txt", "requirements-pip.txt", "pyproject.toml", "constraints.txt", "scripts\install_desktop_dependencies.py") |
        ForEach-Object { Join-Path $Root $_ }
    $needsDesktopInstall = Test-DependencyInstallNeeded -Stamp $desktopStamp -Files $desktopInputs
    if (-not $needsDesktopInstall) {
        & $VenvPython scripts/install_desktop_dependencies.py --check
        $needsDesktopInstall = $LASTEXITCODE -ne 0
    }
    if ($needsDesktopInstall) {
        & $VenvPython scripts/install_desktop_dependencies.py
        if ($LASTEXITCODE -ne 0) { throw "Desktop-Installation fehlgeschlagen." }
        Set-Content -LiteralPath $desktopStamp -Value (Get-Date).ToString("o") -Encoding UTF8
    }
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
# python -m backend first runs the explicit upgrade step: when the database is behind the
# program, a verified full backup (backups\full) is made and the migrations run; otherwise
# nothing changes. If that step fails, the program does not start.

$backendArgs = @(Get-BackendArguments -Port $Port -DataDir $DataDir -Console:$Console -Demo:$Demo -Mode $Mode -Seed:$Seed -NoBrowser:$NoBrowser)

if ($Console) {
    & $VenvPython @backendArgs
    exit $LASTEXITCODE
}

$VenvPythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $VenvPythonw -PathType Leaf)) {
    throw "Der fensterlose Python-Starter pythonw.exe fehlt. Reparieren Sie die Python-Installation oder verwenden Sie fuer bewussten Administrationsbetrieb start.bat -Console."
}

# Start-Process in Windows PowerShell joins ArgumentList before passing it to
# CreateProcess. Quote each Windows argument, including quotes/backslashes, so
# paths containing spaces/Unicode (or a trailing backslash) arrive unchanged.
function Quote-ProcessArgument([string]$Value) {
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}
$desktopCommandLine = ($backendArgs | ForEach-Object { Quote-ProcessArgument $_ }) -join ' '
# pythonw is a GUI-subsystem host: the manager remains visible and this setup
# terminal returns immediately. Startup errors are shown by the manager.
Start-Process -FilePath $VenvPythonw -ArgumentList $desktopCommandLine -WorkingDirectory $Root -WindowStyle Normal
exit 0
