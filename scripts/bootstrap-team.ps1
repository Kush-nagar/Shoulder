# Create the one initial team and its coach membership. Operator-only; the
# token comes from the running .\scripts\dev.ps1 session.
param(
    [Parameter(Mandatory)][string]$CoachUserId,
    [Parameter(Mandatory)][string]$Token,
    [string]$Name = 'Local Test Team',
    [string]$SeasonLabel = 'Local season',
    [string]$AgeGroup = 'U14'
)
$ErrorActionPreference = 'Stop'
$body = @{
    coach_user_id = $CoachUserId
    name          = $Name
    season_label  = $SeasonLabel
    season_end_at = (Get-Date).AddMonths(6).ToUniversalTime().ToString('o')
    age_group     = $AgeGroup
} | ConvertTo-Json
$response = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/v1/teams' `
    -ContentType 'application/json' -Headers @{ 'X-Operator-Token' = $Token } -Body $body
Write-Host "Team created: $($response.team_id)"
