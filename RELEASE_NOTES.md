# ComPort Zone v0.3.0 Release Notes

Release date: 2026-05-13

ComPort Zone v0.3.0 expands the terminal beyond local COM ports with raw TCP LAN connections. Serial and LAN sessions now share the same terminal workspace, command-file targets, status/footer behavior, settings capture/restore, and transport adapter layer. This release also fixes terminal autocomplete handling so Enter sends the draft while Tab accepts a highlighted completion.

## Highlights

- Terminal tabs can now connect to raw TCP LAN endpoints by host and port.
- Connection Settings now switches between Serial and LAN profiles, including LAN host, port, line ending, timeout, and auto-reconnect fields.
- Terminal sends, Quick Commands, command-file runs, logging, pause buffering, receive display modes, and auto-reconnect now run through a shared transport adapter contract.
- App settings and restored workspace tabs now persist generic transport profiles, with schema v3 required when LAN data is present.
- Restored LAN tabs can reconnect to saved endpoints on launch, and duplicated tabs/command-file run targets preserve LAN endpoint details.
- Pressing Enter with the autocomplete popup visible now sends the current draft; Tab and Shift+Tab still accept the highlighted completion.

## What's New

### LAN Connections

- Added a raw TCP LAN client with host/port connect, text and hex send paths, RX raw-byte preservation, remote-close detection, and reconnect status events.
- Added LAN connection profiles with host, port, line ending, timeout, and auto-reconnect settings.
- Connection Settings now includes a Serial/LAN selector and a dedicated LAN settings page.
- LAN tabs use endpoint-aware titles, status text, tooltips, and Set Endpoint/Connect actions.
- LAN endpoints are entered manually; Refresh Ports now reports that LAN endpoint discovery is not available.

### Shared Transport Workflow

- Serial and LAN adapters now expose the same connect, disconnect, send, event, and subscription contract.
- The terminal controller, batch runner, quick command execution, event draining, logging, and pause buffering now use the shared transport adapter.
- Command-file target menus can target connected LAN tabs, and target labels no longer assume COM ports.
- Command palette tab entries and workspace status text now use connection endpoints instead of serial-only port text.

### Settings And Restore

- Settings schema now supports generic `transport.kind` and `transport.profile` payloads for both defaults and restored terminal tabs.
- Serial-only payloads remain minimum-compatible with schema v2; LAN payloads mark schema v3 as the minimum compatible version.
- Workspace capture, restore, app-settings import/export, and duplicated terminal tabs preserve LAN profiles.
- Restored connected LAN tabs auto-connect to saved hosts and ports because there is no LAN endpoint discovery step.

### Terminal Input

- Enter no longer accepts a visible autocomplete suggestion in the integrated terminal prompt; it hides the popup and submits the draft.
- Tab and Shift+Tab continue to accept the visible completion without sending the command.

## Validation

The release added or expanded regression coverage for:

- LAN connect/send/disconnect, RX raw-byte preservation, remote-close handling, failed-connect reconnect loops, and reconnect cancellation.
- Serial and LAN transport adapter contracts, including profile kind validation and event subscriptions.
- LAN settings serialization, schema v3 compatibility rules, restored LAN terminal tabs, workspace capture/restore, and app-settings import/export.
- LAN connection dialog fields, restored LAN auto-connect, duplicated LAN tabs, command-file LAN targets, command palette endpoint text, and workspace status labels.
- Integrated terminal autocomplete behavior for Enter versus Tab/Shift+Tab.

Run the full suite with:

```powershell
.\run_tests.bat
```

---

# ComPort Zone v0.2.7 Release Notes

Release date: 2026-05-11

ComPort Zone v0.2.7 reorganizes the Windows release package around a faster one-folder PyInstaller bundle and an Inno Setup installer. It also adds settings compatibility metadata so local settings can survive compatible upgrades and downgrades more predictably.

## Highlights

