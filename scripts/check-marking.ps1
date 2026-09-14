$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Task 14 acceptance: real auth, Postgres RLS, object storage, video playback,
# and keyboard-only marking in each supported browser.
function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [BitConverter]::ToString($bytes).Replace('-', '')
}
$container = 'supabase_db_shoulder-local'
try {
    & ./scripts/infra.ps1 start
    if (!(Test-Path apps/web/.env.local)) { & ./scripts/bootstrap-auth.ps1 }
    if (!(Test-Path .env.local)) { throw 'Run .\scripts\bootstrap-infra.ps1 first.' }
    $password = New-Secret
    $env:MIGRATION_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres'
    & ./.tools/uv.exe run --locked alembic upgrade head
    if ($LASTEXITCODE) { throw 'Migration upgrade failed' }
    foreach ($role in @('shoulder_api', 'shoulder_operator')) {
        "ALTER ROLE $role PASSWORD '$password';" |
            & docker exec -i $container psql -U postgres -d postgres -q -v ON_ERROR_STOP=1
        if ($LASTEXITCODE) { throw "Could not set the local $role password" }
    }
    $env:DATABASE_URL = "postgresql+psycopg://shoulder_api:$password@127.0.0.1:54322/postgres"
    $env:OPERATOR_DATABASE_URL = "postgresql+psycopg://shoulder_operator:$password@127.0.0.1:54322/postgres"
    $env:OPERATOR_BOOTSTRAP_TOKEN = New-Secret

    $local = @{}
    foreach ($line in Get-Content .env.local) {
        if ($line -match '^\s*#' -or !$line.Trim()) { continue }
        $pair = $line -split '=', 2
        $local[$pair[0]] = $pair[1]
    }
    $env:R2_ENDPOINT_URL = 'http://127.0.0.1:9000'
    $env:R2_BUCKET = 'shoulder-local'
    $env:R2_REGION = 'auto'
    $env:R2_ACCESS_KEY_ID = $local['MINIO_ROOT_USER']
    $env:R2_SECRET_ACCESS_KEY = $local['MINIO_ROOT_PASSWORD']

    & node apps/web/node_modules/next/dist/bin/next build apps/web
    if ($LASTEXITCODE) { throw 'Marking production build failed' }
    & node node_modules/@playwright/test/cli.js test --config playwright.marking.config.mjs
    if ($LASTEXITCODE) { throw 'Real local marking integration failed' }
    & ./scripts/infra.ps1 health
    Write-Host 'PASS: keyboard-only marking under six seconds and text-field suppression.'
} finally {
    foreach ($role in @('shoulder_api', 'shoulder_operator')) {
        "ALTER ROLE $role PASSWORD NULL;" |
            & docker exec -i $container psql -U postgres -d postgres -q 2>$null
    }
    $env:R2_SECRET_ACCESS_KEY = $null
    $env:R2_ACCESS_KEY_ID = $null
    $env:R2_REGION = $null
    $env:R2_BUCKET = $null
    $env:R2_ENDPOINT_URL = $null
    $env:OPERATOR_BOOTSTRAP_TOKEN = $null
    $env:OPERATOR_DATABASE_URL = $null
    $env:DATABASE_URL = $null
    $env:MIGRATION_DATABASE_URL = $null
    & ./scripts/infra.ps1 stop
}
