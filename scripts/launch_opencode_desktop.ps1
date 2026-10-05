# launch_opencode_desktop.ps1 - Masaustu kisayolunun hedefi (Matia).
# .env'i yukler, Mem0 on-kontrolu yapar (uyari amaçli), OpenCode Desktop'u baslatir.
# GUI ile acilan uygulamalara PowerShell profili islemez; bu baslatici o boslugu kapatir.

$ErrorActionPreference = "SilentlyContinue"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ([string]::IsNullOrWhiteSpace($repoRoot)) { $repoRoot = "C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia" }

$loadEnv = Join-Path $repoRoot "scripts/load_env.ps1"
if (Test-Path -LiteralPath $loadEnv) { . $loadEnv }

$check = Join-Path $repoRoot "scripts/check_mem0.ps1"
if (Test-Path -LiteralPath $check) { & $check }

$exe = Join-Path $env:LOCALAPPDATA "Programs/@opencode-aidesktop/OpenCode.exe"
if (-not (Test-Path -LiteralPath $exe)) {
  Write-Host ("[launch] [XX] OpenCode.exe bulunamadi: " + $exe) -ForegroundColor Red
  Write-Host "Devam etmek icin bir tusa basin..."; [void][Console]::ReadKey($true)
  exit 1
}

Write-Host "[launch] OpenCode Desktop baslatiliyor..." -ForegroundColor Green
# --start-maximized tek basina yetmedi: uygulama kendi pencere durumunu geri
# yukluyor. Bu yuzden Win32 ShowWindow ile maximize etmeye zorluyoruz.
Start-Process -FilePath $exe -WorkingDirectory $repoRoot -ArgumentList "--start-maximized"
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win32Max {
  [DllImport("user32.dll")]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
function Maximize-OpenCodeWindows {
  $done = $false
  foreach ($proc in (Get-Process | Where-Object { $_.ProcessName -like "*OpenCode*" })) {
    try { $proc.Refresh() } catch { continue }
    if ($proc.MainWindowHandle -ne [IntPtr]::Zero) {
      [void][Win32Max]::ShowWindow($proc.MainWindowHandle, 3)  # SW_MAXIMIZE
      [void][Win32Max]::SetForegroundWindow($proc.MainWindowHandle)
      $done = $true
    }
  }
  return $done
}
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
  if (Maximize-OpenCodeWindows) { break }
  Start-Sleep -Milliseconds 500
}