- Windows releases now use a PyInstaller one-folder bundle plus an installer for faster startup and cleaner upgrades/downgrades.
- The release workflow now produces both a portable zip and an Inno Setup installer.
- Installs are per-user under `%LOCALAPPDATA%\ComPortZone`, with the frozen app isolated in the `app` folder.
- Upgrades and downgrades replace the installed app bundle while preserving `settings.json`, `settings.json.bak`, the uninstaller, and user data.
- Settings now declare minimum-compatible schema metadata so compatible future payloads can load safely and incompatible ones fall back to backups/defaults.

## What's New

### Windows Packaging

- PyInstaller now builds a one-folder app bundle instead of a one-file executable.
- The build script can create a portable zip and an Inno Setup installer; use `-SkipInstaller` to build only the portable zip.
- The installer creates Start Menu and desktop shortcuts for the per-user install.
- The installed app internals live under `%LOCALAPPDATA%\ComPortZone\app`.
- The portable publish folder keeps the PyInstaller bundle under `app`.

### Settings Compatibility

- App settings JSON now includes `minimum_compatible_schema_version`.
- Compatible upgrades and downgrades keep local settings, Quick Commands, and Quick Files because they live outside the installed app bundle.
- Older builds treat payloads with a newer minimum-compatible schema as unsupported and try `settings.json.bak` before falling back to defaults.

### Documentation And Release Workflow

- README build/release instructions now describe the one-folder zip, installer output, install layout, and `-SkipInstaller`.
- Architecture and design docs now describe minimum-compatible schema checks.
- The GitHub release workflow uploads both release artifacts.

## Validation

The release added or expanded coverage for:

- Settings compatibility metadata, compatible future-schema loading, and incompatible future-schema backup fallback.
- Release packaging script and workflow changes for portable zip and installer output.
- Documentation updates for the installer layout, portable bundle layout, and settings compatibility behavior.

Run the full suite with:

```powershell
.\run_tests.bat
```

---

# ComPort Zone v0.2.6 Release Notes

Release date: 2026-05-11

ComPort Zone v0.2.6 adds built-in update discovery and tightens several workspace polish issues from the v0.2.5 terminal-input release. It helps users find newer GitHub releases from inside the app while improving tab layout, active-tab status behavior, and terminal color stability.

## Highlights

- New Help menu actions can check GitHub for the latest ComPort Zone release.
- Update checks can run automatically on launch and are persisted in app settings.
- The About dialog now includes a clickable project repository link.
- The new-tab button no longer overlaps tab close buttons after long titles or renames.
- Background tab connection events no longer replace the active tab's shared status bar.
- Terminal transcript colors are preserved when terminal font/theme formatting is reapplied.

## What's New

### Update Checks

- Added `Help > Check for Updates`.
- Added `Help > Check for Updates on Launch`, a checkable setting that persists with app settings.
- Added a command-palette entry for checking updates.
- Added a version-check service that reads GitHub's latest release metadata, normalizes `v`-prefixed tags, and compares dotted versions.
- Added an update dialog that shows whether a newer release is available, links to the release page, and lets users keep or change the startup-check preference.
- Automatic startup checks are quiet when no update is available or when the check fails; manual checks show a status message or warning.

### Help And Documentation

- The About dialog now shows the current version and a clickable repository URL.
- README documentation now includes UI preview screenshots and GIFs for the terminal workspace, command editor, quick drawer, and workspace tabs.
- Developer/assistant guidance was refreshed through `AGENTS.md`, Copilot instructions, and the Continue rules.

### Workspace Polish

- The custom new-tab button now reserves tab-bar space and repositions after tab insertion, removal, resize, icon changes, and title changes.
- Right-clicking the new-tab button opens the empty-tab context menu with New Tab and New Command File actions.
- Disconnected tabs now show the correct Closed/Connect status when the selected port is valid.
- Background restored tabs and background serial events no longer overwrite the active tab's footer or connection status controls.
- Terminal transcript colors for TX, RX, and errors survive terminal font setting changes and formatting refreshes.

## Validation

The release added or expanded regression coverage for:

