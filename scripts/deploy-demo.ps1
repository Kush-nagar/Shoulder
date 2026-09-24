# Deploy the synthetic-data player demo (ADR 0021): remote migrations, demo
# team, API on Fly, web on Vercel. Run by the owner. Every secret is read from
# ignored env files and piped on stdin, so none reaches argv, logs, or Git.
#   .\scripts\deploy-demo.ps1 -Step migrate   # alembic upgrade + seed demo team
#   .\scripts\deploy-demo.ps1 -Step api       # Fly app, secrets, deploy
#   .\scripts\deploy-demo.ps1 -Step web       # Vercel env + production deploy
param(
    [Parameter(Mandatory)][ValidateSet('migrate', 'api', 'web')][string]$Step,
    [string]$FlyApp = 'shoulder-api-demo',
    [string]$WebOrigin = 'https://shoulder-demo.vercel.app',
    [string]$DemoTeamId
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

function Read-EnvFile([string]$Path) {
    $values = [ordered]@{}
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*#' -or !$line.Trim()) { continue }
        $pair = $line -split '=', 2
        $values[$pair[0].Trim()] = $pair[1]
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
        if (!$DemoTeamId) { throw 'Pass -DemoTeamId from the migrate step.' }
        $api = Read-EnvFile 'services/api/.env'
        $local = Read-EnvFile '.env.local'
        $secrets = [ordered]@{}
        foreach ($name in $api.Keys) { $secrets[$name] = $api[$name] }
        $secrets['OPENROUTER_API_KEY'] = $local['OPENROUTER_API_KEY']
        $secrets['DEMO_MODE'] = 'on'
        $secrets['DEMO_TEAM_ID'] = $DemoTeamId
        $secrets['APP_ORIGIN'] = $WebOrigin
        if (!(& fly apps list | Select-String -Quiet -SimpleMatch $FlyApp)) {
            & fly apps create $FlyApp
            if ($LASTEXITCODE) { throw 'fly apps create failed' }
        }
        ($secrets.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) |
            & fly secrets import --app $FlyApp --stage
        if ($LASTEXITCODE) { throw 'fly secrets import failed' }
        & fly deploy --app $FlyApp --remote-only
        if ($LASTEXITCODE) { throw 'fly deploy failed' }
        Write-Host "API: https://$FlyApp.fly.dev/health"
    }
    'web' {
        # The remote project, never the local stack in apps/web/.env.local.
        $api = Read-EnvFile 'services/api/.env'
        $values = [ordered]@{
            APP_ORIGIN = $WebOrigin
            SUPABASE_URL = $api['SUPABASE_AUTH_ISSUER'] -replace '/auth/v1/?$', ''
            SUPABASE_PUBLISHABLE_KEY = $api['SUPABASE_PUBLISHABLE_KEY']
            API_BASE_URL = "https://$FlyApp.fly.dev"
        }
        foreach ($name in $values.Keys) {
            $values[$name] | & vercel env add $name production --force
            if ($LASTEXITCODE) { throw "vercel env add $name failed" }
        }
        & vercel deploy --prod --yes
        if ($LASTEXITCODE) { throw 'vercel deploy failed' }
    }
}
