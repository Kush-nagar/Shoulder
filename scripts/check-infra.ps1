param([switch]$DiscardLocalData)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!$DiscardLocalData) { throw 'This recovery suite resets Shoulder local volumes. Pass -DiscardLocalData; synthetic local data only.' }
if (!(Get-Command docker -ErrorAction SilentlyContinue)) { $env:PATH = "C:\Program Files\Docker\Docker\resources\bin;$env:PATH" }
$compose = @('compose', '--env-file', '.env.local', '-f', 'infra/compose.yaml')
function Invoke-Mc([string]$Script) {
    $setup = 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; '
    & docker @compose run --rm mc -ec ($setup + $Script)
    if ($LASTEXITCODE) { throw 'MinIO fixture verification failed' }
}
& ./scripts/bootstrap-infra.ps1
$credentialsBefore = (Get-FileHash .env.local).Hash
& ./scripts/bootstrap-infra.ps1
if ((Get-FileHash .env.local).Hash -ne $credentialsBefore) { throw 'Bootstrap overwrote existing local credentials' }
& ./scripts/infra.ps1 reset -DiscardLocalData
& ./scripts/infra.ps1 start
& ./scripts/infra.ps1 migrate
& ./scripts/infra.ps1 migrate
Invoke-Mc 'printf "synthetic-infrastructure-probe" | mc pipe local/shoulder-local/infra-probe.txt >/dev/null'
try {
    Invoke-WebRequest 'http://127.0.0.1:9000/shoulder-local/infra-probe.txt' -TimeoutSec 10 -UseBasicParsing | Out-Null
    throw 'Anonymous object access unexpectedly succeeded'
} catch {
    if (!$_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 403) { throw }
}
& ./scripts/infra.ps1 stop
& ./scripts/infra.ps1 start
Invoke-Mc 'test "$(mc cat local/shoulder-local/infra-probe.txt)" = "synthetic-infrastructure-probe"'
& docker @compose kill minio
if ($LASTEXITCODE) { throw 'Could not simulate MinIO interruption' }
$healthFailed = $false
try { & ./scripts/infra.ps1 health } catch { $healthFailed = $true }
if (!$healthFailed) { throw 'Health check missed interrupted storage' }
& ./scripts/infra.ps1 start
Invoke-Mc 'test "$(mc cat local/shoulder-local/infra-probe.txt)" = "synthetic-infrastructure-probe"'
& ./scripts/infra.ps1 reset -DiscardLocalData
Invoke-Mc 'mc ls --json local/shoulder-local > /tmp/objects; test ! -s /tmp/objects'
Write-Host 'PASS: start, idempotent start/migrate, private object, restart persistence, interruption detection/recovery, reset.'
