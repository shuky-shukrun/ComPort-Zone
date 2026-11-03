# Manual and tutorial production

The initial English manual and tutorial describe ComPort Zone 0.9.0. The manual's source
is [docs/USER_MANUAL.md](../../docs/USER_MANUAL.md); the video script, chapters,
on-screen notes and voice settings live in [storyboard.json](storyboard.json).

The narration matches the RDT reference project's current engine: **local
Kokoro v1.0 through kokoro-onnx, `am_michael`, English**. No account, service, API
key, or paid generation is needed. ElevenLabs is deferred to a later improvement.
The scene-level scripts, cached audio, and timeline make replacing the narrator
possible without rewriting the tutorial.

## Outputs

Builds write to `docs/media/`, with MP4/WAV/PDF ignored by Git. Canonical binary
downloads live on **GitHub Releases**, outside Git history and Git LFS:

- `comport-zone-user-manual.pdf`: illustrated, searchable manual.
- `comport-zone-walkthrough.mp4`: 1920 x 1080 narrated guided walkthrough,
  with real application captures, a short live polling sequence, chapter labels,
  explanatory notes and burned-in English captions.
- `comport-zone-walkthrough.srt`: separate subtitles.
- `comport-zone-walkthrough.chapters.txt`: chapter timestamps.
- `comport-zone-walkthrough.transcript.md`: readable narration transcript.
- `tutorial-*.png`: screenshots captured from the current app.

Commit the manual Markdown, small PNGs, tutorial examples, storyboard, tools,
instructions and text sidecars. Never commit generated MP4/audio/PDF, model files
or the media environment. Text sidecars in Git describe the last locally built
recording; matching release assets are authoritative for a published video.

Every release builds a new PDF from its reviewed Markdown and screenshots.
The manual header declares the reviewed app version and ISO date; the renderer
rejects a version mismatch. `comport-zone-media.json` records the source commit,
manual review date, input fingerprints, download URLs and SHA-256 hashes.
`comport-zone-media.sha256` covers the uploaded files.

Video is rebuilt when application Python sources, storyboard, capture/demo code,
examples or video renderer/dependencies change. A version-only bump or manual-only
correction can reuse the last recording. Its original version and URL remain in
the new release notes/manifest; old videos are not relabeled or duplicated.
Use `--video always` for a new cut, including a screenshot-only refresh. Runtime
timestamps in newly captured images do not force perpetual later rebuilds.

The guide combines actual GUI captures with explanatory command cards. It does
not represent an uninterrupted recording of a physical bench. Serial settings
are illustrated; the demonstrated communication uses localhost TCP and UDP.

Intermediates, model downloads, speech cache, validation reports and video clips
go into the git-ignored `artifacts/user-guide/`. Override that location with
`COMPORT_ZONE_MEDIA_WORK`. Generated full narration WAVs are work files; the MP4
already contains the audio.

## Prerequisites on Windows

1. Set up the app with `setup_dev.bat`. Its Python environment supplies PySide6
   for `capture.py`.
2. Use **Python 3.12** for the media environment. The current Kokoro package
   supports Python 3.10-3.13; a Python 3.14 app environment can still capture the
   GUI but cannot install this Kokoro version.
3. Install the isolated media requirements:

```powershell
py -3.12 -m venv artifacts/user-guide/venv
.\artifacts\user-guide\venv\Scripts\python.exe -m pip install -r tools/media/requirements.txt
.\artifacts\user-guide\venv\Scripts\python.exe tools/media/download_models.py
```

The first model download is about 354 MB. The downloader verifies file size and
SHA-256 before replacing a model. FFmpeg is supplied by `imageio-ffmpeg`.
The renderers use Windows Segoe UI and Consolas. PDF-only work needs just
`tools/media/requirements-pdf.txt`, without speech models. PDF visual review uses
Poppler's `pdftoppm` (not needed merely to read the final PDF).

## Rebuild

Run from the repository root. Keep TCP/UDP port 5025 free; the capture process
starts and stops its own tutorial server. If another tutorial server is running,
stop that process first. Nothing connects to a physical COM port.

```powershell
# Real Qt widgets, actual localhost communication, isolated settings.
.\.venv\Scripts\python.exe tools/media/capture.py

# Local narration; unchanged sentences reuse their cached audio.
.\artifacts\user-guide\venv\Scripts\python.exe tools/media/build.py narrate

# Assemble the video, subtitles, transcript and chapter timestamps.
.\artifacts\user-guide\venv\Scripts\python.exe tools/media/build.py video

# Generate the manual from its Markdown and the captured screenshots.
.\artifacts\user-guide\venv\Scripts\python.exe tools/media/build.py pdf
```

`narrate --pilot` and `video --pilot` build the first two scenes only. Full scene
audio is padded to video frame boundaries to avoid cumulative A/V drift. The
narration manifest records voice settings and model hashes. Video scene caches
include the renderer, captions, screenshot and audio hashes.

