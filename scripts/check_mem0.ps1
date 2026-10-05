# check_mem0.ps1 - Mem0 bulut hafizasinin canli on-kontrolu (read-only, secret yazdirmaz).
#
# Ne yapar:
#   1. MEM0_API_KEY process env'de tanimli mi? (opencode plugin anahtari buradan okur)
#   2. Anahtar gecerli mi? Ayirt edici test: SAHTE anahtar 401 vermeli, GERCEK anahtar
#      401 DISI (400/200) vermeli. Ikisi de 401 ise ag/sunucu sorunu; sadece gercek
#      401 ise anahtar gecersiz/iptal edilmis demektir.
#
# Kullanim:
#   powershell -ExecutionPolicy Bypass -File scripts/check_mem0.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/start-opencode.ps1  # env'li baslatma
#
# Cikis kodlari: 0 = saglikli, 1 = anahtar gecersiz/sunucu hatasi, 2 = anahtar eksik.
# Guvenlik: anahtar degeri ASLA ekrana/loga yazilmaz (uzunluk dahi yazilmaz).

[CmdletBinding()]
param(
  [int]$TimeoutSec = 30
)

$ErrorActionPreference = "Stop"

$key = $env:MEM0_API_KEY
if ([string]::IsNullOrWhiteSpace($key)) {
  Write-Host "[check_mem0] [XX] MEM0_API_KEY process env'de YOK." -ForegroundColor Red
  Write-Host "  Cozum sirasi:" -ForegroundColor Yellow
  Write-Host "    1. Repo kokunde: powershell -ExecutionPolicy Bypass -File scripts/start-opencode.ps1"
  Write-Host "       (dogrudan 'opencode' komutu workspace .env'i yuklemez)"
  Write-Host "    2. Yeni makine: powershell -File scripts/setup_new_machine.ps1"
  Write-Host "  Not: dosya logu (.agents/memory/errors-log.md) calismaya devam eder,"
  Write-Host "  ama add_memory/search_memories 401 verir."
  exit 2
}
$key = $key.Trim()
Write-Host "[check_mem0] MEM0_API_KEY tanimli, canli dogrulama yapiliyor..." -ForegroundColor Cyan

Add-Type -AssemblyName System.Net.Http
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.AllowAutoRedirect = $false
$http = New-Object System.Net.Http.HttpClient($handler)
$http.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)

function Test-Key($k) {
  try {
    $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, "https://api.mem0.ai/v1/memories/?page=1&page_size=1")
    $req.Headers.Add("Authorization", "Token " + $k)
    $r = $http.SendAsync($req).Result
    return [int]$r.StatusCode
  }
  catch {
    Write-Host ("[check_mem0] [XX] Ag hatasi: " + $_.Exception.Message) -ForegroundColor Red
    return -1
  }
}

$fakeCode = Test-Key "INVALID-KEY-PROBE"
$realCode = Test-Key $key
Write-Host ("[check_mem0] sahte anahtar => HTTP " + $fakeCode + " (401 beklenir)")
Write-Host ("[check_mem0] gercek anahtar => HTTP " + $realCode + " (401 DISI beklenir: 400/200)")

if ($fakeCode -ne 401) {
  Write-Host "[check_mem0] [XX] Sunucu beklenmedik cevap veriyor (sahte anahtar 401 almadi)." -ForegroundColor Red
  Write-Host "  https://app.mem0.ai dashboard veya ag baglantisini kontrol et."
  exit 1
}
if ($realCode -eq 401) {
  Write-Host "[check_mem0] [XX] Anahtar GECERSIZ/IPTAL (401)." -ForegroundColor Red
  Write-Host "  Cozum: https://app.mem0.ai/dashboard/api-keys adresinden yeni anahtar uret,"
  Write-Host "  kullanici ortam degiskenine yaz + opencode'u restart et."
  Write-Host "  (Detay: scripts/setup_new_machine.ps1 adim 2)"
  exit 1
}
if ($realCode -lt 0) { exit 1 }

Write-Host "[check_mem0] [OK] Mem0 canli: auth gecerli, write+search kullanilabilir." -ForegroundColor Green
exit 0
