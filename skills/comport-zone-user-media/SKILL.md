---
name: comport-zone-user-media
description: Maintain ComPort Zone's English user manual, tutorial sources, local Kokoro narration, and versioned GitHub Release downloads. Use for documentation reviews, media rebuilds, and publishing manual/tutorial assets; keep generated PDF/video out of Git.
---

# ComPort Zone User Manual And Tutorial

Read root `AGENTS.md` and `tools/media/README.md`. All commands below run from
the repository root. The latter is the single detailed production runbook.

## During a PR

Review `docs/USER_MANUAL.md` and the linked CLI/scripting references for every
change. Include updated user instructions and relevant screenshots when behavior
changes. If users observe no difference, explain why in the PR template's manual
review notes. A checked review is a statement of actual review, not a substitute
for checking the changed workflow.

Update `tools/media/storyboard.json`, `walkthrough.py` actions, capture steps and runnable examples when a
demonstrated workflow changes. PRs contain these sources and small images/text,
not generated PDF, MP4, audio or models. `tools/media/check_docs.py` checks the
version, links, tracked binaries and PR declaration; CI builds a PDF preview.

## Rebuild and verify

- The app environment runs `tools/media/capture.py` against its isolated localhost
  demo. It never uses physical COM hardware or the user's settings.
- The video is a hands-on GUI recording: real clicks, typing, menus, dialogs,
  scripts and polling. Preserve this tutorial style when updating it. Run
  `walkthrough.py --rehearse`, inspect the step screenshots, then record with
  `walkthrough.py` after narration. Keep Qt tests separate from recording.
- A separate Python 3.12 media environment uses `tools/media/requirements.txt`.
  For PDF-only work, install `requirements-pdf.txt`; do not download speech models.
- Narration is local **Kokoro v1.0 / am_michael**. ElevenLabs is a later upgrade.
  `download_models.py` verifies model hashes. Do not substitute another narrator
  unless the user asks to change the voice/provider.
- For a voice comparison, use `tools/media/audition.py` and `audition.json`.
  The runbook covers the separate GPU environment and pinned local Qwen model.
  Auditions are local review files; select a production narrator only after the
  user chooses a candidate, then rebuild production media through its usual checks.
- Use `build.py pdf`, `narrate`, `walkthrough.py`, and `build.py video`; see the runbook for ordering. Inspect
  PDF page renders and representative finished video frames, verify captions and
  audio, and exercise the GUI/CLI examples. Tests use unittest, not pytest.

## Release assets

The manual's English-edition header records the reviewed app version and ISO
date. Review/update it before releasing. The release workflow always generates
the PDF from current Markdown and screenshots; it never carries forward a PDF.

`release_media.py plan --online` compares the previous release's manifest with
the current app, storyboard, capture, demo and renderer sources. It rebuilds a
changed recording; an unchanged one retains its original version and download
URL. A version-only bump can reuse it. `--video always` forces a new recording.

Build receipts and SHA-256 checks prevent publishing stale/mutated files. Use
`release_media.py package`, then the explicit `upload --tag vX.Y.Z` command when
publication is in the user's authorized scope. It attaches only media files to
an existing release, preserves app assets and notes, and verifies uploaded
checksums. `--replace` is for an intentional revision to existing media assets.
Never create a new app release/tag merely to refresh documentation.

Use the version-release skill when actually bumping/cutting a new app release;
this skill does not itself authorize that wider action. Stop on a version/hash
mismatch, repair the source/build, and retry the deterministic step. Do not work
around a stale receipt by changing its fingerprint manually.
