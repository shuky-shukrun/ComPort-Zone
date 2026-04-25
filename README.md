# ComPort Zone

ComPort Zone is a Windows-first COM-port terminal for device bring-up, debugging, and repeated engineering command workflows.

The current UI is terminal-first: a menu bar, Windows Terminal-style tabs, one large terminal surface, a compact command bar, and a foldable left drawer for quick-send commands and shortcuts.

## Current Features
- Terminal-first layout with minimal chrome and a VS Code dark default theme
- Bundled Tabler Icons subset for richer, modern, MIT-licensed UI icons
- Tabs for independent serial sessions
- Foldable and resizable left drawer, collapsed by default
- Quick-send commands with add, edit, delete, reorder, groups, text mode, hex mode, optional descriptions, optional line-ending override, and CSV import/export
- Serial profiles with COM port, baud rate, data bits, parity, stop bits, flow control, DTR, RTS, auto-reconnect, and line ending
- Rich profiles that also include theme, terminal font, history, drawer state, quick commands, log/script paths, and other workflow preferences
- Default profile autosaves changes; non-default profiles ask whether to save unsaved changes on exit or profile switch
- Profile management includes save-as, rename, delete, import, and export. The Default profile is protected from rename/delete.
- Serial Settings opens automatically for the active tab on launch and for each new blank tab
- Connect, disconnect, refresh ports, and reconnect feedback
- Text sending and hex/raw-byte sending
- Up/Down command history navigation
- Autocomplete from command history and saved quick commands with `Ctrl+Space`
- Search within the active terminal tab with highlighted matches
- RX, TX, status, and error coloring
- Optional terminal timestamps
- Clear, copy, select all, pause/resume output, and line wrap controls
- Per-tab command file execution
- Per-tab logging to text files
- Persisted settings for theme, drawer state, profiles, quick commands, font size, history, scrollback, and restored tabs

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

## Batch Script Format
Plain text files can be run from `File > Run Command File`. Every non-empty bare line is sent as a command with the active session line-ending setting.

The parser also supports a small batch DSL:

```text
# Comment
SEND version
WAIT 1000
HEX 55 AA 01 0D
reset
```

- `SEND <text>` sends text with the active line ending.
- `WAIT <milliseconds>` pauses before the next step.
- `HEX <bytes>` sends raw bytes without appending a line ending.
- Bare lines are treated like `SEND`.

## Quick Commands CSV Format
Quick commands can be exported from `Tools > Export Quick Commands to CSV` or imported from `Tools > Import Quick Commands from CSV`.

Import appends commands to the current quick-command list. Export writes UTF-8 CSV with these columns:

| Column | Required | Description |
| --- | --- | --- |
| `label` | No | Display name shown in Quick Send. If empty, the command text is used. |
| `command` | Yes | Text command or hex byte sequence to send. |
| `description` | No | Optional hover text for the saved command. |
| `send_mode` | No | `Text` or `Hex Bytes`. Invalid or empty values default to `Text`. |
| `group` | No | Group name used for sorting and show/hide filtering. Empty values become `General`. |
| `line_ending_override` | No | Optional text-mode line ending override: `None`, `CR`, `LF`, or `CRLF`. Empty uses the active session setting. |

Example:

```csv
label,command,description,send_mode,group,line_ending_override
Read Version,version,Read firmware version,Text,General,CRLF
Boot Wake,55 AA 00,Send bootloader wake bytes,Hex Bytes,Boot,
Read ID,id?,Read factory identity string,Text,Factory,LF
```

## Keyboard Shortcuts
- `Ctrl+T`: New tab
- `Ctrl+Shift+T`: Duplicate tab
- `Ctrl+W`: Close tab
- `Ctrl+B`: Toggle left drawer
- `Ctrl+Enter`: Connect or disconnect
- `Ctrl+F`: Search active terminal
- `Ctrl+K`: Clear terminal
- `Ctrl+Space`: Autocomplete command input
- `Up` / `Down`: Navigate command history
- `Ctrl+=` / `Ctrl+-`: Increase or decrease terminal font size

## Settings
Settings are stored under `%LOCALAPPDATA%\ComPortZone\settings.json`.

## Third-Party Notices
The bundled icon subset comes from Tabler Icons under the MIT license. See `THIRD_PARTY_NOTICES.md`.
