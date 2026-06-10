#requires -Version 5.1
<#
  ComPort Zone release driver
  ========================================================================
  Automates the mechanical, verifiable steps of a version release so the
  only thing left to human/agent judgement is writing user-focused notes.

  Verbs:
    preflight  -Version X.Y.Z                       Gate checks before a release (read-only)
    changes    [-Since vA.B.C] [-Out <file>]        Raw change list since the previous tag (read-only)
    bump       -Version X.Y.Z [-DryRun]             Update VERSION + pyproject via the project script
    tag        -Version X.Y.Z -MessageFile <f> [-DryRun]   Create + verify the annotated vX.Y.Z tag
    verify     -Version X.Y.Z                        Inspect the tag message + GitHub Release body (read-only)
    help                                            This text

  Safe to run anytime (read-only / no mutation):
    preflight, changes, verify, and ANY verb with -DryRun.
  Mutating verbs:
    bump  -> writes src\ComPort_Zone\VERSION and pyproject.toml
    tag   -> creates an annotated git tag

  Works the same under Windows PowerShell 5.1 and PowerShell 7.
  Run from anywhere inside the repo; the script relocates to the repo root.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('preflight', 'changes', 'bump', 'tag', 'verify', 'help')]
    [string]$Command = 'help',

    [string]$Version = '',
    [string]$Since = '',
    [string]$Out = '',
    [string]$MessageFile = '',
    [switch]$DryRun
)

Set-StrictMode -Version Latest
# Native git/gh exit codes are checked explicitly; do not let their stderr abort us.
$ErrorActionPreference = 'Continue'

$script:Failed = $false
$script:Warned = $false

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "  [OK]   $m" }
function Warn ($m) { Write-Host "  [WARN] $m"; $script:Warned = $true }
function Bad  ($m) { Write-Host "  [FAIL] $m"; $script:Failed = $true }
function Die  ($m) { Write-Host "ERROR: $m"; exit 2 }

$SemVer = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$'

# --- locate the repo root and relocate there -----------------------------
$RepoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $RepoRoot) { Die "not inside a git repository" }
$RepoRoot = ($RepoRoot | Select-Object -First 1).Trim()
Set-Location -LiteralPath $RepoRoot

$VersionFile = Join-Path $RepoRoot 'src\ComPort_Zone\VERSION'
$PyProject   = Join-Path $RepoRoot 'pyproject.toml'
$Readme      = Join-Path $RepoRoot 'README.md'
$UpdatePs1   = Join-Path $RepoRoot 'scripts\update_version.ps1'

# --- repo slug (owner/name) + default branch -----------------------------
$RepoSlug = ''
$originUrl = (& git remote get-url origin 2>$null)
if ($LASTEXITCODE -eq 0 -and $originUrl -and ($originUrl -match 'github\.com[:/](.+?)(?:\.git)?/?\s*$')) {
    $RepoSlug = $Matches[1]
}

$DefaultBranch = 'master'
$sym = (& git symbolic-ref --quiet refs/remotes/origin/HEAD 2>$null)
if ($LASTEXITCODE -eq 0 -and $sym) {
    $DefaultBranch = (($sym | Select-Object -First 1).Trim() -replace '^refs/remotes/origin/', '')
}

