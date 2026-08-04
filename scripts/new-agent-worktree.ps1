[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[a-z0-9][a-z0-9-]{1,48}$")]
    [string]$Task,

    [ValidateSet("local-llm", "codex")]
    [string]$Agent = "local-llm",

    [string]$BaseBranch = "main",

    [string]$Objective,

    [switch]$Start
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repositoryName = Split-Path $projectRoot -Leaf
$worktreeRoot = Join-Path (Split-Path $projectRoot -Parent) "$repositoryName-worktrees"
$branch = "$Agent/$Task"
$target = Join-Path $worktreeRoot "$Agent-$Task"
$taskBrief = Join-Path $target ".agent-task.md"

Push-Location $projectRoot
try {
    & git rev-parse --verify $BaseBranch *> $null
    if ($LASTEXITCODE -ne 0) { throw "No existe la rama base '$BaseBranch'." }

    & git show-ref --verify --quiet "refs/heads/$branch"
    if ($LASTEXITCODE -eq 0) { throw "La rama '$branch' ya existe." }

    if (Test-Path -LiteralPath $target) {
        throw "La ruta de worktree ya existe: $target"
    }

    New-Item -ItemType Directory -Force -Path $worktreeRoot | Out-Null
    & git worktree add -b $branch $target $BaseBranch
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el worktree." }
}
finally {
    Pop-Location
}

if (-not [string]::IsNullOrWhiteSpace($Objective)) {
    $brief = @"
# Tarea activa

## Objetivo

$Objective

## Condiciones

- Trabajá únicamente en la rama `$branch` y en este worktree.
- Leé `AGENTS.md` antes de modificar archivos.
- Conservá cambios ajenos y mantené el alcance acotado.
- Ejecutá pruebas enfocadas durante el desarrollo y `scripts/validate.ps1` al finalizar.
- No hagas commit, push ni merge sin autorización explícita.
"@
    [IO.File]::WriteAllText($taskBrief, $brief, [Text.UTF8Encoding]::new($false))
}

Write-Host "Worktree creado: $target"
Write-Host "Rama: $branch"
Write-Host "Preparar el entorno aislado con:"
Write-Host "& '$target\scripts\bootstrap.ps1'"
Write-Host "Iniciar agente local con:"
Write-Host "& '$projectRoot\scripts\start-local-codex.ps1' -WorkingDirectory '$target'"

if ($Start) {
    if ($Agent -ne "local-llm") {
        throw "-Start sólo inicia el agente local. Abra las tareas Codex desde la app de escritorio."
    }
    & (Join-Path $target "scripts\bootstrap.ps1")
    if ($LASTEXITCODE -ne 0) { throw "No se pudo preparar el entorno del worktree." }

    $initialPrompt = if (Test-Path -LiteralPath $taskBrief) {
        "Leé AGENTS.md y .agent-task.md. Confirmá el objetivo y empezá a trabajar respetando esas instrucciones."
    }
    else {
        "Leé AGENTS.md. Preguntame cuál es el objetivo concreto antes de modificar archivos."
    }
    & (Join-Path $projectRoot "scripts\start-local-codex.ps1") `
        -WorkingDirectory $target `
        -Prompt $initialPrompt
}
