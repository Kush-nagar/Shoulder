$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Real local roster and development-goal flow through the browser, the BFF, and
# FastAPI. Mirrors check-auth.ps1: every credential is generated per run, kept
# in this process, and cleared in the finally block.
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
    # The spec bootstraps one team through the operator endpoint; the token is
    # generated per run and never written to a file.
    $env:OPERATOR_BOOTSTRAP_TOKEN = New-Secret
    & node apps/web/node_modules/next/dist/bin/next build apps/web
    if ($LASTEXITCODE) { throw 'Roster production build failed' }
    & node node_modules/@playwright/test/cli.js test --config playwright.roster.config.mjs
    if ($LASTEXITCODE) { throw 'Real local roster integration failed' }
    & ./scripts/infra.ps1 health
} finally {
    # Includes failure paths. Tests remove only their own synthetic Auth users.
    foreach ($role in @('shoulder_api', 'shoulder_operator')) {
        "ALTER ROLE $role PASSWORD NULL;" |
            & docker exec -i $container psql -U postgres -d postgres -q 2>$null
    }
    $env:OPERATOR_BOOTSTRAP_TOKEN = $null
    $env:OPERATOR_DATABASE_URL = $null
    $env:DATABASE_URL = $null
    $env:MIGRATION_DATABASE_URL = $null
    & ./scripts/infra.ps1 stop
}
