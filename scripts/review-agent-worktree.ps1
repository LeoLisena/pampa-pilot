[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$WorkingDirectory,

    [switch]$SkipFullTests
)

$ErrorActionPreference = "Stop"
$target = (Resolve-Path $WorkingDirectory).Path
$branch = (& git -C $target branch --show-current 2>$null) -join ""
if ([string]::IsNullOrWhiteSpace($branch)) {
    throw "La ruta no es un worktree Git válido: $target"
}
if ($branch -notlike "local-llm/*") {
    throw "La revisión automática sólo acepta ramas local-llm/*. Rama actual: $branch"
}

$status = & git -C $target status --short
$baseCommit = (& git -C $target merge-base main HEAD 2>$null) -join ""
if ([string]::IsNullOrWhiteSpace($baseCommit)) {
    throw "No se pudo calcular la base común con main."
}

Write-Host "Revisión aislada"
Write-Host "Worktree: $target"
Write-Host "Rama: $branch"
Write-Host "Base común con main: $baseCommit"
Write-Host ""
Write-Host "Estado:"
if ($status) { $status | Write-Host } else { Write-Host "Sin cambios locales." }
Write-Host ""
Write-Host "Resumen del diff contra main:"
& git -C $target diff --stat main...HEAD
& git -C $target diff --stat

$validator = Join-Path $target "scripts\validate.ps1"
if (-not (Test-Path -LiteralPath $validator)) {
    throw "El worktree no contiene scripts/validate.ps1. Actualice la rama antes de revisarla."
}

Write-Host ""
Write-Host "Ejecutando validación del worktree..."
& $validator -SkipFullTests:$SkipFullTests
if ($LASTEXITCODE -ne 0) { throw "La validación del worktree falló." }

Write-Host ""
Write-Host "Revisión automática completada. Falta la revisión semántica del diff por Codex."