The PDF renderer is `manual_pdf.py`, separate from the video renderer in
`build.py`; changing PDF formatting alone does not invalidate a video. Build
receipts in the work directory record inputs/output hashes. Changed sources
require rebuilding; do not edit receipt hashes to bypass this check.

Capture uses the offscreen Qt backend and explicitly loads fonts on Windows.
It never drives your desktop. It writes only to the media work directory and
the tutorial screenshots, disabling app update checks in its isolated settings.
It verifies the identity reply and three successful script checks, then runs
the documented CLI examples with a separate configuration file. Check
`capture-validation.json` and `cli-validation.json` after rebuilding.

## Verify before publishing

```powershell
.\scripts\run_tests.ps1 tests.test_tutorial_media
.\scripts\run_tests.ps1 tests.test_media_release
.\run_tests.bat
python tools/media/check_docs.py
git diff --check
pdftoppm -scale-to 1100 -png docs/media/comport-zone-user-manual.pdf artifacts/user-guide/page
```

Inspect the rendered PDF pages and representative final video frames, and check
that the caption timing stays within the audio/video duration. Check narration
for pauses, pronunciation and consistent volume when reviewing an updated cut.
Do not add model files, intermediate WAVs, or the media environment to Git.

## Every pull request

Review `docs/USER_MANUAL.md`, `docs/COMMAND_FILES.md` and `docs/CLI_REFERENCE.md`
against changed behavior. Include affected instructions and relevant screenshots
in a user-facing PR. For a change with no observable user effect, explain why
instead of making an empty documentation edit.

Complete the PR template's checked `User manual reviewed`, `Manual impact:` and
`Manual review notes:` declarations. The Documentation workflow verifies the
declarations, requires changed user documentation for an `updated` declaration,
checks the manual's version/local links, rejects tracked video/PDF/models, and
builds a searchable PDF preview. It reruns on PR-body edits. Reviewers still
judge whether the instructions actually match the application; a checkbox cannot
establish semantic completeness.

PRs update tutorial source/storyboard where relevant, but never include an MP4.
PDF previews are temporary Actions artifacts (14 days), not published downloads.
Only releases produce and publish the narrated video.

## Publish media on an existing release

These commands use GitHub CLI authentication (`gh auth status`) and do not create
an app release or tag. Run upload within the user's authorized publishing scope.
The Release workflow runs the same sequence before/after publishing the normal
installer and portable build.

```powershell
# Activate the isolated Python 3.12 media environment first.
.\artifacts\user-guide\venv\Scripts\Activate.ps1

# Read the previous published receipt and make a local rebuild/reuse plan.
python tools/media/release_media.py plan --online
# Optional: --video always forces a new recording.

# If rebuilding: run capture.py, build.py narrate and build.py video.
# Always build the PDF after any capture refresh, even when reusing video.
python tools/media/build.py pdf
python tools/media/check_docs.py --pdf docs/media/comport-zone-user-manual.pdf
python tools/media/release_media.py package

# Inspect artifacts/user-guide/publish/, its manifest and checksums first.
python tools/media/release_media.py upload --tag v0.9.0
python tools/media/release_media.py verify --tag v0.9.0
```

Replace `v0.9.0` with the package's app version. Replacing an existing asset needs
explicit `--replace`; unchanged uploads are skipped when GitHub reports the
matching hash. Upload verifies size and SHA-256, preserves installer/ZIP assets,
and changes only its marked section in existing release notes. An immutable
release needs a new release instead of editing its assets.

The PDF uses `/releases/latest/download/comport-zone-user-manual.pdf`, since each
release publishes one. Video links go to release notes, whose versioned URL can
refer to an unchanged earlier recording. Do not use a latest MP4 URL when a
release might intentionally reuse a prior recording.

The Release workflow's `video` dispatch input defaults to `auto`. It caches the
verified model, generates changed video only on releases, rebuilds the manual
every time, packages checksums/manifest and verifies publication. A manual
dispatch on a branch produces build artifacts without publishing a tag.

## When the app changes

Update the matching manual section and storyboard scenes, rerun captures, then
rebuild affected media. Keep the documented release/version aligned with the
app. Update the manual's `Reviewed YYYY-MM-DD` date when reviewing a new app
version. A text-only edit need not regenerate unchanged narration sentences.
Follow the shared [user-media skill](../../skills/comport-zone-user-media/SKILL.md)
and [version-release skill](../../skills/comport-zone-version-update/SKILL.md).

For a future ElevenLabs upgrade, replace the speech-generation adapter while
retaining scene IDs, readable captions and timing output. That upgrade needs a
separate voice/model choice and an account; it is not part of this version.

## References and attribution

The structure was informed by RDT's
[user manual](https://github.com/rani-feldman/RDT/blob/main/docs/USER_MANUAL.md)
and [media workflow](https://github.com/rani-feldman/RDT/blob/main/tools/media/README.md).
Its Linux/X11 capture implementation is not required here. The ComPort Zone
manual, narration, demo instrument and media tools are written for this project.
Kokoro model files come from the
[kokoro-onnx v1.0 model release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0).
