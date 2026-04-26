# ComPort Zone

ComPort Zone is a Windows-first COM-port terminal for device bring-up, debugging, and repeated engineering command workflows.

The current UI is terminal-first: a menu bar, Windows Terminal-style tabs, one large terminal surface, a compact command bar, and a foldable left drawer for quick-send commands and shortcuts.

## Current Features

- Terminal-first layout with minimal chrome and a VS Code dark default theme
- Bundled Tabler Icons subset for richer, modern, MIT-licensed UI icons
- Tabs for independent serial sessions
- Foldable and resizable left drawer, collapsed by default
- Quick-send commands with add, edit, delete, reorder, groups, text mode, hex mode, optional descriptions, optional line-ending override, and CSV import/export
- Separate quick-file drawer entry for saved command-file paths, with sorting, double-click/send execution, Explorer reveal, and CSV import/export
- Serial settings with COM port, baud rate, data bits, parity, stop bits, flow control, DTR, RTS, auto-reconnect, and line ending
- Full settings import/export as JSON bundles instead of an internal profile list
- Settings bundles include serial defaults, theme, terminal font, history, drawer state, quick commands, log/script paths, restored tabs, and workflow preferences
- Serial Settings opens automatically for the active tab on launch and for each new blank tab
- Connect, disconnect, refresh ports, and reconnect feedback
- Text sending and hex/raw-byte sending
- Up/Down command history navigation
- Autocomplete from command history and saved quick commands with `Ctrl+Space`
- Search within the active terminal tab with highlighted matches
- RX, TX, status, and error coloring
- Optional terminal timestamps
- Clear, copy, select all, pause/resume output, terminal font settings, and line wrap controls
- Per-tab command file execution
- Per-tab logging to text files
- Persisted settings for theme, drawer state, serial defaults, quick commands, font size, history, scrollback, and restored tabs

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Run

```powershell
python -m ComPort_Zone
```

After installation, the console script can also launch the app:

```powershell
comport-zone
```

## Build Windows EXE

Update the app version before a release:

```powershell
.\update_version.bat -Version 1.2.3
.\update_version.bat -Bump patch
.\update_version.bat -Bump minor
.\update_version.bat -Bump major
```

Double-click `build_exe.bat` from the project folder.

The script creates or reuses `.venv`, installs the app with build dependencies, runs PyInstaller, embeds Windows file-version properties, and writes publishable output to:

```text
release\ComPort_Zone-X.Y.Z-win64\
release\ComPort_Zone-X.Y.Z-win64.zip
```

The generated executable is also available at:

```text
dist\ComPort Zone vX.Y.Z.exe
```

After the first setup, later builds skip dependency installation when the `.venv` build environment is already ready. To force a dependency refresh, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_exe.ps1 -ForceInstall
```

## Batch Script Format

Plain text files can be run from `File > Run Command File` or saved in the left drawer as quick files. Every non-empty bare line is sent as a command with the active session line-ending setting.

The parser also supports a small batch DSL:

```text
# Comment
// C-style comment
SEND version
WAIT 1000 // Pause one second
HEX 55 AA 01 0D // Send raw bytes
reset // Bare command
```

- `SEND <text>` sends text with the active line ending.
- `WAIT <milliseconds>` pauses before the next step.
- `HEX <bytes>` sends raw bytes without appending a line ending.
- Bare lines are treated like `SEND`.
- `//` starts a single-line comment. Everything after it is ignored until the next line.

### Command File Parameters

Command files can include simple runtime parameters:

```text
VOLT {{VOLT_VALUE}}
CURR {{CURR_VALUE=1.00}}
WAIT {{DELAY_MS=10}}
HEX {{WAKE_BYTES=55 AA 01 0D}}
```

- `{{PARAM}}` appears in the pre-run parameter window with an empty value.
- `{{PARAM=default}}` appears in the pre-run parameter window with `default` already filled in.
- Parameter names may use letters, numbers, and underscores, and must start with a letter or underscore.
- Before a parameterized file starts, ComPort Zone lets you set or override parameter values.
- If a value is left empty, or a prefilled default is deleted, ComPort Zone asks for that value when execution reaches the line.
- Values are remembered for the current run. If `{{VOLT_VALUE}}` appears again later, the first entered value is reused automatically.
- Parameters work in bare commands, `SEND`, `WAIT`, and `HEX` lines.

