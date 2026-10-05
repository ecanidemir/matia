# lint_error_log.ps1 - Hata hafiza dosyalarinin makine-kontrollu saglik taramasi.
#
# Kontrol eder (degisiklik YAPMAZ, sadece raporlar):
#   1. errors-log.md satir formati: `YYYY-MM-DD | parmakizi | kok neden -> cozum`
#   2. Kurate edilmemis [auto] satir sayisi (esik ustundeyse uyari)
#   3. Secret deseni taramasi (API key, sifre, token degeri) - dosyalarda olmamali
#   4. HOT.md satir siniri (<=30 veri satiri)
#
# Kullanim: push oncesi calistir. Cikis 0 = temiz, 1 = sorun var.
#   powershell -ExecutionPolicy Bypass -File scripts/lint_error_log.ps1

[CmdletBinding()]
param(
  [int]$AutoWarnAt = 5,
  [int]$HotMaxLines = 30
)

$ErrorActionPreference = "Stop"
$failures = @()
$warnings = @()

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($repoRoot)) { $repoRoot = (Get-Location).Path }
$logFile = Join-Path $repoRoot ".agents/memory/errors-log.md"
$hotFile = Join-Path $repoRoot ".agents/memory/HOT.md"

if (-not (Test-Path -LiteralPath $logFile)) { $failures += "errors-log.md bulunamadi: $logFile" }
else {
  $lines = Get-Content -LiteralPath $logFile -Encoding UTF8
  $data = @($lines | Where-Object { $_ -match "^\d{4}-\d{2}-\d{2} \|" })
  $auto = @($data | Where-Object { $_ -match "\[auto\]" })
  if ($auto.Count -ge $AutoWarnAt) { $warnings += ("kurate edilmemis [auto] satir: " + $auto.Count + " (esik " + $AutoWarnAt + ") - /log-error ile isle") }
  $badFormat = @($data | Where-Object { $_ -notmatch "^\d{4}-\d{2}-\d{2} \| [^|]+ \| .+ -> .+" })
  foreach ($b in $badFormat) { $failures += ("format disi satir: " + $b.Substring(0, [Math]::Min(100, $b.Length))) }
  $secretHits = @($lines | Where-Object { $_ -match "m0-[A-Za-z0-9]{10,}|sk-[A-Za-z0-9]{10,}|ghp_[A-Za-z0-9]{10,}|(PASSWORD|API_KEY)\s*=\s*\S+" })
  foreach ($s in $secretHits) { $failures += ("SECRET SUPHESI: " + $s.Substring(0, [Math]::Min(80, $s.Length))) }
  Write-Host ("[lint] errors-log.md: " + $data.Count + " veri satiri, " + $auto.Count + " [auto]")
}

if (-not (Test-Path -LiteralPath $hotFile)) { $warnings += "HOT.md bulunamadi" }
else {
  $hot = @((Get-Content -LiteralPath $hotFile -Encoding UTF8) | Where-Object { $_ -match "^\d{4}-\d{2}-\d{2} \|" })
  if ($hot.Count -gt $HotMaxLines) { $failures += ("HOT.md satir siniri asildi: " + $hot.Count + " > " + $HotMaxLines) }
  Write-Host ("[lint] HOT.md: " + $hot.Count + " desen satiri")
}

foreach ($w in $warnings) { Write-Host ("[lint] [!!] " + $w) -ForegroundColor Yellow }
foreach ($f in $failures) { Write-Host ("[lint] [XX] " + $f) -ForegroundColor Red }
if ($failures.Count -eq 0) { Write-Host "[lint] [OK] temiz" -ForegroundColor Green; exit 0 }
exit 1
