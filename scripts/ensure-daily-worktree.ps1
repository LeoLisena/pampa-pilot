[CmdletBinding()]
param(
    [string]$BaseBranch = "main",
    [switch]$PrepareEnvironment
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repositoryName = Split-Path $projectRoot -Leaf
$worktreeRoot = Join-Path (Split-Path $projectRoot -Parent) "$repositoryName-worktrees"
$target = Join-Path $worktreeRoot "local-llm-daily"
$branch = "local-llm/daily"

& git -C $projectRoot rev-parse --verify $BaseBranch *> $null
if ($LASTEXITCODE -ne 0) { throw "No existe la rama base '$BaseBranch'." }

$attachedPath = $null
foreach ($line in (& git -C $projectRoot worktree list --porcelain)) {
    if ($line -like "worktree *") { $candidatePath = $line.Substring(9) }
    elseif ($line -eq "branch refs/heads/$branch") { $attachedPath = $candidatePath }
}

if ($attachedPath) {
    $target = (Resolve-Path -LiteralPath $attachedPath).Path
}
else {
    if (Test-Path -LiteralPath $target) {
        throw "La ruta reservada para daily ya existe y no es un worktree: $target"
    }
    New-Item -ItemType Directory -Force -Path $worktreeRoot | Out-Null
    & git -C $projectRoot show-ref --verify --quiet "refs/heads/$branch"
    if ($LASTEXITCODE -eq 0) {
        & git -C $projectRoot worktree add $target $branch
    }
    else {
        & git -C $projectRoot worktree add -b $branch $target $BaseBranch
    }
    if ($LASTEXITCODE -ne 0) { throw "No se pudo preparar el worktree daily." }
}

if ($PrepareEnvironment) {
    $python = Join-Path $target ".venv-pampapilot\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host "Preparando el entorno persistente de daily por primera vez..."
        & (Join-Path $target "scripts\bootstrap.ps1")
        if ($LASTEXITCODE -ne 0) { throw "No se pudo preparar el entorno de daily." }
    }
}

Write-Output $target
