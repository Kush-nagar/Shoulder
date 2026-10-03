# Deploy the synthetic-data player demo (ADR 0021, hosting ADR 0028): remote
# migrations, demo team, API on Vercel, worker on GitHub Actions, web on Vercel.
# Run by the owner. Every secret is read from ignored env files and piped on
# stdin, so none reaches argv, logs, or Git.
#   .\scripts\deploy-demo.ps1 -Step migrate   # alembic upgrade + seed demo team
#   .\scripts\deploy-demo.ps1 -Step api -DemoTeamId <id>  # Vercel `shoulder-api`
#   .\scripts\deploy-demo.ps1 -Step worker    # GitHub Actions secrets
#   .\scripts\deploy-demo.ps1 -Step web       # Vercel env + production deploy
param(
    [Parameter(Mandatory)][ValidateSet('migrate', 'api', 'worker', 'web')][string]$Step,
    [string]$ApiProject = 'shoulder-api',
    [string]$ApiOrigin = 'https://shoulderapp-api.vercel.app',
    [string]$WebOrigin = 'https://shoulderapp.vercel.app',
    [string]$DemoTeamId
)
$ErrorActionPreference = 'Stop'
# Windows PowerShell prefixes piped native stdin with a UTF-8 BOM otherwise,
# which corrupts the first secret name.
$global:OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $global:OutputEncoding
Set-Location (Split-Path $PSScriptRoot -Parent)

function Read-EnvFile([string]$Path) {
    $values = [ordered]@{}
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*#' -or !$line.Trim()) { continue }
        $pair = $line -split '=', 2
        $values[$pair[0].Trim().TrimStart([char]0xFEFF)] = $pair[1]
    }
    return $values
}

$remote = Read-EnvFile '.env.remote'
switch ($Step) {
    'migrate' {
        $env:MIGRATION_DATABASE_URL = $remote['MIGRATION_DATABASE_URL']
        try {
            & ./.tools/uv.exe run --locked alembic upgrade head
            if ($LASTEXITCODE) { throw 'Remote migration failed' }
            & ./.tools/uv.exe run --locked python -m scripts.seed_demo
            if ($LASTEXITCODE) { throw 'Demo seed failed' }
        } finally { $env:MIGRATION_DATABASE_URL = $null }
        Write-Host 'Next: .\scripts\deploy-demo.ps1 -Step api -DemoTeamId <printed id>'
    }
    'api' {
        # Windows PowerShell 5.1 turns native stderr chatter into terminating
        # errors under 'Stop'; every native call below checks $LASTEXITCODE.
        $ErrorActionPreference = 'Continue'
        if (!$DemoTeamId) { throw 'Pass -DemoTeamId from the migrate step.' }
        $api = Read-EnvFile 'services/api/.env'
        $local = Read-EnvFile '.env.local'
        $secrets = [ordered]@{}
        foreach ($name in $api.Keys) { $secrets[$name] = $api[$name] }
        $secrets['OPENROUTER_API_KEY'] = $local['OPENROUTER_API_KEY']
        if ($local['AI_COACH_MODEL']) { $secrets['AI_COACH_MODEL'] = $local['AI_COACH_MODEL'] }
        $secrets['DEMO_MODE'] = 'on'
        $secrets['DEMO_TEAM_ID'] = $DemoTeamId
        $secrets['APP_ORIGIN'] = $WebOrigin
        # Vercel builds Python 3.12 from requirements.txt (ADR 0028), so the
        # deploy uploads a staged copy: the API package plus exported pins.
        $stage = Join-Path ([System.IO.Path]::GetTempPath()) "shoulder-api-$PID"
        $file = [System.IO.Path]::GetTempFileName()
        try {
            New-Item -ItemType Directory -Force "$stage/services" | Out-Null
            Copy-Item -Recurse services/api "$stage/services/api"
            Copy-Item services/timeline.py "$stage/services/"
            Get-ChildItem -Recurse -Directory -Filter __pycache__ $stage | Remove-Item -Recurse -Force
            Remove-Item -Force -ErrorAction SilentlyContinue "$stage/services/api/.env"
            & ./.tools/uv.exe export --quiet --locked --no-dev --no-hashes --no-emit-project --format requirements-txt -o "$stage/requirements.txt" | Out-Null
            if ($LASTEXITCODE) { throw 'uv export failed' }
            Set-Content -Encoding utf8 "$stage/index.py" "from services.api.main import app`n`n__all__ = [`"app`"]"
            Push-Location $stage
            try {
                & vercel link --yes --project $ApiProject | Out-Null
                if ($LASTEXITCODE) { throw 'vercel link failed' }
                foreach ($name in $secrets.Keys) {
                    [System.IO.File]::WriteAllText($file, $secrets[$name], (New-Object System.Text.UTF8Encoding $false))
                    & cmd /c "vercel env add $name production --force < `"$file`"" | Out-Null
                    if ($LASTEXITCODE) { throw "vercel env add $name failed" }
                }
                & vercel deploy --prod --yes
                if ($LASTEXITCODE) { throw 'vercel deploy failed' }
            } finally { Pop-Location }
        } finally {
            Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $stage
        }
        Write-Host "API: $ApiOrigin/health"
    }
    'worker' {
        # Windows PowerShell 5.1 turns native stderr chatter into terminating
        # errors under 'Stop'; every native call below checks $LASTEXITCODE.
        $ErrorActionPreference = 'Continue'
        $worker = Read-EnvFile 'services/worker/.env'
        $file = [System.IO.Path]::GetTempFileName()
        try {
            foreach ($name in $worker.Keys) {
                if ($name -in @('APP_ORIGIN', 'WORKER_LOG_LEVEL')) { continue }
                [System.IO.File]::WriteAllText($file, $worker[$name], (New-Object System.Text.UTF8Encoding $false))
                & cmd /c "gh secret set $name < `"$file`""
                if ($LASTEXITCODE) { throw "gh secret set $name failed" }
            }
        } finally { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
        Write-Host 'Worker secrets set. Start a run: gh workflow run worker'
    }
    'web' {
        $ErrorActionPreference = 'Continue'
        # The remote project, never the local stack in apps/web/.env.local.
        $api = Read-EnvFile 'services/api/.env'
        $values = [ordered]@{
            APP_ORIGIN = $WebOrigin
            SUPABASE_URL = $api['SUPABASE_AUTH_ISSUER'] -replace '/auth/v1/?$', ''
            SUPABASE_PUBLISHABLE_KEY = $api['SUPABASE_PUBLISHABLE_KEY']
            API_BASE_URL = $ApiOrigin
        }
        # Same BOM hazard as the Fly step: redirect a BOM-free file via cmd.
        $file = [System.IO.Path]::GetTempFileName()
        try {
            foreach ($name in $values.Keys) {
                [System.IO.File]::WriteAllText($file, $values[$name], (New-Object System.Text.UTF8Encoding $false))
                & cmd /c "vercel env add $name production --force < `"$file`""
                if ($LASTEXITCODE) { throw "vercel env add $name failed" }
            }
        } finally { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
        & vercel deploy --prod --yes
        if ($LASTEXITCODE) { throw 'vercel deploy failed' }
    }
}
