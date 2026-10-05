# load_env.ps1 - Proje kokundeki .env dosyasini current PowerShell process'in
# environment'ina yukler. OpenCode dahil her child process bu env'i gorur.
#
# Kullanim (manuel, mevcut terminal icin):
#   . .\scripts\load_env.ps1
#
# Not: opencode.json'daki {env:ODOO_*} substitution'lari yalnizca proses
# environment'indan okunur; workspace .env OTOMATIK yuklenmez. Kalici cozum:
# opencode'u `scripts/start-opencode.ps1` ile baslat.
#
# Guvenlik: API key / sifre gibi secret degerler .env dosyasindadir ve
# .gitignore'da ignore edilir. Bu script sadece current process'e inject eder,
# disariya yazmaz.
#
# NOT: PowerShell 5.1 -match operatoru uzun string'lerde (5+ karakter) yanlis
# sonuc verebiliyor. Bu yuzden env name validation icin .NET Regex kullaniliyor.

$envFile = Join-Path $PSScriptRoot "..\.env"
$envFile = (Resolve-Path $envFile -ErrorAction SilentlyContinue).Path

if (-not $envFile -or -not (Test-Path $envFile)) {
    Write-Warning ".env dosyasi bulunamadi: $envFile"
    return
}

Add-Type -AssemblyName System.Text.RegularExpressions -ErrorAction SilentlyContinue
$envNamePattern = [System.Text.RegularExpressions.Regex]::new('^[A-Za-z_][A-Za-z0-9_]*$')

$loaded = 0
$skipped = 0
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) {
        $skipped++
        return
    }
    $idx = $line.IndexOf("=")
    if ($idx -le 0) {
        $skipped++
        return
    }
    $name = $line.Substring(0, $idx).Trim()
    $value = $line.Substring($idx + 1).Trim()
    if ($value.Length -ge 2) {
        $first = $value[0]
        $last = $value[$value.Length - 1]
        if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
    }
    if (-not $envNamePattern.IsMatch($name)) {
        $skipped++
        return
    }
    Set-Item -Path "Env:$name" -Value $value
    $loaded++
}

Write-Host "[load_env] $loaded env variable yuklendi, $skipped satir atlandi ($envFile)" -ForegroundColor Green
