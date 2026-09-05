$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$uv = if ($IsLinux -or $IsMacOS) { 'uv' } else { './.tools/uv.exe' }
$pnpm = if ($IsLinux -or $IsMacOS) { 'pnpm' } else { 'pnpm.cmd' }
function Invoke-Check([string]$program, [string[]]$arguments) {
    Write-Host "$program $($arguments -join ' ')"
    & $program @arguments
    if ($LASTEXITCODE) { throw "Check failed: $program $($arguments -join ' ')" }
}
# npm exec supplies the exact package manager locally; CI provides the same pinned binary.
if (!($IsLinux -or $IsMacOS)) {
    $pnpm = 'npm.cmd'
    $prefix = @('exec', '--yes', '--package=pnpm@11.25.0', '--', 'pnpm')
} else { $prefix = @() }
foreach ($step in @('format:check', 'lint', 'typecheck', 'test')) {
    Invoke-Check $pnpm ($prefix + @($step))
}
Invoke-Check $uv @('run', '--locked', 'ruff', 'format', '--check', '.')
Invoke-Check $uv @('run', '--locked', 'ruff', 'check', '.')
Invoke-Check $uv @('run', '--locked', 'mypy')
Invoke-Check $uv @('run', '--locked', 'python', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py')
$before = Get-FileHash packages/contracts/openapi.json,packages/contracts/api.d.ts
Invoke-Check $uv @('run', '--locked', 'python', '-m', 'scripts.export_openapi')
Invoke-Check $pnpm ($prefix + @('contracts'))
$after = Get-FileHash packages/contracts/openapi.json,packages/contracts/api.d.ts
if (Compare-Object $before.Hash $after.Hash) { throw 'Generated API contracts drifted; regenerate and review them.' }
Invoke-Check $pnpm ($prefix + @('build'))
Invoke-Check $pnpm ($prefix + @('smoke'))
Invoke-Check 'git' @('diff', '--check')
