param(
    [string]$Version = "",
    [ValidateSet("major", "minor", "patch")]
    [string]$Bump = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$VersionFile = Join-Path $Root "src\ComPort_Zone\VERSION"
$PyProjectFile = Join-Path $Root "pyproject.toml"
$SemVerPattern = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$'

function Get-CurrentVersion {
    if (-not (Test-Path $VersionFile)) {
        throw "Version file was not found: $VersionFile"
    }
    $CurrentVersion = (Get-Content $VersionFile -Raw).Trim()
    if ($CurrentVersion -notmatch $SemVerPattern) {
        throw "Current version '$CurrentVersion' must use major.minor.patch format."
    }
    return $CurrentVersion
}

function Get-VersionParts {
    param([string]$Value)
    if ($Value -notmatch $SemVerPattern) {
        throw "Version '$Value' must use major.minor.patch format, for example 1.2.3."
    }
    return [pscustomobject]@{
        Major = [int]$Matches[1]
        Minor = [int]$Matches[2]
        Patch = [int]$Matches[3]
    }
}

if ([string]::IsNullOrWhiteSpace($Version) -eq [string]::IsNullOrWhiteSpace($Bump)) {
    throw "Provide exactly one option: -Version 1.2.3 or -Bump major|minor|patch."
}

$Current = Get-CurrentVersion
if ($Version) {
    $Parts = Get-VersionParts $Version
}
else {
    $CurrentParts = Get-VersionParts $Current
    $Parts = [pscustomobject]@{
        Major = $CurrentParts.Major
        Minor = $CurrentParts.Minor
        Patch = $CurrentParts.Patch
    }
    switch ($Bump) {
        "major" {
            $Parts.Major += 1
            $Parts.Minor = 0
            $Parts.Patch = 0
        }
        "minor" {
            $Parts.Minor += 1
            $Parts.Patch = 0
        }
        "patch" {
            $Parts.Patch += 1
        }
    }
}

$Next = "$($Parts.Major).$($Parts.Minor).$($Parts.Patch)"
$PyProjectText = Get-Content $PyProjectFile -Raw
$UpdatedPyProjectText = $PyProjectText -replace '(?m)^version\s*=\s*"[^"]+"', "version = `"$Next`""
if ($UpdatedPyProjectText -eq $PyProjectText -and $PyProjectText -notmatch "(?m)^version\s*=") {
    throw "Could not find project version in pyproject.toml."
}

Write-Host "Current version: $Current"
Write-Host "Next version:    $Next"

if ($DryRun) {
    Write-Host "Dry run only. No files were changed."
    return
}

Set-Content -Path $VersionFile -Value $Next -NoNewline -Encoding UTF8
Set-Content -Path $PyProjectFile -Value $UpdatedPyProjectText -NoNewline -Encoding UTF8
Write-Host "Updated:"
Write-Host "  $VersionFile"
Write-Host "  $PyProjectFile"
