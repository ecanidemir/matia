# .env dosyasini PowerShell environment'ina yukler
# Kullanim: . .\scripts\load_env.ps1  (dot-source ile)

$envFile = Join-Path -Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) -ChildPath ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*([^#=]+)=(.*)$") {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            Set-Item -Path "env:$key" -Value $value
        }
    }
    Write-Host ".env loaded - $envFile"
} else {
    Write-Warning ".env not found at $envFile"
}
