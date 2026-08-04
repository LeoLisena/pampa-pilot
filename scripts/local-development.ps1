[CmdletBinding()]
param(
    [string]$Model,
    [string]$Task,
    [string]$Objective,
    [string]$BaseBranch = "main",
    [switch]$NewSession,
    [switch]$DryRun,
    [string]$BaseUrl = $env:LM_STUDIO_BASE_URL
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repositoryName = Split-Path $projectRoot -Leaf
$worktreeRoot = Join-Path (Split-Path $projectRoot -Parent) "$repositoryName-worktrees"
$pythonExecutable = Join-Path $projectRoot ".venv-pampapilot\Scripts\python.exe"

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = "http://127.0.0.1:1234/v1"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

function Get-LocalTaskWorktrees {
    $entries = @()
    $path = $null
    $branch = $null
    foreach ($line in (& git -C $projectRoot worktree list --porcelain)) {
        if ($line -like "worktree *") { $path = $line.Substring(9) }
        elseif ($line -like "branch refs/heads/local-llm/*") {
            $branch = $line.Substring(18)
        }
        elseif ([string]::IsNullOrWhiteSpace($line) -and $path -and $branch) {
            $entries += [pscustomobject]@{ Path = $path; Branch = $branch; Task = $branch.Substring(10) }
            $path = $null
            $branch = $null
        }
    }
    if ($path -and $branch) {
        $entries += [pscustomobject]@{ Path = $path; Branch = $branch; Task = $branch.Substring(10) }
    }
    return @($entries)
}

$dailyPath = & (Join-Path $projectRoot "scripts\ensure-daily-worktree.ps1") -BaseBranch $BaseBranch
$existingTasks = @(Get-LocalTaskWorktrees | Sort-Object @{ Expression = { if ($_.Task -eq "daily") { 0 } else { 1 } } }, Task)
if ([string]::IsNullOrWhiteSpace($Task)) {
    Write-Host "Espacios de desarrollo disponibles:"
    for ($index = 0; $index -lt $existingTasks.Count; $index++) {
        Write-Host "  $($index + 1). $($existingTasks[$index].Task)"
    }
    Write-Host "  N. Nueva tarea aislada"
    $selection = (Read-Host "Elegí una opción (Enter = daily)").Trim()
    if ([string]::IsNullOrWhiteSpace($selection)) {
        $Task = "daily"
    }
    elseif ($selection -match "^[Nn]$") {
        $Task = (Read-Host "Nombre breve (letras, números y guiones)").Trim()
    }
    elseif ($selection -match "^\d+$" -and [int]$selection -ge 1 -and [int]$selection -le $existingTasks.Count) {
        $Task = $existingTasks[[int]$selection - 1].Task
    }
    else {
        throw "Selección de tarea inválida."
    }
}
if ($Task -notmatch "^[a-z0-9][a-z0-9-]{1,48}$") {
    throw "El nombre de tarea debe usar letras minúsculas, números y guiones."
}

$taskEntry = $existingTasks | Where-Object Task -EQ $Task | Select-Object -First 1
$isNewTask = -not $taskEntry
if ($isNewTask) {
    if ([string]::IsNullOrWhiteSpace($Objective)) {
        $Objective = (Read-Host "Objetivo concreto de la tarea").Trim()
    }
    if ([string]::IsNullOrWhiteSpace($Objective)) { throw "La tarea necesita un objetivo." }
    & (Join-Path $projectRoot "scripts\new-agent-worktree.ps1") `
        -Task $Task `
        -Agent local-llm `
        -BaseBranch $BaseBranch `
        -Objective $Objective
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el worktree." }
    $workingDirectory = Join-Path $worktreeRoot "local-llm-$Task"
}
else {
    $workingDirectory = $taskEntry.Path
}

$worktreePython = Join-Path $workingDirectory ".venv-pampapilot\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $worktreePython)) {
    Write-Host "Preparando el entorno aislado por primera vez..."
    & (Join-Path $workingDirectory "scripts\bootstrap.ps1")
    if ($LASTEXITCODE -ne 0) { throw "No se pudo preparar el entorno Python." }
}

$previousApiKey = [Environment]::GetEnvironmentVariable("LM_STUDIO_API_KEY", "Process")
$apiKey = $previousApiKey
if ([string]::IsNullOrWhiteSpace($apiKey) -and (Test-Path -LiteralPath $pythonExecutable)) {
    $apiKey = (& $pythonExecutable -c "from pampapilot.secret_store import WindowsSecretStore; print(WindowsSecretStore().load())" 2>$null) -join ""
}
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    $secureKey = Read-Host "Token de LM Studio (sólo para esta sesión)" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try { $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
[Environment]::SetEnvironmentVariable("LM_STUDIO_API_KEY", $apiKey, "Process")
$headers = @{ Authorization = "Bearer $apiKey" }
$models = Invoke-RestMethod -Uri "$BaseUrl/models" -Headers $headers -TimeoutSec 10
$modelIds = @($models.data | ForEach-Object id | Sort-Object -Unique)
if ($modelIds.Count -eq 0) { throw "LM Studio no informó modelos cargados." }

if ([string]::IsNullOrWhiteSpace($Model)) {
    Write-Host "Modelos cargados:"
    for ($index = 0; $index -lt $modelIds.Count; $index++) {
        Write-Host "  $($index + 1). $($modelIds[$index])"
    }
    $selection = (Read-Host "Elegí un modelo").Trim()
    if ($selection -notmatch "^\d+$" -or [int]$selection -lt 1 -or [int]$selection -gt $modelIds.Count) {
        throw "Selección de modelo inválida."
    }
    $Model = $modelIds[[int]$selection - 1]
}
elseif ($modelIds -notcontains $Model) {
    throw "El modelo '$Model' no está cargado en LM Studio."
}

$resumeLast = -not $isNewTask -and -not $NewSession
$initialPrompt = if ($isNewTask) {
    "Leé AGENTS.md y .agent-task.md. Confirmá brevemente el objetivo y empezá a trabajar."
}
elseif ($NewSession -or $Task -eq "daily") {
    "Leé AGENTS.md y revisá el estado actual de la rama. Este es el espacio diario persistente: trabajá con fluidez sobre el pedido del usuario y preguntá sólo si falta una decisión material."
}
else { $null }

Write-Host ""
Write-Host "Tarea: $Task"
Write-Host "Worktree: $workingDirectory"
Write-Host "Modelo: $Model"
Write-Host $(if ($resumeLast) { "Sesión: continuar la última" } else { "Sesión: nueva" })

if ($DryRun) {
    Write-Host "Dry run correcto: no se inició Codex."
    [Environment]::SetEnvironmentVariable("LM_STUDIO_API_KEY", $previousApiKey, "Process")
    return
}

try {
    & (Join-Path $projectRoot "scripts\start-local-codex.ps1") `
        -Model $Model `
        -BaseUrl $BaseUrl `
        -WorkingDirectory $workingDirectory `
        -ResumeLast:$resumeLast `
        -Prompt $initialPrompt
}
finally {
    [Environment]::SetEnvironmentVariable("LM_STUDIO_API_KEY", $previousApiKey, "Process")
}
