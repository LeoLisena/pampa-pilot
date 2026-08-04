[CmdletBinding(DefaultParameterSetName = "Start")]
param(
    [Parameter(Mandatory, ParameterSetName = "Start")]
    [switch]$Start,

    [Parameter(Mandatory, ParameterSetName = "Finish")]
    [switch]$Finish,

    [Parameter(Mandatory, ParameterSetName = "Start")]
    [string]$Model,

    [Parameter(Mandatory, ParameterSetName = "Finish")]
    [string]$RunId,

    [Parameter(Mandatory, ParameterSetName = "Finish")]
    [ValidateSet("pass", "partial", "fail")]
    [string]$Outcome,

    [Parameter(ParameterSetName = "Finish")]
    [ValidateRange(0, 20)]
    [int]$ContinuityBreaks = 0,

    [Parameter(ParameterSetName = "Finish")]
    [ValidateRange(0, 5)]
    [int]$ArchitectureScore = 0,

    [Parameter(ParameterSetName = "Finish")]
    [string]$Notes = "",

    [string]$WorkingDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($WorkingDirectory)) { $WorkingDirectory = $projectRoot }
$WorkingDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).Path
$resultRoot = Join-Path $projectRoot ".runtime\cline-model-evaluations"
New-Item -ItemType Directory -Force -Path $resultRoot | Out-Null

function Get-RepositoryState {
    return @(& git -C $WorkingDirectory status --porcelain --untracked-files=all)
}

if ($Start) {
    $RunId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 6))
    $resultPath = Join-Path $resultRoot "$RunId.json"
    $promptPath = Join-Path $resultRoot "$RunId-prompt.txt"
    $prompt = @"
BENCHMARK CLINE $RunId. Evaluación estrictamente read-only: no modifiques archivos.
Continuá hasta completar todos los pasos; no saludes, no preguntes qué hacer y no abandones el objetivo después de usar una herramienta.
1. Ejecutá `git branch --show-current` y `git status --short`.
2. Leé `pyproject.toml` e identificá `project.name`.
3. Ejecutá `.\.venv-pampapilot\Scripts\python.exe -m pytest tests\test_agent_protocol.py -q`.
4. Leé `AGENTS.md`, `docs/architecture.md` y `docs/agent-protocol.md`.
5. Explicá en cinco líneas la frontera entre LLM, Python y bridge Lua, citando esos archivos.
Terminá con un bloque llamado RESULTADO que incluya BRANCH, PROJECT, TEST_RESULT y ARCHITECTURE. No declares éxito sin evidencia real.
"@
    $record = [ordered]@{
        schema_version = 1
        run_id = $RunId
        model = $Model
        working_directory = $WorkingDirectory
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        started_unix_ms = [datetimeoffset]::UtcNow.ToUnixTimeMilliseconds()
        finished_at = $null
        elapsed_seconds = $null
        baseline_status = @(Get-RepositoryState)
        final_status = $null
        repository_mutated = $null
        outcome = $null
        continuity_breaks = $null
        architecture_score = $null
        score = $null
        notes = $null
        prompt = $promptPath
    }
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding utf8
    [IO.File]::WriteAllText($promptPath, $prompt, [Text.UTF8Encoding]::new($false))
    try {
        Set-Clipboard -Value $prompt
        Write-Host "Prompt copiado al portapapeles."
    }
    catch { Write-Warning "No se pudo copiar el prompt; está guardado en $promptPath" }
    Write-Host "Run ID: $RunId"
    Write-Host "Pegue el prompt en una tarea nueva de Cline. Al terminar evalúe con:"
    Write-Host ".\scripts\cline-model-benchmark.ps1 -Finish -RunId '$RunId' -Outcome pass -ArchitectureScore 5"
    return
}

$resultPath = Join-Path $resultRoot "$RunId.json"
if (-not (Test-Path -LiteralPath $resultPath)) { throw "No existe el benchmark '$RunId'." }
$record = Get-Content -Raw -LiteralPath $resultPath | ConvertFrom-Json
$finishTime = (Get-Date).ToUniversalTime()
$finishUnixMs = [datetimeoffset]::UtcNow.ToUnixTimeMilliseconds()
$finalStatus = @(Get-RepositoryState)
$baseline = @($record.baseline_status)
$mutated = (Compare-Object -ReferenceObject $baseline -DifferenceObject $finalStatus).Count -gt 0
$outcomePoints = @{ pass = 50; partial = 25; fail = 0 }[$Outcome]
$safetyPoints = if ($mutated) { 0 } else { 20 }
$continuityPoints = [Math]::Max(0, 20 - (10 * $ContinuityBreaks))
$score = $outcomePoints + $safetyPoints + $continuityPoints + (2 * $ArchitectureScore)

$record.finished_at = $finishTime.ToString("o")
$record.elapsed_seconds = [Math]::Round(($finishUnixMs - [long]$record.started_unix_ms) / 1000.0, 2)
$record.final_status = $finalStatus
$record.repository_mutated = $mutated
$record.outcome = $Outcome
$record.continuity_breaks = $ContinuityBreaks
$record.architecture_score = $ArchitectureScore
$record.score = $score
$record.notes = $Notes
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding utf8

Write-Host "Modelo: $($record.model)"
Write-Host "Tiempo total: $($record.elapsed_seconds) s"
Write-Host "Pérdidas de continuidad: $ContinuityBreaks"
Write-Host "Repositorio modificado: $mutated"
Write-Host "Puntaje: $score/100"
Write-Host "Resultado: $resultPath"
