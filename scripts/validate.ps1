[CmdletBinding()]
param(
    [switch]$SkipFullTests
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExecutable = Join-Path $projectRoot ".venv-pampapilot\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "El entorno no existe. Ejecute primero .\scripts\bootstrap.ps1"
}

Push-Location $projectRoot
try {
    Write-Host "Verificando el diff de Git..."
    & git diff --check
    if ($LASTEXITCODE -ne 0) { throw "git diff --check encontró errores." }

    Write-Host "Compilando los módulos Python..."
    & $pythonExecutable -m compileall -q src scripts
    if ($LASTEXITCODE -ne 0) { throw "La compilación de Python falló." }

    if (-not $SkipFullTests) {
        Write-Host "Ejecutando la suite completa..."
        & $pythonExecutable -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw "La suite de tests falló." }
    }

    Write-Host "Validación completada correctamente."
}
finally {
    Pop-Location
}
