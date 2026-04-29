# Changelog

All notable changes to ComPort Zone are documented here.

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
