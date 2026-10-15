param(
    [ValidateSet('memory', 'sql')][string]$Backend = 'memory',
    [string]$Label = 'targeted',
    [string[]]$Tests = @('backend/tests/test_auth_failclosed.py', 'backend/tests/test_message_thread_boundary.py'),
    [switch]$Coverage
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$qa = Join-Path $root ('artifacts\pro-tests\' + $Label + '-' + $Backend + '-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $qa -Force | Out-Null
$env:DATA_DIR = $qa
$env:UPLOADS_DIR = Join-Path $qa 'uploads'
$env:BACKUP_DIR = Join-Path $qa 'backups'
$env:INTEGRATION_STATE_FILE = Join-Path $qa 'integrations.json'
$env:SECRET_KEY_FILE = Join-Path $qa 'secrets\keyring.json'
$env:ENVIRONMENT = 'development'
$env:JOB_SCHEDULER_ENABLED = 'false'
$env:BACKUP_SCHEDULE_ENABLED = 'false'
$env:TEST_STORE_BACKEND = $Backend
$env:SQLITE_PERSISTENT_STORE = if ($Backend -eq 'sql') { 'true' } else { 'false' }
$env:ALLOW_INMEMORY_FALLBACK = if ($Backend -eq 'sql') { 'false' } else { 'true' }
$env:DATABASE_URL = if ($Backend -eq 'sql') { 'sqlite:///' + (Join-Path $qa 'test.db').Replace('\', '/') } else { 'sqlite:///:memory:' }
# Do not inherit keys or production database/admin endpoints from the caller.
foreach ($key in @('JWT_SECRET_KEY', 'SECRET_KEYS', 'SECRET_KEY', 'SECRET_PASSPHRASE', 'IMMO_TEST_POSTGRES_ADMIN_URL')) {
    Remove-Item "Env:$key" -ErrorAction SilentlyContinue
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$py = 'C:\Users\matth\Documents\Codex\2026-10-01\wi\work\review-venv-20261013\Scripts\python.exe'
$pytestArgs = @('-m', 'pytest') + $Tests + @('-q', '--tb=short', ('--junitxml=' + (Join-Path $qa 'junit.xml')))
if ($Coverage) { $pytestArgs += @('--cov=backend', '--cov-fail-under=80') }
$head = git rev-parse HEAD
Write-Output "QA_DIRECTORY=$qa"
Write-Output "QA_BASE=$head BACKEND=$Backend"
& $py @pytestArgs 2>&1 | Tee-Object -FilePath (Join-Path $qa 'pytest.log')
$code = $LASTEXITCODE
@{ commit = $head; backend = $Backend; exit_code = $code; tests = $Tests; coverage = [bool]$Coverage } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $qa 'result.json')
Write-Output "QA_EXIT=$code"
exit $code