# --- small helpers --------------------------------------------------------
function Get-FileVersion {
    if (-not (Test-Path -LiteralPath $VersionFile)) { return '' }
    return ((Get-Content -LiteralPath $VersionFile -Raw).Trim().TrimStart([char]0xfeff))
}
function Get-PyVersion {
    if (-not (Test-Path -LiteralPath $PyProject)) { return '' }
    $t = Get-Content -LiteralPath $PyProject -Raw
    if ($t -match '(?m)^version\s*=\s*"([^"]+)"') { return $Matches[1] }
    return ''
}
function Get-ReadmeVersion {
    if (-not (Test-Path -LiteralPath $Readme)) { return '' }
    $t = Get-Content -LiteralPath $Readme -Raw
    if ($t -match 'badge/version-([0-9]+\.[0-9]+\.[0-9]+)-') { return $Matches[1] }
    return ''
}
function Get-PrevTag {
    if ($Since) { return $Since }
    $t = (& git describe --tags --abbrev=0 2>$null)
    if ($LASTEXITCODE -eq 0 -and $t) { return ($t | Select-Object -First 1).Trim() }
    return ''
}
function Get-ChangeLines ($prev) {
    if ($prev) { $range = "$prev..HEAD" } else { $range = 'HEAD' }
    $lines = & git log --no-merges --format="- %s (%h)" $range
    if ($null -eq $lines) { return @() }
    return @($lines)
}
function Test-TagLocal ($tag) {
    $hit = & git tag --list $tag
    return [bool]$hit
}
function Test-TagRemote ($tag) {
    $r = & git ls-remote --tags origin "refs/tags/$tag" 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }   # could not check (offline / no remote)
    return [bool]$r
}
function Need-Version {
    if (-not $Version) { Die "this verb needs -Version X.Y.Z" }
    if ($Version -notmatch $SemVer) { Die "version '$Version' must be X.Y.Z (e.g. 0.5.0)" }
}
function Write-TextNoBom ($path, $text) {
    # PowerShell 5.1's Set-Content -Encoding UTF8 writes a BOM that git -F would
    # embed in commit/tag messages. Always write BOM-free, with an absolute path
    # ([System.IO.File] ignores PowerShell's location and uses the process CWD).
    if (-not [System.IO.Path]::IsPathRooted($path)) { $path = Join-Path (Get-Location).Path $path }
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding $false))
}

# --- verbs ----------------------------------------------------------------
function Invoke-Preflight {
    Need-Version
    $tag    = "v$Version"
    $cur    = Get-FileVersion
    $py     = Get-PyVersion
    $rdm    = Get-ReadmeVersion
    $branch = ((& git rev-parse --abbrev-ref HEAD) | Select-Object -First 1).Trim()
    $prev   = Get-PrevTag
    $range  = Get-ChangeLines $prev

    Say "Preflight for release $tag"
    Say "  repo             : $RepoSlug"
    Say "  default branch   : $DefaultBranch"
    Say "  current branch   : $branch"
    Say "  VERSION file     : $cur"
    Say "  pyproject.toml   : $py"
    Say "  README badge     : $rdm"
    if ($prev) { Say "  previous tag     : $prev" } else { Say "  previous tag     : (none - first release)" }
    Say "  commits in range : $($range.Count)"
    Say ""

    if (Test-TagLocal $tag) { Bad "$tag already exists locally (choose a new version, or delete the tag)" }
    else { Ok "$tag not present locally" }

    $rem = Test-TagRemote $tag
    if ($null -eq $rem) { Warn "could not reach origin to check for $tag; verify with: git ls-remote --tags origin $tag" }
    elseif ($rem) { Bad "$tag already exists on origin" }
    else { Ok "$tag not present on origin" }

    if ($branch -ne $DefaultBranch) {
        Warn "on '$branch', not '$DefaultBranch'. Releases are normally cut from '$DefaultBranch' - merge there first, or proceed deliberately."
    }
    else { Ok "on default branch '$DefaultBranch'" }

    $dirty = & git status --porcelain
    if ($dirty) {
        Warn "working tree has uncommitted changes (preflight expects a clean tree BEFORE 'bump'):"
        @($dirty) | Select-Object -First 8 | ForEach-Object { Say "           $_" }
    }
    else { Ok "working tree clean" }

    if ($cur -eq $Version) { Warn "VERSION is already $Version - 'bump' would be a no-op" }
    if ($py  -and ($py  -ne $cur)) { Warn "pyproject ($py) and VERSION ($cur) already disagree" }
    if ($rdm -and ($rdm -ne $cur)) { Warn "README badge ($rdm) and VERSION ($cur) already disagree" }
    if ($range.Count -eq 0) { Warn "no commits since $prev - nothing to release?" }

    Say ""
    if ($script:Failed)      { Say "PREFLIGHT: FAIL"; exit 1 }
    elseif ($script:Warned)  { Say "PREFLIGHT: PASS (with warnings)"; exit 0 }
    else                     { Say "PREFLIGHT: PASS"; exit 0 }
}

