param(
    [switch]$WithBuild,
    [switch]$SkipInstall,
    [switch]$SkipTests,
    [switch]$NoPipUpgrade,
    [switch]$RecreateVenv,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$SourcePath = Join-Path $Root "src"
$PipRunner = Join-Path $ScriptDir "run_pip.py"
$SetupCompatPath = Join-Path $ScriptDir "setup_compat"
$VenvPath = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$SetupBuildPath = Join-Path $Root "build\setup"
$SetupTempPath = Join-Path $SetupBuildPath "temp"
$PipCachePath = Join-Path $SetupBuildPath "pip-cache"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Format-Command {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    return (@($FilePath) + $Arguments) -join " "
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    $CommandText = Format-Command -FilePath $FilePath -Arguments $Arguments
    if ($DryRun) {
        Write-Host "[dry-run] $CommandText"
        return
    }
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $CommandText"
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
        Invoke-Checked -FilePath $VenvPython -Arguments (@($PipRunner) + $Arguments)
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

function Find-Python {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        return [pscustomobject]@{
            FilePath = $pyLauncher.Source
            BaseArgs = @("-3.12")
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{
            FilePath = $python.Source
            BaseArgs = @()
        }
    }

    throw "Python 3.12+ was not found. Install Python 3.12 or newer, then rerun setup."
}

function Test-PythonVersion {
    param(
        [string]$FilePath,
        [string[]]$BaseArgs
    )
    $Arguments = @($BaseArgs) + @(
        "-c",
        "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
    )
    Invoke-Checked -FilePath $FilePath -Arguments $Arguments
}

function Remove-Venv {
    if (-not (Test-Path -LiteralPath $VenvPath)) {
        return
    }
    $ResolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    $ResolvedVenv = (Resolve-Path -LiteralPath $VenvPath).Path
    if (-not $ResolvedVenv.StartsWith($ResolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove venv outside repository root: $ResolvedVenv"
    }
    if ($DryRun) {
        Write-Host "[dry-run] Remove-Item -LiteralPath `"$ResolvedVenv`" -Recurse -Force"
        return
    }
    Remove-Item -LiteralPath $ResolvedVenv -Recurse -Force
}

function Remove-StaleEditableMetadata {
    $SitePackagesPath = Join-Path $VenvPath "Lib\site-packages"
    if (Test-Path -LiteralPath $SitePackagesPath) {
        $ResolvedVenv = (Resolve-Path -LiteralPath $VenvPath).Path
        $Patterns = @(
            "comport_zone-*.dist-info",
            "__editable__.comport_zone-*.pth",
            "__editable___comport_zone_*.py"
        )

        foreach ($Pattern in $Patterns) {
            $Items = Get-ChildItem -LiteralPath $SitePackagesPath -Force -Filter $Pattern -ErrorAction SilentlyContinue
            foreach ($Item in $Items) {
                if (-not $Item.FullName.StartsWith($ResolvedVenv, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Refusing to remove editable metadata outside virtual environment: $($Item.FullName)"
                }
                if ($DryRun) {
                    Write-Host "[dry-run] Remove-Item -LiteralPath `"$($Item.FullName)`" -Recurse -Force"
                }
                else {
                    Remove-Item -LiteralPath $Item.FullName -Recurse -Force
                }
            }
        }
    }

    $SourceEggInfoPath = Join-Path $SourcePath "ComPort_Zone.egg-info"
    if (Test-Path -LiteralPath $SourceEggInfoPath) {
        $ResolvedRoot = (Resolve-Path -LiteralPath $Root).Path
        $ResolvedEggInfo = (Resolve-Path -LiteralPath $SourceEggInfoPath).Path
        if (-not $ResolvedEggInfo.StartsWith($ResolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove source metadata outside repository root: $ResolvedEggInfo"
        }
        if ($DryRun) {
            Write-Host "[dry-run] Remove-Item -LiteralPath `"$ResolvedEggInfo`" -Recurse -Force"
        }
        else {
            Remove-Item -LiteralPath $ResolvedEggInfo -Recurse -Force
        }
    }
}

function Initialize-LocalBuildTemp {
    if ($DryRun) {
        Write-Host "[dry-run] New-Item -ItemType Directory -Force `"$SetupTempPath`""
        Write-Host "[dry-run] New-Item -ItemType Directory -Force `"$PipCachePath`""
    }
    else {
        New-Item -ItemType Directory -Force -Path $SetupTempPath | Out-Null
        New-Item -ItemType Directory -Force -Path $PipCachePath | Out-Null
    }
    $env:TEMP = $SetupTempPath
    $env:TMP = $SetupTempPath
    $env:PIP_CACHE_DIR = $PipCachePath
    $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

    Write-Host "Setup temp: $SetupTempPath"
    Write-Host "Pip cache:  $PipCachePath"
    Write-Host "Pip runner: $PipRunner"
}

Write-Step "Preparing ComPort Zone development environment"
Write-Host "Repository: $Root"

$Python = Find-Python
Write-Host "Bootstrap Python: $(Format-Command -FilePath $Python.FilePath -Arguments $Python.BaseArgs)"
Test-PythonVersion -FilePath $Python.FilePath -BaseArgs $Python.BaseArgs

if ($RecreateVenv) {
    Write-Step "Recreating virtual environment"
    Remove-Venv
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Step "Creating virtual environment"
    Invoke-Checked -FilePath $Python.FilePath -Arguments (@($Python.BaseArgs) + @("-m", "venv", $VenvPath))
}
else {
    Write-Step "Using existing virtual environment"
    Write-Host $VenvPython
}

if (-not $DryRun -and -not (Test-Path -LiteralPath $VenvPython)) {
    throw "Virtual environment Python was not created: $VenvPython"
}

$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $SourcePath
}
else {
    "$SourcePath$([IO.Path]::PathSeparator)$env:PYTHONPATH"
}

Write-Step "Using local setup temp/cache"
Initialize-LocalBuildTemp

if (-not $SkipInstall) {
    Push-Location $Root
    try {
        if (-not $NoPipUpgrade) {
            Write-Step "Upgrading pip"
            Invoke-Pip -Arguments @("install", "--upgrade", "pip")
        }

        Write-Step "Installing packaging backend"
        Invoke-Pip -Arguments @("install", "setuptools>=68")

        Write-Step "Cleaning stale editable metadata"
        Remove-StaleEditableMetadata

        Write-Step "Installing ComPort Zone editable package"
        $InstallTarget = if ($WithBuild) { ".[build]" } else { "." }
        Invoke-Pip -Arguments @("install", "--no-build-isolation", "-e", $InstallTarget)

        Write-Step "Verifying editable package metadata"
        Invoke-Checked -FilePath $VenvPython -Arguments @(
            "-c",
            "import importlib.metadata as m, pathlib, tomllib; expected = tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version']; actual = m.version('ComPort-Zone'); print(f'ComPort-Zone {actual}'); raise SystemExit(0 if actual == expected else 1)"
        )
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Step "Skipping dependency installation"
}

if (-not $SkipTests) {
    Push-Location $Root
    try {
        Write-Step "Running test suite"
        Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "unittest", "discover", "-q")
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Step "Skipping tests"
}

Write-Step "Setup complete"
Write-Host "Launch: .\launch_app.bat"
Write-Host "Tests:  .\run_tests.bat"
Write-Host "Shell:  .\.venv\Scripts\Activate.ps1"
