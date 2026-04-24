# ComPort Zone

ComPort Zone is a Windows-first serial terminal for device bring-up, debugging, and repeated engineering command workflows.

The current UI is terminal-first: a menu bar, Windows Terminal-style tabs, one large terminal surface, a compact command bar, and a foldable left drawer for quick-send commands and shortcuts.

## Current Features
- Terminal-first layout with minimal chrome and a VS Code dark default theme
- Tabs for independent serial sessions
- Foldable and resizable left drawer, collapsed by default
- Quick-send commands with add, edit, delete, reorder, groups, text mode, hex mode, and optional line-ending override
- Serial profiles with COM port, baud rate, data bits, parity, stop bits, flow control, DTR, RTS, auto-reconnect, and line ending
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
python -m serial_terminal
```

After installation, either console script can also launch the app:

```powershell
comport-zone
serial-terminal
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

Older prototype settings from `%LOCALAPPDATA%\SerialTerminal\settings.json` are read automatically if the new settings file does not exist yet.
