$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Real local Supabase Postgres. The runtime password is generated per run, kept
# in this process only, and never written to a file or printed.
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$password = [BitConverter]::ToString($bytes).Replace('-', '')
$container = 'supabase_db_shoulder-local'
try {
    & ./scripts/infra.ps1 start
    $env:MIGRATION_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres'
    & ./.tools/uv.exe run --locked alembic upgrade head
    if ($LASTEXITCODE) { throw 'Migration upgrade failed' }
    $alter = "ALTER ROLE shoulder_api PASSWORD '$password';"
    $alter | & docker exec -i $container psql -U postgres -d postgres -q -v ON_ERROR_STOP=1
    if ($LASTEXITCODE) { throw 'Could not set the local runtime role password' }
    $env:DATABASE_URL = "postgresql+psycopg://shoulder_api:$password@127.0.0.1:54322/postgres"
    & ./.tools/uv.exe run --locked python -m unittest discover -s tests -p test_database.py -v
    if ($LASTEXITCODE) { throw 'Database isolation tests failed' }
    & ./scripts/infra.ps1 health
} finally {
    # The generated credential dies with this process; the role stays locked out
    # until the next run or an operator provisions a real password.
    'ALTER ROLE shoulder_api PASSWORD NULL;' |
        & docker exec -i $container psql -U postgres -d postgres -q 2>$null
    $env:DATABASE_URL = $null
    $env:MIGRATION_DATABASE_URL = $null
    & ./scripts/infra.ps1 stop
}