function Invoke-Changes {
    $prev  = Get-PrevTag
    $lines = Get-ChangeLines $prev
    if ($prev) { $src = $prev } else { $src = 'the beginning' }
    Say "Raw change list since $src ($($lines.Count) non-merge commits):"
    if ($lines.Count -eq 0) { Say "  (none)" } else { $lines | ForEach-Object { Say $_ } }
    if ($Out) {
        Write-TextNoBom $Out (($lines -join "`r`n") + "`r`n")
        Say ""
        Say "Wrote $($lines.Count) lines to $Out (BOM-free UTF-8; use as commit body / tag traceability)."
    }
}

function Invoke-Bump {
    Need-Version
    if (-not (Test-Path -LiteralPath $UpdatePs1)) { Die "missing $UpdatePs1" }
    Say "Bumping version to $Version via scripts\update_version.ps1"
    Say "(equivalent to '.\update_version.bat $Version'; called directly to avoid the .bat's pause-on-error prompt)"
    Say ""
    if ($DryRun) {
        try { & $UpdatePs1 -Version $Version -DryRun } catch { Die "update_version.ps1 failed: $_" }
        Say ""
        Say "DRY RUN - no files changed."
        return
    }
    try { & $UpdatePs1 -Version $Version } catch { Die "update_version.ps1 failed: $_" }
    Say ""
    $cur = Get-FileVersion; $py = Get-PyVersion; $rdm = Get-ReadmeVersion
    if ($cur -eq $Version) { Ok "VERSION   = $cur" }   else { Bad "VERSION = $cur (expected $Version)" }
    if ($py  -eq $Version) { Ok "pyproject = $py" }    else { Bad "pyproject = $py (expected $Version)" }
    if ($rdm -eq $Version) { Ok "README badge = $rdm" }
    else { Warn "README badge = $rdm (expected $Version). update_version.bat does NOT touch README - edit the version badge by hand during doc updates." }
    Say ""
    Say "Next: update CHANGELOG.md (rename '## Unreleased' -> '## $Version - <date>', then add a fresh empty Unreleased),"
    Say "      prepend RELEASE_NOTES.md, refresh README badge, and update docs/ if architecture changed."
    if ($script:Failed) { exit 1 }
}

function Invoke-Tag {
    Need-Version
    if (-not $MessageFile) { Die "tag needs -MessageFile <path> to an annotated-tag message file" }
    if (-not (Test-Path -LiteralPath $MessageFile)) { Die "message file not found: $MessageFile" }
    $tag = "v$Version"
    if (Test-TagLocal $tag) { Die "$tag already exists locally" }

    $msg = Get-Content -LiteralPath $MessageFile -Raw
    $hadBom = ($msg.Length -gt 0 -and $msg[0] -eq [char]0xFEFF)
    if ($hadBom) { $msg = $msg.TrimStart([char]0xFEFF) }
    $firstLine = (($msg -split "`r?`n") | Select-Object -First 1)
    $want      = "ComPort Zone $tag"
    if ($firstLine.Trim() -ne $want) { Warn "first line is '$($firstLine.Trim())' (convention: '$want')" }
    if ($hadBom) { Say "  (stripped a UTF-8 BOM from the message file so the tag stays clean)" }

    if ($DryRun) {
        Say "DRY RUN - would create annotated tag $tag from a BOM-free copy of $MessageFile"
        Say "----- message preview -----"
        Say $msg
        Say "----- verify after creating -----"
        Say "  git cat-file -t $tag      (expect: tag)"
        Say "  git tag -n99 $tag"
        return
    }
    # Tag from a normalized, BOM-free temp file regardless of how the source was written.
    $tmp = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tmp, $msg, (New-Object System.Text.UTF8Encoding $false))
    & git tag -a $tag -F $tmp
    $tagExit = $LASTEXITCODE
    Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
    if ($tagExit -ne 0) { Die "git tag failed" }
    $type = ((& git cat-file -t $tag) | Select-Object -First 1).Trim()
    if ($type -eq 'tag') { Ok "$tag created as an annotated tag" } else { Bad "$tag has type '$type' (expected annotated 'tag')" }
    Say "----- git tag -n99 $tag -----"
    & git tag -n99 $tag
    Say ""
    Say "Push when ready:  git push origin $DefaultBranch  ;  git push origin $tag"
    if ($script:Failed) { exit 1 }
}