- Version comparison, GitHub release payload parsing, update-result construction, update dialogs, Help menu entries, command-palette entries, startup checks, manual checks, and persisted update preferences.
- About dialog repository links.
- New-tab button positioning, context menu forwarding, and close-button spacing after long tab titles.
- Active-tab-only connection/status behavior for restored and background tabs.
- Terminal transcript color preservation after terminal font settings are reapplied.

Run the full suite with:

```powershell
.\run_tests.bat
```

---

# ComPort Zone v0.2.5 Release Notes

Release date: 2026-05-06

ComPort Zone v0.2.5 rolls up the terminal polish, settings hardening, and release-infrastructure work completed since the v0.2.3 release notes. The main user-facing change is a more terminal-native input experience, with follow-up fixes around restore, text/hex conversion, and packaging reliability.

## Highlights

- Terminal input now lives directly in the terminal surface behind a `TX> ` prompt, while previously committed output stays protected from normal typing.
- Restored connected tabs skip auto-connect cleanly when their saved COM port is not currently detected.
- Settings saves are more resilient: writes use a temporary file and the previous valid settings payload is kept as `settings.json.bak`.
- Terminal selection conversion and replacement actions now work correctly with the integrated terminal input.
- GitHub Actions now runs Windows CI and can build tagged Windows release artifacts.

## What's New

### Integrated Terminal Input

- Replaced the separate command-entry line with an integrated terminal draft prompt.
- Pressing Enter sends the current draft; Shift+Enter inserts a new line into the draft.
- Committed terminal transcript text is locked during normal editing, while the active draft remains editable.
- Sent commands are committed back into the transcript as TX output and the active draft clears after send.
- Autocomplete, command history, paste, copy, cut, Home, and selection behavior now operate inside the integrated terminal prompt.
- Terminal font zoom through Ctrl+mouse wheel now works from the terminal surface.

### Startup And Settings Resilience

- Restored tabs preserve terminal transcript text, command draft, and send mode with the integrated input model.
- Auto-connect for restored tabs now checks whether the saved port is present before connecting.
- Missing restored ports are reported in the terminal/status area instead of leaving the UI stuck during startup.
- Local settings saves now write atomically through a temporary file.
- The last valid settings file is retained as a `.bak` backup, and startup can fall back to it if the primary file is corrupt or has an invalid schema.

### Terminal Selection Tools

- Show Selection as Hex and Show Hex Selection as Text continue to work from the terminal context menu.
- Replace Selection with Hex and Replace Hex Selection with Text now update committed transcript selections without corrupting the active prompt or draft.
- Autocomplete insertions now keep the expected terminal draft coloring.

### Release Infrastructure

- Added a Windows CI workflow that installs the app, runs the unit suite, and checks installed dependencies.
- Added a release workflow that validates version tags, runs tests, builds the PyInstaller Windows zip, uploads the artifact, and publishes a GitHub Release for matching tags.
- Setup and build scripts use local temp/cache folders more consistently and avoid fragile pip/build-isolation paths in CI and local Windows builds.
- Added a `-NoPipUpgrade` setup option for CI environments that should use the provisioned pip version.

## Validation

The release added or expanded regression coverage for:

- Integrated terminal input editing, protected transcript behavior, multiline drafts, autocomplete coloring, and menu-driven text/hex replacement.
- App-session behavior for integrated sends, TX echo handling, font zoom, restored tabs, missing restored ports, and terminal selection conversion.
- Settings backup/fallback behavior and atomic save cleanup.
- CI/release workflow script paths and setup/build command options.

Run the full suite with:

```powershell
.\run_tests.bat
```

---

# ComPort Zone v0.2.3 Release Notes

Release date: 2026-05-05

ComPort Zone v0.2.3 is a focused polish and bug-fix release on top of the v0.2.2 modularization work.

## Highlights

- Terminal output right-click menus now include Clear Terminal, Line Wrap, and Show Timestamps.
- The left drawer behaves consistently across terminal tabs and embedded command-file editor tabs.
- RX hex display now streams byte chunks as one readable sequence instead of inserting an unwanted break after the first chunk.

## What's New

### Terminal Context Menu

