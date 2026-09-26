$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
try {
    & ./scripts/infra.ps1 start
    if (!(Test-Path apps/web/.env.local)) { & ./scripts/bootstrap-auth.ps1 }
    # Task 4 schema plus a per-run runtime credential, kept in this process.
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $password = [BitConverter]::ToString($bytes).Replace('-', '')
    $env:MIGRATION_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres'
    & ./.tools/uv.exe run --locked python -m alembic upgrade head
    if ($LASTEXITCODE) { throw 'Migration upgrade failed' }
    "ALTER ROLE shoulder_api PASSWORD '$password';" |
        & docker exec -i supabase_db_shoulder-local psql -U postgres -d postgres -q -v ON_ERROR_STOP=1
    if ($LASTEXITCODE) { throw 'Could not set the local runtime role password' }
    $env:DATABASE_URL = "postgresql+psycopg://shoulder_api:$password@127.0.0.1:54322/postgres"
    & node apps/web/node_modules/next/dist/bin/next build apps/web
    if ($LASTEXITCODE) { throw 'Auth production build failed' }
    & node node_modules/@playwright/test/cli.js test --config playwright.auth.config.mjs
    if ($LASTEXITCODE) { throw 'Real local auth integration failed' }
    & ./scripts/infra.ps1 health
} finally {
    # Includes failure paths. Tests remove only their own synthetic Auth users/mail.
    'ALTER ROLE shoulder_api PASSWORD NULL;' |
        & docker exec -i supabase_db_shoulder-local psql -U postgres -d postgres -q 2>$null
    $env:DATABASE_URL = $null
    $env:MIGRATION_DATABASE_URL = $null
    & ./scripts/infra.ps1 stop
}
