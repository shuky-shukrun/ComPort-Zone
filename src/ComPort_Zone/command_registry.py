from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import QStyle


CallbackFactory = Callable[[Any], Callable[[], None]]


@dataclass(frozen=True, slots=True)
class CommandPaletteEntry:
    title: str
    subtitle: str
    callback: Callable[[], None]
    icon: QStyle.StandardPixmap | None = None
    keywords: str = ""

    def searchable_text(self) -> str:
        return f"{self.title} {self.subtitle} {self.keywords}".casefold()


@dataclass(frozen=True, slots=True)
class CommandSpec:
    command_id: str
    callback: CallbackFactory
    menu_text: str = ""
    shortcut: str = ""
    icon: QStyle.StandardPixmap | None = None
    checkable: bool = False
    palette_title: str = ""
    palette_subtitle: str = ""
    palette_keywords: str = ""

    def menu_label(self) -> str:
        return self.menu_text or self.palette_title

    def palette_entry(self, host: Any) -> CommandPaletteEntry | None:
        if not self.palette_title:
            return None
        return CommandPaletteEntry(
            title=self.palette_title,
            subtitle=self.palette_subtitle,
            callback=self.callback(host),
            icon=self.icon,
            keywords=self.palette_keywords,
        )


SEPARATOR: None = None

# Submenu placeholders consumed by MainWindowMenuBuilder; each "@..." token in a
# MENU_SECTIONS tuple is replaced by the matching dynamically-built submenu.
SUBMENU_OPEN_RECENT = "@open_recent"
SUBMENU_OPEN_DASHBOARD = "@open_dashboard"
SUBMENU_IMPORT_EXPORT = "@import_export"
SUBMENU_THEME = "@theme"
SUBMENU_TERMINAL_FONT = "@terminal_font"
SUBMENU_RX_DISPLAY = "@rx_display"
SUBMENU_SEND_MODE = "@send_mode"
SUBMENU_LINE_ENDING = "@line_ending"
SUBMENU_CONVERT_SELECTION = "@convert_selection"
SUBMENU_RUN_IN_TERMINAL = "@run_in_terminal"


COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec(
        "file.new_tab",
        lambda host: lambda: host.add_session(prompt_settings=True),
        menu_text="New Terminal",
        shortcut="Ctrl+T",
        icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
    ),
    CommandSpec(
        "file.duplicate_tab",
        lambda host: host.duplicate_current_session,
        menu_text="Duplicate Tab",
        shortcut="Ctrl+Shift+T",
        icon=QStyle.StandardPixmap.SP_FileIcon,
    ),
    CommandSpec(
        "file.close_tab",
        lambda host: host.close_current_session,
        menu_text="Close Tab",
        shortcut="Ctrl+W",
        icon=QStyle.StandardPixmap.SP_DialogCloseButton,
    ),
    CommandSpec(
        "file.app_settings_transfer",
        lambda host: host.show_app_settings_transfer_dialog,
        menu_text="App Settings Import / Export...",
        icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        palette_title="App Settings Import / Export",
        palette_subtitle="Import or export app preferences as JSON",
        palette_keywords="settings json import export restore backup preferences",
    ),
    CommandSpec(
        "file.exit",
        lambda host: host.close,
        menu_text="Exit",
        shortcut="Ctrl+Q",
        icon=QStyle.StandardPixmap.SP_TitleBarCloseButton,
    ),
    CommandSpec(
        "edit.copy",
        lambda host: lambda: host.with_session(lambda session: session.copy_selection()),
        menu_text="Copy",
        shortcut="Ctrl+Shift+C",
        icon=QStyle.StandardPixmap.SP_FileIcon,
    ),
    CommandSpec(
        "edit.select_all",
        lambda host: lambda: host.with_session(lambda session: session.select_all()),
        menu_text="Select All",
        shortcut="Ctrl+A",
        icon=QStyle.StandardPixmap.SP_FileDialogListView,
    ),
    CommandSpec(
        "edit.find",
        lambda host: host.show_find_in_current_tab,
        menu_text="Find",
        shortcut="Ctrl+F",
        icon=QStyle.StandardPixmap.SP_FileDialogContentsView,
        palette_title="Find / Search",
        palette_subtitle="Find in an editor tab or search terminal output in the active tab",
        palette_keywords="find search current tab terminal editor",
    ),
    CommandSpec(
        "edit.replace",
        lambda host: host.show_replace_in_current_tab,
        menu_text="Replace",
        shortcut="Ctrl+H",
        icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
        palette_title="Replace in Editor",
        palette_subtitle="Open find and replace for the active command-file editor tab",
        palette_keywords="find replace command file editor",
    ),
    CommandSpec(
        "edit.clear_terminal",
        lambda host: lambda: host.with_session(lambda session: session.clear_terminal()),
        menu_text="Clear Terminal",
        shortcut="Ctrl+K",
        icon=QStyle.StandardPixmap.SP_TrashIcon,
        palette_title="Clear Terminal",
        palette_subtitle="Clear output in the active tab",
        palette_keywords="clean erase output",
    ),
    CommandSpec(
        "edit.clear_command_history",
        lambda host: host.clear_command_history,
        menu_text="Clear Command History",
        icon=QStyle.StandardPixmap.SP_TrashIcon,
        palette_title="Clear Command History",
        palette_subtitle="Delete all remembered command input history",
        palette_keywords="history commands autocomplete delete cleanup",
    ),
    CommandSpec(
        "view.toggle_drawer",
        lambda host: host.toggle_drawer,
        menu_text="Toggle Drawer",
        shortcut="Ctrl+B",
        icon="list",
    ),
    CommandSpec(
        "view.split_right",
        lambda host: host.split_current_tab_right,
        menu_text="Split Right",
        shortcut="Ctrl+\\",
        icon=QStyle.StandardPixmap.SP_ArrowRight,
        palette_title="Split Right",
        palette_subtitle="Move the active tab into a side-by-side pane",
        palette_keywords="split pane tab right side by side",
    ),
    CommandSpec(
        "view.split_down",
        lambda host: host.split_current_tab_down,
        menu_text="Split Down",
        icon=QStyle.StandardPixmap.SP_ArrowDown,
        palette_title="Split Down",
        palette_subtitle="Move the active tab into a stacked pane",
        palette_keywords="split pane tab down stacked horizontal",
    ),
    CommandSpec(
        "view.join_panes",
        lambda host: host.join_workspace_panes,
        menu_text="Join Tabs",
        icon=QStyle.StandardPixmap.SP_DialogCloseButton,
        palette_title="Join Tabs",
        palette_subtitle="Move all split tabs back into one pane",
        palette_keywords="join unsplit merge panes tabs",
    ),
    CommandSpec(
        "view.increase_font",
        lambda host: lambda: host.change_font_size(1),
        menu_text="Increase Font",
        shortcut="Ctrl+=",
        icon=QStyle.StandardPixmap.SP_ArrowUp,
    ),
    CommandSpec(
        "view.decrease_font",
        lambda host: lambda: host.change_font_size(-1),
        menu_text="Decrease Font",
        shortcut="Ctrl+-",
        icon=QStyle.StandardPixmap.SP_ArrowDown,
    ),
    CommandSpec(
        "view.terminal_font_settings",
        lambda host: host.show_terminal_font_settings,
        menu_text="Terminal Font Settings",
        icon="cog",
        palette_title="Terminal Font Settings",
        palette_subtitle="Choose terminal font family and size",
        palette_keywords="font family size monospace terminal",
    ),
    CommandSpec(
        "view.show_timestamps",
        lambda host: host.toggle_timestamps,
        menu_text="Show Timestamps",
        icon=QStyle.StandardPixmap.SP_FileDialogInfoView,
        checkable=True,
    ),
    CommandSpec(
        "view.line_wrap",
        lambda host: host.toggle_line_wrap,
        menu_text="Line Wrap",
        icon=QStyle.StandardPixmap.SP_FileDialogListView,
        checkable=True,
    ),
    CommandSpec(
        "session.rename_tab",
        lambda host: host.rename_current_session,
        menu_text="Rename Tab",
        shortcut="F2",
        icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
    ),
    CommandSpec(
        "session.pause_resume",
        lambda host: lambda: host.with_session(lambda session: session.toggle_pause()),
        menu_text="Pause / Resume RX Output",
        shortcut="Ctrl+P",
        icon=QStyle.StandardPixmap.SP_MediaPause,
    ),
    CommandSpec(
        "session.toggle_log",
        lambda host: lambda: host.with_session(lambda session: session.toggle_logging()),
        menu_text="Start / Stop Log",
        shortcut="Ctrl+L",
        icon=QStyle.StandardPixmap.SP_DialogSaveButton,
    ),
    CommandSpec(
        "serial.connect_disconnect",
        lambda host: lambda: host.with_session(lambda session: session.toggle_connection()),
        menu_text="Connect / Disconnect",
        shortcut="Ctrl+Enter",
        icon=QStyle.StandardPixmap.SP_ComputerIcon,
        palette_title="Connect / Disconnect",
        palette_subtitle="Connect, disconnect, or stop auto-reconnect for the active tab",
        palette_keywords="serial port open close reconnect stop retry",
    ),
    CommandSpec(
        "serial.settings",
        lambda host: lambda: host.with_session(lambda session: session.open_connection_settings()),
        menu_text="Connection Settings",
        shortcut="Ctrl+,",
        icon="cog",
        palette_title="Connection Settings",
        palette_subtitle="Open serial COM port or LAN host settings",
        palette_keywords="settings connection serial lan tcp port baud parity stop bits flow control",
    ),
    CommandSpec(
        "serial.refresh_ports",
        lambda host: lambda: host.with_session(lambda session: session.refresh_ports()),
        menu_text="Refresh Ports",
        shortcut="F5",
        icon=QStyle.StandardPixmap.SP_BrowserReload,
    ),
    CommandSpec(
        "tools.command_palette",
        lambda host: host.show_command_palette,
        menu_text="Command Palette",
        shortcut="Ctrl+Shift+P",
        icon=QStyle.StandardPixmap.SP_CommandLink,
    ),
    CommandSpec(
        "command_file.new",
        lambda host: host.new_command_file_editor,
        menu_text="New Command File",
        shortcut="Ctrl+N",
        icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
        palette_title="New Command File",
        palette_subtitle="Create a command file in the built-in editor",
        palette_keywords="script batch file editor create",
    ),
    CommandSpec(
        "command_file.open_editor",
        lambda host: host.open_command_file_editor,
        menu_text="Open Command File Editor",
        shortcut="Ctrl+O",
        icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
        palette_title="Open Command File Editor",
        palette_subtitle="Open or edit a command file with autocomplete and validation",
        palette_keywords="script batch file editor autocomplete validate",
    ),
    CommandSpec(
        "command_file.run",
        lambda host: lambda: host.with_session(lambda session: session.run_script()),
        menu_text="Run Command File",
        shortcut="Ctrl+R",
        icon=QStyle.StandardPixmap.SP_MediaPlay,
        palette_title="Run Command File",
        palette_subtitle="Run a SEND / WAIT / HEX command script in the active tab",
        palette_keywords="script batch file",
    ),
    CommandSpec(
        "command_file.stop",
        lambda host: lambda: host.with_session(lambda session: session.stop_script()),
        menu_text="Stop Command File",
        shortcut="Ctrl+.",
        icon=QStyle.StandardPixmap.SP_MediaStop,
        palette_title="Stop Command File",
        palette_subtitle="Stop the running command file in the active tab",
        palette_keywords="script batch file stop cancel",
    ),
    CommandSpec(
        "command_file.pause_resume",
        lambda host: lambda: host.with_session(lambda session: session.toggle_script_pause()),
        menu_text="Pause / Resume Command File",
        icon=QStyle.StandardPixmap.SP_MediaPause,
        palette_title="Pause / Resume Command File",
        palette_subtitle="Pause or resume the running command file in the active tab",
        palette_keywords="script batch file pause resume",
    ),
    CommandSpec(
        "quick_commands.save_current_input",
        lambda host: lambda: host.with_session(lambda session: session.save_current_input_as_quick_command()),
        menu_text="Save Current Input",
        icon=QStyle.StandardPixmap.SP_DialogSaveButton,
        palette_title="Save Current Input as Quick Command",
        palette_subtitle="Save the command input from the active tab into Quick Send",
        palette_keywords="snippet quick send shortcut",
    ),
    CommandSpec(
        "quick_commands.add",
        lambda host: host.add_quick_command,
        menu_text="Add Saved Command...",
        icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
    ),
    CommandSpec(
        "quick_commands.delete_all",
        lambda host: host.delete_all_quick_commands,
        menu_text="Delete All Quick Commands",
        icon=QStyle.StandardPixmap.SP_TrashIcon,
        palette_title="Delete All Quick Commands",
        palette_subtitle="Remove every saved quick command",
        palette_keywords="quick send snippets commands delete cleanup",
    ),
    CommandSpec(
        "quick_commands.import_csv",
        lambda host: host.import_quick_commands_csv,
        menu_text="Import Saved Commands (CSV)...",
        icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        palette_title="Import Quick Commands from CSV",
        palette_subtitle="Append quick commands from a CSV file",
        palette_keywords="quick send snippets commands csv import",
    ),
    CommandSpec(
        "quick_commands.export_csv",
        lambda host: host.export_quick_commands_csv,
        menu_text="Export Saved Commands (CSV)...",
        icon=QStyle.StandardPixmap.SP_DialogSaveButton,
        palette_title="Export Quick Commands to CSV",
        palette_subtitle="Save all quick commands to a CSV file",
        palette_keywords="quick send snippets commands csv export",
    ),
    CommandSpec(
        "quick_files.run_selected",
        lambda host: lambda: host.with_session(lambda session: session.run_selected_quick_file()),
        menu_text="Run Selected",
        icon=QStyle.StandardPixmap.SP_ArrowForward,
        palette_title="Run Selected Quick File",
        palette_subtitle="Run the saved command file selected in the left drawer",
        palette_keywords="script batch file saved quick",
    ),
    CommandSpec(
        "quick_files.add",
        lambda host: host.add_quick_file,
        menu_text="Add Saved File...",
        icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
        palette_title="Add Quick File",
        palette_subtitle="Save a command file path in the left drawer",
        palette_keywords="script batch file save shortcut",
    ),
    CommandSpec(
        "quick_files.edit_selected_content",
        lambda host: host.edit_selected_quick_file_content,
        menu_text="Edit Selected File",
        icon=QStyle.StandardPixmap.SP_FileDialogContentsView,
        palette_title="Edit Selected Quick File",
        palette_subtitle="Open the selected saved command file in the built-in editor",
        palette_keywords="script batch file saved quick edit",
    ),
    CommandSpec(
        "quick_files.delete_all",
        lambda host: host.delete_all_quick_files,
        menu_text="Delete All Quick Files",
        icon=QStyle.StandardPixmap.SP_TrashIcon,
        palette_title="Delete All Quick Files",
        palette_subtitle="Remove every saved command-file shortcut",
        palette_keywords="quick files command files scripts delete cleanup",
    ),
    CommandSpec(
        "quick_files.import_csv",
        lambda host: host.import_quick_files_csv,
        menu_text="Import Saved Files (CSV)...",
        icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        palette_title="Import Quick Files from CSV",
        palette_subtitle="Append saved command-file paths from a CSV file",
        palette_keywords="quick files command files scripts csv import",
    ),
    CommandSpec(
        "quick_files.export_csv",
        lambda host: host.export_quick_files_csv,
        menu_text="Export Saved Files (CSV)...",
        icon=QStyle.StandardPixmap.SP_DialogSaveButton,
        palette_title="Export Quick Files to CSV",
        palette_subtitle="Save all saved command-file paths to a CSV file",
        palette_keywords="quick files command files scripts csv export",
    ),
    CommandSpec(
        "help.check_for_updates",
        lambda host: host.check_for_updates,
        menu_text="Check for Updates",
        icon=QStyle.StandardPixmap.SP_BrowserReload,
        palette_title="Check for Updates",
        palette_subtitle="Look for a newer ComPort Zone release on GitHub",
        palette_keywords="update version release github download",
    ),
    CommandSpec(
        "help.check_for_updates_on_launch",
        lambda host: host.toggle_check_for_updates_on_launch,
        menu_text="Check for Updates on Launch",
        checkable=True,
    ),
    CommandSpec(
        "help.about",
        lambda host: host.show_about,
        menu_text="About",
        icon=QStyle.StandardPixmap.SP_MessageBoxInformation,
    ),
    # --- Restructured-menu additions ---------------------------------------
    CommandSpec(
        "file.preferences",
        lambda host: host.show_preferences,
        menu_text="Preferences...",
        icon="cog",
        palette_title="Preferences",
        palette_subtitle="Theme, fonts, scrollback, logging, reconnect, data & reset",
        palette_keywords="settings preferences options config theme font scrollback log reset",
    ),
    CommandSpec(
        "file.close_other_tabs",
        lambda host: host.close_other_current_session,
        menu_text="Close Other Tabs",
        icon=QStyle.StandardPixmap.SP_TitleBarCloseButton,
    ),
    CommandSpec(
        "command_file.save",
        lambda host: host.save_current_command_file,
        menu_text="Save Command File",
        icon="save",
    ),
    CommandSpec(
        "command_file.save_as",
        lambda host: host.save_current_command_file_as,
        menu_text="Save Command File As...",
        icon="save-as",
    ),
    CommandSpec(
        "command_file.send_file",
        lambda host: lambda: host.with_session(lambda session: session.send_file()),
        menu_text="Send File...",
        icon=QStyle.StandardPixmap.SP_ArrowForward,
        palette_title="Send File",
        palette_subtitle="Stream a file's raw bytes over the active connection",
        palette_keywords="send file upload bytes raw transfer",
    ),
    CommandSpec(
        "edit.paste",
        lambda host: host.paste_into_focused,
        menu_text="Paste",
        shortcut="Ctrl+Shift+V",
        icon="copy",
    ),
    CommandSpec(
        "view.move_to_other_pane",
        lambda host: host.move_tab_to_other_pane,
        menu_text="Move to Other Pane",
        icon=QStyle.StandardPixmap.SP_ArrowRight,
    ),
    CommandSpec(
        "view.reset_font",
        lambda host: host.reset_font_size,
        menu_text="Reset Zoom",
        shortcut="Ctrl+0",
        icon="refresh",
    ),
    CommandSpec(
        "connection.auto_reconnect",
        lambda host: lambda: host.with_session(lambda session: session.toggle_auto_reconnect()),
        menu_text="Auto-Reconnect",
        checkable=True,
    ),
    CommandSpec(
        "connection.dtr",
        lambda host: lambda: host.with_session(lambda session: session.toggle_dtr()),
        menu_text="DTR",
        checkable=True,
    ),
    CommandSpec(
        "connection.rts",
        lambda host: lambda: host.with_session(lambda session: session.toggle_rts()),
        menu_text="RTS",
        checkable=True,
    ),
    CommandSpec(
        "connection.send_break",
        lambda host: lambda: host.with_session(lambda session: session.send_break()),
        menu_text="Send Break",
        icon="bolt",
        palette_title="Send Break",
        palette_subtitle="Send a serial break condition on the active connection",
        palette_keywords="serial break signal line",
    ),
    CommandSpec(
        "terminal.open_log_folder",
        lambda host: host.open_log_folder,
        menu_text="Open Log Folder",
        icon="folder",
    ),
    CommandSpec(
        "tools.open_config_folder",
        lambda host: host.open_config_folder,
        menu_text="Open Config Folder",
        icon="folder",
        palette_title="Open Config Folder",
        palette_subtitle="Open the folder holding settings.json",
        palette_keywords="config settings folder json appdata location",
    ),
    CommandSpec(
        "help.shortcuts",
        lambda host: host.show_keyboard_shortcuts,
        menu_text="Keyboard Shortcuts...",
        icon="list",
        palette_title="Keyboard Shortcuts",
        palette_subtitle="Show the keyboard shortcut reference",
        palette_keywords="keyboard shortcuts keys reference cheat sheet",
    ),
    # --- Control panel (formerly Dashboard view; the command ids stay) ----
    CommandSpec(
        "dashboard.new",
        lambda host: host.new_dashboard_tab,
        menu_text="New Control Panel",
        icon=QStyle.StandardPixmap.SP_FileDialogListView,
        palette_title="New Control Panel",
        palette_subtitle="Create a control panel of background-polled commands and controls",
        palette_keywords=(
            "control panel dashboard tiles poll monitor values gauges background "
            "setpoint enum hmi"
        ),
    ),
    CommandSpec(
        "dashboard.manage",
        lambda host: host.show_dashboard_manager,
        menu_text="Control Panels...",
        shortcut="Ctrl+Shift+D",
        icon=QStyle.StandardPixmap.SP_FileDialogListView,
        palette_title="Manage Control Panels",
        palette_subtitle="Open, rename, duplicate, import or export saved control panels",
        palette_keywords=(
            "control panel dashboard manage library open rename duplicate delete"
        ),
    ),
    CommandSpec(
        "dashboard.import_json",
        lambda host: host.import_dashboards_json,
        menu_text="Import Control Panels (JSON)...",
        icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        palette_title="Import Control Panels from JSON",
        palette_subtitle="Merge control panels from a ComPort Zone control panel file",
        palette_keywords="control panel dashboard json import merge transfer",
    ),
    CommandSpec(
        "dashboard.export_json",
        lambda host: host.export_dashboards_json,
        menu_text="Export Control Panels (JSON)...",
        icon=QStyle.StandardPixmap.SP_DialogSaveButton,
        palette_title="Export Control Panels to JSON",
        palette_subtitle="Save all control panels to a transferable JSON file",
        palette_keywords="control panel dashboard json export share transfer backup",
    ),
    CommandSpec(
        "help.documentation",
        lambda host: host.open_documentation,
        menu_text="Documentation",
        icon="file",
    ),
    CommandSpec(
        "help.view_on_github",
        lambda host: host.open_github_repo,
        menu_text="View on GitHub",
        icon="info",
    ),
    CommandSpec(
        "help.report_issue",
        lambda host: host.report_issue,
        menu_text="Report a Bug",
        icon="info",
        palette_title="Report a Bug",
        palette_subtitle="Open the GitHub issues page in your browser",
        palette_keywords="bug issue report github feedback",
    ),
)


