[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne "X64") {
    throw "Este instalador inicial soporta Windows x64."
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$installDirectory = Join-Path $projectRoot ".tools\codex-cli"
$codexExecutable = Join-Path $installDirectory "bin\codex.exe"
$downloadDirectory = Join-Path $projectRoot ".runtime\downloads\codex-cli"

if ((Test-Path -LiteralPath $codexExecutable) -and -not $Force) {
    & $codexExecutable --version
    Write-Host "Codex CLI ya está instalado en $codexExecutable"
    return
}

$headers = @{ "User-Agent" = "PampaPilot-bootstrap" }
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/openai/codex/releases/latest" -Headers $headers
$archiveName = "codex-package-x86_64-pc-windows-msvc.tar.gz"
$checksumName = "codex-package_SHA256SUMS"
$archiveAsset = $release.assets | Where-Object name -eq $archiveName
$checksumAsset = $release.assets | Where-Object name -eq $checksumName

if (-not $archiveAsset -or -not $checksumAsset) {
    throw "La release oficial no contiene los artefactos esperados."
}

New-Item -ItemType Directory -Force -Path $downloadDirectory | Out-Null
$archivePath = Join-Path $downloadDirectory $archiveName
$checksumPath = Join-Path $downloadDirectory $checksumName

Write-Host "Descargando Codex CLI $($release.tag_name)..."
Invoke-WebRequest -Uri $archiveAsset.browser_download_url -OutFile $archivePath
Invoke-WebRequest -Uri $checksumAsset.browser_download_url -OutFile $checksumPath

$checksumLine = Select-String -LiteralPath $checksumPath -Pattern "  $([regex]::Escape($archiveName))$"
if (-not $checksumLine) { throw "No se encontró el SHA-256 del artefacto." }
$expected = ($checksumLine.Line -split "\s+")[0].ToLowerInvariant()
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "El SHA-256 de Codex CLI no coincide." }

New-Item -ItemType Directory -Force -Path $installDirectory | Out-Null
& tar -xzf $archivePath -C $installDirectory
if ($LASTEXITCODE -ne 0) { throw "No se pudo extraer Codex CLI." }
if (-not (Test-Path -LiteralPath $codexExecutable)) { throw "No apareció codex.exe tras la extracción." }

Write-Host "Codex CLI instalado y verificado."
& $codexExecutable --version