- Added Clear Terminal to the terminal output context menu.
- Added checkable Line Wrap and Show Timestamps actions to the same context menu.
- Context-menu toggles stay synchronized with the matching main menu actions and persisted app settings.

### Shared Drawer State

- The drawer's collapsed/expanded state, selected Quick Commands or Quick Files page, and resized width are shared across terminal tabs and command-file editor tabs.
- Drawer state is persisted in app settings, including the selected drawer page.
- Command-file editor tabs use the same drawer sizing rules as terminal tabs when embedded in the workspace.

### Hex Receive Rendering

- RX hex output now keeps streamed chunks on the same line with a space between chunks.
- Text receive rendering and progress-dot rendering keep their existing streaming behavior.

## Validation

The release added regression coverage for:

- Terminal context-menu controls and setting synchronization.
- Shared drawer page and width propagation across tabs.
- Streamed RX hex byte spacing in the terminal view and controller.

Run the full suite with:

```powershell
.\run_tests.bat
```

---

# ComPort Zone v0.2.2 Release Notes

Release date: 2026-05-05

ComPort Zone v0.2.2 is a modularization and developer-workflow release. It keeps the existing user workflows intact while moving more of the application out of large UI classes and into focused modules with tests.

## Highlights

- `app.py` is now a thin startup module; `MainWindow` lives in `ui/main_window.py`.
- Terminal tab UI, terminal behavior, and terminal rendering/search are split into separate modules.
- Menus, tab context menus, command-palette workspace entries, workspace state/settings coordination, dialogs, and quick-action workflows now have focused owners.
- Developer documentation now describes the architecture, design, and small-change recipes.
- Setup, launch, and test scripts make fresh clones and day-to-day verification simpler.

## Architecture And Developer Workflow

- Added `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, and `docs/LLM_CHANGE_GUIDE.md`.
- Added `.continue/rules/CONTINUE.md` with repository guidance for AI-assisted changes.
- Added `setup_dev.bat`, `launch_app.bat`, `run_tests.bat`, and PowerShell scripts under `scripts/`.
- Removed committed `.egg-info` metadata from source control.

## Modularization

- Moved `MainWindow` to `ui/main_window.py` while preserving compatibility re-exports from `ComPort_Zone.app`.
- Moved `TerminalSessionWidget` to `ui/terminal_tab.py`.
- Added `terminal_session_controller.py` for terminal send/run/event decisions.
- Added `terminal_view.py` for QTextEdit rendering and terminal search highlighting.
- Added or expanded focused owners for command registry, menu construction, tab context menus, tab workspace behavior, workspace status presentation, workspace state, workspace settings, app settings, quick-action workflows, dialogs, and command-file run-target coordination.

## User-Facing Polish

- Editor font controls now sit beside the editor Send controls.
- Command editor gutter, current-line, and search highlight colors now follow the active theme.
- Auto-reconnect feedback is less noisy and renders repeated attempts as compact progress.
- Running a command file reports success/failure to the UI so focus only shifts to a terminal after a run actually starts.
- The terminal search close button is icon-only and no longer shows an extra `X` label.

## Validation

The release added focused tests for extracted modules and kept app-session regression coverage around the main workflows.

Run the full suite with:

```powershell
.\run_tests.bat
```

---

# ComPort Zone v0.2.1 Release Notes

Release date: 2026-04-29

ComPort Zone v0.2.1 is a behavior-compatible modular redesign release. It keeps the PySide6 Windows-first serial workflow intact while moving important pieces out of the large UI classes and into focused, reusable modules.

## Highlights

- Terminal tabs and command-file editor tabs now share the same quick-action sidebar component.
- The editor sidebar matches the terminal sidebar layout: users view either quick commands or quick files, with the same filter, sort, group, and action controls.
- Mode-specific sidebar actions remain clear: terminal quick commands send to serial, editor quick commands insert into the file, terminal quick files run, and editor quick files open.
- Command-file quick command suggestions now come from the active quick-command filter/group state.
- Command editor behavior is split into focused modules for validation/completion, file I/O, run target selection, search/replace, and syntax highlighting.
- A transport abstraction foundation is now in place while serial remains the only concrete transport.

## What's New

### Shared Quick Actions

- Added a shared quick-actions sidebar used by both terminal and command-file editor tabs.
- Preserved quick command and quick file CSV formats.
- Preserved append/replace import behavior and duplicate handling.
- Preserved sorting, filtering, grouping, manual reorder, and drag reorder behavior.
- Normalized quick-action row sizing so terminal and editor sidebars feel consistent.

### Command-File Editor

- Moved command-file validation, autocomplete source collection, and known-command handling into `command_editor_core.py`.
- Moved command-file load/save/default-path behavior into `command_file_service.py`.
- Moved command-file execution target modeling into `command_run_targets.py`.
- Moved editor find/replace behavior into `command_search.py`.
- Moved syntax highlighting into `command_editor_highlighting.py`.
- Removed the explicit Validate toolbar button; validation and unknown-command warnings now run in the background when enabled.
- Cleaned up Find mode so replace-only controls are hidden unless Replace mode is active.

### Architecture

- Added `transports.py` with transport protocol types, endpoint/profile/event data, and a `SerialTransportAdapter` around the current serial client.
- Replaced the flat app-settings JSON with `schema_version` 2 nested sections for transport, app preferences, history, action libraries, and restored workspace state.
- Moved settings payload validation and conversion into `SettingsService`; raw storage now only reads and writes JSON payloads.
- Continued extracting UI helpers and settings coordination out of the main application module.

## Compatibility

- Older flat app-settings JSON files are not migrated. If `%LOCALAPPDATA%\ComPortZone\settings.json` uses the old schema, the app starts with defaults and writes the new schema on save.
- Existing quick-command CSV files remain compatible.
- Existing quick-file CSV files remain compatible.
- Existing command-file syntax remains compatible, including `SEND`, `WAIT`, `HEX`, `EXPECT`, comments, and runtime parameters.
- PySide6 and the current Windows packaging flow remain unchanged.

## Validation

- The unit test suite was expanded during the redesign work and passes with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -q
```

