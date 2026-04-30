# ComPort Zone Architecture

## Purpose

This document is the living architecture and redesign reference for ComPort Zone. It describes the target shape of the project, the current transition state, what has already been extracted, and what still needs to move.

Update this document in the same change whenever a refactor changes subsystem ownership, introduces a new architectural boundary, or completes a roadmap item. Keep it practical: describe responsibilities, flows, and rules that help the next change land safely. Avoid method-by-method documentation that will drift quickly.

## Architecture Goals

- Keep the app PySide6 based and behavior-compatible while reducing large-widget ownership.
- Make feature work easier by separating UI wiring, controllers, domain services, transport adapters, persistence, and models.
- Keep serial as the only implemented transport for now, while making future transports possible without rewiring the whole app.
- Prefer incremental refactors over rewrites. Every slice should keep the app usable and the test suite green.
- Keep pure/domain modules free of Qt dependencies unless the module is explicitly a Qt UI helper.
- Preserve existing user workflows unless a change is intentionally planned and documented.

## Target Architecture

ComPort Zone should settle into these layers:

| Layer | Responsibility | Target Examples |
| --- | --- | --- |
| App shell | Application startup, main window assembly, top-level dependency wiring | `app.py`, future `ui/main_window.py` |
| Workspace UI | Tabs, status presentation, shared panels, terminal/editor widgets | `ui/tab_workspace.py`, `ui/workspace_status.py`, `ui/command_file_targets.py`, `terminal_view.py`, future `ui/terminal_tab.py`, `ui/command_file_tab.py` |
| Dialog UI | Focused modal dialogs with limited business logic | `ui/dialogs/*` |
| Controllers | Coordinate UI events with domain services and transports | `terminal_session_controller.py`, `quick_action_controller.py`, `app_settings_controller.py`, `workspace_settings_controller.py`, future command-file/workspace controllers |
| Domain/services | Pure or mostly pure behavior: parsing, quick actions, command files, search state, workspace state | `quick_actions.py`, `batch.py`, `command_file_service.py`, `command_search.py`, `workspace_state.py` |
| Commands | One registry for actions used by menus, command palette, shortcuts, and context menus where practical | `command_registry.py` |
| Transports | Abstract communication endpoints and concrete adapters | `transports.py`, `serial_core.py` |
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

The project is in an incremental redesign. `src/ComPort_Zone/app.py` is still large, currently about 3,000 lines, and still owns important UI assembly, some tab/session coordination, and many application commands. However, major behavior has already moved into focused modules.

