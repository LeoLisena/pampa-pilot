[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExecutable = Join-Path $projectRoot ".venv-pampapilot\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Falta el entorno del proyecto. Ejecute primero scripts\bootstrap.ps1."
}

Push-Location $projectRoot
try {
    & $pythonExecutable -m pampapilot.mcp_server
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
