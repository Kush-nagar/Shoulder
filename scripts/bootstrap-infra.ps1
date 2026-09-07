$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force .tools/supabase | Out-Null
$archive = '.tools/supabase.zip'
$checksum = 'd88832770615c915e1782af99ba6475afcfdc026f939214940f7eea9aaa2341e'
if (!(Test-Path $archive)) {
    Invoke-WebRequest 'https://github.com/supabase/cli/releases/download/v2.116.0/supabase_2.116.0_windows_amd64.zip' -OutFile $archive
}
if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLower() -ne $checksum) { throw 'Supabase archive checksum mismatch' }
Expand-Archive $archive .tools/supabase -Force
$env:SUPABASE_HOME = Join-Path $PWD '.tools/supabase-home'
& .tools/supabase/supabase.exe telemetry disable
if ($LASTEXITCODE) { throw 'Supabase setup failed' }
if ((& .tools/supabase/supabase.exe --version) -ne '2.116.0') { throw 'Expected Supabase CLI 2.116.0' }
if (!(Test-Path .env.local)) {
    $bytes = New-Object byte[] 32
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($bytes) } finally { $random.Dispose() }
    $password = [BitConverter]::ToString($bytes).Replace('-', '').ToLower()
    @("MINIO_ROOT_USER=shoulder-local", "MINIO_ROOT_PASSWORD=$password") | Set-Content .env.local
}
Write-Host 'Local CLI ready; generated credentials stay in ignored .env.local.'
