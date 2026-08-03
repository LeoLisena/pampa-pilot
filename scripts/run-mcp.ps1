[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExecutable = Join-Path $projectRoot ".venv-pampapilot\Scripts\python.exe"
$bridgeConfigPath = Join-Path $projectRoot "reaper\bridge_config.local.json"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Falta el entorno del proyecto. Ejecute primero scripts\bootstrap.ps1."
}

if (Test-Path -LiteralPath $bridgeConfigPath) {
    $bridgeConfig = Get-Content -Raw -LiteralPath $bridgeConfigPath | ConvertFrom-Json
    if (-not $bridgeConfig.ipc_root) {
        throw "bridge_config.local.json no contiene ipc_root."
    }
    $env:PAMPAPILOT_IPC_ROOT = [string]$bridgeConfig.ipc_root
}
elseif (-not $env:PAMPAPILOT_IPC_ROOT) {
    $env:PAMPAPILOT_IPC_ROOT = Join-Path $projectRoot ".runtime\reaper-ipc"
}

Push-Location $projectRoot
try {
    & $pythonExecutable -m pampapilot.mcp_server
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
