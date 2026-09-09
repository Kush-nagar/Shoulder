param([switch]$SkipLargeUpload)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Task 8 storage integration against the real S3 API. The bucket is the local
# Compose MinIO; production is Cloudflare R2 behind the same API. Every
# credential is generated or read per run, kept in this process, and cleared in
# the finally block. The 2 GB payload is generated into the system temporary
# directory, never the repository, and is deleted by the test itself.
function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [BitConverter]::ToString($bytes).Replace('-', '')
}
$container = 'supabase_db_shoulder-local'
try {
    & ./scripts/infra.ps1 start
    $password = New-Secret
    $env:MIGRATION_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres'
    & ./.tools/uv.exe run --locked alembic upgrade head
    if ($LASTEXITCODE) { throw 'Migration upgrade failed' }
    foreach ($role in @('shoulder_api', 'shoulder_operator', 'shoulder_worker')) {
        "ALTER ROLE $role PASSWORD '$password';" |
            & docker exec -i $container psql -U postgres -d postgres -q -v ON_ERROR_STOP=1
        if ($LASTEXITCODE) { throw "Could not set the local $role password" }
    }
    $env:DATABASE_URL = "postgresql+psycopg://shoulder_api:$password@127.0.0.1:54322/postgres"
    $env:OPERATOR_DATABASE_URL = "postgresql+psycopg://shoulder_operator:$password@127.0.0.1:54322/postgres"
    $env:WORKER_DATABASE_URL = "postgresql+psycopg://shoulder_worker:$password@127.0.0.1:54322/postgres"
    $env:REQUIRE_DATABASE_TESTS = '1'

    # Local object-storage credentials come from the ignored .env.local that
    # scripts/bootstrap-infra.ps1 generated; they never reach a file here.
    if (!(Test-Path .env.local)) { throw 'Run .\scripts\bootstrap-infra.ps1 first.' }
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
    $env:REQUIRE_STORAGE_TESTS = '1'

    & ./.tools/uv.exe run --locked python -m unittest tests.test_storage tests.test_api_upload -v
    if ($LASTEXITCODE) { throw 'Storage and upload API integration failed' }

    if ($SkipLargeUpload) {
        Write-Host 'Skipped the 2 GB multipart proof by request.'
    } else {
        # Task 8 acceptance: a real 2 GB file through the implemented multipart
        # path, not an administrative upload.
        $env:RUN_LARGE_UPLOAD = '1'
        & ./.tools/uv.exe run --locked python -m unittest tests.test_large_upload -v
        if ($LASTEXITCODE) { throw 'The 2 GB multipart proof failed' }
    }

    # Nothing this run created may survive it; a stray object would otherwise
    # sit in the bucket past the abandoned-upload deadline.
    # The compose service's own command is replaced here, so the alias has to
    # be set in the same shell, exactly as scripts/check-infra.ps1 does.
    $setup = 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; '
    $remaining = & docker compose --env-file .env.local -f infra/compose.yaml run --rm mc -ec `
        ($setup + 'mc ls --recursive --json local/shoulder-local | wc -l')
    if ($LASTEXITCODE) { throw 'Could not inspect the local bucket' }
    $count = [int](($remaining | Select-Object -Last 1) -replace '\D', '')
    if ($count -ne 0) { throw "Storage tests left $count object(s) behind" }
    & ./scripts/infra.ps1 health
    Write-Host 'PASS: storage integration, upload API, 2 GB multipart proof, empty bucket.'
} finally {
    foreach ($role in @('shoulder_api', 'shoulder_operator', 'shoulder_worker')) {
        "ALTER ROLE $role PASSWORD NULL;" |
            & docker exec -i $container psql -U postgres -d postgres -q 2>$null
    }
    $env:RUN_LARGE_UPLOAD = $null
    $env:REQUIRE_STORAGE_TESTS = $null
    $env:R2_SECRET_ACCESS_KEY = $null
    $env:R2_ACCESS_KEY_ID = $null
    $env:R2_REGION = $null
    $env:R2_BUCKET = $null
    $env:R2_ENDPOINT_URL = $null
    $env:REQUIRE_DATABASE_TESTS = $null
    $env:WORKER_DATABASE_URL = $null
    $env:OPERATOR_DATABASE_URL = $null
    $env:DATABASE_URL = $null
    $env:MIGRATION_DATABASE_URL = $null
    & ./scripts/infra.ps1 stop
}
