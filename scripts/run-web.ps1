[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [switch]$ServeOnLocalNetwork
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExecutable = Join-Path $projectRoot ".venv-pampapilot\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "El entorno no existe. Ejecute primero .\scripts\bootstrap.ps1"
}

$env:PAMPAPILOT_WEB_HOST = if ($ServeOnLocalNetwork) { "0.0.0.0" } else { "127.0.0.1" }
$env:PAMPAPILOT_WEB_PORT = "$Port"

Write-Host "Iniciando PampaPilot..."
if ($ServeOnLocalNetwork) {
    Write-Host "Modo LAN activo. Use http://<IP-de-esta-PC>:$Port desde otra computadora."
    Write-Warning "Use token en LM Studio y una red privada confiable. HTTP no cifra el tráfico."
} else {
    Write-Host "Abra http://127.0.0.1:$Port"
}

Push-Location $projectRoot
try {
    & $pythonExecutable -m pampapilot.web_server
}
finally {
    Pop-Location
}