The current test suite is built around `unittest` and has focused coverage for extracted modules plus broader app-session behavior. The standard verification command is:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -q
```

## Subsystem Map

| Subsystem | Current Owner | Ideal Owner | Status | Notes |
| --- | --- | --- | --- | --- |
| App shell and main window assembly | `app.py` | Thin `app.py` plus future `ui/main_window.py` | In Progress | Still large; should become orchestration only. |
| Terminal tab UI | `TerminalSessionWidget` in `app.py` | future `ui/terminal_tab.py` | In Progress | Widget is slimmer, but still in `app.py`. |
| Terminal behavior | `terminal_session_controller.py` | `terminal_session_controller.py` | Done | Owns transport, send, logging, batch runner, event decisions, pause buffering. |
| Terminal text rendering/search | `terminal_view.py` | `terminal_view.py` | Done | Owns QTextEdit insertion, stream rendering, search highlighting. |
| Command-file editor UI | `command_editor.py` plus parts of `app.py` | future `ui/command_file_tab.py` | In Progress | Core services are extracted; final UI location still open. |
| Command-file parsing/running support | `batch.py`, `command_file_service.py`, `command_run_targets.py`, `ui/command_file_targets.py` | Same | Done foundation | `ui/command_file_targets.py` owns run-target menu population, editor target refresh, and editor-to-terminal dispatch. |
| Command editor core/search/highlighting | `command_editor_core.py`, `command_search.py`, `command_editor_highlighting.py` | Same | Done | Focused modules with tests. |
| Quick actions domain | `quick_actions.py` | `quick_actions.py` | Done | Owns CSV, filtering, sorting, lookup, duplicate/reorder behavior. |
| Quick actions workflow | `quick_action_controller.py` | `quick_action_controller.py` | Done foundation | Owns add/edit/delete/import/export/reorder coordination around `QuickActionLibrary`; `MainWindow` keeps compatibility delegates. |
| Quick actions UI | `quick_actions_panel.py`, `quick_actions_sidebar.py` | Same | Done | Shared terminal/editor sidebar behavior. |
| Command registry | `command_registry.py` | `command_registry.py` | Done | Menus and command palette share command specs. |
| Workspace tabs | `ui/tab_workspace.py` | `ui/tab_workspace.py` | Done | Owns typed lookup, duplicate/close behavior, session activation helpers. |
| Workspace status | `ui/workspace_status.py` | `ui/workspace_status.py` | Done | Owns tab colors/icons/tooltips and footer connection action state. |
| Transport abstraction | `transports.py`, `serial_core.py` | Same | Done foundation | Serial is the only adapter. Future transports should add adapters, not rewrite UI. |
| Settings and schema | `settings_service.py`, `storage.py`, `models.py` | Same | Done foundation | `SettingsService` owns schema v2 and import/export payload rules. |
| App settings workflow | `app_settings_controller.py` | `app_settings_controller.py` | Done foundation | Owns app-settings transfer dialogs, file pickers, busy state, load/export calls, status, and save-after-import; `MainWindow` still applies imported settings to live tabs. |
| Workspace restore/capture | `workspace_state.py`, `workspace_settings_controller.py` | Same | Done | Captures/restores terminal and command-file tabs; save/apply-imported-settings coordination is outside `MainWindow`. |
| Dialogs | `ui/dialogs/*` | `ui/dialogs/*` | Done foundation | Named dialog classes are extracted. Some workflow-owned ad hoc prompts still live with their owning feature code. |
| Theme/icons/widgets | `themes.py`, `icons.py`, `widgets.py`, `ui/fonts.py` | Same | In Progress | Font helpers are extracted; more UI helpers may move here. |

## Important Flows

### Launch and Workspace Restore

`app.py` creates `SettingsStore`, `SettingsService`, loads `AppSettings`, creates the main tabs/status/menu shell, then delegates restored workspace creation through `WorkspaceStateService`. Terminal sessions and command-file tabs are recreated from settings state. New blank terminal tabs still prompt for serial settings.

### Terminal Send

The terminal widget reads UI state from the command input and mode combo, then delegates send behavior to `TerminalSessionController`. The controller parses text or hex mode, sends through the transport adapter, and asks the host to record command history. The widget only clears the input and handles user-facing send errors.

### RX Event Rendering

Serial events arrive from the transport event queue. The terminal widget drains events and delegates event decisions to `TerminalSessionController`. The controller decides whether to update connection state, buffer paused RX events, log events, set status text, or render. Rendering is planned by the controller, then `TerminalView` performs QTextEdit insertion, timestamp streaming, and search-highlight refresh.

### Command-File Run

Command-file text may come from a file path, quick file, editor buffer, or run target menu. Parsing and execution use `batch.py` and the terminal session batch runner. Parameter prompts remain UI-owned by the terminal widget, while `TerminalSessionController` coordinates template substitution and starts the runner. `ui/command_file_targets.py` coordinates connected terminal targets, run-target menus, editor target refresh, and editor-to-terminal dispatch.

### Quick Actions

Quick commands and quick files are owned by `QuickActionLibrary`. `QuickActionController` coordinates UI workflows around the library: add/edit/delete, import/export dialogs, bulk cleanup, reorder, refresh, save, and status updates. Terminal and editor sidebars use shared quick-action UI components with mode-specific callbacks. Terminal mode sends/runs; editor mode inserts/opens. CSV parsing/merge/filter/sort behavior stays in the domain service.

### Settings Save, Import, and Export

`SettingsService` owns the application settings payload and schema. `StorageStore` only handles JSON file I/O. `WorkspaceStateService` captures runtime tab state into settings. `WorkspaceSettingsController` coordinates save and imported-settings application around the live workspace through `MainWindow` callbacks. `AppSettingsController` owns the UI workflow for app-settings import/export. App settings import/export intentionally excludes quick actions; quick commands and quick files use their own CSV flows.

### Commands, Menus, and Palette

`CommandRegistry` defines reusable command metadata and callback factories. Menus and the command palette consume registry entries. Context menus should use registry metadata where the action is shared, while keeping index-specific or selection-specific callbacks local.

## Progress Roadmap

| Status | Work Item | Notes |
| --- | --- | --- |
| Done | Quick action domain/library and shared sidebar/panel | Terminal and editor share data and UI shape. |
| Done | Command editor core/file/search/highlighting/run-target extractions | Editor internals are now split into focused modules. |
| Done | Transport abstraction foundation with serial adapter | No non-serial transport yet. |
| Done | SettingsService and schema v2 ownership | Settings payload logic moved out of raw storage. |
| Done | Workspace state service | Restore/capture logic has one owner. |
| Done | CommandRegistry for menus and command palette | Static command definitions now live in one module. |
| Done | TabWorkspaceController and workspace status presenter | Tab lifecycle and tab/status presentation are no longer owned directly by `MainWindow`. |
| Done | TerminalSessionController and TerminalView split | Terminal behavior decisions and QTextEdit rendering are separate. |
| Done | Command-file target/menu coordination | Run-target menu population and editor-to-terminal dispatch are owned by `ui/command_file_targets.py`. |
| Done | Dialog extraction into `ui/dialogs/*` | Terminal font, app settings transfer, quick action edit/import, connection, and command palette dialogs are extracted. |
| Done | QuickActionController workflow extraction | MainWindow delegates quick-action mutation/import/export/reorder workflows to the controller. |
| Done | AppSettingsController workflow extraction | MainWindow delegates app-settings import/export UI workflow to the controller while keeping live workspace application local. |
| Done | WorkspaceSettingsController save/apply extraction | MainWindow delegates settings capture/save and imported-settings live workspace application coordination. |
| Next | Convert `MainWindow` into a thinner shell | Keep construction and top-level wiring; move workflow coordination into services/presenters. |
| Next | Decide final module locations for terminal and command-file tabs | Move classes out of `app.py` once dependencies are stable. |
| Later | Add non-serial transports | Add concrete adapters only after controller/UI boundaries are stable. |
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
- `app.py` behavior should continue to be protected by app-session regression tests for high-value workflows.
- Transport work should use fake adapters/clients for contract tests.
- Settings changes should include serialization/import/export tests and restored workspace tests.
- Command registry changes should verify menus and command palette expose shared actions consistently.
- Quick-action changes should cover CSV, sorting, filtering, lookup, duplicate detection, and reorder behavior.
