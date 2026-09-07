$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:SUPABASE_HOME = Join-Path $PWD '.tools/supabase-home'
# Capture CLI credentials in memory. Write only the non-privileged publishable key.
$statusJson = & .tools/supabase/supabase.exe status -o json
if ($LASTEXITCODE) { throw 'Start local infrastructure first' }
$status = $statusJson | ConvertFrom-Json
$key = $status.PUBLISHABLE_KEY
if (!$key) { $key = $status.ANON_KEY }
if (!$key -or $status.API_URL -ne 'http://127.0.0.1:54321') { throw 'Unexpected local Auth configuration' }
if (Test-Path apps/web/.env.local) { throw 'apps/web/.env.local already exists; preserve or update it explicitly.' }
@(
    'APP_ORIGIN=http://127.0.0.1:3000',
    'AUTH_ALLOW_LOCAL_HTTP=true',
    'SUPABASE_URL=http://127.0.0.1:54321',
    "SUPABASE_PUBLISHABLE_KEY=$key",
    'API_BASE_URL=http://127.0.0.1:8000'
) | Set-Content -Encoding utf8 apps/web/.env.local
Write-Host 'Local server-only Auth environment written; no privileged key was copied.'
