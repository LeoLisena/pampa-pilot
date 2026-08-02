[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$uvVersion = "0.12.1"
$pythonVersion = "3.12.13"
$uvSha256X64Windows = "8fcb0cb46e1229065e344758980924e569bef5882ef45f46fada8fb24e06b74a"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$toolsDirectory = Join-Path $projectRoot ".tools\uv"
$runtimeDirectory = Join-Path $projectRoot ".runtime"
$downloadDirectory = Join-Path $runtimeDirectory "downloads"
$uvExecutable = Join-Path $toolsDirectory "uv.exe"

if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") {
    throw "Este bootstrap inicial soporta Windows. El proyecto Python sigue siendo multiplataforma."
}

if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne "X64") {
    throw "Este bootstrap inicial soporta Windows x64."
}

New-Item -ItemType Directory -Force -Path $toolsDirectory, $downloadDirectory | Out-Null

$uvIsReady = $false
if (Test-Path -LiteralPath $uvExecutable) {
    $installedVersion = (& $uvExecutable --version 2>$null) -join ""
    $uvIsReady = $installedVersion -match "^uv $([regex]::Escape($uvVersion))\b"
}

if (-not $uvIsReady) {
    $archiveName = "uv-x86_64-pc-windows-msvc.zip"
    $archivePath = Join-Path $downloadDirectory "uv-$uvVersion-x86_64-pc-windows-msvc.zip"
    $downloadUrl = "https://releases.astral.sh/github/uv/releases/download/$uvVersion/$archiveName"

    Write-Host "Descargando uv $uvVersion..."
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath

    $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $uvSha256X64Windows) {
        throw "El SHA-256 de uv no coincide. Esperado: $uvSha256X64Windows. Recibido: $actualSha256"
    }

    Expand-Archive -LiteralPath $archivePath -DestinationPath $toolsDirectory -Force
}

$env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot ".venv-pampapilot"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $runtimeDirectory "python"
$env:UV_CACHE_DIR = Join-Path $runtimeDirectory "uv-cache"
$env:UV_SYSTEM_CERTS = "true"

Push-Location $projectRoot
try {
    Write-Host "Preparando Python $pythonVersion..."
    & $uvExecutable python install $pythonVersion --no-bin
    if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar Python $pythonVersion." }

    Write-Host "Sincronizando el entorno reproducible..."
    & $uvExecutable sync --all-extras --locked --python $pythonVersion
    if ($LASTEXITCODE -ne 0) { throw "No se pudo sincronizar el entorno Python." }
}
finally {
    Pop-Location
}

$pythonExecutable = Join-Path $env:UV_PROJECT_ENVIRONMENT "Scripts\python.exe"
Write-Host "PampaPilot listo."
Write-Host "Python: $pythonExecutable"
& $pythonExecutable --version