Current coverage includes quick actions, shared sidebar behavior, command editor services, command search/replace, syntax highlighting, transport contracts, settings transfer behavior, batch parsing, and serial core behavior.

## Notes For This Release

- This release is intentionally not a visual redesign. The main user-visible change is sidebar alignment between terminal and editor tabs.
- Serial communication remains the only implemented transport. The new transport layer is preparation for future communication types.
- The largest remaining design work is to keep slimming the main window/session code into focused controllers and tab modules.

---

# ComPort Zone v0.1.0 Release Notes

Release date: 2026-04-26

ComPort Zone v0.1.0 is the first public release candidate of the Windows-first serial terminal for device bring-up, debugging, and repeated engineering command workflows.

## Highlights

- Terminal-first Windows desktop UI inspired by Windows Terminal and VS Code dark styling.
- Multi-tab serial sessions, each with its own serial settings, terminal output, command input, logging state, and command-file execution.
- Quick-send commands and quick command-file shortcuts in a foldable left sidebar.
- Text and hex/raw-byte send and receive workflows.
- Command-file automation with `SEND`, `WAIT`, `HEX`, bare commands, `//` comments, and runtime parameters.
- Import/export support for settings, quick commands, and quick files.
- One-click Windows `.exe` build flow with app icon and version metadata.

## Feature Overview

### Serial Terminal

- Configure COM port, baud rate, data bits, parity, stop bits, flow control, DTR, RTS, line ending, timeout, and auto-reconnect.
- Connect, disconnect, refresh ports, and receive clear connection-state feedback.
- Auto-open serial settings for new blank tabs so selecting a port is the first action.
- Bottom status area shows connection, port, baud, line ending, and logging state.
- Double-click connection info to open serial settings.

### Tabs And Sessions

- Create, close, rename, duplicate, and switch terminal tabs.
- Restore tabs between launches.
- Tab titles can follow the selected COM port, and tab styling indicates connection state.
- Right-click tab context menu for common tab actions.

