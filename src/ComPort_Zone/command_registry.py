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
        icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
        palette_title="New Command File",
        palette_subtitle="Create a command file in the built-in editor",
        palette_keywords="script batch file editor create",
    ),
    CommandSpec(
        "command_file.open_editor",
        lambda host: host.open_command_file_editor,
        menu_text="Open Command File Editor",
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
        "quick_commands.send_selected",
        lambda host: lambda: host.with_session(lambda session: session.send_selected_quick_command()),
        menu_text="Send Selected",
        icon=QStyle.StandardPixmap.SP_ArrowForward,
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
        menu_text="Add Command",
        icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
    ),
    CommandSpec(
        "quick_commands.edit_selected",
        lambda host: lambda: host.with_session(lambda session: host.edit_quick_command(session.selected_quick_command_id())),
        menu_text="Edit Selected",
        icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
    ),
    CommandSpec(
        "quick_commands.delete_selected",
        lambda host: lambda: host.with_session(lambda session: host.delete_quick_command(session.selected_quick_command_id())),
        menu_text="Delete Selected",
        icon=QStyle.StandardPixmap.SP_TrashIcon,
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
        menu_text="Import CSV",
        icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        palette_title="Import Quick Commands from CSV",
        palette_subtitle="Append quick commands from a CSV file",
        palette_keywords="quick send snippets commands csv import",
    ),
    CommandSpec(
        "quick_commands.export_csv",
        lambda host: host.export_quick_commands_csv,
        menu_text="Export CSV",
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
        menu_text="Add File",
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
        "quick_files.edit_selected",
        lambda host: lambda: host.with_session(lambda session: host.edit_quick_file(session.selected_quick_file_id())),
        menu_text="Edit Selected",
        icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
    ),
    CommandSpec(
        "quick_files.delete_selected",
        lambda host: lambda: host.with_session(lambda session: host.delete_quick_file(session.selected_quick_file_id())),
        menu_text="Delete Selected",
        icon=QStyle.StandardPixmap.SP_TrashIcon,
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
        menu_text="Import CSV",
        icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        palette_title="Import Quick Files from CSV",
        palette_subtitle="Append saved command-file paths from a CSV file",
        palette_keywords="quick files command files scripts csv import",
    ),
    CommandSpec(
        "quick_files.export_csv",
        lambda host: host.export_quick_files_csv,
        menu_text="Export CSV",
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
)


MENU_SECTIONS: dict[str, tuple[str | None, ...]] = {
    "file": (
        "file.new_tab",
        "file.duplicate_tab",
        "file.close_tab",
        SEPARATOR,
        "file.app_settings_transfer",
        SEPARATOR,
        "file.exit",
    ),
    "edit": (
        "edit.copy",
        "edit.select_all",
        SEPARATOR,
        "edit.find",
        "edit.replace",
        "edit.clear_terminal",
        SEPARATOR,
        "edit.clear_command_history",
    ),
    "view": (
        "view.toggle_drawer",
        "view.split_right",
        "view.split_down",
        "view.join_panes",
        SEPARATOR,
        "view.increase_font",
        "view.decrease_font",
        "view.terminal_font_settings",
        SEPARATOR,
        "view.show_timestamps",
        "view.line_wrap",
    ),
    "session": (
        "session.rename_tab",
        SEPARATOR,
        "session.pause_resume",
        "session.toggle_log",
    ),
    "serial": (
        "serial.connect_disconnect",
        "serial.settings",
        "serial.refresh_ports",
    ),
    "command_files": (
        "command_file.new",
        "command_file.open_editor",
        SEPARATOR,
        "command_file.run",
        "command_file.pause_resume",
        "command_file.stop",
    ),
    "quick_commands": (
        "quick_commands.send_selected",
        "quick_commands.save_current_input",
        SEPARATOR,
        "quick_commands.add",
        "quick_commands.edit_selected",
        "quick_commands.delete_selected",
        "quick_commands.delete_all",
        SEPARATOR,
        "quick_commands.import_csv",
        "quick_commands.export_csv",
    ),
    "quick_files": (
        "quick_files.run_selected",
        "quick_files.add",
        "quick_files.edit_selected_content",
        "quick_files.edit_selected",
        "quick_files.delete_selected",
        "quick_files.delete_all",
        SEPARATOR,
        "quick_files.import_csv",
        "quick_files.export_csv",
    ),
    "help": (
        "help.check_for_updates",
        "help.check_for_updates_on_launch",
        SEPARATOR,
        "help.about",
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
        return [item for item in items if item is not None]
