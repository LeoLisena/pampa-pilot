[CmdletBinding()]
param(
    [string]$ReaperResourcePath = (Join-Path $env:APPDATA "REAPER")
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bridgeSource = (Resolve-Path (Join-Path $projectRoot "reaper\PampaPilot_Bridge.lua")).Path
$targetDirectory = Join-Path $ReaperResourcePath "Scripts\PampaPilot"
$targetPath = Join-Path $targetDirectory "PampaPilot_Bridge.lua"

New-Item -ItemType Directory -Force -Path $targetDirectory | Out-Null
$loader = @"
-- Cargador local; la implementación versionada vive en el repositorio.
dofile([[$bridgeSource]])
"@
[System.IO.File]::WriteAllText($targetPath, $loader, [System.Text.UTF8Encoding]::new($false))

Write-Host "Cargador PampaPilot instalado en: $targetPath"
Write-Host "Fuente versionada: $bridgeSource"
Write-Host "Si la acción aún no existe, agréguela una vez desde la lista Actions de REAPER."
