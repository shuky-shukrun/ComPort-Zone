# Changelog

All notable changes to ComPort Zone are documented here.

## Unreleased

### Added

- **UDP endpoints, in the app and the CLI** — a terminal tab can now talk to a UDP device: pick **UDP** in Connection Settings, enter a host and port, and send/receive exactly as you would over serial or TCP. The CLI gains matching `--udp-host`/`--udp-port`/`--udp-timeout` flags on `send`/`hex`/`listen`/`run`/`repl`, quick send, and `files run` (kept distinct from the serial `--port` and the TCP `--host`; mixing flags from two transports is a usage error), plus `COMPORTZONE_UDP_*` environment variables, UDP `/set` shortcuts in the REPL, and `"transport": "udp"` in JSON records. `resources/udp_echo_server.py` ships as a local target to test against.

  UDP is connectionless and the app treats it that way rather than pretending otherwise. A reply is **one whole datagram**, so devices that answer without a CR/LF terminator work with no configuration — where a line-framed transport would sit there until the timeout. There is no auto-reconnect (there is no link to lose), so that checkbox is absent from the UDP page and `--auto-reconnect` is accepted and ignored; `--wait` is likewise a no-op, because opening a datagram socket does no network I/O. Sending to a port with no listener does not tear the session down: the resulting ICMP port-unreachable is ignored, as UDP requires.

- **Release notes in the update prompt** — when a new version is found, the dialog now shows what is actually in it, read from the release notes published on GitHub Releases. If your build is more than one version behind, the notes of *every* release you skipped are accumulated newest-first, each under its own version heading with its date and a link to its release page, in a scrollable pane sized to the notes (capped, so the dialog stays on screen). The notes come from the same releases feed the check already uses, so this costs no extra request and is still not subject to the GitHub API rate limit. Notes are HTML from the network, so they are re-serialized down to a safe subset before rendering: scripts, styles, images, inline event handlers, and non-`http(s)` links are dropped, and only link text survives from a rejected link.

### Changed

- **The raw TCP connection type is now labelled "TCP", not "LAN".** With UDP alongside it, "LAN" named the network rather than the protocol — both are LAN transports — and read as a third category next to UDP. The Connection Settings dropdown, tab titles, status bar, tooltips, and error messages all say TCP now. Nothing about saved settings changes: the persisted transport kind is still `lan`, so existing files load untouched and older builds still read them.
- **Settings schema is now version 9.** Only a settings file that actually contains a UDP endpoint declares the new floor, so serial- and TCP-only files stay readable by older builds exactly as before. A file that *does* use UDP will be refused by builds older than this one rather than silently losing the endpoint.

## 0.6.1 - 2026-08-12

### Fixed

- **Reverted the v0.6.0 burst RX-read coalescing** — the change that merged consecutive small reads into a single render pass to speed up long messages caused problems in practice and has been reverted; RX events render one at a time again, as in v0.5.2 and earlier. A revisit will follow in a later release.

## 0.6.0 - 2026-08-11

### Added

- **`@@settings` persistent execution directives in command files** — `@@name value` lines set execution properties that persist from that line to the end of the run (or until the same setting is set again): `@@wait <ms>` (delay before each following command), `@@expect-timeout <ms>` (timeout for following `EXPECT` steps), `@@on-error stop|continue` (abort on a failed step, or log it and continue), and `@@send-mode text|hex` (read following bare/SEND lines as text or raw hex). They're distinct from the one-time `WAIT` step and `{{param}}` templating, and are never sent to the device. A single settings registry keeps the parser, both run engines (GUI and CLI), syntax highlighting, completion, and validation in agreement, with editor squiggles and CLI `validate` catching unknown or malformed `@@` lines. See `example-settings.cpz` and the README for the full list.
- **CLI: raw TCP endpoints alongside serial** — `send`/`hex`/`listen`/`run`/`repl`, quick send, and `files run` now also accept a raw TCP endpoint via `--host`/`--tcp-port`/`--tcp-timeout`, kept distinct from the serial `--port` (mixing the two is a usage error). The REPL gains matching TCP `/set` shortcuts and `/show endpoint`. JSON `rx`/`status` records self-identify their transport. See `docs/CLI_REFERENCE.md` and the bundled `resources/tcp_echo_server.py` for a local target to test against.

