# ComPort Zone - Project Guide

## 1. Project Overview

**ComPort Zone** is a Windows-first COM-port terminal application designed for device bring-up, debugging, and repeated engineering command workflows. It provides a terminal-first interface with a menu bar, Windows Terminal-style tabs, a large terminal surface, a compact command bar, and a foldable left drawer for quick commands and files.

### Key Technologies
- **Python 3.12+** - Core programming language
- **PySide6 (Qt 6)** - Desktop GUI framework
- **pyserial** - Serial port communication library
- **PyInstaller** - Windows executable bundling

### High-Level Architecture
The application follows a modular architecture:
- **Serial Core Layer** (`serial_core.py`) - Handles serial port connections, reading, writing, and auto-reconnect
- **Session Controller Layer** (`terminal_session_controller.py`) - Manages terminal sessions and tabs
- **Command Editor Layer** (`command_editor.py`, `command_editor_core.py`) - Handles command file editing and execution
- **UI Layer** - PySide6 widgets and views for the desktop interface
- **Models & Storage** (`models.py`, `storage.py`) - Data structures and persistence

## 2. Getting Started

### Prerequisites
- Windows 10/11 (64-bit)
- Python 3.12 or higher
- PowerShell

### Installation

```powershell
# Create virtual environment
python -m venv .venv

# Activate the environment
.venv\Scripts\Activate.ps1

# Install the application
python -m pip install -e .
```

### Running the Application

```powershell
# Run via module
python -m ComPort_Zone

# Or use the console script (after installation)
comport-zone
```

### Building Windows EXE

```powershell
# Update version before release
.\update_version.bat -Version 1.2.3

# Build the executable
.\build_exe.bat

# Output location:
# release\ComPort_Zone-X.Y.Z-win64\
# release\ComPort_Zone-X.Y.Z-win64.zip
# dist\ComPort Zone.exe
```

### Running Tests

```powershell
# Install test dependencies
python -m pip install pytest

# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_serial_core.py -v
```

## 3. Project Structure

```
src/ComPort_Zone/
├── __init__.py              # Package initialization
├── __main__.py              # Entry point for python -m ComPort_Zone
├── app.py                   # Main application entry point
├── app_settings_controller.py # Settings management
├── assets/                  # Static assets (icons, images)
├── batch.py                 # Command file parsing and execution
├── command_editor.py        # Command file editor UI
├── command_editor_core.py   # Command editor core logic
├── command_editor_highlighting.py # Syntax highlighting
├── command_file_service.py  # Command file operations
├── command_registry.py      # Command registration
├── command_run_targets.py   # Execution targets
├── command_search.py        # Terminal search functionality
├── history.py               # Command history management
├── icons.py                 # UI icons management
├── models.py                # Data models (SerialProfile, QuickCommand, etc.)
├── quick_actions.py         # Quick command/file actions
├── quick_actions_panel.py   # Quick actions UI panel
├── quick_actions_sidebar.py # Quick actions sidebar
├── quick_action_controller.py # Quick actions controller
├── serial_core.py           # Serial port communication core
├── session_log.py           # Session logging
├── settings_service.py      # Settings persistence
├── storage.py               # Data storage utilities
├── terminal_session_controller.py # Terminal session management
├── terminal_view.py         # Terminal UI view
├── themes.py                # Theme definitions
├── transports.py            # Transport layer abstraction
├── ui/                      # UI components
├── VERSION                  # Version file
├── widgets.py               # Custom widgets
├── workspace_state.py       # Workspace state management
└── __pycache__/            # Python cache

tests/
└── test_*.py                # Unit tests for each module
```

### Key Configuration Files

- `pyproject.toml` - Project metadata and dependencies
- `VERSION` - Application version
- `.gitignore` - Git ignore rules
- `.vscode/` - VS Code configuration

### Important Data Files

