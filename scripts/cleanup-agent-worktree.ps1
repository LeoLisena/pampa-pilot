[CmdletBinding(SupportsShouldProcess, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[a-z0-9][a-z0-9-]{1,48}$")]
    [string]$Task,

    [string]$BaseBranch = "main",
    [switch]$KeepBranch,
    [switch]$IncludeDaily
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repositoryName = Split-Path $projectRoot -Leaf
$worktreeRoot = [IO.Path]::GetFullPath((Join-Path (Split-Path $projectRoot -Parent) "$repositoryName-worktrees"))
$expectedPath = [IO.Path]::GetFullPath((Join-Path $worktreeRoot "local-llm-$Task"))
$branch = "local-llm/$Task"

if ($Task -eq "daily" -and -not $IncludeDaily) {
    throw "daily es persistente. Use -IncludeDaily sólo si realmente quiere eliminarlo."
}
if (-not ($expectedPath.StartsWith($worktreeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))) {
    throw "La ruta calculada quedó fuera del directorio de worktrees."
}
if (-not (Test-Path -LiteralPath $expectedPath -PathType Container)) {
    throw "No existe el worktree esperado: $expectedPath"
}

$actualRoot = [IO.Path]::GetFullPath((& git -C $expectedPath rev-parse --show-toplevel).Trim())
$actualBranch = (& git -C $expectedPath branch --show-current).Trim()
if ($actualRoot -ne $expectedPath -or $actualBranch -ne $branch) {
    throw "El destino no coincide exactamente con el worktree '$branch'."
}

$changes = @(& git -C $expectedPath status --porcelain --untracked-files=all)
if ($changes.Count -gt 0) {
    throw "El worktree tiene cambios sin integrar. Se conserva intacto."
}

$uniqueCommits = [int]((& git -C $projectRoot rev-list --count "$BaseBranch..$branch").Trim())
if ($uniqueCommits -gt 0) {
    throw "La rama contiene $uniqueCommits commit(s) que no están en '$BaseBranch'. Se conserva intacta."
}

if ($PSCmdlet.ShouldProcess("$expectedPath ($branch)", "Eliminar worktree limpio e integrado")) {
    & git -C $projectRoot worktree remove --force $expectedPath
    if ($LASTEXITCODE -ne 0) { throw "Git no pudo eliminar el worktree." }
    if (-not $KeepBranch) {
        & git -C $projectRoot branch -d $branch
        if ($LASTEXITCODE -ne 0) { throw "El worktree se eliminó, pero la rama no pudo borrarse." }
    }
    Write-Host "Limpieza completada: $Task"
}
