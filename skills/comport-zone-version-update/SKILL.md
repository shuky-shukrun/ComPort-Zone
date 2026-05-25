---
name: comport-zone-version-update
description: Guides ComPort Zone release preparation and publishing. Use when Codex needs to bump the ComPort Zone app version, update README/changelog/release notes/CLI reference material, create a release commit, create and verify an annotated vX.Y.Z tag, push release refs, and verify or repair the generated GitHub Release body.
---

# ComPort Zone Version Update

## Purpose

Use this skill for ComPort Zone version releases. It keeps the version files, release documentation, git tag, and GitHub Release message aligned with the release workflow in `.github/workflows/release.yml`.

## Preflight

1. Work from the repo root and read these files before changing anything:
   - `docs/LLM_CHANGE_GUIDE.md`
   - `.github/workflows/release.yml`
   - `src\ComPort_Zone\VERSION`
   - `pyproject.toml`
   - `README.md`
   - `CHANGELOG.md`
   - `RELEASE_NOTES.md`
2. Inspect the repo state:
   - `git status --short --branch`
   - `git branch --show-current`
   - `git describe --tags --abbrev=0`
   - `git tag --list vX.Y.Z`
3. Continue only when the current branch is `master`, the target version is strict `X.Y.Z`, and no local tag named `vX.Y.Z` exists. If network access is available, also check the remote tag with `git ls-remote --tags origin vX.Y.Z`.
4. If version files are already modified or staged, inspect them. Reuse them only if they already match the requested target version; otherwise stop and report the mismatch.

## Version And Documentation

1. Run the real project script from the repo root:
   - Preferred shorthand: `.\update_version.bat X.Y.Z`
   - Equivalent explicit form: `.\update_version.bat -Version X.Y.Z`
   - Do not use `version_update.bat`; that is not the current repo script name.
2. Confirm both version surfaces now match:
   - `src\ComPort_Zone\VERSION` contains `X.Y.Z`
   - `pyproject.toml` has `version = "X.Y.Z"`
3. Update release documentation:
   - `README.md`: update `Current version:`, release command examples if they name the release version, and CLI reference sections when CLI behavior changed.
   - `CHANGELOG.md`: prepend `## X.Y.Z - YYYY-MM-DD` with Added/Changed/Fixed/Tests sections as appropriate.
   - `RELEASE_NOTES.md`: prepend `# ComPort Zone vX.Y.Z Release Notes`, release date, highlights, user-facing changes, and validation.
4. Search before deciding whether CLI reference text needs edits:
   - `rg -n "CLI|comport-zone|Usage|Commands|--json|--port|version|update|settings|history|quick|files|run|validate" README.md docs src\ComPort_Zone\cli tests -S`
   - Update README or nearby CLI documentation when commands, options, output formats, or examples changed.

## Change List

1. Identify the previous release tag with `git describe --tags --abbrev=0`.
2. Generate the raw change list before creating the release commit:
   - `git log --format="- %s (%h)" <previous-tag>..HEAD`
3. Use the raw list as the source for:
   - user-facing changelog bullets,
   - release notes highlights,
   - the release commit body,
   - the annotated tag message,
   - the GitHub Release body.
4. The tag message and GitHub Release body must contain the concrete list of changes since the previous version, not only a generic "Release vX.Y.Z" line.

## Validate, Commit, Tag, And Push

1. Run validation:
   - `.\run_tests.bat`
   - `git diff --check`
2. Review `git status --short`. Stage all intended release changes with `git add -A` only after reviewing the status output.
3. Commit with subject `Release vX.Y.Z`. Include the generated change list in the commit body.
4. Create an annotated tag from a message file to avoid shell quoting issues:
   - First line: `ComPort Zone vX.Y.Z`
   - Include the release date.
   - Include the generated change list.
   - Command: `git tag -a vX.Y.Z -F <tag-message-file>`
5. Verify the tag:
   - `git cat-file -t vX.Y.Z` must output `tag`
   - `git tag -n99 vX.Y.Z` must include the release title and change list
6. Push the branch and tag separately:
   - `git push origin master`
   - `git push origin vX.Y.Z`

## GitHub Release Verification

The release workflow publishes on tags matching `v*.*.*` and rejects tags that do not match `src\ComPort_Zone\VERSION`.

1. Wait for the tag-triggered release workflow to create the release.
2. Verify the GitHub Release body:
   - `gh release view vX.Y.Z --repo shuky-shukrun/ComPort-Zone --json body,url`
3. If the release body does not contain the generated change list, write the curated release body to a temporary file and update the release:
   - `gh release edit vX.Y.Z --repo shuky-shukrun/ComPort-Zone --notes-file <release-notes-file>`
4. Re-run `gh release view` and confirm the body now contains the change list.
5. If `gh`, auth, or network access is unavailable, report the exact blocked command and the local verification already completed.

## Final Report

Summarize:

- target version and previous tag,
- files updated,
- tests and whitespace check results,
- commit hash,
- annotated tag verification,
- branch and tag push results,
- GitHub Release URL and whether the body was already correct or edited.