### Terminal Output

- Large terminal-first output surface with compact chrome.
- RX, TX, status, error, and log coloring.
- Optional timestamps.
- Search in the active terminal tab with match highlighting.
- Copy, select all, clear terminal, pause/resume output, and line wrap controls.
- Text receive and hex/raw-byte receive display modes.
- Select terminal text and convert between text and hex.

### Command Input

- Send normal text commands.
- Send hex/raw bytes.
- Select line ending: none, CR, LF, or CRLF.
- Use Up/Down command history.
- Use `Ctrl+Space` autocomplete from command history and quick commands.
- Paste and send repeated engineering commands quickly from the command bar.

### Quick Commands

- Save, edit, delete, send, reorder, and group quick commands.
- Add optional descriptions shown on hover.
- Compact quick-command rows for dense workflows.
- Sort by title or group.
- Show/hide commands by group.
- Right-click context menu for quick-command management.
- Import/export quick commands using CSV.
- During import, append to existing commands or replace them, with duplicate skipping.

### Quick Files

- Save command-file paths in a dedicated left-sidebar entry.
- Run saved command files by double-clicking or pressing send.
- Sort quick files.
- Right-click a quick file to run, edit, delete, import/export, or reveal in Windows Explorer.
- Import/export quick files using CSV.
- During import, append to existing files or replace them, with duplicate skipping.

### Command Files

Command files can be run from the app menu or saved as quick files.

Supported syntax:

```text
# Comment
// C-style comment
SEND version
WAIT 1000
HEX 55 AA 01 0D
reset
VOLT {{VOLT_VALUE}}
CURR {{CURR_VALUE=1.00}}
```

- `SEND <text>` sends text with the active line ending.
- `WAIT <milliseconds>` pauses before the next step.
- `HEX <bytes>` sends raw bytes without appending a line ending.
- Bare lines are treated as text commands.
- `//` comments ignore everything after `//` until the next line.
- `{{PARAM}}` opens as an empty value in the pre-run parameter window.
- `{{PARAM=default}}` opens prefilled and can be overridden.
- Empty parameter values are requested later when execution reaches the line.
- Reused parameter names keep the first value entered during that run.

### Settings And Persistence

- Autosaves app settings under `%LOCALAPPDATA%\ComPortZone\settings.json`.
- Export/import the complete app setup as a JSON settings bundle.
- Settings bundles include serial defaults, restored tabs, quick commands, quick files, command history, theme, terminal font, line wrap, scrollback, RX display mode, timestamps, drawer state, last paths, and window size.
- This replaces the earlier named-profile management concept.

### Appearance

- App name: ComPort Zone.
- Custom app icon in the window and Windows taskbar.
- VS Code style dark theme by default.
- Tabler Icons based icon set.
- Foldable and resizable left drawer.
- Terminal font family and size settings.
- Bottom-right app version display.

### Keyboard Shortcuts

- `Ctrl+T`: New tab.
- `Ctrl+Shift+T`: Duplicate tab.
- `Ctrl+W`: Close tab.
- `Ctrl+Shift+P`: Command palette.
- `Ctrl+B`: Toggle left drawer.
- `Ctrl+Enter`: Connect or disconnect.
- `Ctrl+F`: Search active terminal.
- `Ctrl+K`: Clear terminal.
- `Ctrl+Space`: Autocomplete command input.
- `Up` / `Down`: Command history.
- `Ctrl+=` / `Ctrl+-`: Increase or decrease terminal font size.

### Packaging

- Build script: `build_exe.bat`.
- Version script: `update_version.bat`.
- PyInstaller one-file Windows executable.
- Versioned output name: `ComPort Zone v0.1.0.exe`.
- Publish folder and zip package are generated under `release\`.

## Notes For This Release

- This is a Windows-first release focused on serial communication with physical devices.
- No formal `0.0.2` release package exists; it was a development-only version.
- Because the app is still early, settings formats may continue to evolve before a stable `1.0.0`.