- `settings.json` - User settings (stored in `%LOCALAPPDATA%\ComPortZone\`)
- `release/*.zip` - Built executable distribution

## 4. Development Workflow

### Coding Standards

- **Python Version**: 3.12+
- **Type Hinting**: All functions and classes are type-annotated
- **Data Classes**: Use `@dataclass(slots=True)` for model classes
- **Futures Import**: Use `from __future__ import annotations` at file top
- **Thread Safety**: Use `Lock` and `Event` for thread-safe operations
- **Error Handling**: Catch specific exceptions (e.g., `SerialException`)

### Testing Approach

- Unit tests in `tests/` directory
- Test files named `test_<module>.py`
- Use `pytest` for test execution
- Tests cover:
  - Serial communication (`test_serial_core.py`)
  - Command file parsing (`test_batch.py`)
  - Models and storage (`test_models_and_storage.py`)
  - UI components (`test_terminal_view.py`, etc.)

### Build and Deployment

1. **Development**:
   ```powershell
   python -m pip install -e .
   ```

2. **Production EXE**:
   ```powershell
   .\build_exe.bat
   ```

3. **Force rebuild with dependencies**:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_exe.ps1 -ForceInstall
   ```

### Contribution Guidelines

1. Fork the repository
2. Create a feature branch
3. Make changes and test thoroughly
4. Update documentation if needed
5. Run all tests: `python -m pytest tests/ -v`
6. Commit with clear messages
7. Submit a pull request

## 5. Key Concepts

### Domain-Specific Terminology

- **COM Port**: Serial communication port (e.g., `COM1`, `COM3`)
- **BAUDRATE**: Serial communication speed (e.g., 115200)
- **PARITY**: Parity bit setting (N, E, O, M)
- **FLOW_CONTROL**: Hardware/software flow control (RTS/CTS, XON/XOFF)
- **DTR/RTS**: Data Terminal Ready / Request To Send control lines
- **SEND**: Command to send data to the device
- **WAIT**: Pause before next command
- **EXPECT**: Wait for specific response text
- **HEX**: Send raw bytes without line ending

### Core Abstractions

- **SerialProfile**: Configuration for serial port connection
- **SerialClient**: Manages serial port connection and events
- **QuickCommand**: Saved command for quick sending
- **QuickFile**: Path to a command file for quick access
- **TerminalSessionState**: State of a terminal tab
- **BatchStep**: Individual step in a command file
- **BatchRunner**: Executes command files

### Design Patterns

- **Event Queue Pattern**: Uses `Queue` for thread-safe event communication
- **Observer Pattern**: Serial events broadcast to subscribers
- **Thread Pool**: Background threads for serial reading and reconnect
- **Singleton-like**: `SerialClient` manages singleton connection state
- **Strategy Pattern**: Different transport kinds (currently serial)

## 6. Common Tasks

### Connecting to a COM Port

```python
from ComPort_Zone.serial_core import SerialClient, SerialProfile

profile = SerialProfile(port="COM3", baudrate=115200)
client = SerialClient()
client.connect(profile)
```

### Sending Text

```python
client.send_text("AT\r\n")
```

### Sending Raw Bytes

```python
client.send_bytes(b'\xAA\x55\x01')
```

### Listing Available Ports

```python
ports = client.list_ports()
for port in ports:
    print(f"{port['device']}: {port['description']}")
```

### Creating a Quick Command

```python
from ComPort_Zone.models import QuickCommand

cmd = QuickCommand(
    label="Read Version",
    command="AT+VER\r\n",
    description="Read firmware version",
    group="General"
)
```

### Parsing a Command File

```python
from ComPort_Zone.batch import load_batch_file

steps = load_batch_file("scripts/smoke-test.cmd")
for step in steps:
    print(f"{step.kind}: {step.payload}")
```

### Substituting Parameters

```python
from ComPort_Zone.batch import substitute_batch_parameters

text = "SEND {{COMMAND}}"
values = {"COMMAND": "AT+VER\r\n"}
result = substitute_batch_parameters(text, values, lambda n, l, t: None)
# Result: "SEND AT+VER\r\n"
```

### Managing Settings

```python
from ComPort_Zone.settings_service import SettingsService

service = SettingsService()
settings = service.load()
settings.theme = "VS Code Dark"
service.save(settings)
```

## 7. Troubleshooting

### Common Issues

**Issue**: "Serial port not found"
- **Solution**: Check Device Manager for COM port availability
- Verify the port is not in use by another application

**Issue**: "Connection timeout"
- **Solution**: Increase `timeout_ms` in `SerialProfile`
- Check baud rate matches device specification

**Issue**: "Auto-reconnect not working"
- **Solution**: Set `auto_reconnect=True` in `SerialProfile`
- Check network/USB device is not disconnected

**Issue**: "PySide6 not found"
- **Solution**: Run `python -m pip install PySide6`

**Issue**: "Build failed - missing dependencies"
- **Solution**: Force reinstall with `scripts\build_exe.ps1 -ForceInstall`

### Debugging Tips

1. Enable serial event logging by subscribing to events:
   ```python
   events = client.subscribe_events()
   while True:
       event = events.get(timeout=1)
       print(event.kind, event.message)
   ```

2. Check thread status:
   ```python
   print(f"Is connected: {client.is_connected}")
   print(f"Is reconnecting: {client.is_reconnecting}")
   ```

3. Use Python debugger for batch runner issues:
   ```python
   import pdb; pdb.set_trace()
   ```

## 8. References

### Documentation

- [PySide6 Documentation](https://www.riverbankcomputing.com/static/Docs/PySide6/)
- [pyserial Documentation](https://pyserial.readthedocs.io/)
- [Python Data Classes](https://docs.python.org/3/library/dataclasses.html)

### Resources

- [Windows COM Port Guide](https://learn.microsoft.com/en-us/windows/win32/devguide/port-enum)
- [Serial Communication Basics](https://www.arduino.cc/en/Tutorial/Serial)

### Project Files

- `README.md` - Full feature list and usage
- `CHANGELOG.md` - Version history
- `RELEASE_NOTES.md` - Release information
- `THIRD_PARTY_NOTICES.md` - License information

### Keyboard Shortcuts

- `Ctrl+T` - New tab
- `Ctrl+Shift+T` - Duplicate tab
- `Ctrl+W` - Close tab
- `Ctrl+Enter` - Connect/disconnect
- `Ctrl+Space` - Autocomplete
- `Ctrl+K` - Clear terminal
- `Ctrl+F` - Search terminal
- `Ctrl+B` - Toggle left drawer

---

**Note**: This guide covers the main aspects of ComPort Zone. For detailed information about specific features, refer to the README.md and source code comments.
</think>

Now let me verify the file was created successfully and provide a summary.


```tool
TOOL_NAME: ls
BEGIN_ARG: dirPath
".continue/rules"