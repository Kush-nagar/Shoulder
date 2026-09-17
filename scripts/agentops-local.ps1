# Start, stop, inspect and resume the local AgentOps runtime.
#
# `start` authorises local execution on this machine. That is a different
# permission from cloud autonomy, which lives in ops/policy.json, stays off,
# and is never written from here. `stop` withdraws the local authorisation.
#
# A thin argument map over `python -m services.agentops.cli`. It deliberately
# holds no logic of its own: two places that decide the same thing eventually
# decide it differently, and the one people would debug is this one.
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status', 'resume', 'dashboard', 'doctor',
                 'dry-run', 'models', 'evaluate')]
    [string]$Command = 'status',

    [switch]$Once,
    [int]$Iterations = 1,
    [string[]]$Models,
    [ValidateSet('fast', 'gated')]
    [string]$Verification = 'fast',
    [int]$Port
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo

# The repository pins an exact uv. The resolver in services/agentops/toolchain
# finds it; this only needs something able to import the package, so it asks
# the resolver through the same uv it is about to use.
$uv = if ($env:SHOULDER_UV_PATH) { $env:SHOULDER_UV_PATH }
      elseif (Test-Path "$repo/.tools/uv.exe") { "$repo/.tools/uv.exe" }
      elseif (Test-Path "$repo/.tools/uv") { "$repo/.tools/uv" }
      else { 'uv' }

function Invoke-AgentOps([string[]]$CliArgs) {
    & $uv @('run', '--locked', 'python', '-m', 'services.agentops.cli') + $CliArgs
    if ($LASTEXITCODE) { throw "agentops $($CliArgs -join ' ') failed with $LASTEXITCODE" }
}

switch ($Command) {
    'start' {
        # Typing this command is the local authorisation. It is recorded in
        # ignored local state and never touches ops/policy.json, so cloud
        # autonomy stays exactly as it was.
        $arguments = @('run', '--enable', '--iterations', "$Iterations",
                       '--verification', $Verification)
        if ($Once) { $arguments += '--once' }
        Invoke-AgentOps $arguments
    }
    'stop' { Invoke-AgentOps @('stop') }
    'status' { Invoke-AgentOps @('local-status') }
    'resume' { Invoke-AgentOps @('resume') }
    'doctor' { Invoke-AgentOps @('doctor') }
    'dry-run' { Invoke-AgentOps @('dry-run') }
    'models' { Invoke-AgentOps @('models') }
    'evaluate' {
        if (-not $Models) { throw 'evaluate needs -Models <id> [<id>...]' }
        Invoke-AgentOps (@('evaluate') + $Models)
    }
    'dashboard' {
        $arguments = @('serve')
        if ($Port) { $arguments += @('--port', "$Port") }
        Invoke-AgentOps $arguments
    }
}
