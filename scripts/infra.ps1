param(
    [ValidateSet('start', 'stop', 'health', 'migrate', 'reset')]
    [string]$Action = 'start',
    [switch]$DiscardLocalData
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
    if (Test-Path "$dockerBin/docker.exe") { $env:PATH = "$dockerBin;$env:PATH" }
}
$env:SUPABASE_HOME = Join-Path $PWD '.tools/supabase-home'
$supabase = Join-Path $PWD '.tools/supabase/supabase.exe'
$compose = @('compose', '--env-file', '.env.local', '-f', 'infra/compose.yaml')
$images = Get-Content infra/supabase-images.json -Raw | ConvertFrom-Json
function Invoke-Infra([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE) { throw "Infrastructure command failed: $Program $($Arguments -join ' ')" }
}
function Test-Health {
    foreach ($url in @('http://127.0.0.1:54321/auth/v1/health', 'http://127.0.0.1:54324/livez', 'http://127.0.0.1:9000/minio/health/ready')) {
        $response = Invoke-WebRequest $url -TimeoutSec 10 -UseBasicParsing
        if ($response.StatusCode -ne 200) { throw "Unhealthy: $url" }
    }
    Invoke-Infra docker @('exec', 'supabase_db_shoulder-local', 'psql', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', 'SELECT 1;')
    $version = & docker exec supabase_db_shoulder-local psql -U postgres -d postgres -Atc 'SHOW server_version;'
    if ($LASTEXITCODE -or $version -notmatch '^17\.6') { throw 'Unexpected local Postgres version; see ADR 0013' }
    $ids = @(& docker ps --filter 'label=com.supabase.cli.project=shoulder-local' --format '{{.ID}}')
    if ($LASTEXITCODE -or $ids.Count -lt 3) { throw 'Required Supabase containers missing' }
    foreach ($id in $ids) {
        $container = (& docker inspect $id | ConvertFrom-Json)[0]
        $digest = $images.PSObject.Properties[$container.Config.Image].Value
        if (!$digest) { throw "Unpinned Supabase image: $($container.Config.Image)" }
        $pinnedId = & docker image inspect "$($container.Config.Image)@$digest" --format '{{.Id}}'
        if ($LASTEXITCODE -or $pinnedId -ne $container.Image) { throw 'Running Supabase image differs from the digest lock' }
        foreach ($port in $container.NetworkSettings.Ports.PSObject.Properties) {
            foreach ($binding in $port.Value) {
                if ($binding.HostIp -notin @('127.0.0.1', '::1')) { throw "Non-loopback published port on $($container.Name)" }
            }
        }
        if (!$container.State.Running) { throw "Stopped container: $($container.Name)" }
        if ($container.State.Health -and $container.State.Health.Status -ne 'healthy') { throw "Unhealthy container: $($container.Name)" }
    }
    Write-Host 'Auth, Postgres, local mail, and MinIO are healthy; Supabase ports are loopback-only.'
}
if ($Action -eq 'reset' -and !$DiscardLocalData) { throw 'Reset erases only Shoulder local database/object volumes. Pass -DiscardLocalData explicitly.' }
if (!(Test-Path $supabase) -or !(Test-Path .env.local)) { throw 'Run .\scripts\bootstrap-infra.ps1 first.' }
# Newer CLI builds also print an update-nag line alongside the version, in
# either order (the update check races the version print), so this matches
# the version's own shape rather than assuming a line position.
$supabaseVersion = (& $supabase --version) -match '^\d+\.\d+\.\d+$'
if ($supabaseVersion.Count -ne 1 -or $supabaseVersion[0] -ne '2.116.0') {
    throw 'Expected Supabase CLI 2.116.0'
}
Invoke-Infra docker @('info', '--format', '{{.ServerVersion}}')
switch ($Action) {
    'start' {
        if ($env:OS -eq 'Windows_NT') {
            $settingsPath = Join-Path $env:APPDATA 'Docker/settings-store.json'
            $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
            if ($settings.PortBindingBehavior -notin @('default-local-port-binding', 'local-only-port-binding')) {
                throw 'Docker Desktop Settings > Resources > Network: select Localhost by default for Port binding behavior, apply, and restart Docker.'
            }
        }
        foreach ($image in $images.PSObject.Properties) {
            $pinned = "$($image.Name)@$($image.Value)"
            & docker image inspect $pinned --format '{{.Id}}' 2>$null | Out-Null
            if ($LASTEXITCODE) { Invoke-Infra docker @('pull', $pinned) }
            # The CLI owns container definitions and asks for these exact tags.
            Invoke-Infra docker @('tag', $pinned, $image.Name)
        }
        # Linking a hosted project makes the CLI adopt that project's Postgres
        # patch version locally, which would bypass the digest pins above.
        $pinnedPostgres = @($images.PSObject.Properties.Name |
                Where-Object { $_ -like '*/postgres:*' }) -replace '.*:', ''
        $versionFile = 'supabase/.temp/postgres-version'
        if ((Test-Path $versionFile) -and
            (Get-Content $versionFile -Raw).Trim() -ne $pinnedPostgres) {
            Remove-Item $versionFile -Force
        }
        $network = & docker network ls --filter 'name=^shoulder-supabase-local$' --format '{{.Name}}'
        if ($LASTEXITCODE) { throw 'Cannot inspect local Docker networks' }
        if (!$network) {
            Invoke-Infra docker @('network', 'create', '--driver', 'bridge', '--opt', 'com.docker.network.bridge.host_binding_ipv4=127.0.0.1', 'shoulder-supabase-local')
        }
        $networkInfo = (& docker network inspect shoulder-supabase-local | ConvertFrom-Json)[0]
        if ($networkInfo.Options.'com.docker.network.bridge.host_binding_ipv4' -ne '127.0.0.1') { throw 'Local Supabase network must bind to loopback' }
        # The CLI's success output includes local credentials; do not print or log it.
        $null = & $supabase start --network-id shoulder-supabase-local --exclude realtime,storage-api,imgproxy,postgrest,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
        if ($LASTEXITCODE) { throw 'Supabase startup failed; inspect local container health without sharing credentials.' }
        Invoke-Infra docker ($compose + @('up', '-d', '--wait', '--wait-timeout', '120', 'minio'))
        Invoke-Infra docker ($compose + @('run', '--rm', 'mc'))
        try { Test-Health } catch {
            # Fail closed if Desktop did not honor the configured binding policy.
            $null = & $supabase stop --project-id shoulder-local
            throw
        }
    }
    'health' { Test-Health }
    'migrate' {
        # No application migrations exist in Task 2; Alembic begins with Task 4.
        Invoke-Infra $supabase @('migration', 'up', '--local')
        Test-Health
    }
    'stop' {
        Invoke-Infra docker ($compose + @('down'))
        Invoke-Infra $supabase @('stop', '--project-id', 'shoulder-local')
    }
    'reset' {
        Invoke-Infra docker ($compose + @('down', '--volumes'))
        Invoke-Infra $supabase @('stop', '--project-id', 'shoulder-local', '--no-backup')
        & $PSCommandPath start
    }
}
