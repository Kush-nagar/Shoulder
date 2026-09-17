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
                 'dry-run', 'models', 'evaluate', 'project')]
    [string]$Command = 'status',

    [switch]$Once,
    [int]$Iterations = 1,
    [string[]]$Models,
    [ValidateSet('fast', 'gated')]
    [string]$Verification = 'fast',
    [int]$Port,
    [string]$Repo,
    [int]$MaxTasks
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
    # Build the whole argument array first, then splat it. Writing
    # `& $uv @(...) + $CliArgs` puts the `+` in argument mode, where it is not
    # an operator: uv received a literal "+" and every wrapper command was
    # malformed.
    $all = @('run', '--locked', 'python', '-m', 'services.agentops.cli') + $CliArgs
    & $uv @all
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
    'project' {
        # Works the canonical backlog end to end: implement, review, verify,
        # pull request, required CI, required review, repair, merge, reconcile,
        # next task. It stops on a named blocker rather than improvising, and
        # never force-merges, resets, stashes or discards anything.
        $arguments = @('project', '--verification', $Verification)
        if ($Repo) { $arguments += @('--repo', $Repo) }
        if ($MaxTasks) { $arguments += @('--max-tasks', "$MaxTasks") }
        Invoke-AgentOps $arguments
    }
    'stop' { Invoke-AgentOps @('stop') }
    'status' { Invoke-AgentOps @('local-status') }
    'resume' { Invoke-AgentOps @('resume') }
    'doctor' { Invoke-AgentOps @('doctor') }
    'dry-run' { Invoke-AgentOps @('dry-run') }
    'models' { Invoke-AgentOps @('models') }
    'evaluate' {
        # A comma-separated list arrives as one token when the script is run
        # with -File rather than from an interactive prompt, so split it here
        # and accept both spellings.
        $ids = @($Models | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
        if (-not $ids) { throw 'evaluate needs -Models <id>[,<id>...]' }
        Invoke-AgentOps (@('evaluate') + $ids)
    }
    'dashboard' {
        $arguments = @('serve')
        if ($Port) { $arguments += @('--port', "$Port") }
        Invoke-AgentOps $arguments
    }
}
