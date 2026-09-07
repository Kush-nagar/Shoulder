$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
try {
    & ./scripts/infra.ps1 start
    if (!(Test-Path apps/web/.env.local)) { & ./scripts/bootstrap-auth.ps1 }
    & node apps/web/node_modules/next/dist/bin/next build apps/web
    if ($LASTEXITCODE) { throw 'Auth production build failed' }
    & node node_modules/@playwright/test/cli.js test --config playwright.auth.config.mjs
    if ($LASTEXITCODE) { throw 'Real local auth integration failed' }
    & ./scripts/infra.ps1 health
} finally {
    # Includes failure paths. Tests remove only their own synthetic Auth users/mail.
    & ./scripts/infra.ps1 stop
}
