param(
    [switch]$NoZip,
    [switch]$ForceInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$AppName = "ComPort Zone"
$PackageName = "ComPort_Zone"
$SourcePath = Join-Path $Root "src"
$EntryPoint = Join-Path $Root "scripts\pyinstaller_entry.py"
$IconPng = Join-Path $Root "src\$PackageName\assets\comport-zone-icon.png"
$BuildId = Get-Date -Format "yyyyMMdd-HHmmss"
$BuildRoot = Join-Path $Root "build\pyinstaller"
$ToolTempRoot = Join-Path $BuildRoot "temp"
$PipTempPath = Join-Path $ToolTempRoot "pip-$BuildId"
$PipCachePath = Join-Path $ToolTempRoot "pip-cache"
$WorkRoot = Join-Path $BuildRoot "work"
$WorkPath = Join-Path $WorkRoot $BuildId
$SpecPath = Join-Path $BuildRoot "spec"
$DistPath = Join-Path $Root "dist"
$ReleaseRoot = Join-Path $Root "release"
$VenvPath = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$Version = (Get-Content (Join-Path $Root "src\$PackageName\VERSION") -Raw).Trim()
$PublishDir = Join-Path $ReleaseRoot "$($AppName.Replace(' ', '_'))-$Version-win64"
$ZipPath = Join-Path $ReleaseRoot "$($AppName.Replace(' ', '_'))-$Version-win64.zip"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Find-Python {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        return @($pyLauncher.Source, "-3.12")
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }
    throw "Python 3.12+ was not found. Install Python, then run build_exe.bat again."
}

function Test-PythonModule {
    param(
        [string]$PythonExe,
        [string]$ModuleName
    )
    & $PythonExe -c "import $ModuleName" *> $null
    return $LASTEXITCODE -eq 0
}

function Test-BuildEnvironment {
    $Modules = @("PyInstaller", "PySide6", "serial", "ComPort_Zone")
    foreach ($Module in $Modules) {
        if (-not (Test-PythonModule -PythonExe $VenvPython -ModuleName $Module)) {
            return $false
        }
    }
    return $true
}

function Remove-OldWorkFolders {
    $Cutoff = (Get-Date).AddDays(-3)
    @($WorkRoot, $ToolTempRoot) |
        Where-Object { Test-Path $_ } |
        ForEach-Object {
            Get-ChildItem -LiteralPath $_ -Directory -ErrorAction SilentlyContinue
        } |
        Where-Object { $_.LastWriteTime -lt $Cutoff } |
        ForEach-Object {
            try {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
            }
            catch {
                Write-Warning "Could not remove old build temp folder: $($_.FullName). $($_.Exception.Message)"
            }
        }
}

function New-IconFile {
    param(
        [string]$PythonExe,
        [string]$SourcePng,
        [string]$TargetIco
    )
    $IconScript = Join-Path $BuildRoot "make_icon.py"
    @'
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap

app = QGuiApplication.instance() or QGuiApplication([])
source = Path(sys.argv[1])
target = Path(sys.argv[2])
pixmap = QPixmap(str(source))
if pixmap.isNull():
    raise RuntimeError(f"Could not load icon source: {source}")

icon = QIcon()
for size in (16, 24, 32, 48, 64, 128, 256):
    icon.addPixmap(
        pixmap.scaled(
            QSize(size, size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )

target.parent.mkdir(parents=True, exist_ok=True)
if not icon.pixmap(QSize(256, 256)).save(str(target), "ICO"):
    raise RuntimeError(f"Could not write ICO file: {target}")
'@ | Set-Content -Path $IconScript -Encoding UTF8
    Invoke-Checked $PythonExe @($IconScript, $SourcePng, $TargetIco)
}

Write-Step "Preparing build folders"
New-Item -ItemType Directory -Force -Path $BuildRoot, $ToolTempRoot, $PipTempPath, $PipCachePath, $WorkRoot, $WorkPath, $SpecPath, $ReleaseRoot | Out-Null
Remove-OldWorkFolders
$env:TEMP = $PipTempPath
$env:TMP = $PipTempPath
$env:PIP_CACHE_DIR = $PipCachePath
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PIP_NO_INPUT = "1"
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $SourcePath
}
else {
    "$SourcePath;$env:PYTHONPATH"
}

if (-not (Test-Path $VenvPython)) {
    Write-Step "Creating virtual environment"
    $PythonCommand = Find-Python
    $PythonExe = $PythonCommand[0]
    $PythonArgs = @()
    if ($PythonCommand.Count -gt 1) {
        $PythonArgs = $PythonCommand[1..($PythonCommand.Count - 1)]
    }
    Invoke-Checked $PythonExe ($PythonArgs + @("-m", "venv", $VenvPath))
}

if ($ForceInstall -or -not (Test-BuildEnvironment)) {
    Write-Step "Installing build dependencies"
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked $VenvPython @("-m", "pip", "install", "-e", "${Root}[build]")
}
else {
    Write-Step "Build dependencies already installed"
    Write-Host "Skipping pip install. Use scripts\build_exe.ps1 -ForceInstall to refresh the build environment."
}

$IconArgs = @()
$IconIco = Join-Path $BuildRoot "comport-zone.ico"
try {
    Write-Step "Preparing Windows icon"
    New-IconFile -PythonExe $VenvPython -SourcePng $IconPng -TargetIco $IconIco
    if (Test-Path $IconIco) {
        $IconArgs = @("--icon", $IconIco)
    }
}
catch {
    Write-Warning "Could not create .ico file. The app will still build, but the .exe file icon may be generic. $($_.Exception.Message)"
}

Write-Step "Building one-file executable"
$AddDataVersion = "$((Join-Path $Root "src\$PackageName\VERSION"));$PackageName"
$AddDataAssets = "$((Join-Path $Root "src\$PackageName\assets"));$PackageName\assets"
$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", $AppName,
    "--distpath", $DistPath,
    "--workpath", $WorkPath,
    "--specpath", $SpecPath,
    "--add-data", $AddDataVersion,
    "--add-data", $AddDataAssets,
    "--hidden-import", "serial.tools.list_ports_windows",
    "--hidden-import", "serial.tools.list_ports_common"
) + $IconArgs + @($EntryPoint)
Invoke-Checked $VenvPython $PyInstallerArgs

$ExePath = Join-Path $DistPath "$AppName.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build completed, but the executable was not found: $ExePath"
}

Write-Step "Preparing publish folder"
if (Test-Path $PublishDir) {
    Remove-Item -LiteralPath $PublishDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PublishDir | Out-Null
Copy-Item -LiteralPath $ExePath -Destination (Join-Path $PublishDir "$AppName.exe") -Force
Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination $PublishDir -Force
Copy-Item -LiteralPath (Join-Path $Root "THIRD_PARTY_NOTICES.md") -Destination $PublishDir -Force

if (-not $NoZip) {
    Write-Step "Creating zip package"
    if (Test-Path $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Compress-Archive -LiteralPath (Join-Path $PublishDir "*") -DestinationPath $ZipPath -Force
}

Write-Host ""
Write-Host "Build completed successfully." -ForegroundColor Green
Write-Host "Executable: $ExePath"
Write-Host "Publish folder: $PublishDir"
if (-not $NoZip) {
    Write-Host "Zip package: $ZipPath"
}
