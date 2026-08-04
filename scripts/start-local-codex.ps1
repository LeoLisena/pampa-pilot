[CmdletBinding()]
param(
    [string]$Model = "qwen/qwen3.6-35b-a3b",
    [string]$BaseUrl = $env:LM_STUDIO_BASE_URL,
    [string]$WorkingDirectory,
    [ValidateRange(1024, 65535)]
    [int]$ProxyPort = 1235,
    [switch]$NoAuthentication,
    [switch]$NonInteractive,
    [switch]$DiagnosticFullAccess,
    [switch]$ResumeLast,
    [string]$Prompt
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$codexExecutable = Join-Path $projectRoot ".tools\codex-cli\bin\codex.exe"
$pythonExecutable = Join-Path $projectRoot ".venv-pampapilot\Scripts\python.exe"
$proxyScript = Join-Path $projectRoot "scripts\lmstudio_codex_proxy.py"
$localCodexHome = Join-Path $projectRoot ".runtime\codex-local-home"
$apiKeyVariable = "LM_STUDIO_API_KEY"

if ([string]::IsNullOrWhiteSpace($BaseUrl)) { $BaseUrl = "http://127.0.0.1:1234/v1" }
$BaseUrl = $BaseUrl.TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($WorkingDirectory)) { $WorkingDirectory = $projectRoot }
$WorkingDirectory = (Resolve-Path $WorkingDirectory).Path

if ($DiagnosticFullAccess) {
    $branch = (& git -C $WorkingDirectory branch --show-current 2>$null) -join ""
    if ($branch -notlike "local-llm/*") {
        throw "-DiagnosticFullAccess sólo se permite en una rama local-llm/* aislada."
    }
}

if (-not (Test-Path -LiteralPath $codexExecutable)) {
    throw "Codex CLI no está instalado. Ejecute .\scripts\install-codex-cli.ps1"
}
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "El entorno Python no existe. Ejecute .\scripts\bootstrap.ps1"
}
New-Item -ItemType Directory -Force -Path $localCodexHome | Out-Null
$env:CODEX_HOME = $localCodexHome
# A child Codex process must not inherit the desktop host's thread or enforced
# permission profile; it uses the isolated profile written below.
[Environment]::SetEnvironmentVariable("CODEX_PERMISSION_PROFILE", $null, "Process")
[Environment]::SetEnvironmentVariable("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", $null, "Process")
[Environment]::SetEnvironmentVariable("CODEX_THREAD_ID", $null, "Process")
$trustedPath = $WorkingDirectory.ToLowerInvariant().Replace("'", "''")
$localConfig = @"
sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "disabled"

[projects.'$trustedPath']
trust_level = "trusted"

[features]
plugins = false
remote_plugin = false
multi_agent = false
"@
[IO.File]::WriteAllText(
    (Join-Path $localCodexHome "config.toml"),
    $localConfig,
    [Text.UTF8Encoding]::new($false)
)

$headers = @{}
if (-not $NoAuthentication) {
    $apiKey = [Environment]::GetEnvironmentVariable($apiKeyVariable, "Process")
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        $apiKey = (& $pythonExecutable -c "from pampapilot.secret_store import WindowsSecretStore; print(WindowsSecretStore().load())" 2>$null) -join ""
    }
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        if ($NonInteractive) { throw "LM_STUDIO_API_KEY no está definido y PampaPilot no tiene un token guardado." }
        $secureKey = Read-Host "Token de LM Studio (no se guardará)" -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        try { $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    }
    [Environment]::SetEnvironmentVariable($apiKeyVariable, $apiKey, "Process")
    $headers.Authorization = "Bearer $apiKey"
}

try {
    $models = Invoke-RestMethod -Uri "$BaseUrl/models" -Headers $headers -TimeoutSec 10
}
catch {
    throw "No se pudo consultar LM Studio en $BaseUrl. Revise red, token y 'Serve on Local Network'. Detalle: $($_.Exception.Message)"
}