MENU_SECTIONS: dict[str, tuple[str | None, ...]] = {
    "file": (
        "file.new_tab",
        "command_file.new",
        "command_file.open_editor",
        SUBMENU_OPEN_RECENT,
        SEPARATOR,
        "dashboard.new",
        SUBMENU_OPEN_DASHBOARD,
        SEPARATOR,
        "command_file.save",
        "command_file.save_as",
        "command_file.send_file",
        SEPARATOR,
        "file.duplicate_tab",
        "file.close_tab",
        "file.close_other_tabs",
        SEPARATOR,
        SUBMENU_IMPORT_EXPORT,
        "file.preferences",
        SEPARATOR,
        "file.exit",
    ),
    "edit": (
        "edit.copy",
        "edit.paste",
        "edit.select_all",
        SEPARATOR,
        "edit.find",
        "edit.replace",
        SEPARATOR,
        SUBMENU_CONVERT_SELECTION,
        SEPARATOR,
        "edit.clear_command_history",
    ),
    "view": (
        "view.toggle_drawer",
        SEPARATOR,
        "view.split_right",
        "view.split_down",
        "view.move_to_other_pane",
        "view.join_panes",
        SEPARATOR,
        SUBMENU_THEME,
        SUBMENU_TERMINAL_FONT,
        SEPARATOR,
        "view.show_timestamps",
        "view.line_wrap",
        SUBMENU_RX_DISPLAY,
    ),
    "connection": (
        "serial.connect_disconnect",
        "serial.settings",
        "serial.refresh_ports",
        SEPARATOR,
        SUBMENU_SEND_MODE,
        SUBMENU_LINE_ENDING,
        SEPARATOR,
        "connection.auto_reconnect",
        "connection.dtr",
        "connection.rts",
        "connection.send_break",
    ),
    "terminal": (
        "session.rename_tab",
        "edit.clear_terminal",
        SEPARATOR,
        "session.pause_resume",
        SEPARATOR,
        "session.toggle_log",
        "terminal.open_log_folder",
    ),
    "tools": (
        "tools.command_palette",
        SEPARATOR,
        "command_file.run",
        "command_file.pause_resume",
        "command_file.stop",
        SUBMENU_RUN_IN_TERMINAL,
        SEPARATOR,
        "dashboard.manage",
        SEPARATOR,
        "quick_commands.add",
        "quick_files.add",
        SEPARATOR,
        "tools.open_config_folder",
    ),
    "help": (
        "help.shortcuts",
        SEPARATOR,
        "help.documentation",
        "help.view_on_github",
        "help.report_issue",
        SEPARATOR,
        "help.check_for_updates",
        "help.check_for_updates_on_launch",
        SEPARATOR,
        "help.about",
    ),
    # Populated into the File > Import / Export submenu (not a top-level menu).
    "import_export": (
        "file.app_settings_transfer",
        SEPARATOR,
        "quick_commands.import_csv",
        "quick_commands.export_csv",
        SEPARATOR,
        "quick_files.import_csv",
        "quick_files.export_csv",
        SEPARATOR,
        "dashboard.import_json",
        "dashboard.export_json",
    ),
}


