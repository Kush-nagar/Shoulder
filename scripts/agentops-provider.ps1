# Show or switch the provider local workers run against.
#
#   ./scripts/agentops-provider.ps1 claude
#   ./scripts/agentops-provider.ps1 openrouter
#   ./scripts/agentops-provider.ps1 status
#
# The OpenRouter key is never stored, never printed and never committed. It is
# read from the environment of the shell that starts a worker, so enabling the
# lane means setting it there:
#
#   $env:OPENROUTER_API_KEY = '<key>'
#
# Without it the lane reports AVAILABLE_LATER, which is a state to fix rather
# than a failure to recover from.
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'claude', 'openrouter')]
    [string]$Choice = 'status'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo

$uv = if ($env:SHOULDER_UV_PATH) { $env:SHOULDER_UV_PATH }
      elseif (Test-Path "$repo/.tools/uv.exe") { "$repo/.tools/uv.exe" }
      elseif (Test-Path "$repo/.tools/uv") { "$repo/.tools/uv" }
      else { 'uv' }

& $uv @('run', '--locked', 'python', '-m', 'services.agentops.cli', 'provider', $Choice)
if ($LASTEXITCODE) { throw "provider $Choice failed with $LASTEXITCODE" }