$availableModelIds = @($models.data | ForEach-Object id)
if ($availableModelIds -notcontains $Model) {
    Write-Warning "El modelo solicitado '$Model' no figura entre los modelos cargados: $($availableModelIds -join ', ')"
}

$proxyProcess = $null
$codexBaseUrl = $BaseUrl
if (-not $NoAuthentication) {
    $upstreamUri = [Uri]$BaseUrl
    $env:PAMPAPILOT_LMSTUDIO_UPSTREAM_ORIGIN = "$($upstreamUri.Scheme)://$($upstreamUri.Authority)"
    $env:PAMPAPILOT_LMSTUDIO_PROXY_PORT = "$ProxyPort"
    $proxyLogDirectory = Join-Path $projectRoot ".runtime\codex-proxy"
    New-Item -ItemType Directory -Force -Path $proxyLogDirectory | Out-Null
    $proxyStdout = Join-Path $proxyLogDirectory "stdout.log"
    $proxyStderr = Join-Path $proxyLogDirectory "stderr.log"
    $proxyProcess = Start-Process -FilePath $pythonExecutable `
        -ArgumentList @("`"$proxyScript`"") `
        -RedirectStandardOutput $proxyStdout `
        -RedirectStandardError $proxyStderr `
        -PassThru -WindowStyle Hidden
    $codexBaseUrl = "http://127.0.0.1:$ProxyPort/v1"

    $proxyReady = $false
    foreach ($attempt in 1..20) {
        try {
            Invoke-RestMethod -Uri "$codexBaseUrl/models" -TimeoutSec 2 | Out-Null
            $proxyReady = $true
            break
        }
        catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $proxyReady) {
        Stop-Process -Id $proxyProcess.Id -ErrorAction SilentlyContinue
        $proxyError = if (Test-Path -LiteralPath $proxyStderr) { (Get-Content -Raw $proxyStderr).Trim() } else { "" }
        throw "El proxy autenticado de LM Studio no pudo iniciar en el puerto $ProxyPort. $proxyError"
    }
}

$env:CODEX_OSS_BASE_URL = $codexBaseUrl
$arguments = @(
    "--cd", $WorkingDirectory,
    "--model", $Model,
    "--oss",
    "--local-provider", "lmstudio",
    "--disable", "plugins",
    "--disable", "remote_plugin",
    "--disable", "multi_agent",
    "--config", "web_search=`"disabled`""
)
if ($NonInteractive) {
    if ($ResumeLast) { throw "-ResumeLast sólo está disponible en modo interactivo." }
    if ([string]::IsNullOrWhiteSpace($Prompt)) { throw "-NonInteractive requiere -Prompt." }
    $arguments += @("exec", "--ephemeral")
    if ($DiagnosticFullAccess) {
        $arguments += "--dangerously-bypass-approvals-and-sandbox"
    }
    else {
        $arguments += @("--sandbox", "workspace-write")
    }
    $arguments += $Prompt
}
else {
    if ($DiagnosticFullAccess) { throw "-DiagnosticFullAccess exige -NonInteractive." }
    $arguments += @("--sandbox", "workspace-write", "--ask-for-approval", "on-request")
    if ($ResumeLast) {
        $arguments += @("resume", "--last")
        if (-not [string]::IsNullOrWhiteSpace($Prompt)) { $arguments += $Prompt }
    }
    elseif (-not [string]::IsNullOrWhiteSpace($Prompt)) {
        $arguments += $Prompt
    }
}

Write-Host "Iniciando Codex local en: $WorkingDirectory"
Write-Host "LM Studio: $BaseUrl | Modelo: $Model"
try {
    & $codexExecutable @arguments
}
finally {
    if ($proxyProcess -and -not $proxyProcess.HasExited) {
        Stop-Process -Id $proxyProcess.Id -ErrorAction SilentlyContinue
    }
}
