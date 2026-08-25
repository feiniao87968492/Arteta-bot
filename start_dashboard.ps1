param(
    [string]$Password = "change-me",
    [string]$SecretKey = "dev-secret",
    [int]$ApiPort = 8765,
    [int]$WebPort = 5173,
    [switch]$ReadOnly,
    [switch]$EcsSync,
    [string]$EcsHost = "arteta",
    [string]$EcsUser = "root",
    [string]$EcsKeyPath = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$RemoteDbPath = "/opt/arteta_bot/arsenal_data.db",
    [string]$LocalDbPath = "data/ecs_arsenal_data.db",
    [int]$SyncIntervalSeconds = 10
)

$ErrorActionPreference = "Stop"
# Default web URL: http://localhost:5173
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WebRoot = Join-Path $RepoRoot "dashboard/web"
$SyncScript = Join-Path $RepoRoot "tools/sync_ecs_sqlite.py"

if (-not (Test-Path (Join-Path $RepoRoot "dashboard/api/main.py"))) {
    throw "dashboard/api/main.py not found. Run this script from the Arteta Bot repository root."
}

if (-not (Test-Path (Join-Path $WebRoot "package.json"))) {
    throw "dashboard/web/package.json not found. Dashboard frontend is missing."
}

if ($EcsSync -and -not (Test-Path $SyncScript)) {
    throw "tools/sync_ecs_sqlite.py not found. ECS sync cannot start."
}

$LocalDbFullPath = if ([System.IO.Path]::IsPathRooted($LocalDbPath)) { $LocalDbPath } else { Join-Path $RepoRoot $LocalDbPath }
$SyncStatusPath = Join-Path $RepoRoot "data/ecs_sync_status.json"

if ($EcsSync) {
    $env:ARTETA_DB_PATH = $LocalDbFullPath
    $env:DASHBOARD_READONLY = "true"
    Write-Host "Running initial ECS SQLite sync..." -ForegroundColor Cyan
    python $SyncScript --once --host $EcsHost --user $EcsUser --key-path $EcsKeyPath --remote-db $RemoteDbPath --local-db $LocalDbFullPath --status-path $SyncStatusPath --interval $SyncIntervalSeconds
    if ($LASTEXITCODE -ne 0) {
        throw "Initial ECS SQLite sync failed. Check data/ecs_sync_status.json for details."
    }
}

$env:DASHBOARD_ADMIN_PASSWORD = $Password
$env:DASHBOARD_SECRET_KEY = $SecretKey
$env:DASHBOARD_ALLOWED_ORIGINS = "http://localhost:$WebPort,http://127.0.0.1:$WebPort"
$env:DASHBOARD_READONLY = if ($ReadOnly -or $EcsSync) { "true" } else { "false" }

Write-Host "Arteta Developer Dashboard" -ForegroundColor Cyan
Write-Host "API:  http://127.0.0.1:$ApiPort" -ForegroundColor Gray
Write-Host "Web:  http://localhost:$WebPort" -ForegroundColor Gray
if ($EcsSync) {
    Write-Host "DB:   $LocalDbFullPath (syncing from $EcsUser@$EcsHost`:$RemoteDbPath)" -ForegroundColor Gray
} else {
    Write-Host "DB:   default local ARTETA_DB_PATH" -ForegroundColor Gray
}
Write-Host "User: admin password = $Password" -ForegroundColor Yellow
Write-Host "ReadOnly: $env:DASHBOARD_READONLY" -ForegroundColor Gray

if (-not (Test-Path (Join-Path $WebRoot "node_modules"))) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    npm --prefix "dashboard/web" install
}

$apiCommand = "`$env:DASHBOARD_ADMIN_PASSWORD='$Password'; `$env:DASHBOARD_SECRET_KEY='$SecretKey'; `$env:DASHBOARD_ALLOWED_ORIGINS='http://localhost:$WebPort,http://127.0.0.1:$WebPort'; `$env:DASHBOARD_READONLY='$env:DASHBOARD_READONLY'; `$env:ARTETA_DB_PATH='$env:ARTETA_DB_PATH'; python -m uvicorn dashboard.api.main:app --reload --port $ApiPort"
$webCommand = "npm --prefix dashboard/web run dev -- --host 127.0.0.1 --port $WebPort"
$syncCommand = "python tools/sync_ecs_sqlite.py --host $EcsHost --user $EcsUser --key-path '$EcsKeyPath' --remote-db '$RemoteDbPath' --local-db '$LocalDbFullPath' --status-path '$SyncStatusPath' --interval $SyncIntervalSeconds"

if ($EcsSync) {
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $syncCommand) -WorkingDirectory $RepoRoot
}
Start-Process powershell -ArgumentList @("-NoExit", "-Command", $apiCommand) -WorkingDirectory $RepoRoot
Start-Process powershell -ArgumentList @("-NoExit", "-Command", $webCommand) -WorkingDirectory $RepoRoot

Start-Sleep -Seconds 2
Start-Process "http://localhost:$WebPort"

if ($EcsSync) {
    Write-Host "Dashboard launch commands started in three PowerShell windows." -ForegroundColor Green
} else {
    Write-Host "Dashboard launch commands started in two PowerShell windows." -ForegroundColor Green
}
