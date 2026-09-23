# Local development stack: containers, migrations, API, and web in one terminal.
# Runtime role passwords and the operator token are generated per run, live in
# this process only, and are never written to a file.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

function New-Secret([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [BitConverter]::ToString($buffer).Replace('-', '')
}

function Read-EnvFile([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*#' -or !$line.Trim()) { continue }
        $pair = $line -split '=', 2
        $values[$pair[0].Trim()] = $pair[1]
    }
    return $values
}

if (!(Test-Path .env.local) -or !(Test-Path apps/web/.env.local)) {
    throw 'Run .\scripts\bootstrap-infra.ps1 and .\scripts\bootstrap-auth.ps1 first.'
}

& ./scripts/infra.ps1 start

$container = 'supabase_db_shoulder-local'
$password = New-Secret 32
$env:MIGRATION_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres'
& ./.tools/uv.exe run --locked alembic upgrade head
if ($LASTEXITCODE) { throw 'Migration upgrade failed' }
$env:MIGRATION_DATABASE_URL = $null
foreach ($role in @('shoulder_api', 'shoulder_operator', 'shoulder_worker')) {
    "ALTER ROLE $role PASSWORD '$password';" |
        & docker exec -i $container psql -U postgres -d postgres -q -v ON_ERROR_STOP=1
    if ($LASTEXITCODE) { throw "Could not set the local $role password" }
}

$web = Read-EnvFile 'apps/web/.env.local'
$local = Read-EnvFile '.env.local'
$env:SUPABASE_AUTH_ISSUER = 'http://127.0.0.1:54321/auth/v1'
$env:SUPABASE_PUBLISHABLE_KEY = $web['SUPABASE_PUBLISHABLE_KEY']
$env:DATABASE_URL = "postgresql+psycopg://shoulder_api:$password@127.0.0.1:54322/postgres"
$env:OPERATOR_DATABASE_URL = "postgresql+psycopg://shoulder_operator:$password@127.0.0.1:54322/postgres"
$env:WORKER_DATABASE_URL = "postgresql+psycopg://shoulder_worker:$password@127.0.0.1:54322/postgres"
$env:OPERATOR_BOOTSTRAP_TOKEN = New-Secret 24
$env:R2_ENDPOINT_URL = 'http://127.0.0.1:9000'
$env:R2_BUCKET = 'shoulder-local'
$env:R2_REGION = 'auto'
$env:R2_ACCESS_KEY_ID = $local['MINIO_ROOT_USER']
$env:R2_SECRET_ACCESS_KEY = $local['MINIO_ROOT_PASSWORD']

$api = Start-Process -FilePath ./.tools/uv.exe -PassThru -NoNewWindow -ArgumentList @(
    'run', '--locked', 'python', '-m', 'uvicorn', 'services.api.main:app',
    '--host', '127.0.0.1', '--port', '8000', '--no-access-log'
)
try {
    Write-Host ''
    Write-Host 'App          http://127.0.0.1:3000/auth/sign-in'
    Write-Host 'Captured mail http://127.0.0.1:54324'
    Write-Host 'API docs     http://127.0.0.1:8000/docs'
    Write-Host ''
    Write-Host 'After signing in, create the first team (coach id is on /auth/session):'
    Write-Host "  .\scripts\bootstrap-team.ps1 -CoachUserId <uuid> -Token $($env:OPERATOR_BOOTSTRAP_TOKEN)"
    Write-Host ''
    & npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm dev:web
} finally {
    if ($api -and !$api.HasExited) { Stop-Process -Id $api.Id -Force }
}
