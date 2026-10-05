# Yeni makine / klasor tasima sonrasi kurulum script'i (idempotent, tekrar calistirilabilir).
#
# Yaptiklari:
#   1. Gerekli araclari kontrol eder (opencode, node/npx, uvx).
#   2. MEM0_API_KEY kullanici ortam degiskenini kontrol eder, yoksa ister ve kalici kaydeder.
#   3. Proje opencode.json icindeki makineye-ozel mutlak yollari bu klasore gore duzeltir.
#   4. Global opencode.json'a @mem0/opencode-plugin girdisini ekler (yoksa).
#   5. Global error-memory skill'ini repo'daki kanonik kopyadan kurar (.agents/bootstrap/).
#   6. Global AGENTS.md'ye memory rituelini ekler (yoksa, marker ile).
#   7. .env yoksa .env.example'dan olusturur (icini doldurman gerekir).
#
# Kullanim (yeni makinede, repo kokunde):
#   powershell -ExecutionPolicy Bypass -File scripts/setup_new_machine.ps1
# Sadece kontrol (degisiklik yapmadan):
#   powershell -ExecutionPolicy Bypass -File scripts/setup_new_machine.ps1 -DryRun
#
# NOT: Bu proje Odoo 15 (matia.odoobulut.com), tek canli instance, XML-RPC, SSH yok.
# SSH key / staging-prod / postgres tuneli adimlari bilerek YOKTUR.

[CmdletBinding()]
param(
  [string]$RepoRoot = "",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$failures = @()

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
  $invPath = $MyInvocation.MyCommand.Path
  if (-not [string]::IsNullOrWhiteSpace($invPath)) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $invPath) }
  else { $RepoRoot = (Get-Location).Path }
}

function Step($msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red; $script:failures += $msg }

if ($DryRun) { Write-Host "(DRY-RUN: degisiklik yapilmayacak)" -ForegroundColor Magenta }

# --- 1. Arac kontrolleri ---
Step "1/7 Araclar"
foreach ($tool in @("opencode", "node", "npx", "uvx")) {
  if (Get-Command $tool -ErrorAction SilentlyContinue) { Ok "$tool bulundu" }
  else { Fail "$tool bulunamadi (PATH'te yok)" }
}

# --- 2. Ortam degiskenleri (makine-seviyesi, repo DISI) ---
Step "2/7 Ortam degiskenleri"
foreach ($name in @("MEM0_API_KEY")) {
  $val = [Environment]::GetEnvironmentVariable($name, "User")
  if ([string]::IsNullOrWhiteSpace($val)) { $val = [Environment]::GetEnvironmentVariable($name, "Machine") }
  if ([string]::IsNullOrWhiteSpace($val)) { $val = [Environment]::GetEnvironmentVariable($name, "Process") }
  if ([string]::IsNullOrWhiteSpace($val)) {
    if ($DryRun) { Warn "$name yok (DryRun: sorulmadi)" }
    else {
      $entered = Read-Host "  $name bulunamadi, yapistir (bos birakilabilir)"
      if (-not [string]::IsNullOrWhiteSpace($entered)) {
        [Environment]::SetEnvironmentVariable($name, $entered.Trim(), "User")
        [Environment]::SetEnvironmentVariable($name, $entered.Trim(), "Process")
        Ok "$name kullanici ortamina kaydedildi"
      }
      else { Fail "$name bos birakildi - Mem0 hafizasi calismaz (dosya logu calisir)" }
    }
  }
  else { Ok "$name tanimli (degeri gosterilmiyor)" }
}

# --- 2b. Mem0 canli dogrulama (read-only, secret yazdirmaz) ---
Step "2b/7 Mem0 canli dogrulama"
$checkMem0 = Join-Path $RepoRoot "scripts/check_mem0.ps1"
if (-not (Test-Path -LiteralPath $checkMem0)) { Warn "check_mem0.ps1 yok - canli dogrulama atlandi" }
elseif ($DryRun) { Warn "canli Mem0 dogrulamasi calistirilirdi (check_mem0.ps1)" }
else {
  try {
    & $checkMem0
    if ($LASTEXITCODE -eq 0) { Ok "Mem0 canli (auth gecerli)" }
    elseif ($LASTEXITCODE -eq 2) { Fail "MEM0_API_KEY process env'de yok - scripts/start-opencode.ps1 ile baslat" }
    else { Fail "Mem0 auth basarisiz (401) - anahtari https://app.mem0.ai/dashboard/api-keys adresinden yenile" }
  }
  catch { Fail "Mem0 dogrulama calismadi: $($_.Exception.Message)" }
}

