# Workspace .env'ini yukleyip opencode baslatir.
# Neden: opencode.json'daki {env:ODOO_*} degerleri yalnizca proses
# environment'indan okunur, workspace .env otomatik yuklenmez.
# Kullanim (opencode kapali iken, bu klasorde):
#   powershell -ExecutionPolicy Bypass -File scripts\start-opencode.ps1
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $workspace '.env'
if (-not (Test-Path -LiteralPath $envFile)) { Write-Error ".env bulunamadi: $envFile"; exit 1 }
Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
  if ($_ -match '^\s*([^#=\s][^=]*)=(.*)$') {
    Set-Item -Path ('env:' + $Matches[1].Trim()) -Value $Matches[2].Trim()
  }
}
Write-Host '.env yuklendi, opencode baslatiliyor...'
Set-Location -LiteralPath $workspace
& opencode
