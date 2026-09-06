$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ((node --version) -ne 'v24.11.1') { throw 'Install Node.js 24.11.1 from https://nodejs.org/download/release/v24.11.1/ first.' }
New-Item -ItemType Directory -Force .tools | Out-Null
if (!(Test-Path .tools/uv.exe)) {
    Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/download/0.12.10/uv-x86_64-pc-windows-msvc.zip' -OutFile .tools/uv.zip
    if ((Get-FileHash .tools/uv.zip -Algorithm SHA256).Hash.ToLower() -ne 'f65744f94072152b1f86ba2aace4d01f1124d9a8ecb235805039e3718c36cac2') { throw 'uv checksum mismatch' }
    Expand-Archive .tools/uv.zip -DestinationPath .tools -Force
}
if ((& ./.tools/uv.exe --version) -notmatch '^uv 0\.12\.10 ') { throw 'Expected uv 0.12.10' }
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.tools/python'
$env:UV_CACHE_DIR = Join-Path $PWD '.cache/uv'
& ./.tools/uv.exe python install 3.11.16 --no-bin
if ($LASTEXITCODE) { throw 'Python installation failed' }
& ./.tools/uv.exe sync --locked
if ($LASTEXITCODE) { throw 'Python dependency installation failed' }
npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm install --frozen-lockfile
if ($LASTEXITCODE) { throw 'Web dependency installation failed' }
npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm exec playwright install chromium firefox webkit
if ($LASTEXITCODE) { throw 'Browser installation failed' }
