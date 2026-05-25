# ComPort Zone Architecture

## Purpose

This document is the living architecture and redesign reference for ComPort Zone. It describes the target shape of the project, the current transition state, what has already been extracted, and what still needs to move.

Update this document in the same change whenever a refactor changes subsystem ownership, introduces a new architectural boundary, or completes a roadmap item. Keep it practical: describe responsibilities, flows, and rules that help the next change land safely. Avoid method-by-method documentation that will drift quickly.

Companion documents:

- `docs/DESIGN.md`: detailed project design, module ownership, Mermaid diagrams, and data/control flows.
- `docs/LLM_CHANGE_GUIDE.md`: compact task guide for small LLMs and developers making minor fixes.

## Architecture Goals

- Keep the app PySide6 based and behavior-compatible while reducing large-widget ownership.
- Make feature work easier by separating UI wiring, controllers, domain services, transport adapters, persistence, and models.
- Support serial and LAN transports through the shared transport layer, while making future transports possible without rewiring the whole app.
- Prefer incremental refactors over rewrites. Every slice should keep the app usable and the test suite green.
- Keep pure/domain modules free of Qt dependencies unless the module is explicitly a Qt UI helper.
- Preserve existing user workflows unless a change is intentionally planned and documented.

## Target Architecture

ComPort Zone should settle into these layers:

| Layer | Responsibility | Target Examples |
| --- | --- | --- |
| App shell | Application startup, main window assembly, top-level dependency wiring | `app.py`, `ui/main_window.py` |
| Workspace UI | Tabs, status presentation, command-palette workspace entries, shared panels, terminal/editor widgets | `ui/tab_workspace.py`, `ui/workspace_status.py`, `ui/command_palette_entries.py`, `ui/command_file_targets.py`, `ui/terminal_tab.py`, `terminal_view.py`, future `ui/command_file_tab.py` |
| Dialog UI | Focused modal dialogs with limited business logic | `ui/dialogs/*` |
| Controllers | Coordinate UI events with domain services and transports | `terminal_session_controller.py`, `quick_action_controller.py`, `app_settings_controller.py`, `workspace_settings_controller.py`, future command-file/workspace controllers |
| Domain/services | Pure or mostly pure behavior: parsing, quick actions, command files, search state, workspace state | `quick_actions.py`, `batch.py`, `command_file_service.py`, `command_search.py`, `workspace_state.py` |
| Commands | One registry for actions used by menus, command palette, shortcuts, and context menus where practical | `command_registry.py` |
| Transports | Abstract communication endpoints and concrete adapters | `transports.py`, `serial_core.py`, `lan_core.py` |
| Persistence/settings | Read/write settings payloads, schema ownership, import/export behavior | `settings_service.py`, `storage.py`, `models.py` |
| Shared utilities | Theme, icons, widgets, history, logging | `themes.py`, `icons.py`, `widgets.py`, `history.py`, `session_log.py` |
| Tests | Focused tests beside each extracted module plus app-session regression tests | `tests/` |

The ideal dependency direction is:

```text
MainWindow/app shell
  -> UI widgets/presenters
  -> controllers
  -> domain/services
  -> models/persistence/transports
```

Qt-specific helpers may depend on Qt and theme/icon helpers. Pure services should not depend on Qt widgets.

## Current State Snapshot

The project is in an incremental redesign. `src/ComPort_Zone/app.py` is now a thin startup and compatibility module, while `src/ComPort_Zone/ui/main_window.py` owns the main window shell. The main window module is still large and still owns important UI assembly, some tab/session coordination, and many application commands. However, major behavior has already moved into focused modules. Serial and raw TCP LAN are now concrete transports behind the shared adapter contract.

The workspace drawer is treated as app-level UI state: collapsed/expanded state, drawer width, and selected Quick Commands/Quick Files page are applied consistently to terminal tabs and embedded command-file editor tabs. The top-level workspace now supports a two-pane split through `ui/split_workspace.py`, which owns one or two tab widgets while keeping terminal/editor widgets as live pages that can move between panes.

Terminal command entry is integrated into the terminal surface through `IntegratedTerminalEdit` in `widgets.py`. The widget owns prompt/draft editing rules, while `ui/terminal_tab.py` coordinates send, history, autocomplete, font zoom, and context-menu conversion actions around it.

Settings storage is intentionally conservative: `SettingsService` owns schema interpretation, including minimum-compatible schema declarations for upgrade/downgrade safety, while `SettingsStore` owns JSON file I/O, atomic replacement, and backup fallback. Loading tries valid payload candidates before returning defaults.

