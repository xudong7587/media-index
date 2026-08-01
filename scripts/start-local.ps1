[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $repoRoot ".tmp/local-055"
$runtimeEnv = Join-Path $runtimeDir "runtime.env"
$python = Join-Path $repoRoot ".venv/Scripts/python.exe"
$backendLog = Join-Path $runtimeDir "backend.stdout.log"
$backendErrorLog = Join-Path $runtimeDir "backend.stderr.log"
$frontendLog = Join-Path $runtimeDir "frontend.stdout.log"
$frontendErrorLog = Join-Path $runtimeDir "frontend.stderr.log"

function Test-ListeningPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try { $client.Connect("127.0.0.1", $Port); return $true }
    catch { return $false }
    finally { $client.Dispose() }
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
if (-not (Test-Path $runtimeEnv)) {
    @"
APP_ENV=local-test
AUTH_SECRET=replace-with-a-local-only-secret
MEDIA_USER=local
MEDIA_PASS=replace-with-a-local-only-password
DB_PATH=$runtimeDir/media_index.db
CACHE_DIR=$runtimeDir/cache
MEDIA_CONFIG_PATH=$runtimeEnv
TRACKING_SCHEDULER_ENABLED=false
WISHLIST_SCHEDULER_ENABLED=false
NOTIFICATION_EXTERNAL_ENABLED=false
TELEGRAM_ENABLED=false
WECOM_ENABLED=false
WECOM_APP_ENABLED=false
WECOM_CALLBACK_ENABLED=false
DIRECT_DOWNLOAD_ENABLED=false
OPENLIST_ENABLED=false
OPENLIST_AUTO_SYNC=false
"@ | Set-Content -Encoding utf8 -NoNewline $runtimeEnv
}

if (-not (Test-Path $python)) { throw "Local Python environment is missing: $python" }

if (-not (Test-ListeningPort 8000)) {
    $env:MEDIA_CONFIG_PATH = $runtimeEnv
    Start-Process -FilePath $python -WorkingDirectory $repoRoot `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8000", "--reload" `
        -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog | Out-Null
}
if (-not (Test-ListeningPort 5173)) {
    Start-Process -FilePath "pnpm.cmd" -WorkingDirectory $repoRoot `
        -ArgumentList "--dir", "frontend", "dev", "--", "--host", "127.0.0.1", "--port", "5173" `
        -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog | Out-Null
}

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if ((Test-ListeningPort 8000) -and (Test-ListeningPort 5173)) { break }
    Start-Sleep -Milliseconds 500
}
if (-not (Test-ListeningPort 8000) -or -not (Test-ListeningPort 5173)) {
    throw "Local services did not start. Check $backendErrorLog and $frontendErrorLog"
}

Write-Host "Frontend: http://127.0.0.1:5173/"
Write-Host "Backend:  http://127.0.0.1:8000/openapi.json"
Write-Host "Runtime:  $runtimeEnv"