### Changed

- **Large device messages render instantly instead of over ~2 seconds** — a long message that arrives from the port as many small reads used to trigger a full render pass per read; those bursts are now coalesced into a single render pass, over 1000x faster in the worst case, with per-source ordering (TX echoes, status lines, control-panel traffic) preserved.

### Fixed

- **App stuck on the logo at launch when a restored command file was deleted** — if a command-file tab was open when the app last closed and that file was later deleted, moved, or lived on a drive that is no longer mounted, startup raised a modal "Open Command File" error while rebuilding the workspace — before the main window existed, and behind the always-on-top splash. The dialog was invisible but blocking, so the app sat on the logo forever; the only sign of it was an extra window under ComPortZone in Task Manager, and ending that window let the launch continue. Restoring a tab whose file is gone now keeps the tab (still bound to its path, so Save recreates the file) with an empty buffer, and reports the reason in the tab's status line and the status bar instead of a dialog. Two guards back it up: the startup splash is no longer always-on-top, so nothing on screen can be hidden behind it, and the freeze watchdog now also covers window construction — a startup that stalls writes `freeze-dump.txt` next to the settings file instead of leaving nothing to diagnose.
- **Control Panel binding chip shows the terminal's name, not just the port** — a bound panel's status chip now reads `Polling My Tab (COM10)` instead of the raw `COM10`, matching the name shown in the bind menu; an unnamed terminal still shows just its endpoint (no redundant `COM10 (COM10)`). Renaming the bound terminal updates the chip immediately (it previously stayed stale until the next connect/disconnect).

## 0.5.2 - 2026-06-23

### Added

- **Multi-tile editing on the Control Panel canvas** — select several tiles (Ctrl-click, or drag a marquee box over them) and operate on them as a group:
  - **Drag-move the group**: dragging any selected tile in edit mode moves the whole selection together, preserving their relative layout; a dashed preview shows every tile's destination.
  - **Delete / Cut / Copy / Duplicate** the selection from the right-click menu (labelled with the count, e.g. "Remove 3 Tiles") or the keyboard. Cut is editor-style — it copies to the clipboard and removes the originals immediately (Paste re-adds them, here or in another panel). Multi-delete asks to confirm; duplicate clones the selection as a block.
  - **Apply Size to all selected** at once from the tile's Size submenu.
  - **Keyboard shortcuts** (when the grid is focused, so they never hijack copy in an input field): Ctrl+C / Ctrl+X / Ctrl+V, Delete, Ctrl+A (select all), Ctrl+D (duplicate), and Esc (clear the selection, then disarm).
  - **Marquee box-select**: drag a rectangle on empty grid space to select every tile it touches; Ctrl+drag adds to the current selection.
- **Sort + drag-reorder for the Control Panels side bar** — the Control Panels rail and the Favorite Control Panels panel now match the Files panel: a sort button (Custom order / Name) in the header and drag-to-reorder rows. Dragging a row switches that list to Custom order and remembers the arrangement; the sort mode and custom order persist (separately for the saved list and the favourites).
- **Open files from Explorer, and drag them in** — double-click a `.cpz` command file (or pass one on the command line) and it opens as a tab in your already-running ComPort Zone instead of launching a second copy; re-opening a file that is already open just focuses its tab. You can also drag command files from Explorer onto the tab area to open them, or onto the sidebar's Files list to add them as Quick Files.

### Changed

- **Control Panel polling pauses for command-file runs, with one-click Resume** — when a command file runs on a panel's bound connection, the panel pauses its polling and controls and shows a prominent amber banner with a **Resume polling** button that lifts the pause for that run only. It is safe: a resumed panel's polls are ignored by the running script's `EXPECT` checks, so they can neither satisfy nor pollute them.
- **More reliable shared connections** — the serial/LAN I/O layer was reworked into a single serialized request/response channel per connection. When the terminal, a running command file, and Control Panel polling share one port, each reply now reliably reaches the requester that asked for it; the previous design could misroute replies under heavy concurrency.

### Fixed