PALETTE_COMMAND_IDS: tuple[str, ...] = (
    "serial.connect_disconnect",
    "serial.settings",
    "command_file.run",
    "command_file.pause_resume",
    "command_file.new",
    "command_file.open_editor",
    "command_file.stop",
    "quick_files.run_selected",
    "quick_files.edit_selected_content",
    "quick_files.add",
    "edit.clear_terminal",
    "edit.clear_command_history",
    "edit.find",
    "edit.replace",
    "view.terminal_font_settings",
    "view.split_right",
    "view.split_down",
    "view.join_panes",
    "quick_commands.save_current_input",
    "file.app_settings_transfer",
    "quick_commands.import_csv",
    "quick_commands.export_csv",
    "quick_commands.delete_all",
    "quick_files.import_csv",
    "quick_files.export_csv",
    "quick_files.delete_all",
    "dashboard.new",
    "dashboard.manage",
    "dashboard.import_json",
    "dashboard.export_json",
    "help.check_for_updates",
)


class CommandRegistry:
    def __init__(self, host: Any, specs: Iterable[CommandSpec] = COMMAND_SPECS) -> None:
        self.host = host
        self._specs = {spec.command_id: spec for spec in specs}

    def spec(self, command_id: str) -> CommandSpec:
        return self._specs[command_id]

    def menu_items(self, menu_key: str) -> tuple[str | None, ...]:
        return MENU_SECTIONS[menu_key]

    def palette_entries(self) -> list[CommandPaletteEntry]:
        entries: list[CommandPaletteEntry] = []
        for command_id in PALETTE_COMMAND_IDS:
            spec = self.spec(command_id)
            entry = spec.palette_entry(self.host)
            if entry is not None:
                entries.append(entry)
        return entries

    def palette_command_ids(self) -> list[str]:
        return list(PALETTE_COMMAND_IDS)

    def menu_command_ids(self, menu_key: str | None = None) -> list[str]:
        items = (
            self.menu_items(menu_key)
            if menu_key is not None
            else tuple(item for section in MENU_SECTIONS.values() for item in section)
        )
        return [
            item
            for item in items
            if item is not None and not item.startswith("@")
        ]

    def shortcut_entries(self) -> list[tuple[str, str]]:
        """(label, shortcut) pairs for every command with a keyboard shortcut."""
        return [
            (spec.menu_label(), spec.shortcut)
            for spec in self._specs.values()
            if spec.shortcut
        ]