The current test suite is built around `unittest` and has focused coverage for extracted modules plus broader app-session behavior. The standard verification command is:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -q
```

## Subsystem Map

| Subsystem | Current Owner | Ideal Owner | Status | Notes |
| --- | --- | --- | --- | --- |
| App shell and main window assembly | `app.py`, `ui/main_window.py` | Thin `app.py` plus `ui/main_window.py` shell | In Progress | `app.py` is thin; `ui/main_window.py` should continue shrinking toward orchestration only. |
| Terminal tab UI | `ui/terminal_tab.py` | `ui/terminal_tab.py` | In Progress | Module location is extracted; the widget owns terminal layout/glue around the integrated prompt, quick drawer, status, context menus, and dialogs. |
| Terminal behavior | `terminal_session_controller.py` | `terminal_session_controller.py` | Done | Owns transport, send, logging, batch runner, event decisions, pause buffering. |
| Terminal text rendering/search | `terminal_view.py` | `terminal_view.py` | Done | Owns committed QTextEdit insertion, stream rendering, and search highlighting. |
| Command-file editor UI | `command_editor.py` plus coordination in `ui/main_window.py` | future `ui/command_file_tab.py` | In Progress | Core services are extracted; final UI location still open. |
| Command-file parsing/running support | `batch.py`, `command_file_service.py`, `command_run_targets.py`, `ui/command_file_targets.py` | Same | Done foundation | `ui/command_file_targets.py` owns run-target menu population, editor target refresh, and editor-to-terminal dispatch. |
| Command editor core/search/highlighting | `command_editor_core.py`, `command_search.py`, `command_editor_highlighting.py` | Same | Done | Focused modules with tests. |
| Quick actions domain | `quick_actions.py` | `quick_actions.py` | Done | Owns CSV, filtering, sorting, lookup, duplicate/reorder behavior. |
| Quick actions workflow | `quick_action_controller.py` | `quick_action_controller.py` | Done foundation | Owns add/edit/delete/import/export/reorder coordination around `QuickActionLibrary`; `MainWindow` keeps compatibility delegates. |
| Quick actions UI | `quick_actions_panel.py`, `quick_actions_sidebar.py` | Same | Done | Shared terminal/editor sidebar behavior. |
| Command registry | `command_registry.py` | `command_registry.py` | Done | Menus and command palette share command specs. |
| Main menu/action wiring | `ui/main_window_menus.py` | Same | Done | Top menu construction and shared QAction helpers are outside `MainWindow`. |
| Tab context menus | `ui/tab_context_menus.py` | Same | Done | Terminal/editor/empty tab context menu construction is outside `MainWindow`. |
| Command palette workspace entries | `ui/command_palette_entries.py` | Same | Done | Dynamic tab-switch entries are built outside `MainWindow`. |
| Workspace tabs | `ui/split_workspace.py`, `ui/tab_workspace.py` | Same | Done foundation | Split workspace owns one or two tab panes and live tab movement; tab workspace owns typed lookup, duplicate/close behavior, and session activation helpers. |
| Workspace status | `ui/workspace_status.py` | `ui/workspace_status.py` | Done | Owns tab colors/icons/tooltips and footer connection action state. |
| Workspace drawer state | `ui/main_window.py`, terminal/editor tab drawer hooks | Future presenter/controller if it grows | Done foundation | Collapsed state, selected page, and width are global settings applied across terminal and editor tabs. |
| Transport abstraction | `transports.py`, `serial_core.py`, `lan_core.py` | Same | Done foundation | Serial and raw TCP LAN adapters share the terminal controller/event contract. Future transports should add adapters, not rewrite UI. |
| Settings and schema | `settings_service.py`, `storage.py`, `models.py` | Same | Done foundation | `SettingsService` owns schema v2, minimum-compatible schema checks, and import/export payload rules; `SettingsStore` owns atomic save and backup fallback. |
| App settings workflow | `app_settings_controller.py` | `app_settings_controller.py` | Done foundation | Owns app-settings transfer dialogs, file pickers, busy state, load/export calls, status, and save-after-import; `MainWindow` still applies imported settings to live tabs. |
| Workspace restore/capture | `workspace_state.py`, `workspace_settings_controller.py` | Same | Done | Captures/restores terminal and command-file tabs; save/apply-imported-settings coordination is outside `MainWindow`. |
| Dialogs | `ui/dialogs/*` | `ui/dialogs/*` | Done foundation | Named dialog classes are extracted, including command-file parameter dialogs. Some workflow-owned ad hoc prompts still live with their owning feature code. |
| Theme/icons/widgets | `themes.py`, `icons.py`, `widgets.py`, `ui/fonts.py` | Same | In Progress | Font helpers and `IntegratedTerminalEdit` are extracted; more UI helpers may move here. |

## Important Flows

### Launch and Workspace Restore

`app.py` creates the QApplication, splash screen, and `MainWindow`. `ui/main_window.py` creates `SettingsStore`, `SettingsService`, loads `AppSettings`, creates the main tabs/status/menu shell, then delegates restored workspace creation through `WorkspaceStateService`. Terminal sessions and command-file tabs are recreated from settings state. New blank terminal tabs still prompt for connection settings. Restored connected serial tabs only auto-connect when the saved port is currently detected; missing ports are reported and left disconnected. Restored LAN tabs connect to the saved host and port directly because there is no endpoint discovery in v1.

### Terminal Send

The terminal widget reads the active draft from `IntegratedTerminalEdit` and the selected send mode, then delegates send behavior to `TerminalSessionController`. The controller parses text or hex mode, sends through the transport adapter, and asks the host to record command history. The widget commits the sent command into the terminal transcript, suppresses duplicate TX echo where needed, clears the draft after send, and handles user-facing send errors.

### RX Event Rendering

Serial events arrive from the transport event queue. The terminal widget drains events and delegates event decisions to `TerminalSessionController`. The controller decides whether to update connection state, buffer paused RX events, log events, set status text, or render. Rendering is planned by the controller, then `TerminalView` performs QTextEdit insertion, timestamp streaming, and search-highlight refresh.

### Command-File Run

Command-file text may come from a file path, quick file, editor buffer, or run target menu. Parsing and execution use `batch.py` and the terminal session batch runner. Parameter prompts remain UI-owned by the terminal widget, while `TerminalSessionController` coordinates template substitution and starts the runner. `ui/command_file_targets.py` coordinates connected terminal targets, run-target menus, editor target refresh, and editor-to-terminal dispatch.

### Quick Actions

Quick commands and quick files are owned by `QuickActionLibrary`. `QuickActionController` coordinates UI workflows around the library: add/edit/delete, import/export dialogs, bulk cleanup, reorder, refresh, save, and status updates. Terminal and editor sidebars use shared quick-action UI components with mode-specific callbacks. Terminal mode sends/runs; editor mode inserts/opens. CSV parsing/merge/filter/sort behavior stays in the domain service.

The drawer container around those shared panels is app-level UI state. Selecting Quick Commands or Quick Files, collapsing/expanding the drawer, or resizing it should update all terminal and embedded editor tabs through the main workspace callbacks.

### Settings Save, Import, and Export

`SettingsService` owns the application settings payload, schema, and minimum-compatible schema checks. `SettingsStore` only handles JSON file I/O, atomic replacement, and backup fallback. `WorkspaceStateService` captures runtime tab state into settings, including split-pane layout metadata while continuing to write flat terminal/editor fallback lists. `WorkspaceSettingsController` coordinates save and imported-settings application around the live workspace through `MainWindow` callbacks. `AppSettingsController` owns the UI workflow for app-settings import/export. App settings import/export intentionally excludes quick actions; quick commands and quick files use their own CSV flows. Local app settings persist drawer collapsed state, drawer width, and selected drawer page.

### Commands, Menus, and Palette

`CommandRegistry` defines reusable command metadata and callback factories. Menus and the command palette consume registry entries. Dynamic workspace tab-switch entries are built by `ui/command_palette_entries.py` from generic tab lookup callbacks. Context menus should use registry metadata where the action is shared, while keeping index-specific or selection-specific callbacks local.

## Progress Roadmap

| Status | Work Item | Notes |
| --- | --- | --- |
| Done | Quick action domain/library and shared sidebar/panel | Terminal and editor share data and UI shape. |
| Done | Command editor core/file/search/highlighting/run-target extractions | Editor internals are now split into focused modules. |
| Done | Transport abstraction foundation with serial and LAN adapters | Raw TCP LAN is implemented as a client transport. |
| Done | SettingsService and schema v2 ownership | Settings payload logic moved out of raw storage. |
| Done | Workspace state service | Restore/capture logic has one owner. |
| Done | CommandRegistry for menus and command palette | Static command definitions now live in one module. |
| Done | TabWorkspaceController and workspace status presenter | Tab lifecycle and tab/status presentation are no longer owned directly by `MainWindow`. |
| Done | Shared workspace drawer state | Drawer collapsed state, width, and selected page are synchronized across terminal and embedded editor tabs. |
| Done | TerminalSessionController and TerminalView split | Terminal behavior decisions and QTextEdit rendering are separate. |
| Done | Integrated terminal input widget | `IntegratedTerminalEdit` keeps transcript text protected while editing the active `TX> ` draft. |
| Done | Settings atomic save, backup fallback, and compatibility metadata | `SettingsStore` writes through a temp file, keeps a `.bak`, and `SettingsService` tries compatible primary/backup candidates before defaults. |
| Done | Command-file target/menu coordination | Run-target menu population and editor-to-terminal dispatch are owned by `ui/command_file_targets.py`. |
| Done | Dialog extraction into `ui/dialogs/*` | Terminal font, app settings transfer, quick action edit/import, connection, command palette, and command-file parameter dialogs are extracted. |
| Done | QuickActionController workflow extraction | MainWindow delegates quick-action mutation/import/export/reorder workflows to the controller. |
| Done | AppSettingsController workflow extraction | MainWindow delegates app-settings import/export UI workflow to the controller while keeping live workspace application local. |
| Done | WorkspaceSettingsController save/apply extraction | MainWindow delegates settings capture/save and imported-settings live workspace application coordination. |
| Done | Command-palette workspace entry extraction | Dynamic tab-switch entries now live in `ui/command_palette_entries.py`. |
| Done | Split workspace v1 | `ui/split_workspace.py` supports two tab panes, live tab moves, split/join commands, and persisted layout metadata. |
| Done | Terminal tab module-location extraction | `TerminalSessionWidget` now lives in `ui/terminal_tab.py`; `app.py` keeps a compatibility import. |
| Done | Command-file parameter dialog extraction | Parameter review and per-line summary UI moved from `TerminalSessionWidget` into `ui/dialogs/command_file_parameters.py`. |
| Done | MainWindow module-location extraction | `MainWindow` now lives in `ui/main_window.py`; `app.py` keeps startup, splash, and compatibility re-exports. |
| Done | MainWindow menu/action extraction | `ui/main_window_menus.py` owns top menu construction, registered QAction creation, and shared context-action helpers. |
| Done | Tab context menu extraction | `ui/tab_context_menus.py` owns terminal/editor/empty-tab context menu construction. |
| Next | Slim `ui/main_window.py` into a thinner shell | Keep construction and top-level wiring; move workflow coordination into services/presenters. |
| Next | Decide final module location for the command-file tab | Terminal tab moved; command-file tab still needs the same treatment once dependencies are stable. |
| Later | Add more non-serial transports | Add concrete adapters only after controller/UI boundaries are stable. |
| Later | Broaden command registry use in context menus | Use registry metadata for shared actions; keep selection-specific logic local. |

## Refactor Rules

- Keep each refactor behavior-compatible unless an intentional behavior change is documented.
- Keep changes small enough to review and test in one pass.
- Run the focused tests for touched modules and the full `unittest discover` suite after each slice.
- Do not move code just to move it. Extract only when it clarifies ownership, reduces duplication, or enables a planned feature.
- Keep Qt widgets and visual formatting out of pure services and domain modules.
- Keep controllers free of direct widget manipulation where possible. Controllers may return decisions or plans; widgets/presenters apply them to Qt controls.
- Preserve existing settings and CSV formats unless a schema change is explicitly planned.
- Update this document whenever a subsystem status changes or a new architectural boundary is introduced.

## Test Strategy

- Every extracted pure/domain module should have focused unit tests.
- Every extracted Qt helper or presenter should have lightweight QApplication-backed tests when practical.
- Startup and main-window behavior should continue to be protected by app-session regression tests for high-value workflows.
- Terminal input widget changes should include `tests/test_integrated_terminal_input.py` coverage plus app-session tests for send/history/autocomplete behavior.
- Transport work should use fake adapters/clients for contract tests.
- Settings changes should include serialization/import/export tests and restored workspace tests.
- Command registry changes should verify menus and command palette expose shared actions consistently.
- Quick-action changes should cover CSV, sorting, filtering, lookup, duplicate detection, and reorder behavior.
