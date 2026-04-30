param(
    [switch]$NoVenv,
    [switch]$VerboseOutput,
    [switch]$FailFast,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Tests
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

    throw "Python 3.12+ was not found. Create .venv or install Python before running tests."
}

$Python = Find-Python
$TestList = @(if ($null -eq $Tests) {
    @()
}
else {
    @($Tests) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
})
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $SourcePath
}
else {
    "$SourcePath$([IO.Path]::PathSeparator)$env:PYTHONPATH"
}

$UnittestArgs = @("-m", "unittest")
if ($FailFast) {
    $UnittestArgs += "-f"
}

if ($TestList.Count -gt 0) {
    $UnittestArgs += $TestList
}
else {
    $UnittestArgs += @("discover")
    if (-not $VerboseOutput) {
        $UnittestArgs += "-q"
    }
}

$Arguments = @($Python.BaseArgs) + $UnittestArgs
Write-Host "Running tests from: $Root"
Write-Host "Command: $(@($Python.FilePath) + $Arguments -join ' ')"

Push-Location $Root
try {
    & $Python.FilePath @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
