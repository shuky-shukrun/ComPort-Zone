# Changelog

All notable changes to ComPort Zone are documented here.

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
