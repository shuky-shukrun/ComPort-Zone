# Changelog

All notable changes to ComPort Zone are documented here.

## Unreleased

### Added

- **Dashboard View**: a new workspace tab type that polls commands in the background and shows the replies as live tiles.
  - Each entry has its own interval, timeout, parse rule (first line or regex capture, text or numeric), and ordered color rules that drive the tile state (OK / WARN / FAIL, plus stale and error); LED indicator tiles render GO/NO-GO states with a label override (e.g. "TRIPPED"). The entry editor includes a live tester: paste sample device output and see the parsed value and resulting state.
  - A dashboard binds to an open terminal tab and shares its connection. Poll traffic stays out of the terminal transcript so the terminal remains usable for manual commands (it still reaches the session log and command-file EXPECT matching; tile tooltips show each entry's raw reply window). Polling pauses automatically while the session is disconnected or a command file is running and resumes by itself; a header chip shows the binding state, and a pause/play control lets you pause manually.
  - Tiles arrange on a drag-and-drop grid with 1×1–2×2 sizes in an explicit edit-layout mode. Edits auto-save — a live **Saved HH:MM:SS** indicator in the header makes that visible — so there is no unsaved state to lose.
  - Dashboards are named, saved to the settings library, star-able as favorites, and import/export as JSON. Open them from File > New Dashboard, the Open Dashboard submenu, the tab strip, the command palette, Tools > Dashboards… (Ctrl+Shift+D), or the left drawer's new **Dashboards** rail page, which lists the library with the same inline row actions as commands and files (open, star, rename, delete) plus New / Import / Export / Manage in the header. A third **Favorite Dashboards** panel joins the Favorites page.
  - Open dashboard tabs restore with the workspace and rebind to their terminal by endpoint. Feature requirements: `docs/dashboard-view-requirements.md`.

### Changed

- Settings schema bumped to v5 for the dashboard library. Files without dashboards remain readable by older builds; LAN-only settings now declare the LAN feature floor (v4) instead of pinning to the newest schema, so future schema bumps no longer lock LAN users out of older builds.

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
