$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Force -Path .\tools, .\vendor, .\.runtime | Out-Null
$cloudflared = Join-Path $PSScriptRoot 'tools\cloudflared.exe'
if (-not (Test-Path -LiteralPath $cloudflared)) {
    Write-Host 'Downloading cloudflared to G: ...'
    Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $cloudflared
}
if (-not (Test-Path -LiteralPath .\vendor\qrcode)) {
    Write-Host 'Installing the QR code library to G: ...'
    $env:TEMP = Join-Path $PSScriptRoot '.runtime'
    $env:TMP = $env:TEMP
    $env:PIP_CACHE_DIR = $env:TEMP
    & python -m pip install --disable-pip-version-check --no-cache-dir --no-deps --target .\vendor 'qrcode>=8,<9'
    if ($LASTEXITCODE -ne 0) { throw 'QR code library installation failed.' }
}
& $cloudflared --version
& python -c "import sys; sys.path.insert(0, 'vendor'); import qrcode; print('QR code library ready')"