## Quick Commands CSV Format

Quick commands can be exported from `Tools > Export Quick Commands to CSV` or imported from `Tools > Import Quick Commands from CSV`.

During import, choose whether to append incoming commands to the current list or replace the current list.
The import dialog can also skip duplicates, where duplicates are matched by group, title, command text, and send mode.
Export writes UTF-8 CSV with these columns:

| Column                 | Required | Description                                                                                                    |
| ---------------------- | -------- | -------------------------------------------------------------------------------------------------------------- |
| `label`                | No       | Display name shown in Quick Send. If empty, the command text is used.                                          |
| `command`              | Yes      | Text command or hex byte sequence to send.                                                                     |
| `description`          | No       | Optional hover text for the saved command.                                                                     |
| `send_mode`            | No       | `Text` or `Hex Bytes`. Invalid or empty values default to `Text`.                                              |
| `group`                | No       | Group name used for sorting and show/hide filtering. Empty values become `General`.                            |
| `line_ending_override` | No       | Optional text-mode line ending override: `None`, `CR`, `LF`, or `CRLF`. Empty uses the active session setting. |

Example:

```csv
label,command,description,send_mode,group,line_ending_override
Read Version,version,Read firmware version,Text,General,CRLF
Boot Wake,55 AA 00,Send bootloader wake bytes,Hex Bytes,Boot,
Read ID,id?,Read factory identity string,Text,Factory,LF
```

## Quick Files CSV Format

Quick files are saved command-file paths shown in the left drawer. They can be exported from `Tools > Export Quick Files to CSV` or imported from `Tools > Import Quick Files from CSV`.

During import, choose whether to append incoming files to the current list or replace the current list.
The import dialog can also skip duplicates, where duplicates are matched by file path.
Export writes UTF-8 CSV with these columns:

| Column  | Required | Description                                                                           |
| ------- | -------- | ------------------------------------------------------------------------------------- |
| `label` | No       | Display name shown in Quick Files. If empty, the file name is used during import.     |
| `path`  | Yes      | Path to the command file to run. The app stores the path as written in the CSV file.  |

Import also accepts `title` as an alias for `label`, and `file`, `command_file`, or `script` as aliases for `path`.

Example:

```csv
label,path
Bring-up,C:/scripts/bringup.txt
Factory Check,C:/scripts/factory-check.scr
Smoke Test,C:/scripts/smoke-test.cmd
```

## Settings Bundles

The app autosaves the current setup to:

```text
%LOCALAPPDATA%\ComPortZone\settings.json
```

Use `File > Export Settings` to save a complete JSON settings bundle, and `File > Import Settings` to load one. This replaces the older idea of managing named profiles inside the app.
During settings import, ComPort Zone asks how to handle quick commands:

- `Replace current quick commands`: use the commands from the settings file.
- `Append imported commands`: keep local commands and add the imported ones.
- `Skip duplicate commands`: avoid repeated commands when appending.

Settings bundles include:

- Serial defaults for new tabs
- Restored tabs and each tab's serial settings, terminal text, command draft, and send mode
- Quick commands, descriptions, groups, sort mode, hidden groups, and saved quick files with sort mode
- Command history and autocomplete source data
- Theme, terminal font, line wrap, scrollback, RX display mode, timestamps, and drawer state
- Last log/script paths and window size

## Keyboard Shortcuts

- `Ctrl+T`: New tab
- `Ctrl+Shift+T`: Duplicate tab
- `Ctrl+W`: Close tab
- `Ctrl+Shift+P`: Command palette
- `Ctrl+B`: Toggle left drawer
- `Ctrl+Enter`: Connect or disconnect
- `Ctrl+F`: Search active terminal
- `Ctrl+K`: Clear terminal
- `Ctrl+Space`: Autocomplete command input
- `Up` / `Down`: Navigate command history
- `Ctrl+=` / `Ctrl+-`: Increase or decrease terminal font size

Terminal font family and size can also be changed from `View > Terminal Font Settings`.

## Third-Party Notices

The bundled icon subset comes from Tabler Icons under the MIT license. See `THIRD_PARTY_NOTICES.md`.
