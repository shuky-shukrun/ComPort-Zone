---
name: comport-zone-version-update
description: Prepare and publish a ComPort Zone version release. Use to cut/release/publish a new version, bump the app version (vX.Y.Z) with update_version.bat, update user-facing docs (README version badge, CHANGELOG, RELEASE_NOTES, architecture), create the release commit and an annotated vX.Y.Z tag, push, and then verify and repair the GitHub Release so its body and the tag message are a user-focused summary of changes since the previous release. Triggers on: release, publish, cut a version, version bump, tag a release, changelog, release notes.
---

# ComPort Zone Version Release

Prepare and publish a ComPort Zone release: bump the version, update the
user-facing docs, make the release commit, create and verify an annotated
`vX.Y.Z` tag, push, then verify and curate the GitHub Release body.

This skill is **agent-neutral** — Codex and Claude both run the same
commands. It lives in the tracked top-level `skills/` directory (not
`.claude/skills/`, which is git-ignored here) so it is shared, not per-user.

## How this is driven

The mechanical, verifiable steps are a PowerShell driver committed next to
this file. **All paths below are relative to the repo root.**

```
powershell -NoProfile -ExecutionPolicy Bypass -File skills\comport-zone-version-update\driver.ps1 <verb> ...
```

| Verb | What it does | Mutates? |
|------|--------------|----------|
| `preflight -Version X.Y.Z` | Gate checks: branch, clean tree, semver, tag-absent (local+remote), previous tag, commit count, version-surface agreement | no |
| `changes [-Since vA.B.C] [-Out <file>]` | Raw `- <subject> (<hash>)` change list since the previous tag | no |
| `bump -Version X.Y.Z [-DryRun]` | Runs the project version script, then checks `VERSION` + `pyproject` match | yes (writes 2 files) |
| `tag -Version X.Y.Z -MessageFile <f> [-DryRun]` | Creates the annotated `vX.Y.Z` tag from a message file and verifies it | yes (creates tag) |
| `verify -Version X.Y.Z` | Inspects the annotated-tag message **and** the GitHub Release body, flags anything not user-focused | no |

**Read-only / safe to run anytime:** `preflight`, `changes`, `verify`, and
**any** verb with `-DryRun`. The judgment steps — choosing the version number
and writing the user-focused docs and notes — are yours.

## Prerequisites

