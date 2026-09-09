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
    "ALTER ROLE shoulder_operator PASSWORD '$password';" |
        & docker exec -i $container psql -U postgres -d postgres -q -v ON_ERROR_STOP=1
    if ($LASTEXITCODE) { throw 'Could not set the local operator role password' }
    $env:OPERATOR_DATABASE_URL = "postgresql+psycopg://shoulder_operator:$password@127.0.0.1:54322/postgres"
    $env:REQUIRE_DATABASE_TESTS = '1'
    $env:DATABASE_URL = "postgresql+psycopg://shoulder_api:$password@127.0.0.1:54322/postgres"
    # Local databases are disposable, so the policy mutation checks run here.
    $env:ALLOW_POLICY_MUTATION = '1'
    # `test_*.py`, not `test_database*.py`: the roster API suite also needs a
    # real database, and a pattern that misses it would skip it silently.
    & ./.tools/uv.exe run --locked python -m unittest discover -s tests -p 'test_*.py' -v
    if ($LASTEXITCODE) { throw 'Database isolation tests failed' }
    & ./scripts/infra.ps1 health
} finally {
    # The generated credential dies with this process; the role stays locked out
    # until the next run or an operator provisions a real password.
    'ALTER ROLE shoulder_api PASSWORD NULL;' |
        & docker exec -i $container psql -U postgres -d postgres -q 2>$null
    'ALTER ROLE shoulder_operator PASSWORD NULL;' |
        & docker exec -i $container psql -U postgres -d postgres -q 2>$null
    $env:ALLOW_POLICY_MUTATION = $null
    $env:OPERATOR_DATABASE_URL = $null
    $env:REQUIRE_DATABASE_TESTS = $null
    $env:DATABASE_URL = $null
    $env:MIGRATION_DATABASE_URL = $null
    & ./scripts/infra.ps1 stop
}