# --- 3. Proje opencode.json ---
Step "3/7 Proje opencode.json"
$projConfig = Join-Path $RepoRoot "opencode.json"
if (-not (Test-Path -LiteralPath $projConfig)) { Fail "opencode.json bulunamadi: $projConfig" }
else {
  try {
    $null = (Get-Content -LiteralPath $projConfig -Raw) | ConvertFrom-Json
    Ok "opencode.json gecerli JSON"
  }
  catch { Fail "opencode.json JSON hatasi: $($_.Exception.Message)" }
}
foreach ($d in @(".opencode/plugins", ".opencode/tools", ".opencode/commands", ".opencode/agents", ".agents/memory", ".agents/workflows")) {
  if (Test-Path -LiteralPath (Join-Path $RepoRoot $d)) { Ok "$d mevcut" }
  else { Fail "$d eksik (repo tam kopyalanmamis olabilir)" }
}

# --- 4. Global opencode.json plugin girdisi ---
Step "4/7 Global opencode.json (Mem0 plugin)"
$globalConfig = Join-Path $HOME ".config/opencode/opencode.json"
if (-not (Test-Path -LiteralPath $globalConfig)) { Fail "global config yok: $globalConfig (opencode en az bir kez calismali)" }
elseif ((Get-Content -LiteralPath $globalConfig -Raw) -match "mem0/opencode-plugin") { Ok "Mem0 plugin girdisi mevcut" }
else {
  if ($DryRun) { Warn "Mem0 plugin girdisi eklenirdi" }
  else {
    $g = Get-Content -LiteralPath $globalConfig -Raw | ConvertFrom-Json
    if ($null -eq $g.plugin) { $g | Add-Member -NotePropertyName "plugin" -NotePropertyValue @() }
    $g.plugin += "@mem0/opencode-plugin"
    $g | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $globalConfig -Encoding UTF8
    Ok "Mem0 plugin girdisi eklendi (opencode restart gerekir)"
  }
}

# --- 5. Global error-memory skill (kanonik kopya repo'dan) ---
Step "5/7 Global error-memory skill"
$canon = Join-Path $RepoRoot ".agents/bootstrap/error-memory-SKILL.md"
$destDir = Join-Path $HOME ".config/opencode/skills/error-memory"
$dest = Join-Path $destDir "SKILL.md"
if (-not (Test-Path -LiteralPath $canon)) { Fail "kanonik skill yok: $canon" }
else {
  $srcRaw = Get-Content -LiteralPath $canon -Raw
  $needsCopy = $true
  if (Test-Path -LiteralPath $dest) {
    $needsCopy = (Get-Content -LiteralPath $dest -Raw) -ne $srcRaw
  }
  if (-not $needsCopy) { Ok "skill guncel" }
  elseif ($DryRun) { Warn "skill kopyalanirdi: $dest" }
  else {
    if (-not (Test-Path -LiteralPath $destDir)) { New-Item -ItemType Directory -Path $destDir | Out-Null }
    Set-Content -LiteralPath $dest -Value $srcRaw -Encoding UTF8
    Ok "skill kuruldu/guncellendi"
  }
}

# --- 6. Global AGENTS.md ritueli ---
Step "6/7 Global AGENTS.md ritueli"
$ritualSrc = Join-Path $RepoRoot ".agents/bootstrap/global-memory-ritual.md"
$globalAgents = Join-Path $HOME ".config/opencode/AGENTS.md"
if (-not (Test-Path -LiteralPath $ritualSrc)) { Fail "rituel sablonu yok: $ritualSrc" }
elseif (-not (Test-Path -LiteralPath $globalAgents)) { Fail "global AGENTS.md yok: $globalAgents" }
elseif ((Get-Content -LiteralPath $globalAgents -Raw) -match "ODOO-HUB-MEMORY-RITUAL-START") { Ok "rituel zaten mevcut" }
else {
  if ($DryRun) { Warn "rituel global AGENTS.md sonuna eklenirdi" }
  else {
    Add-Content -LiteralPath $globalAgents -Value ("`n" + (Get-Content -LiteralPath $ritualSrc -Raw)) -Encoding UTF8
    Ok "rituel eklendi"
  }
}

# --- 7. .env ---
Step "7/7 .env"
$envFile = Join-Path $RepoRoot ".env"
$envExample = Join-Path $RepoRoot ".env.example"
if (Test-Path -LiteralPath $envFile) { Ok ".env mevcut" }
elseif (-not (Test-Path -LiteralPath $envExample)) { Fail ".env.example yok" }
elseif ($DryRun) { Warn ".env, .env.example'dan olusturulurdu (icini doldur)" }
else {
  Copy-Item -LiteralPath $envExample -Destination $envFile
  Warn ".env olusturuldu - DEGERLERI DOLDURMAN GEREKIR"
}

Write-Host ""
if ($failures.Count -eq 0) { Write-Host "TAMAM - kurulum saglikli." -ForegroundColor Green }
else {
  Write-Host "EKSIKLER ($($failures.Count)):" -ForegroundColor Red
  $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
  exit 1
}
