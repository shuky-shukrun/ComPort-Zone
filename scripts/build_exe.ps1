param(
    [switch]$NoZip,
    [switch]$ForceInstall,
    [switch]$SkipInstaller,
    [string]$InstallerCompilerPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$AppName = "ComPort Zone"
$PackageName = "ComPort_Zone"
$SourcePath = Join-Path $Root "src"
$EntryPoint = Join-Path $Root "scripts\pyinstaller_entry.py"
$PipRunner = Join-Path $ScriptDir "run_pip.py"
$SetupCompatPath = Join-Path $ScriptDir "setup_compat"
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
$InstallerBuildPath = Join-Path $BuildRoot "installer"
$VenvPath = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$Version = (Get-Content (Join-Path $Root "src\$PackageName\VERSION") -Raw).Trim()
$SemVerPattern = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$'
if ($Version -notmatch $SemVerPattern) {
    throw "Version '$Version' must use major.minor.patch format, for example 1.2.3."
}
$VersionMajor = [int]$Matches[1]
$VersionMinor = [int]$Matches[2]
$VersionPatch = [int]$Matches[3]
$ExeBaseName = $AppName
$ExeFileName = "$ExeBaseName.exe"
$DistBundlePath = Join-Path $DistPath $ExeBaseName
$PublishDir = Join-Path $ReleaseRoot "$($AppName.Replace(' ', '_'))-$Version-win64"
$PublishAppDir = Join-Path $PublishDir "app"
$ZipPath = Join-Path $ReleaseRoot "$($AppName.Replace(' ', '_'))-$Version-win64.zip"
$InstallerBaseName = "$($AppName.Replace(' ', '_'))-$Version-win64-setup"
$InstallerFileName = "$InstallerBaseName.exe"
$InstallerPath = Join-Path $ReleaseRoot $InstallerFileName
$InstallerScriptPath = Join-Path $InstallerBuildPath "$($AppName.Replace(' ', '_'))-$Version.iss"

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
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $PythonExe -c "import importlib, sys; importlib.import_module(sys.argv[1])" $ModuleName *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
}

function Invoke-Pip {
    param([string[]]$Arguments)

    $PreviousCompat = $env:COMPORT_ZONE_SETUP_INHERIT_TEMP_ACL
    $PreviousPythonPath = $env:PYTHONPATH
    $env:COMPORT_ZONE_SETUP_INHERIT_TEMP_ACL = "1"
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $SetupCompatPath
    }
    else {
        "$SetupCompatPath$([IO.Path]::PathSeparator)$PreviousPythonPath"
    }
    try {
        $PipArguments = if ($Arguments.Count -ge 3 -and $Arguments[0] -eq "install" -and $Arguments -contains "--upgrade" -and $Arguments -contains "pip") {
            @("-m", "pip") + $Arguments
        }
        else {
            @($PipRunner) + $Arguments
        }
        Invoke-Checked -FilePath $VenvPython -Arguments $PipArguments
    }
    finally {
        if ([string]::IsNullOrEmpty($PreviousPythonPath)) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
        else {
            $env:PYTHONPATH = $PreviousPythonPath
        }

        if ([string]::IsNullOrEmpty($PreviousCompat)) {
            Remove-Item Env:COMPORT_ZONE_SETUP_INHERIT_TEMP_ACL -ErrorAction SilentlyContinue
        }
        else {
            $env:COMPORT_ZONE_SETUP_INHERIT_TEMP_ACL = $PreviousCompat
        }
    }
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

function New-VersionInfoFile {
    param(
        [string]$TargetPath
    )
    @"
# UTF-8
#
# Generated by scripts/build_exe.ps1. Used by PyInstaller for Windows file properties.

VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($VersionMajor, $VersionMinor, $VersionPatch, 0),
    prodvers=($VersionMajor, $VersionMinor, $VersionPatch, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'ComPort Zone'),
          StringStruct('FileDescription', 'ComPort Zone serial terminal'),
          StringStruct('FileVersion', '$Version'),
          StringStruct('InternalName', '$AppName'),
          StringStruct('OriginalFilename', '$ExeFileName'),
          StringStruct('ProductName', '$AppName'),
          StringStruct('ProductVersion', '$Version')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Path $TargetPath -Encoding UTF8
}

