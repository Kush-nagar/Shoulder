# Start or resume Shoulder AgentOps, with the dashboard, from one command.
#
#     cd D:\Shoulder
#     .\agentops.ps1
#
# This is the deterministic part of the system and nothing more. It launches
# processes, watches whether they are alive, decides whether a stop is worth
# retrying, and preserves the checkpoint across a restart. It makes no
# engineering decision: which task runs, which model writes it, what gets
# committed and what blocks are all decided by the coordinator in
# services/agentops, which this script only starts.
#
# It holds no logic that already lives in the CLI. Everything here is process
# lifecycle, because two places that decide the same thing eventually decide it
# differently, and the one people would debug is this one.
[CmdletBinding()]
param(
    # 'gated' runs the full required verification before a pull request.
    [ValidateSet('fast', 'gated')]
    [string]$Verification = 'gated',

    [int]$Port,

    # owner/name. Left unset, the CLI asks git for the origin remote.
    [string]$Repo,

    # Stop after this many merged tasks instead of working the whole backlog.
    [int]$MaxTasks,

    # Bring the dashboard up and print the URL, then exit without working.
    [switch]$DashboardOnly,

    # How many times a crash or a provider wait may be restarted before this
    # hands the question back to a person.
    [int]$MaxRestarts = 24
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
Set-Location $repoRoot

$localDir = Join-Path $repoRoot '.agentops/local'
$projectState = Join-Path $localDir 'project.json'
$runtimeState = Join-Path $localDir 'runtime.json'

# The repository pins an exact uv; services/agentops/toolchain resolves it.
$uv = if ($env:SHOULDER_UV_PATH) { $env:SHOULDER_UV_PATH }
      elseif (Test-Path "$repoRoot/.tools/uv.exe") { "$repoRoot/.tools/uv.exe" }
      elseif (Test-Path "$repoRoot/.tools/uv") { "$repoRoot/.tools/uv" }
      else { 'uv' }

function Get-Json([string]$Path) {
    if (-not (Test-Path $Path)) { return $null }
    try { Get-Content $Path -Raw | ConvertFrom-Json } catch { $null }
}

function Test-ProcessAlive([int]$Pid, [string]$Image) {
    # Same question localstate.process_alive answers, and for the same reason:
    # a pid on its own can have been reused, and treating an unrelated process
    # as the coordinator would refuse to start forever.
    if (-not $Pid -or $Pid -le 0) { return $false }
    $process = Get-Process -Id $Pid -ErrorAction SilentlyContinue
    if (-not $process) { return $false }
    if ($Image) { return $process.ProcessName -like "*$([IO.Path]::GetFileNameWithoutExtension($Image))*" }
    return $true
}

function Get-DashboardEndpoint {
    $config = Get-Json (Join-Path $localDir 'config.json')
    $configuredHost = if ($config -and $config.dashboard.host) { $config.dashboard.host } else { '127.0.0.1' }
    $configuredPort = if ($Port) { $Port }
                      elseif ($config -and $config.dashboard.port) { $config.dashboard.port }
                      else { 4317 }
    return @{ Host = $configuredHost; Port = [int]$configuredPort }
}

function Test-DashboardUp([string]$EndpointHost, [int]$EndpointPort) {
    try {
        $probe = New-Object Net.Sockets.TcpClient
        $probe.Connect($EndpointHost, $EndpointPort)
        $probe.Close()
        return $true
    } catch { return $false }
}

function Start-Dashboard {
    $endpoint = Get-DashboardEndpoint
    if (Test-DashboardUp $endpoint.Host $endpoint.Port) {
        return @{ Url = "http://$($endpoint.Host):$($endpoint.Port)"; Started = $false }
    }
    $serveArgs = @('run', '--locked', 'python', '-m', 'services.agentops.cli', 'serve')
    if ($Port) { $serveArgs += @('--port', "$Port") }
    # Its own window would need a terminal nobody is watching; its output is
    # the dashboard itself, so it is discarded rather than interleaved with the
    # coordinator's.
    $process = Start-Process -FilePath $uv -ArgumentList $serveArgs `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    foreach ($attempt in 1..40) {
        Start-Sleep -Milliseconds 250
        if (Test-DashboardUp $endpoint.Host $endpoint.Port) {
            return @{ Url = "http://$($endpoint.Host):$($endpoint.Port)"; Started = $true; Process = $process }
        }
        if ($process.HasExited) { break }
    }
    return @{ Url = $null; Started = $false; Process = $process }
}

function Invoke-AgentOps([string[]]$CliArgs) {
    $all = @('run', '--locked', 'python', '-m', 'services.agentops.cli') + $CliArgs
    & $uv @all
    return $LASTEXITCODE
}

# --- One coordinator at a time -------------------------------------------
# One write-capable owner per checkout is the invariant the whole system rests
# on. A second coordinator here would take a second lease and put two writers
# in the same worktrees, so this refuses rather than racing.
$runtime = Get-Json $runtimeState
if ($runtime -and $runtime.state -eq 'running' -and (Test-ProcessAlive ([int]$runtime.pid) $runtime.image)) {
    Write-Host "A Shoulder AgentOps coordinator is already running (pid $($runtime.pid))." -ForegroundColor Yellow
    Write-Host "Stop it with .\scripts\agentops-local.ps1 stop, or watch it on the dashboard."
    $existing = Get-DashboardEndpoint
    Write-Host "Dashboard: http://$($existing.Host):$($existing.Port)"
    exit 0
}

# --- Dashboard ------------------------------------------------------------
$dashboard = Start-Dashboard
Write-Host ''
Write-Host 'Shoulder AgentOps running' -ForegroundColor Green
if ($dashboard.Url) {
    Write-Host "Dashboard: $($dashboard.Url)"
} else {
    # Not fatal. The dashboard reports work; it does not perform any, and
    # refusing to work because the read-only view failed to bind would be the
    # wrong trade.
    Write-Host 'Dashboard: unavailable (the coordinator still runs; see .agentops/local/events.jsonl)' -ForegroundColor Yellow
}
Write-Host ''

if ($DashboardOnly) { exit 0 }

# --- Local authorisation -------------------------------------------------
# Typing this command is the authorisation to execute locally, exactly as
# `agentops-local.ps1 start` is. It is recorded in ignored local state. Cloud
# autonomy lives in ops/policy.json, stays off, and is never written here.
$null = Invoke-AgentOps @('enable-local')

# --- Resume, then work ---------------------------------------------------
# What the last run left behind, printed before anything moves: the task, the
# branch, the worktree, the pull request, and any provider still cooling down.
# Nothing here discards any of it.
Invoke-AgentOps @('resume') | Out-Host

$projectArgs = @('project', '--verification', $Verification)
if ($Repo) { $projectArgs += @('--repo', $Repo) }
if ($MaxTasks) { $projectArgs += @('--max-tasks', "$MaxTasks") }

$restarts = 0
while ($true) {
    $code = Invoke-AgentOps $projectArgs

    # The durable record, not the exit code, says what happened: it survives a
    # crash that never reached an exit code at all.
    $state = Get-Json $projectState
    $status = if ($state) { $state.status } else { '' }
    $detail = if ($state) { $state.detail } else { '' }

    if ($status -eq 'PROJECT_COMPLETE') {
        Write-Host ''
        Write-Host 'PROJECT_COMPLETE — every canonical task is complete.' -ForegroundColor Green
        exit 0
    }

    # A decision belongs to a person. Restarting would spend allowance to
    # arrive at the same stop, so this prints it and gets out of the way.
    if ($status -in @('BLOCKED_HUMAN', 'BLOCKED_LOCAL_CHECKOUT')) {
        Write-Host ''
        Write-Host "Stopped: $status" -ForegroundColor Yellow
        Write-Host "  $detail"
        Write-Host 'The work is intact. Nothing was discarded, reset, or force-merged.'
        exit 1
    }

    if ($restarts -ge $MaxRestarts) {
        Write-Host ''
        Write-Host "Stopped after $restarts restarts: $status $detail" -ForegroundColor Yellow
        exit 1
    }
    $restarts++

    # Two things reach here, and both are worth another pass rather than a
    # person: every provider is out of allowance, and the coordinator died
    # without recording a stop. The checkpoint is already on disk, so the next
    # pass re-derives its position from Git, GitHub and the lease ledger and
    # continues the task instead of restarting it.
    if ($status -eq 'BLOCKED_WAITING_PROVIDER') {
        Write-Host ''
        Write-Host "Every provider is out of allowance. Waiting 15 minutes (restart $restarts/$MaxRestarts)." -ForegroundColor Yellow
        Start-Sleep -Seconds 900
    } else {
        Write-Host ''
        Write-Host "Coordinator exited with $code and status '$status'. Resuming from the checkpoint (restart $restarts/$MaxRestarts)." -ForegroundColor Yellow
        Start-Sleep -Seconds 20
    }
}