function Invoke-Verify {
    Need-Version
    $tag = "v$Version"

    # 1) annotated-tag message richness
    if (Test-TagLocal $tag) {
        $n = @(& git tag -n99 $tag)
        $bodyLines = @($n | Select-Object -Skip 1 | Where-Object { $_.Trim() -ne '' })
        if ($bodyLines.Count -eq 0) { Warn "tag $tag has only a title line - no user summary or maintainer traceability in the tag message" }
        else { Ok "tag $tag carries a $($bodyLines.Count)-line message body" }
    }
    else { Warn "tag $tag not found locally" }

    # 2) GitHub Release body
    if (-not $RepoSlug) { Warn "could not derive owner/repo from origin; pass --repo to gh manually"; return }
    $json = & gh release view $tag --repo $RepoSlug --json url,name,isDraft,body 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $json) {
        Warn "no readable GitHub Release for $tag yet. The tag-triggered Release workflow may still be running, or gh needs auth/network. Check:"
        Say  "      gh release view $tag --repo $RepoSlug"
        return
    }
    $rel = $json | ConvertFrom-Json
    Say "Release : $($rel.name)"
    Say "URL     : $($rel.url)"
    Say "Draft   : $($rel.isDraft)"
    $body = ''
    if (($rel.PSObject.Properties.Name -contains 'body') -and $rel.body) { $body = [string]$rel.body }
    $trimmed = $body.Trim()
    Say "----- release body -----"
    if ($trimmed) { Say $body } else { Say "(empty)" }
    Say "------------------------"

    $bodyLineArr = @($trimmed -split "`n")
    if (-not $trimmed) {
        Bad "release body is EMPTY - add a user-focused summary"
    }
    elseif (($trimmed -match '(?m)^\*\*Full Changelog\*\*') -and ($bodyLineArr.Count -le 2)) {
        Bad "release body is ONLY an auto-generated compare link - replace it with a user-focused summary"
    }
    else {
        $prose = @($bodyLineArr | Where-Object {
            ($_.Trim() -ne '') -and ($_ -notmatch '^\s*[\*\-]') -and ($_ -notmatch '^\s*#') -and ($_ -notmatch 'Full Changelog')
        }).Count
        if ($prose -eq 0) { Warn "release body has no prose lines - looks like a raw bullet/PR list; confirm it reads as user-facing notes" }
        else { Ok "release body has content ($prose prose line(s))" }
    }
    Say ""
    Say "Replace the body with curated notes when needed:"
    Say "  gh release edit $tag --repo $RepoSlug --notes-file <user-focused-notes.md>"
    if ($script:Failed) { exit 1 }
}

function Invoke-Help {
    Say @"
ComPort Zone release driver

  preflight  -Version X.Y.Z                              Gate checks before a release (read-only)
  changes    [-Since vA.B.C] [-Out <file>]               Raw change list since previous tag (read-only)
  bump       -Version X.Y.Z [-DryRun]                    Update VERSION + pyproject via project script
  tag        -Version X.Y.Z -MessageFile <f> [-DryRun]   Create + verify the annotated vX.Y.Z tag
  verify     -Version X.Y.Z                              Inspect tag message + GitHub Release body (read-only)

Read-only / safe anytime: preflight, changes, verify, and any verb with -DryRun.
Repo: $RepoSlug   Default branch: $DefaultBranch
"@
}

switch ($Command) {
    'preflight' { Invoke-Preflight }
    'changes'   { Invoke-Changes }
    'bump'      { Invoke-Bump }
    'tag'       { Invoke-Tag }
    'verify'    { Invoke-Verify }
    default     { Invoke-Help }
}