function Remove-DirectoryInsideRoot {
    param(
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $ResolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    $ResolvedPath = (Resolve-Path -LiteralPath $Path).Path
    if (-not $ResolvedPath.StartsWith($ResolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove directory outside repository root: $ResolvedPath"
    }
    Remove-Item -LiteralPath $ResolvedPath -Recurse -Force
}

function Format-InnoStringLiteral {
    param(
        [string]$Value
    )
    return '"' + $Value.Replace('"', '""') + '"'
}

function Find-InnoSetupCompiler {
    if (-not [string]::IsNullOrWhiteSpace($InstallerCompilerPath)) {
        if (Test-Path -LiteralPath $InstallerCompilerPath) {
            return (Resolve-Path -LiteralPath $InstallerCompilerPath).Path
        }
        throw "Inno Setup compiler was not found at '$InstallerCompilerPath'."
    }

    $Command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }

    $Candidates = @()
    $AppPathKeys = @(
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe"
    )
    foreach ($Key in $AppPathKeys) {
        $AppPath = Get-ItemProperty -Path $Key -ErrorAction SilentlyContinue
        if ($AppPath) {
            $Candidates += $AppPath."(default)"
        }
    }
    $UninstallKeys = @(
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($Key in $UninstallKeys) {
        $Installations = Get-ItemProperty -Path $Key -ErrorAction SilentlyContinue |
            Where-Object {
                $DisplayName = $_.PSObject.Properties["DisplayName"]
                $InstallLocation = $_.PSObject.Properties["InstallLocation"]
                $DisplayName -and
                    $InstallLocation -and
                    $DisplayName.Value -like "Inno Setup*" -and
                    -not [string]::IsNullOrWhiteSpace([string]$InstallLocation.Value)
            }
        foreach ($Installation in $Installations) {
            $Candidates += Join-Path $Installation.InstallLocation "ISCC.exe"
        }
    }
    $ProgramFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $ProgramFiles = [Environment]::GetEnvironmentVariable("ProgramFiles")
    $LocalAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA")
    if (-not [string]::IsNullOrWhiteSpace($ProgramFilesX86)) {
        $Candidates += Join-Path $ProgramFilesX86 "Inno Setup 6\ISCC.exe"
    }
    if (-not [string]::IsNullOrWhiteSpace($ProgramFiles)) {
        $Candidates += Join-Path $ProgramFiles "Inno Setup 6\ISCC.exe"
    }
    if (-not [string]::IsNullOrWhiteSpace($LocalAppData)) {
        $Candidates += Join-Path $LocalAppData "Programs\Inno Setup 6\ISCC.exe"
    }
    foreach ($Candidate in $Candidates) {
        if (-not [string]::IsNullOrWhiteSpace($Candidate) -and (Test-Path -LiteralPath $Candidate)) {
            return $Candidate
        }
    }

    throw "Inno Setup 6 compiler (ISCC.exe) was not found. Install Inno Setup 6 or rerun with -SkipInstaller."
}

function New-InnoSetupScript {
    param(
        [string]$TargetPath
    )

    $AppNameLiteral = Format-InnoStringLiteral $AppName
    $AppVersionLiteral = Format-InnoStringLiteral $Version
    $AppExeNameLiteral = Format-InnoStringLiteral $ExeFileName
    $SourceDirLiteral = Format-InnoStringLiteral $PublishDir
    $OutputDirLiteral = Format-InnoStringLiteral $ReleaseRoot
    $OutputBaseFilenameLiteral = Format-InnoStringLiteral $InstallerBaseName

    @"
#define MyAppName $AppNameLiteral
#define MyAppVersion $AppVersionLiteral
#define MyAppExeName $AppExeNameLiteral
#define MySourceDir $SourceDirLiteral
#define MyOutputDir $OutputDirLiteral
#define MyOutputBaseFilename $OutputBaseFilenameLiteral

[Setup]
AppId={{A80A1B61-FC77-4656-A5DB-4047D0E7348C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=ComPort Zone
DefaultDirName={localappdata}\ComPortZone
DefaultGroupName=ComPort Zone
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
PrivilegesRequired=lowest
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no
SetupMutex=ComPortZoneSetup
UninstallDisplayIcon={app}\app\{#MyAppExeName}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "associatecpz"; Description: "Open .cpz command files with {#MyAppName}"; GroupDescription: "File associations:"

[InstallDelete]
Type: filesandordirs; Name: "{app}\app"

[Files]
Source: "{#MySourceDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MySourceDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MySourceDir}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\app\{#MyAppExeName}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\app\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Associate .cpz command files with ComPort Zone so double-clicking opens them in
; the editor. Per-user (HKCU\Software\Classes) since the installer runs unprivileged.
Root: HKCU; Subkey: "Software\Classes\.cpz"; ValueType: string; ValueName: ""; ValueData: "ComPortZone.CommandFile"; Flags: uninsdeletevalue; Tasks: associatecpz
Root: HKCU; Subkey: "Software\Classes\ComPortZone.CommandFile"; ValueType: string; ValueName: ""; ValueData: "ComPort Zone Command File"; Flags: uninsdeletekey; Tasks: associatecpz
Root: HKCU; Subkey: "Software\Classes\ComPortZone.CommandFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\app\{#MyAppExeName},0"; Tasks: associatecpz
Root: HKCU; Subkey: "Software\Classes\ComPortZone.CommandFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\app\{#MyAppExeName}"" ""%1"""; Tasks: associatecpz

[Run]
Filename: "{app}\app\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"
"@ | Set-Content -Path $TargetPath -Encoding UTF8
}

Write-Step "Preparing build folders"
New-Item -ItemType Directory -Force -Path $BuildRoot, $ToolTempRoot, $PipTempPath, $PipCachePath, $WorkRoot, $WorkPath, $SpecPath, $ReleaseRoot, $InstallerBuildPath | Out-Null
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
    Invoke-Pip -Arguments @("install", "--upgrade", "pip")
    Invoke-Pip -Arguments @("install", "setuptools>=68")
    Invoke-Pip -Arguments @("install", "--no-build-isolation", "-e", "${Root}[build]")
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

Write-Step "Building one-folder executable"
$AddDataVersion = "$((Join-Path $Root "src\$PackageName\VERSION"));$PackageName"
$AddDataAssets = "$((Join-Path $Root "src\$PackageName\assets"));$PackageName\assets"
$VersionInfoPath = Join-Path $BuildRoot "version_info.txt"
New-VersionInfoFile -TargetPath $VersionInfoPath
Remove-DirectoryInsideRoot -Path $DistBundlePath
$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", $ExeBaseName,
    "--distpath", $DistPath,
    "--workpath", $WorkPath,
    "--specpath", $SpecPath,
    "--version-file", $VersionInfoPath,
    "--add-data", $AddDataVersion,
    "--add-data", $AddDataAssets,
    "--hidden-import", "serial.tools.list_ports_windows",
    "--hidden-import", "serial.tools.list_ports_common",
    # ui/alert_sound.py imports QtMultimedia lazily inside a try/except so
    # PyInstaller's static scan can miss it (and silently fall back to
    # QApplication.beep in the shipped exe). Pin it as a hidden import
    # so control_panel alert sounds work after packaging.
    "--hidden-import", "PySide6.QtMultimedia",
    # single_instance.py uses QtNetwork (QLocalServer/QLocalSocket) to forward
    # a double-clicked .cpz into the running instance. The import is static, but
    # pin it so packaging can never silently drop the single-instance feature.
    "--hidden-import", "PySide6.QtNetwork"
) + $IconArgs + @($EntryPoint)
Invoke-Checked $VenvPython $PyInstallerArgs

$ExePath = Join-Path $DistBundlePath $ExeFileName
if (-not (Test-Path $ExePath)) {
    throw "Build completed, but the executable was not found: $ExePath"
}

Write-Step "Preparing publish folder"
Remove-DirectoryInsideRoot -Path $PublishDir
New-Item -ItemType Directory -Force -Path $PublishDir, $PublishAppDir | Out-Null
$BundleItems = @(Get-ChildItem -LiteralPath $DistBundlePath -Force)
if ($BundleItems.Count -eq 0) {
    throw "Build completed, but the PyInstaller bundle is empty: $DistBundlePath"
}
Copy-Item -LiteralPath $BundleItems.FullName -Destination $PublishAppDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination $PublishDir -Force
Copy-Item -LiteralPath (Join-Path $Root "THIRD_PARTY_NOTICES.md") -Destination $PublishDir -Force

if (-not $SkipInstaller) {
    Write-Step "Creating installer"
    $InnoCompiler = Find-InnoSetupCompiler
    if (Test-Path -LiteralPath $InstallerPath) {
        Remove-Item -LiteralPath $InstallerPath -Force
    }
    New-InnoSetupScript -TargetPath $InstallerScriptPath
    Invoke-Checked $InnoCompiler @($InstallerScriptPath)
    if (-not (Test-Path -LiteralPath $InstallerPath)) {
        throw "Installer build completed, but the installer was not found: $InstallerPath"
    }
}

if (-not $NoZip) {
    Write-Step "Creating zip package"
    if (Test-Path $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    $PublishItems = Get-ChildItem -LiteralPath $PublishDir -Force
    Compress-Archive -LiteralPath $PublishItems.FullName -DestinationPath $ZipPath -Force
}

Write-Host ""
Write-Host "Build completed successfully." -ForegroundColor Green
Write-Host "Executable: $ExePath"
Write-Host "Publish folder: $PublishDir"
if (-not $SkipInstaller) {
    Write-Host "Installer: $InstallerPath"
}
if (-not $NoZip) {
    Write-Host "Zip package: $ZipPath"
}