- Windows + PowerShell 5.1+ (the driver and the project's own scripts are PowerShell).
- `git` and the GitHub CLI `gh` on `PATH`. `gh` must be authed with `repo` + `workflow` scope:

```
gh auth status
```

- For the test gate, a dev virtualenv (first time only): `.\setup_dev.bat`. Run tests with `.\run_tests.bat`.

## Release procedure

Run from the branch you will release from — normally **`master`**, after merging
feature branches. Use the bare version `X.Y.Z` (no `v`) for `-Version`; tags are
`vX.Y.Z`. Scratch files below go under `build\` (git-ignored).

### 1. Preflight

```
powershell -NoProfile -ExecutionPolicy Bypass -File skills\comport-zone-version-update\driver.ps1 preflight -Version X.Y.Z
```

Resolve every `[FAIL]` before continuing; read every `[WARN]`. Pick `X.Y.Z`
per semver, guided by the change list (breaking → major, new features → minor,
fixes only → patch).

### 2. Capture the raw change list (traceability input, not release copy)

```
powershell -NoProfile -ExecutionPolicy Bypass -File skills\comport-zone-version-update\driver.ps1 changes -Out build\release-vX.Y.Z-changes.txt
```

### 3. Bump the version

```
.\update_version.bat X.Y.Z
```

This updates `src\ComPort_Zone\VERSION` and `pyproject.toml`. Agents should
prefer the driver's `bump` verb instead — it calls `scripts\update_version.ps1`
directly (so it avoids the `.bat`'s interactive `pause`-on-error, which hangs a
non-interactive session) and then verifies both surfaces:

```
powershell -NoProfile -ExecutionPolicy Bypass -File skills\comport-zone-version-update\driver.ps1 bump -Version X.Y.Z
```

### 4. Update the documents — write for users first

- **`README.md`** — bump the version badge (this is the only version string in the README; there is **no** "Current version:" line, and `update_version.bat` does **not** touch the README):

  ```
  ![Version](https://img.shields.io/badge/version-X.Y.Z-3aa675)
  ```

  Also update CLI/usage sections if commands, options, or output changed.
- **`CHANGELOG.md`** (Keep-a-Changelog style) — rename the top `## Unreleased`
  heading to `## X.Y.Z - YYYY-MM-DD`, then add a fresh empty `## Unreleased`
  block above it. **Reconcile** its Added/Changed/Fixed entries against the
  change list from step 2 — the hand-written `Unreleased` section often lags the
  actual commits.
- **`RELEASE_NOTES.md`** — prepend a block:

  ```
  # ComPort Zone vX.Y.Z Release Notes

  Release date: YYYY-MM-DD

  <one-line summary of the release for users>

  ## Highlights
  - ...

  ## What's New / ## Fixed / ## Compatibility   (sections as needed)

  ## Upgrading
  <settings/data compatibility, any action required>
  ```

  Use "Users can…" / "The app now…". Mention internal refactors or tests only
  when they explain a user-visible reliability, compatibility, or automation
  benefit.
- **`docs/ARCHITECTURE.md`**, **`docs/DESIGN.md`** — update only if ownership, flow, or architecture changed.

### 5. Validate

```
.\run_tests.bat
git diff --check
```

### 6. Commit

Review `git status`, then stage and commit with subject `Release vX.Y.Z` and the
change list as the body. Put the message in a file to avoid quoting issues —
first line `Release vX.Y.Z`, a blank line, then the lines from step 2:

```
git add -A
git commit -F build\release-vX.Y.Z-commit.txt
```

### 7. Create and verify the annotated tag

Write `build\release-vX.Y.Z-tag.txt` (first line must be the title):

```
ComPort Zone vX.Y.Z

Release date: YYYY-MM-DD

<2-4 line user-facing summary>

Maintainer traceability:
<the raw change list from step 2>
```

Then create + verify it through the driver:

```
powershell -NoProfile -ExecutionPolicy Bypass -File skills\comport-zone-version-update\driver.ps1 tag -Version X.Y.Z -MessageFile build\release-vX.Y.Z-tag.txt
```

The driver runs `git tag -a vX.Y.Z -F <file>`, confirms `git cat-file -t vX.Y.Z`
is `tag`, and prints `git tag -n99 vX.Y.Z`. A **title-only** tag message is the
exact bug this step prevents.

### 8. Push — this triggers the Release workflow

```
git push origin master
git push origin vX.Y.Z
```

`.github/workflows/release.yml` runs on `v*.*.*` tags: it re-checks that
`vX.Y.Z` matches `src\ComPort_Zone\VERSION`, runs the tests, builds the Windows
`onedir` package + Inno Setup installer, and creates the GitHub Release with
`gh release create --generate-notes`.

### 9. Verify and curate the GitHub Release — mandatory

```
powershell -NoProfile -ExecutionPolicy Bypass -File skills\comport-zone-version-update\driver.ps1 verify -Version X.Y.Z
```

CI's auto-`--generate-notes` body is **not** a user summary — when the release
range has no merged PRs it is only a `**Full Changelog**` compare link (this is
exactly what shipped for `v0.4.1`). Replace it with a curated, user-focused body
(reuse your `RELEASE_NOTES.md` section):

```
gh release edit vX.Y.Z --repo shuky-shukrun/ComPort-Zone --notes-file build\release-vX.Y.Z-notes.md
```

Re-run `verify` until both the release body and the tag message read as a
user-focused summary of changes since the previous release. If `gh`/auth/network
is unavailable, report the exact blocked command and the local verification
already done.

### 10. Final report

Summarize: previous tag → new version, files changed, test + whitespace results,
commit hash, annotated-tag verification, branch + tag push results, the GitHub
Release URL, and whether its body was generated-then-curated.

## Document formats (exact)

| Surface | What to change |
|---------|----------------|
| `src\ComPort_Zone\VERSION` | `X.Y.Z` (no `v`) — written by `update_version.bat` |
| `pyproject.toml` | `version = "X.Y.Z"` — written by `update_version.bat` |
| `README.md` | `badge/version-X.Y.Z-3aa675` badge — **hand-edit** |
| `CHANGELOG.md` | rename `## Unreleased` → `## X.Y.Z - YYYY-MM-DD`; add fresh `## Unreleased` |
| `RELEASE_NOTES.md` | prepend `# ComPort Zone vX.Y.Z Release Notes` block |
| annotated tag `vX.Y.Z` | title `ComPort Zone vX.Y.Z` + date + user summary + traceability |
| GitHub Release body | curated user-focused notes (replace CI's generated body) |

## Gotchas

- **CI publishes a non-user-facing body.** The release workflow uses
  `gh release create --generate-notes`. With no merged PRs in the range the body
  is just `**Full Changelog**: <compare-link>`. Step 9 (curate the body) is
  mandatory, not optional. `verify` flags this with a `[FAIL]`.
- **Annotated tags need a real message body.** `git tag -a vX.Y.Z -m "ComPort Zone vX.Y.Z"`
  leaves `git tag -n99` showing only the title (this happened for `v0.4.1`).
  Always create the tag from a `-F <file>` message; the driver's `tag`/`verify`
  verbs enforce and check this.
- **`update_version.bat` pauses on error.** The `.bat` ends with `pause` when the
  version script fails, which hangs a non-interactive agent. The driver's `bump`
  verb calls `scripts\update_version.ps1` directly to avoid this. Validate the
  version first either way.
- **No "Current version:" line in the README.** The version lives only in the
  shields.io badge, and `update_version.bat` does not edit the README — bump the
  badge by hand. `preflight`/`bump` warn when the badge disagrees with `VERSION`.
- **The CHANGELOG `## Unreleased` section drifts.** It is hand-maintained and can
  lag the actual commits. Always reconcile it against `driver.ps1 changes` before
  renaming it to the version heading.
- **Release from `master`.** `origin/HEAD` → `master`. Feature branches must merge
  to `master` before tagging. CI only enforces tag == `VERSION`, not the branch,
  so it will not catch a mis-branched release; `preflight` warns when you are not
  on the default branch.
- **Two version surfaces must equal the tag** or the workflow's "Verify release
  tag matches project version" step fails: `src\ComPort_Zone\VERSION` and
  `pyproject.toml`.
- **`.claude/` is git-ignored** (per-user). That is why this shared skill lives in
  the tracked top-level `skills/` directory. Claude Code will not auto-trigger it
  as a `/` command — invoke it by running the driver or reading this file.

## Troubleshooting

- `gh release view` exits non-zero right after pushing the tag → the Release
  workflow has not created the release yet. Watch the Actions tab, then re-run
  `verify`.
- Release workflow fails at **"Verify release tag matches project version"** → the
  tag does not match `VERSION` (tagged before bumping, or bumped to the wrong
  number). Delete the bad tag (`git push origin :vX.Y.Z` then `git tag -d vX.Y.Z`),
  fix `VERSION`, re-tag.
- `update_version.ps1` throws *"must use major.minor.patch format"* → you passed a
  `v`-prefixed or non-semver value. Pass `X.Y.Z` only.
- `driver.ps1 preflight` reports `[FAIL] vX.Y.Z already exists` → pick the next
  version, or (if the tag was created in error and not pushed) delete it with
  `git tag -d vX.Y.Z`.
