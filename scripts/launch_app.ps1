param(
    [switch]$NoVenv,
    [switch]$DryRun,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$SourcePath = Join-Path $Root "src"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

function Find-Python {
    if (-not $NoVenv -and (Test-Path -LiteralPath $VenvPython)) {
        return [pscustomobject]@{
            FilePath = $VenvPython
            BaseArgs = @()
        }
    }

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

    throw "Python 3.12+ was not found. Create .venv or install Python before launching ComPort Zone."
}

$Python = Find-Python
$AppArgList = @(if ($null -eq $AppArgs) {
    @()
}
else {
    @($AppArgs) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
})
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $SourcePath
}
else {
    "$SourcePath$([IO.Path]::PathSeparator)$env:PYTHONPATH"
}

$Arguments = @($Python.BaseArgs) + @("-m", "ComPort_Zone") + $AppArgList
$CommandText = @($Python.FilePath) + $Arguments -join " "

if ($DryRun) {
    Write-Host "Would launch from: $Root"
    Write-Host "Command: $CommandText"
    exit 0
}

Write-Host "Launching ComPort Zone..."
Push-Location $Root
try {
    & $Python.FilePath @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
