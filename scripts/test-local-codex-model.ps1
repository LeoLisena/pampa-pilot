[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Model,

    [ValidateSet("smoke", "reasoning")]
    [string]$Mode = "smoke",

    [string]$WorkingDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($WorkingDirectory)) {
    $WorkingDirectory = $projectRoot
}
$WorkingDirectory = (Resolve-Path $WorkingDirectory).Path
$launcher = Join-Path $projectRoot "scripts\start-local-codex.ps1"
$resultRoot = Join-Path $projectRoot ".runtime\model-evaluations"
New-Item -ItemType Directory -Force -Path $resultRoot | Out-Null

$prompt = if ($Mode -eq "smoke") {
@"
Esta es una evaluación read-only de herramientas. No modifiques archivos.
1. Ejecutá git branch --show-current.
2. Leé pyproject.toml e identificá project.name.
3. Ejecutá .\.venv-pampapilot\Scripts\python.exe -m pytest tests\test_agent_protocol.py -q.
Respondé al final con tres líneas: BRANCH, PROJECT y TEST_RESULT. No declares éxito si el comando no pasó.
"@
}
else {
@"
Esta es una evaluación read-only de razonamiento. No modifiques archivos.
Leé src/pampapilot/mastering_qc.py, knowledge/mastering/spotify-delivery-qc.yaml y tests/test_mastering_qc.py.
Explicá tres riesgos concretos de generalizar el sistema a múltiples perfiles sin inventar datos de otras plataformas. Para cada riesgo citá el archivo o función que lo demuestra. No ejecutes cambios.
"@
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$safeModel = $Model -replace "[^A-Za-z0-9._-]", "_"
$logPath = Join-Path $resultRoot "$timestamp-$safeModel-$Mode.log"
$metadataPath = Join-Path $resultRoot "$timestamp-$safeModel-$Mode.json"
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$exitCode = 1

Write-Host "Evaluando: $Model | modo: $Mode"
Write-Host "Para cancelar una inferencia trabada, presione Ctrl+C."
try {
    & $launcher `
        -Model $Model `
        -WorkingDirectory $WorkingDirectory `
        -NonInteractive `
        -Prompt $prompt *>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE
}
finally {
    $stopwatch.Stop()
    $metadata = [ordered]@{
        model = $Model
        mode = $Mode
        working_directory = $WorkingDirectory
        elapsed_seconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
        exit_code = $exitCode
        completed_at = (Get-Date).ToString("o")
        log = $logPath
    }
    $metadata | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding utf8
    Write-Host "Resultado local: $metadataPath"
}

if ($exitCode -ne 0) {
    throw "La evaluación terminó con código $exitCode. Revise $logPath"
}
