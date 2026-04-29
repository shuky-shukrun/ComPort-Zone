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
- Added generic transport fields to settings while preserving current serial settings compatibility.
- Continued extracting UI helpers and settings coordination out of the main application module.

## Compatibility

- Existing settings remain compatible, including `%LOCALAPPDATA%\ComPortZone\settings.json`.
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