- **Control Panel value reading now auto-fits the tile** — a *value* tile sizes its reading to the whole tile: the largest font at which the text actually fits. A short reading in a big 2×2 tile grows to a bold, glanceable number; a long one (e.g. an `*IDN?` identity) shrinks to fit instead of overflowing and being clipped — previously every tile rendered the value at the same fixed size regardless of tile size or text length. The fitted size also survives live polling: it previously rode a plain `setFont`, which the per-poll state refresh silently reset (every poll re-resolves the tile's QSS font, which sets no `font-size`), so the readout snapped back to the default — it now travels on the label's own inline stylesheet and persists.
- **LED tile now scales with tile size** — the indicator lamp grows with the tile (it was a fixed ~18px dot that looked tiny in a large tile) and stays perfectly circular at any size, and its caption scales alongside it; the status-bit register labels scale too. Previously the lamp was fixed and the caption / bit-label fonts — though computed from the cell size — were applied with a plain `setFont` that the per-poll repolish silently reset (the lamp/caption state change, or a bit's active-state toggle, re-resolves the QSS font, which sets no `font-size`), so in the running app they stayed at the default. The lamp size, its radius, and the label fonts now ride each widget's inline stylesheet and persist.
- **Crash when splitting a pane that holds a live Control Panel** — moving a tab between split panes (Split Right/Down, drag, or Join) briefly leaves it parentless, and a live panel keeps a repaint timer running; a paint delivered to the widget mid-reparent hit a paint device with no engine (`QPainter::begin … engine == 0`) and could crash. Updates are now suppressed on the moved widget for the duration of the reparent, then restored. The tile drag-preview also no longer grabs a zero-size tile.
- **Check for Updates no longer fails with "HTTP 403: rate limit exceeded"** — the check queried GitHub's REST API, which caps unauthenticated requests at 60/hour per IP (easily hit with check-on-launch, or on a shared office network). It now reads the releases Atom feed, which has no per-IP cap, so update checks work every time; a failed check also shows a clear message instead of a raw HTTP error.

## 0.5.1 - 2026-06-10

### Fixed

- **Crash on launch in the packaged (installer) build** — v0.5.0 failed to start with `RuntimeError: sys.stderr is None`. The freeze watchdog called `faulthandler.enable()`, which defaults to writing to `sys.stderr`; a windowed (no-console) PyInstaller build has no `sys.stderr`, so it raised before the window appeared. The watchdog now points faulthandler at its own dump file and can never block startup. (Running from source has a console, so dev/CI never hit it.)

## 0.5.0 - 2026-06-10

### Added

- **Control Panel** — a new third workspace tab type (alongside the terminal and the command-file editor) that turns a connection into a live operator console: a grid of tiles, each a command that polls in the background, so you can read and drive your gear at a glance.
  - **Monitoring tiles** — *value* tiles show a parsed reading (first line or a regex capture, numeric or text) with a per-tile interval, unit, and ordered color rules that drive an OK / WARN / FAIL / stale / error state; *LED* tiles render GO/NO-GO indicators with a caption override (e.g. "TRIPPED"); *bits / register* tiles split a number into labelled status and fault bits; and *derived* tiles compute a value from other tiles (e.g. `{Volts} * {Amps}`) with no extra traffic.
  - **Control tiles** — drive the device, not just watch it: *button* and *toggle* tiles send on click, numeric *setpoint* tiles carry a `{value}`-templated command with a value field, and *enum* dropdowns send a command per option. Writing tiles can mirror a live readback — follow another tile or query directly — and warn when the device reports a value different from what was commanded.
  - **Master Arm safety gate** — every panel boots disarmed and writing tiles refuse to send until you Arm it; Esc disarms instantly and unbinding or disconnecting force-disarms. A panel can auto-arm when its device connects, or stay in monitor-only **View only** mode.
  - **Trends & charts** — numeric tiles paint an in-tile sparkline; double-click one to open a full chart page with span presets (1 / 5 / 30 / 60 min), follow-live, and a hover crosshair.
  - **Alerts** — a transition into FAIL/ERROR rings a header bell with an unseen badge, flashes the taskbar, and can play a tone; an alerts panel keeps the history. Silenceable per tile or globally.
  - **CSV logging** — optionally record every parsed value (and every control send) to a CSV for unattended runs and audit.
  - **Layout & library** — arrange tiles on a drag-and-drop grid (long-press to edit, drag to move, drag a corner to resize, configurable grid size), copy/paste tiles within or across panels, duplicate whole panels, and add static **text / note** and **divider** tiles to document a panel. Panels live-save (no dirty state), are named and kept in a library, can be starred as favorites, import/export as JSON, and restore with your workspace. Open one from **File ▸ New Control Panel**, the Open submenu, the tab strip, the command palette, **Tools ▸ Control Panels…** (Ctrl+Shift+D), or the drawer's Control Panels page. A panel binds to an open terminal tab and shares its connection (with per-entry overrides to drive multiple devices at once); poll traffic stays out of the terminal transcript, and polling pauses and resumes automatically with the connection.
  - A favorited **Example Control Panel** is seeded on first run, so the feature is one bind away from showing live data.

### Fixed

- **Crash (access violation) on launch or when connecting** — the automatic update check sent its HTTPS request through Qt's network stack, which loads the system OpenSSL; when that differed from the build Qt expected it could fault with a native access violation (often surfacing as crashes during unrelated GUI repaints right after a connect). The update check now runs on a background thread through Python's own `urllib`/SSL stack, so the crash can't occur and the check never blocks the UI.
- Hardened serial-port close against a shutdown hang and added a UI-freeze watchdog.

### Changed

- The settings schema advanced to store Control Panels. Builds without the feature stay forward-compatible with files that don't use it — a saved panel only raises the minimum-compatible version for the specific tile capabilities it actually uses, so older builds still open simpler panels and refuse only the ones they genuinely can't render.

## 0.4.2 - 2026-06-10

### Added

- Add a live theme preview: hovering a theme in the Theme menu applies it across the whole app instantly, so you can compare looks before committing — move away to revert, click to keep.
- Add line-wise cut, copy, and paste in the terminal and command-file editor: with nothing selected, Ctrl+X / Ctrl+C / Ctrl+V act on the whole current line.
- Add inline edit (pencil) and remove (✕) glyphs to every Saved Commands, Files, and Favorites row — alongside the existing star and send/run actions — so an entry can be edited or deleted in one click without opening a menu.
- Add a right-click context menu on the side bar's command and file rows (saved and favorites) offering the same actions: send/run, add to or remove from favorites, edit, and remove.

### Changed

- Reorganize the top menu bar into seven task-focused menus so common actions are easier to find.
- A tab dragged toward the bottom of a pane now splits the workspace downward; dragging toward the side still splits to the right.
- Auto-reconnect now retries on a steady interval and shows a single calm prompt spinner instead of a stream of dots.
- Make disconnected state obvious at a glance: the editor's Run button is disabled when no terminal is connected, and a disconnected port's prompt, tab name, and input are dimmed.
- On a Favorites row, make the scope of each control explicit: ✕ removes the item from Saved entirely (deleting it everywhere) while the star only drops it from Favorites — spelled out in both the glyph tooltips and the context-menu wording.
- Editing or removing a saved command or file now reflects in the Favorites view immediately, and vice versa.
- Adding a quick file now opens the file explorer first; the editor dialog then appears pre-filled with the chosen file's name and path (both still editable).

### Fixed

- The Line spacing preference now applies to the command-file editor, not just the terminal. Previously the editor ignored the setting; it now re-renders at the configured spacing, with the line-number gutter staying aligned.
- Fix undo and redo in the terminal and command-file editor.
- Restore the live font preview in Preferences so font changes are shown before you apply them.
- Fix the Preferences spin-box steppers (the up/down arrows).
- Fix a missing highlight on combo-box dropdown rows so the focused row stands out again.
- Editing a favorited command or file no longer unfavorites it: the edit dialog now preserves favorite membership instead of resetting it.

## 0.4.1 - 2026-06-07

### Fixed

- Fix slow command sending when many commands are saved: pressing Enter no longer rebuilds the entire side bar (saved commands, favorites, and files) on every send — only the history list refreshes, so send latency no longer grows with the number of saved Quick Commands. This restores the responsiveness regressed after 0.3.2.

## 0.4.0 - 2026-06-07

### Added

- Redesign the desktop app into a modern, VS Code-style workbench: a single unified title row (menu, command search, and window controls) on a frameless custom title bar, a design-token system, and theme-aware Tabler icons.
- Add a Favorites model so individual Quick Commands and Quick Files can be starred, surfaced through an activity-bar drawer with four curated views: Favorites, Saved Commands (grouped, text or hex), Files, and History.
- Add a collapsible, resizable, scrollable drawer layout, and seed default example commands and command files on first run.
- Add a tab-name terminal prompt leader and inline autocomplete ghost text in the terminal input.
- Add a shared find/replace overlay, a redesigned completion popup with descriptions, and an inline display of the current line's saved-command description in the command-file editor.
- Add a terminal timestamp toggle and configurable terminal/editor line spacing.

### Changed

- Unify editor and terminal autocomplete so Tab accepts a completion and Enter never does.
- Collapse a crowded tab strip into a `⋯` overflow menu, and collapse command bars to a single primary button when the window is very narrow.
- Focus the active tab's terminal or editor on launch with the caret at the end, and improve line wrapping.
- Rewrite the README around user-facing features, with new screenshots and GIFs captured from the redesigned UI.

### Fixed

- Fix new tabs landing in the wrong pane and the tab context menu targeting the wrong tab when the workspace is split.
- Keep split panes resizable by capping each pane's minimum width, and fix the split-pane status line and active-tab indicator.
- Stop the embedded editor's Run button from clipping in a narrow pane.
- Fix missing favorite indicators in command history.

### Tests

- Add title-bar tests and expand coverage for the tab workspace, terminal view, and workspace status.

## 0.3.2 - 2026-05-26

### Added

- Add terminal command-file controls so each terminal tab can start a file run, pause it, resume it, stop it, and show the current file-run state from the command bar.
- Add a split-workspace drop preview and clearer active-pane/active-tab styling so tab moves and split layouts are easier to follow.
- Add editor-aware quick drawer dispatch so Quick Commands insert into command-file editors while Quick Files open there, and the same drawer still sends or runs items from terminal tabs.

### Changed

- Pause command-file execution when the serial port or LAN endpoint disconnects, then wait for the user to reconnect and click Resume instead of continuing automatically.
- Keep command-file pause/resume separate from RX-output pause/resume, with distinct status text for each workflow.
- Move shared font controls to the status bar and keep connection controls local to the active terminal when a terminal tab owns that state.

### Fixed

- Prevent starting a second command-file run in a terminal that already has one active.
- Keep shared drawer chrome focused on one split pane, reducing duplicated drawer surfaces in split workspaces.
- Improve command-file wait and EXPECT timing so paused runs do not burn timeout while waiting for a connection or user resume.

### Tests

- Added and expanded coverage for command-file pause/resume/stop behavior, disconnect pauses, busy-run rejection, EXPECT timing, split-workspace pane styling/drop preview behavior, and active-tab quick drawer dispatch.

## 0.3.1 - 2026-05-25

### Added

- Add split workspace panes so terminal and command-file tabs can be split right or down, dragged between panes, joined back together, and restored from saved layout state.
- Add the `comport-zone` CLI for version, port discovery, send/hex, listen, command-file run/validate, Quick Commands, Quick Files, settings, history, update checks, and interactive REPL workflows.
- Add stable CLI output modes, shared serial connection flags, JSON support, and public exit codes for automation.
- Add a repo-local `comport-zone-version-update` Codex skill for repeatable release prep, annotated tag creation, and GitHub Release verification.

### Changed

- Introduce a GUI-free core package and CLI dispatcher so headless commands can reuse settings, serial, command-file, quick-action, and version-check behavior without importing PySide.
- Persist split workspace layout metadata in app settings schema v4 while keeping flat terminal/editor tab fallbacks for compatibility.
- Update README release guidance, CLI reference material, and settings-schema documentation for the new release process and CLI surface.

### Tests

- Added and expanded CLI coverage for dispatch, output formatting, serial config resolution, send/listen/run/validate, quick libraries, files, settings, history, updates, hex parsing, and wait/retry behavior.
- Added split-workspace coverage for pane creation, tab movement, empty-pane handling, active-pane selection, join behavior, and restored layout configuration.
- Expanded core, storage, settings, transport, command-runner, and edge-case tests for the GUI-free service layer.

## 0.3.0 - 2026-05-13

### Added

- Add raw TCP LAN transport support with host/port connections, text and hex sends, RX raw-byte preservation, remote-close detection, and auto-reconnect retries.
- Add LAN connection settings for host, port, line ending, timeout, and auto-reconnect.
- Add generic transport profile persistence for default settings and restored terminal tabs.
- Add LAN-aware command-file run targets, command-palette tab entries, workspace status text, and restored-tab auto-connect behavior.

### Changed

- Route terminal sends, Quick Commands, command-file runs, logging, pause buffering, and event handling through a shared serial/LAN transport adapter contract.
- Update Connection Settings to switch between Serial and LAN profiles.
- Update workspace capture, restore, duplication, and app-settings import/export to preserve LAN profiles.
- Move settings schema to v3 while keeping serial-only payloads minimum-compatible with schema v2.
- Refresh architecture, design, and LLM guidance docs for LAN and transport ownership.

### Fixed

- Fix Enter in the integrated terminal prompt so it submits the draft instead of accepting a visible autocomplete suggestion.
- Keep Tab and Shift+Tab as the completion-accept keys while the autocomplete popup is visible.

### Tests

- Added `tests/test_lan_core.py` coverage for LAN connect/send/disconnect, RX events, remote-close handling, and reconnect loops.
- Expanded transport, settings/storage, workspace-state, app-session, dialog, command-palette, and workspace-status coverage for LAN profiles and endpoints.
- Expanded integrated terminal input coverage for Enter versus Tab/Shift+Tab autocomplete behavior.

## 0.2.7 - 2026-05-11

### Added

- Add an Inno Setup installer for Windows releases.
- Add settings `minimum_compatible_schema_version` metadata for upgrade and downgrade safety.
- Add `-SkipInstaller` support for portable-only Windows builds.

### Changed

- Build PyInstaller releases as a one-folder bundle instead of a one-file executable.
- Update the release workflow to upload both the portable zip and installer.
- Install as a per-user Windows app under `%LOCALAPPDATA%\ComPortZone`, with the PyInstaller bundle isolated in the `app` folder and replaced on upgrades/downgrades while preserving local user settings.
- Update README and architecture/design docs for the installer layout and settings compatibility behavior.

### Tests

- Expanded settings tests for compatible future schema reads and incompatible future schema fallback.

## 0.2.6 - 2026-05-11

### Added

- Add `Help > Check for Updates` and a command-palette entry for manual update checks.
- Add `Help > Check for Updates on Launch` with persisted app-settings support.
- Add GitHub latest-release parsing, dotted-version comparison, and update-result helpers.
- Add a version update dialog with release link and startup-check preference control.
- Add a clickable repository link to the About dialog.
- Add README UI preview screenshots and GIFs.
- Add refreshed `AGENTS.md`, Copilot, and Continue guidance files.

### Changed

- Keep automatic startup update checks quiet when no update is available or when the check fails.
- Reserve space for the custom new-tab button and reposition it after tab/title/layout changes.
- Forward right-clicks on the new-tab button to the empty-tab context menu.
- Keep shared footer and connection status tied to the active tab when background tabs update.

### Fixed

- Fix new-tab button overlap with tab close buttons after long titles or tab renames.
- Fix disconnected valid-port tabs showing the wrong status/action in the shared status bar.
- Fix terminal transcript color loss when terminal font/theme formatting is reapplied.

### Tests

- Added `tests/test_version_check.py` coverage for release payload parsing and version comparison.
- Expanded app-session tests for startup/manual update checks, update preferences, About links, active-tab status behavior, and terminal color preservation.
- Expanded menu/dialog/tab-workspace tests for Help menu update actions, version dialog behavior, and new-tab button positioning/context menus.

## 0.2.5 - 2026-05-06

This entry covers changes after the documented 0.2.3 release notes, including the v0.2.4 packaging and polish work.

### Added

- Add integrated terminal input through a `TX> ` prompt inside the terminal surface.
- Add multiline terminal drafts with Shift+Enter.
- Add Windows CI and release workflows for test, package, artifact upload, and tag-matched GitHub Release publishing.
- Add `-NoPipUpgrade` to the setup script for CI environments.

### Changed

- Commit sent TX commands into the terminal transcript and clear the active draft after send.
- Keep committed terminal transcript text protected during normal editing while preserving editable draft behavior.
- Preserve restored terminal transcript, command draft, and send mode with the integrated terminal input.
- Save settings through a temporary file and retain the previous valid settings payload as `settings.json.bak`.
- Make setup/build scripts use local temp/cache and no-build-isolation install paths more consistently.
- Update release documentation and developer docs for the v0.2.5 workflow.

### Fixed

- Fix startup behavior when a restored connected tab points at a COM port that is no longer detected.
- Fix terminal context-menu replacement actions for text-to-hex and hex-to-text selections.
- Fix terminal autocomplete insertion color in the integrated prompt.
- Fix terminal font zoom with Ctrl+mouse wheel from the terminal surface.
- Fix settings load so a corrupt or invalid primary settings file can fall back to the backup payload.
- Fix CI setup by avoiding pip upgrade behavior that is brittle on hosted Windows runners.

### Tests

- Added `tests/test_integrated_terminal_input.py` coverage for protected transcript editing, multiline drafts, autocomplete coloring, and menu replacement behavior.
- Expanded app-session coverage for integrated sends, TX echo handling, restored missing ports, font zoom, and text/hex replacement.
- Expanded storage/settings tests for backup creation, backup fallback, invalid schema fallback, and temporary-file cleanup.

## 0.2.3 - 2026-05-05

### Added

- Add terminal output context-menu actions for Clear Terminal, Line Wrap, and Show Timestamps.

### Changed

- Keep the shared left drawer's collapsed state, selected Quick Commands/Quick Files page, and resized width synchronized across terminal tabs and embedded command-file editor tabs.
- Stream RX hex display chunks as one continuous byte stream with spaces between chunks.

### Fixed

- Fix a hex receive display issue where later byte chunks could appear after an unwanted line break instead of continuing after the first byte.
- Fix sidebar state propagation so drawer page and width changes are no longer isolated to only the tab where the change was made.

### Tests

- Added app-session coverage for terminal context-menu controls and shared drawer page/width behavior.
- Added focused terminal rendering/controller coverage for streamed hex RX chunk spacing.

## 0.2.2 - 2026-05-05

### Added

- Add `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, and `docs/LLM_CHANGE_GUIDE.md` as living references for the redesign, module ownership, and safe change recipes.
- Add setup, launch, and test helper scripts: `setup_dev.bat`, `launch_app.bat`, `run_tests.bat`, and their PowerShell implementations under `scripts/`.
- Add AI agent and repository guidance through `.continue/rules/CONTINUE.md`.

### Changed

- Move `MainWindow` into `ui/main_window.py` and keep `app.py` focused on startup, splash handling, and compatibility re-exports.
- Move `TerminalSessionWidget` into `ui/terminal_tab.py` while preserving existing `ComPort_Zone.app` compatibility imports.
- Extract terminal behavior into `terminal_session_controller.py` and terminal rendering/search into `terminal_view.py`.
- Extract command registry, top menu wiring, tab context menus, command-palette workspace entries, tab workspace behavior, workspace status presentation, workspace state capture/restore, and settings save/apply coordination into focused modules.
- Extract quick-action workflows, app-settings transfer workflows, dialog classes, command-file target coordination, and command-file parameter dialogs into dedicated modules.
- Move editor font controls beside the editor Send controls.
- Make command editor line-number gutter, current-line highlight, and search highlights use the active theme palette.
- Improve auto-reconnect feedback so repeated reconnect attempts render as compact progress instead of noisy status lines.
- Change command-file execution to report whether a run started so the UI can shift focus to the target terminal only after a successful start.
- Update commit-message generation and LLM/developer instructions.

### Fixed

- Fix the terminal search close button so it uses the icon-only close button instead of showing an extra `X` label.

### Tests

- Added focused coverage for extracted controllers, dialogs, menu builders, context menus, command registry, tab workspace, workspace state/settings, terminal controller/view behavior, and command-file target coordination.

## 0.2.1 - 2026-04-29

### Added

- Add shared quick-action sidebar infrastructure for terminal tabs and command-file editor tabs.
- Add transport abstraction foundations with a serial transport adapter, generic transport profile data, endpoint metadata, and transport events.
- Add focused command-editor modules for validation/completion sources, file I/O, run targets, search/replace state, and syntax highlighting.

### Changed

- Align the command-file editor quick sidebar with the terminal quick sidebar while keeping mode-specific actions: Send/Run in terminal tabs and Insert/Open in editor tabs.
- Make command-file quick command suggestions follow the active quick-command group visibility/filter state.
- Move quick command/file state operations into the quick-action library so CSV import/export, filtering, sorting, duplicate detection, and reorder behavior have one owner.
- Split app styling/icon helpers and settings import/export coordination into smaller reusable services.
- Replace the flat app-settings JSON with `schema_version` 2 nested sections for transport, app preferences, history, action libraries, and restored workspace state.
- Make `SettingsService` the settings payload owner; raw storage now only reads and writes JSON payloads.
- Hide replace-only controls in editor Find mode; show them only in Replace mode.
- Remove the explicit editor Validate toolbar button because unknown-command warnings and syntax validation run in the background.

### Fixed

- Normalize quick-action row sizing between terminal and editor sidebars.

### Tests

- Expanded the unit test suite to cover quick-action library behavior, the shared sidebar, command editor services, transport contracts, settings transfer behavior, command search/replace, and syntax highlighting.

## 0.2.0 - 2026-04-28

### Added

- Add built-in command file editor
- Support of `EXPECT` assertions to batch command files
- Refresh serial settings ports while dialog is open

### Fixed

- Fix command file `WAIT` timing on Windows

## 0.1.0 - 2026-04-26

First public release candidate for ComPort Zone.

Source range used for this changelog: commits after `f0a9a77` (`add version and set to v0.0.1`) through `780beff` (`update resources`).

### Added

- Command-file parameters with `{{PARAM}}` and `{{PARAM=default}}`.
- Pre-run parameter sheet for command files, including default override and runtime prompting for values left empty.
- Command-file support for C-style single-line comments using `//`.
- Quick files: saved command-file paths in their own left-sidebar entry.
- Quick-file CSV import/export, append/replace import behavior, duplicate skipping, sorting, double-click run, send button run, and Explorer reveal.
- Quick-command CSV import/export with append/replace import behavior and duplicate skipping.
- Quick-command descriptions, group sorting, group show/hide controls, and compact command rows.
- Command palette on `Ctrl+Shift+P` for connect, settings, scripts, clear, search, save command, and tab switching.
- RX display mode control for text and hex/raw-byte receive views.
- Terminal selection conversion between text and hex.
- GUI terminal font settings, including font family and font size controls.
- Separate settings import/export JSON bundles replacing the earlier in-app profile-list concept.
- Version management script with SemVer support.
- Windows `.exe` build script and PyInstaller entry point.
- Windows executable version metadata and versioned executable naming.
- App icon assets for the application window and Windows taskbar.
- Default quick commands: `*IDN?`, `SYST:ERR:ALL?`, and `SYST:FIRM?`.
- Example resource files for command files, parameterized command files, feedback calibration, and quick-command CSV import.

### Changed

- Improved connection/disconnection UX with clearer bottom status controls and auto-reconnect feedback.
- Updated tab naming and visual connection-state indication.
- Polished tab context menu and close-tab button behavior.
- Reworked menus and shortcuts for a cleaner application structure.
- Replaced minimal icons with a richer Tabler Icons based visual set.
- Improved settings philosophy: app setup is now managed through import/exportable settings bundles instead of named profiles.
- Updated README documentation for command files, command parameters, quick commands CSV, quick files CSV, settings bundles, shortcuts, versioning, and build flow.
- Added `.egg-info` and build artifact exclusions to `.gitignore`.

### Fixed

- Fixed a receive-rendering bug where the first received character could appear on a separate line.
- Fixed command-file `WAIT` timing so short waits are not forced into a longer minimum delay.
- Fixed and hardened the one-click `.exe` build flow.
- Improved restored-tab and duplicate-tab behavior.

### Tests

- Added coverage for app sessions, settings import/export, quick commands, quick files, command palette entries, serial core receive behavior, batch parsing, command-file timing, and command-file parameters.

## 0.0.1 - 2026-04-24

Initial development baseline with the ComPort Zone name, app icon, version file, and early terminal-first serial application features.
