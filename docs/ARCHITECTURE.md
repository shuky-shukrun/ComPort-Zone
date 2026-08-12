# ComPort Zone Architecture

## Purpose

This document is the living architecture and redesign reference for ComPort Zone. It describes the target shape of the project, the current transition state, what has already been extracted, and what still needs to move.

Update this document in the same change whenever a refactor changes subsystem ownership, introduces a new architectural boundary, or completes a roadmap item. Keep it practical: describe responsibilities, flows, and rules that help the next change land safely. Avoid method-by-method documentation that will drift quickly.

Companion documents:

- `docs/DESIGN.md`: detailed project design, module ownership, Mermaid diagrams, and data/control flows.
- `docs/LLM_CHANGE_GUIDE.md`: compact task guide for small LLMs and developers making minor fixes.
- `docs/control-panel-requirements.md`: requirements contract for the Control Panel feature (FR/NFR, scope, acceptance criteria; formerly `control_panel-view-requirements.md`).

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
| Transports | Abstract communication endpoints and concrete adapters | `transports.py`, `serial_core.py`, `lan_core.py`, `udp_core.py`, `raw_transport.py`, `port_channel.py`, `transport_kinds.py` |
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
| Transport abstraction | `transports.py`, `serial_core.py`, `lan_core.py`, `udp_core.py`, `transport_kinds.py` | Same | Done | Serial, raw TCP LAN, and UDP adapters share the terminal controller/event contract and the same `PortChannel`. `transport_kinds.py` holds every user-visible name for a kind (labels, status prefixes, the CLI's `lan`→`tcp` wire spelling), so a fourth transport is one table row rather than a grep. Future transports add adapters, not UI branches. |
| Settings and schema | `settings_service.py`, `storage.py`, `models.py` | Same | Done foundation | `SettingsService` owns schema v2, minimum-compatible schema checks, and import/export payload rules; `SettingsStore` owns atomic save and backup fallback. |
| App settings workflow | `app_settings_controller.py` | `app_settings_controller.py` | Done foundation | Owns app-settings transfer dialogs, file pickers, busy state, load/export calls, status, and save-after-import; `MainWindow` still applies imported settings to live tabs. |
| Workspace restore/capture | `workspace_state.py`, `workspace_settings_controller.py` | Same | Done | Captures/restores terminal and command-file tabs; save/apply-imported-settings coordination is outside `MainWindow`. |
| Dialogs | `ui/dialogs/*` | `ui/dialogs/*` | Done foundation | Named dialog classes are extracted, including command-file parameter dialogs. Some workflow-owned ad hoc prompts still live with their owning feature code. |
| Theme/icons/widgets | `themes.py`, `icons.py`, `widgets.py`, `ui/fonts.py` | Same | In Progress | Font helpers and `IntegratedTerminalEdit` are extracted; more UI helpers may move here. |
| Control Panel domain (formerly ControlPanel) | `control_panel_models.py`, `control_panel_parse.py`, `control_panel_engine.py`, `control_panel_catalog.py`, `control_panel_expr.py`, `control_panel_history.py`, `control_panel_alerts.py`, `control_panel_value_log.py` | Same | Done | Qt-free models (value/led/control/setpoint/enum tile kinds + sparse v1/v2/v3 serialization), response parsing/rules, poll scheduler + per-session dispatcher, named-panel library, safe-AST expression engine for derived tiles, bounded history rings + paint math (sparkline/chart), alert transition detection + bounded log, and the CSV value logger (now with `kind` column ∈ poll/derived/control); all re-exported via `core/control_panel.py` (Qt-free enforced by tests). Internal module names keep their `control_panel*` prefix so v1/v2 user JSON loads byte-for-byte. Requirements: `docs/control-panel-requirements.md`. |
| Control Panel UI (formerly ControlPanel) | `ui/control_panel_tab.py`, `ui/control_panel_tiles.py`, `ui/control_panel_grid.py`, `ui/control_panel_sparkline.py`, `ui/control_panel_chart.py`, `ui/control_panel_alert_panel.py`, `ui/alert_sound.py`, `ui/control_panel_targets.py`, `ui/dialogs/control_panel_entry.py`, `ui/dialogs/control_panel_manager.py` | Same | Done | Third workspace tab type: tick loop + binding chip, value/LED/control/setpoint/enum tiles, master-arm header toggle (transient, Esc disarms, force-disarm on unbind), span-aware drag grid, in-tile sparkline + large chart page (both custom-painted), floating alert history panel + injectable QSoundEffect sounder, binding coordinator with refcounted dispatchers for per-entry session overrides, redesigned entry editor with live tile preview + tabs (including Setpoint and Enum shapes), library manager. |

## Important Flows

### Launch and Workspace Restore

`app.py` creates the QApplication, splash screen, and `MainWindow`. `ui/main_window.py` creates `SettingsStore`, `SettingsService`, loads `AppSettings`, creates the main tabs/status/menu shell, then delegates restored workspace creation through `WorkspaceStateService`. During normal app launch, startup prompts and the automatic update check are deferred until after the main window is shown and the splash is closed; if the first-run connection settings prompt is needed, the update check waits until that prompt returns. Terminal sessions and command-file tabs are recreated from settings state. New blank terminal tabs still prompt for connection settings. Restored connected serial tabs only auto-connect when the saved port is currently detected; missing ports are reported and left disconnected. Restored LAN and UDP tabs connect to the saved host and port directly because there is no endpoint discovery for either.

Nothing on this path may open a modal dialog: the window is not on screen yet, so a dialog blocks the launch where the user cannot see or dismiss it (the splash is deliberately not always-on-top for the same reason). Restore failures are reported instead — a command file that can no longer be read keeps its tab and surfaces the reason through `CommandFileEditorDialog.load_error` (status line plus the status bar), and a control-panel tab whose config was deleted is skipped with a notice. `MainWindow._restore_notice` carries that message past the "Ready" status set at the end of startup. `app.arm_startup_freeze_dump()` covers window construction, which runs before the event loop and so before the `install_freeze_watchdog` heartbeat can tick.

### Response Framing

`PortChannel` correlates a reply structurally — the worker runs drain → write →
read-window for one transaction at a time — and a `Matcher` decides when that
window holds a complete response. Byte-stream transports (serial, TCP) default
to `LineMatcher`; UDP defaults to `DatagramMatcher`, which completes on the
first whole datagram regardless of terminator. The default travels with the
channel (`PortChannel(default_matcher=...)`) and is read back through
`TransportAdapter.default_matcher()`, so callers never branch on transport kind.

An explicitly configured matcher always wins: a control-panel entry with a
regex parse rule gets its `RegexMatcher` on every transport. Only the
no-explicit-rule path consults the transport default — that single decision
lives in `control_panel_engine._matcher_for`, the one place in production code
that constructs a matcher.

### Terminal Send

The terminal widget reads the active draft from `IntegratedTerminalEdit` and the selected send mode, then delegates send behavior to `TerminalSessionController`. The controller parses text or hex mode, sends through the transport adapter, and asks the host to record command history. The widget commits the sent command into the terminal transcript, suppresses duplicate TX echo where needed, clears the draft after send, and handles user-facing send errors.

### RX Event Rendering

Serial events arrive from the transport event queue. The terminal widget drains events and delegates event decisions to `TerminalSessionController`. The controller decides whether to update connection state, buffer paused RX events, log events, set status text, or render. Rendering is planned by the controller, then `TerminalView` performs QTextEdit insertion, timestamp streaming, and search-highlight refresh.

### Command-File Run

Command-file text may come from a file path, quick file, editor buffer, terminal Run button, or run target menu. Parsing and execution use `batch.py` and the terminal session batch runner. Parameter prompts remain UI-owned by the terminal widget, while `TerminalSessionController` coordinates template substitution and starts the runner. `ui/command_file_targets.py` coordinates connected terminal targets, run-target menus, editor target refresh, and editor-to-terminal dispatch. Terminal tabs expose per-run Run, Pause, Resume, Stop, and status controls. Disconnects pause an active run, and reconnect waits for the user to resume instead of continuing automatically.

### Control Panel Polling (formerly ControlPanel Polling)

A control panel tab (`ui/control_panel_tab.py`) never owns a connection: it binds to an open terminal session and polls through it. The GUI side is a 100 ms `QTimer` tick that drains poll results into tiles, checks the bound session's health (open / connected / batch-running) into scheduler pause reasons, sweeps staleness, and submits due entries. All transport I/O happens on a per-session `SessionPollDispatcher` worker thread that executes transactions strictly one at a time (drain stale RX → send → collect the post-send RX window until the parse rule matches or the entry times out). Every panel bound to one session shares that session's dispatcher through `ControlPanelRunCoordinator`'s reference counting, which is what serializes panel commands on the wire. The dispatcher consumes its own `transport.subscribe_events()` queue and never contends with the terminal's event drain. Poll traffic is kept out of the bound terminal's transcript: panel TX events carry `source="control_panel"`, and the dispatcher's `PollTrafficJournal` marks the transaction windows whose RX the terminal skips rendering (the session log and all event subscribers still see everything). Control-panel configs live in the settings library (`AppSettings.control_panels`, schema v7) and live-save on every mutation; open tabs restore with the workspace and rebind by unique endpoint hint.

v2 layered per-entry session overrides on top: each entry may target a different open terminal via `target_endpoint`, in which case the tab holds a dict of refcounted dispatchers (one per involved session) and per-entry submit-time gating (skip when that target session is unhealthy) replaces v1's scheduler-level connection/batch pause reasons. The shared `_apply_outcome` funnel is the v2 backbone: every successful parse — poll OR derived — flows through it once and sequentially feeds the verdict pipeline, the per-entry `EntryHistory` ring (for sparkline + chart), CSV logging, alert edge detection, and derived dependents. Derived tiles are computed by a safe-AST expression evaluator (`control_panel_expr.py`) that resolves `{Label}` references at configure time and rejects anything but arithmetic / `abs|min|max|round|sqrt`. Alerts fire on transitions into `fail`/`error` (timeouts/staleness deliberately don't refire so a dead device can't notification-storm), populate a bounded `AlertLog`, and — when enabled — flash the taskbar via `QApplication.alert` and ring a debounced `QtAlertSounder` over a bundled WAV (with a `QApplication.beep` fallback when QtMultimedia is missing). Control tiles use distinct `ControlRequest` records through the same per-session FIFO so a click never interleaves with a polling transaction.

v3 adds the **Master Arm + writing tiles** layer. Every panel boots disarmed (`_armed=False`, transient, never persisted). The header `arm_button` toggles state and fans the change out to all writing-tile widgets via `tab.armingChanged: Signal(bool)`; widgets re-render visually inert (`panelArmed="false"` QSS property) when disarmed and refuse pointer interaction. The first check inside `_activate_control` rejects clicks when `not self._armed`, ahead of all session/connect gates. `is_writable()` (= `control | setpoint | enum`) is the umbrella predicate the master-arm gate fires on. Setpoint tiles stage a `{value}`-templated command from the editable spinbox at submit time and show readback in a second read-only field; enum tiles stage the selected option's command. Both flow through the same `_activate_control` → `dispatcher.submit_control` path as v2 control tiles. Shared `ReadbackSpec` on each writing entry can follow another polled tile (`source="entry"`) or send its own readback query (`source="command"`); readbacks pull once on connect, run after writes by default after 20 ms, and can continue at an interval. Setpoint connect-time readbacks also seed the editable spinbox without sending a set command; post-write and interval readbacks only refresh the readback display. Same-session post-write readbacks are attached to the `ControlRequest` so the dispatcher sends them before the next queued poll/control. `_writable_watchers` still fans followed-tile outcomes into setpoint readback fields and enum indicators, while direct readbacks apply to the writing tile runtime itself. Control sends append a `kind="control"` row to the CSV value log on result (success or error). An Esc shortcut scoped to the grid widget disarms instantly; `unbind`, session-close, settings reload, and shutdown all force-disarm. Per-tile `confirm` still fires when armed (belt + suspenders).

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
| Later | Add more non-serial transports | Add concrete adapters only after controller/UI boundaries are stable. UDP (2026-08) is the worked example: raw transport + client + adapter + a `transport_kinds` row, no UI restructuring. |
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
