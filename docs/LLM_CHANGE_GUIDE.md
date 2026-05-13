# LLM Change Guide

## Purpose

This guide is for small LLMs and developers making minor fixes in ComPort Zone. It gives quick ownership rules, safe edit recipes, and test commands.

For full design context, read `docs/DESIGN.md`. For current refactor status, read `docs/ARCHITECTURE.md`.

## First Steps For Any Change

1. Identify the feature area in the ownership table below.
2. Open the owning module and the closest focused tests.
3. Make the smallest behavior-compatible change.
4. Run focused tests.
5. Run the full suite if code changed.
6. Update `docs/ARCHITECTURE.md` or `docs/DESIGN.md` if ownership, flow, or architecture changes.

Full suite:

```powershell
.\run_tests.bat
```

Whitespace/doc sanity:

```powershell
git diff --check
```

## Ownership Quick Map

| If changing...                                | Start in...                                                                                                                        | Tests to run                                                  |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| App startup, splash, compatibility re-exports | `src/ComPort_Zone/app.py`                                                                                                          | `tests/test_app_sessions`                                     |
| Main window shell and high-level wiring       | `src/ComPort_Zone/ui/main_window.py`                                                                                               | `tests/test_app_sessions`                                     |
| Top menu/action wiring                        | `src/ComPort_Zone/ui/main_window_menus.py`, `src/ComPort_Zone/command_registry.py`                                                 | `tests/test_main_window_menus`, `tests/test_command_registry` |
| Tab right-click menus                         | `src/ComPort_Zone/ui/tab_context_menus.py`                                                                                         | `tests/test_tab_context_menus`                                |
| Command palette dynamic tab entries           | `src/ComPort_Zone/ui/command_palette_entries.py`                                                                                   | `tests/test_command_palette_entries`                          |
| Workspace tab lifecycle                       | `src/ComPort_Zone/ui/tab_workspace.py`                                                                                             | `tests/test_tab_workspace`, app-session tests                 |
| Footer/tab status presentation                | `src/ComPort_Zone/ui/workspace_status.py`                                                                                          | `tests/test_workspace_status`                                 |
| Terminal send/run/event behavior              | `src/ComPort_Zone/terminal_session_controller.py`                                                                                  | `tests/test_terminal_session_controller`                      |
| Terminal QTextEdit rendering/search           | `src/ComPort_Zone/terminal_view.py`                                                                                                | `tests/test_terminal_view`                                    |
| Terminal tab UI layout/glue                   | `src/ComPort_Zone/ui/terminal_tab.py`                                                                                              | terminal tests plus app-session tests                         |
| Integrated terminal prompt/draft editing      | `src/ComPort_Zone/widgets.py`                                                                                                      | `tests/test_integrated_terminal_input`                        |
| Serial behavior                               | `src/ComPort_Zone/serial_core.py`                                                                                                  | `tests/test_serial_core`                                      |
| LAN behavior                                  | `src/ComPort_Zone/lan_core.py`                                                                                                     | `tests/test_lan_core`                                         |
| Transport abstraction                         | `src/ComPort_Zone/transports.py`                                                                                                   | `tests/test_transports`                                       |
| Command-file parsing/running                  | `src/ComPort_Zone/batch.py`, `src/ComPort_Zone/command_file_service.py`                                                            | `tests/test_batch`, `tests/test_command_file_service`         |
| Command-file editor UI                        | `src/ComPort_Zone/command_editor.py`                                                                                               | `tests/test_command_editor`                                   |
| Editor core/highlighting/search               | `src/ComPort_Zone/command_editor_core.py`, `src/ComPort_Zone/command_editor_highlighting.py`, `src/ComPort_Zone/command_search.py` | matching focused tests                                        |
| Editor run target menus                       | `src/ComPort_Zone/ui/command_file_targets.py`                                                                                      | `tests/test_command_file_targets`                             |
| Quick command/file domain                     | `src/ComPort_Zone/quick_actions.py`                                                                                                | `tests/test_quick_actions`                                    |
| Quick action workflows                        | `src/ComPort_Zone/quick_action_controller.py`                                                                                      | `tests/test_quick_action_controller`                          |
| Quick action shared UI                        | `src/ComPort_Zone/quick_actions_panel.py`, `src/ComPort_Zone/quick_actions_sidebar.py`                                             | matching quick action UI tests                                |
| Settings schema/import/export                 | `src/ComPort_Zone/settings_service.py`, `src/ComPort_Zone/storage.py`, `src/ComPort_Zone/models.py`                                | `tests/test_models_and_storage`                               |
| Workspace settings save/restore               | `src/ComPort_Zone/workspace_state.py`, `src/ComPort_Zone/workspace_settings_controller.py`                                         | matching workspace tests                                      |
| Dialog UI                                     | `src/ComPort_Zone/ui/dialogs/*`                                                                                                    | `tests/test_dialogs`                                          |

## Do Not Break These Seams

- `ComPort_Zone.app.MainWindow` must keep working even though the class lives in `src/ComPort_Zone/ui/main_window.py`.
- `ComPort_Zone.app.default_config_path` may be monkeypatched by tests and older tooling. `MainWindow.config_path_supplier` preserves this.
- `ComPort_Zone.app` re-exports several dialogs, quick-action helpers, `SerialProfile`, `SerialEvent`, `TerminalSessionWidget`, and `BatchParameterPromptBridge`.
- Terminal/editor quick action sidebars should share the same panel shape. Do not fork separate sidebar designs.
- `TerminalSessionWidget.command_input` is the terminal `IntegratedTerminalEdit`; use `.text()` for the active `TX> ` draft and `.toPlainText()` for committed transcript text.
- Normal typing should never mutate committed terminal transcript text. Menu-driven replacement goes through `IntegratedTerminalEdit.replace_selection_from_menu()`.
- Quick action CSV import/export belongs to `quick_actions.py` and `quick_action_controller.py`, not `MainWindow`.
- App settings JSON import/export intentionally excludes quick actions.
- `SettingsStore` should remain file I/O only. Schema/payload rules belong to `SettingsService`.
- Controllers should make behavior decisions. Widgets should apply UI changes.

## Common Change Recipes

### Add Or Change A Menu Command

1. Edit `src/ComPort_Zone/command_registry.py` if the command is shared or should appear in menus/palette.
2. If it is top-menu-specific, check `src/ComPort_Zone/ui/main_window_menus.py`.
3. If it is tab-right-click-menu-specific, check `src/ComPort_Zone/ui/tab_context_menus.py`.
4. Add/update tests:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_command_registry tests/test_main_window_menus tests/test_tab_context_menus -q
```

### Fix A Tab Context Menu Bug

1. Edit `src/ComPort_Zone/ui/tab_context_menus.py`.
2. Keep `MainWindow.build_tab_context_menu(index)` as a delegate.
3. Add a focused case to `tests/test_tab_context_menus.py`.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_tab_context_menus -q
```

### Fix Tab Rename Behavior

1. Edit `src/ComPort_Zone/ui/main_window.py`.
2. The dialog default should use visible tab text, not always internal `session.title`.
3. Keep `QInputDialog` imported in `src/ComPort_Zone/ui/main_window.py`.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_app_sessions.AppSessionTests.test_rename_tab_updates_title -q
```

### Add A Static Command Palette Entry

1. Add or update `CommandSpec` in `src/ComPort_Zone/command_registry.py`.
2. Add the command id to `PALETTE_COMMAND_IDS`.
3. Update `tests/test_command_registry.py`.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_command_registry tests/test_app_sessions.AppSessionTests.test_command_palette_entries_and_shortcut -q
```

### Change Dynamic Command Palette Tab Entries

1. Edit `src/ComPort_Zone/ui/command_palette_entries.py`.
2. Update `tests/test_command_palette_entries.py`.
3. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_command_palette_entries -q
```

### Fix Terminal Send Behavior

1. Start in `src/ComPort_Zone/terminal_session_controller.py`.
2. Only edit `src/ComPort_Zone/ui/terminal_tab.py` if the bug is UI input, message box, combo state, or focus behavior.
3. If the bug touches the integrated prompt/draft itself, edit `src/ComPort_Zone/widgets.py` and update `tests/test_integrated_terminal_input.py`.
4. Update `tests/test_terminal_session_controller.py` or app-session tests.
5. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_terminal_session_controller tests/test_integrated_terminal_input tests/test_app_sessions -q
```

### Fix Integrated Terminal Prompt Behavior

1. Start in `src/ComPort_Zone/widgets.py`, especially `IntegratedTerminalEdit`.
2. Keep prompt/draft boundary logic inside the widget.
3. Use `src/ComPort_Zone/ui/terminal_tab.py` only for send/history/autocomplete wiring, context-menu actions, or host coordination.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_integrated_terminal_input tests/test_app_sessions -q
```

### Fix Terminal Rendering Or Search

1. Start in `src/ComPort_Zone/terminal_view.py`.
2. Keep committed QTextEdit rendering in `TerminalView`.
3. Keep event decisions in `TerminalSessionController`.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_terminal_view tests/test_terminal_session_controller tests/test_integrated_terminal_input -q
```

### Fix Terminal Selection Conversion

1. Context-menu wiring lives in `src/ComPort_Zone/ui/terminal_tab.py`.
2. Text/hex parsing helpers come from `src/ComPort_Zone/batch.py` and `src/ComPort_Zone/serial_core.py`.
3. Replacing committed transcript selections should go through `IntegratedTerminalEdit.replace_selection_from_menu()`.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_integrated_terminal_input tests/test_app_sessions -q
```

### Fix Command-File Run Behavior

1. Parsing and batch semantics: edit `src/ComPort_Zone/batch.py`.
2. Controller dispatch: edit `src/ComPort_Zone/terminal_session_controller.py`.
3. Run target menu/target selection: edit `src/ComPort_Zone/ui/command_file_targets.py`.
4. Parameter dialog: edit `src/ComPort_Zone/ui/dialogs/command_file_parameters.py`.
5. Run likely tests:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_batch tests/test_terminal_session_controller tests/test_command_file_targets tests/test_dialogs -q
```

### Fix Command Editor Search Or Replace

1. Search state/pure logic: edit `src/ComPort_Zone/command_search.py`.
2. Editor UI: edit `src/ComPort_Zone/command_editor.py`.
3. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_command_search tests/test_command_editor -q
```

### Fix Command Editor Highlighting

1. Edit `src/ComPort_Zone/command_editor_highlighting.py`.
2. Keep parser/search/domain logic elsewhere.
3. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_command_editor_highlighting -q
```

### Fix Quick Commands Or Quick Files

1. Domain behavior: edit `src/ComPort_Zone/quick_actions.py`.
2. Workflow/dialog behavior: edit `src/ComPort_Zone/quick_action_controller.py`.
3. Shared panel/sidebar behavior: edit `src/ComPort_Zone/quick_actions_panel.py` or `src/ComPort_Zone/quick_actions_sidebar.py`.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_quick_actions tests/test_quick_action_controller tests/test_quick_actions_panel tests/test_quick_actions_sidebar -q
```

### Fix Shared Drawer State

1. Start in `src/ComPort_Zone/ui/main_window.py` for global drawer callbacks and persisted settings updates.
2. Terminal drawer UI lives in `src/ComPort_Zone/ui/terminal_tab.py`.
3. Embedded command-file editor drawer UI lives in `src/ComPort_Zone/command_editor.py`.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_app_sessions.AppSessionTests.test_drawer_width_and_page_are_shared_across_tabs -q
```

### Fix Settings Save/Restore

1. Schema/payload: edit `src/ComPort_Zone/settings_service.py` and `src/ComPort_Zone/models.py`.
2. File I/O: edit `src/ComPort_Zone/storage.py`.
3. Runtime tab capture/restore: edit `src/ComPort_Zone/workspace_state.py`.
4. Live save/apply coordination: edit `src/ComPort_Zone/workspace_settings_controller.py`.
5. Preserve atomic save, `.bak` fallback, and primary/backup payload candidate behavior.
6. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_models_and_storage tests/test_workspace_state tests/test_workspace_settings_controller tests/test_app_sessions -q
```

### Add A Future Transport

Do not start by editing UI labels everywhere.

1. Add adapter behavior behind `transports.TransportAdapter`.
2. Add fake adapter contract tests in `tests/test_transports.py`.
3. Extend settings profiles through `models.py` and `settings_service.py` only as needed.
4. Wire controller-level selection before UI polish.
5. Keep serial and LAN behavior unchanged.

## Project Scripts

Set up a fresh clone:

```powershell
.\setup_dev.bat
```

Setup options:

```powershell
.\setup_dev.bat -SkipTests
.\setup_dev.bat -WithBuild
.\setup_dev.bat -RecreateVenv
.\setup_dev.bat -NoPipUpgrade
.\scripts\setup_dev.ps1 -DryRun
```

Launch the app:

```powershell
.\launch_app.bat
```

Verify the launch command without opening the GUI:

```powershell
.\scripts\launch_app.ps1 -DryRun
```

Run all tests:

```powershell
.\run_tests.bat
```

Run focused tests:

```powershell
.\run_tests.bat tests/test_quick_actions
.\scripts\run_tests.ps1 tests/test_app_sessions.AppSessionTests.test_rename_tab_updates_title
```

## Local Invariants To Preserve

- Full test suite should stay green after each slice.
- Existing settings and CSV formats should stay compatible unless the change explicitly says otherwise.
- `MainWindow` should keep shrinking. Do not add a new workflow there if a controller/presenter already exists.
- `ui/terminal_tab.py` is allowed to coordinate terminal UI, but pure behavior should move to controller/domain modules.
- Integrated terminal prompt/draft behavior belongs in `IntegratedTerminalEdit`; `ui/terminal_tab.py` should coordinate around it rather than duplicating boundary rules.
- `command_editor.py` is still the command-file editor UI owner until final module location is decided.
- Drawer collapsed state, selected page, and width are app-level settings shared by terminal and embedded command-file editor tabs.
- Quick action CSV import/export belongs to `quick_actions.py` and `quick_action_controller.py`, not `MainWindow`.
- App settings JSON import/export intentionally excludes quick actions.
- `SettingsStore` should remain file I/O only. Schema/payload rules belong to `SettingsService`.
- Controllers should make behavior decisions. Widgets should apply UI changes.

## Known Pitfalls

- Missing imports after moving Qt code are easy to miss. Add a focused regression test when fixing one.
- Rename tab should suggest visible tab text, such as `COM13`, not the internal default title `Terminal 1`.
- Terminal transcript text and terminal draft text are intentionally different: `.toPlainText()` returns committed transcript only, while `.text()` returns the active prompt draft.
- Quick command manual reorder is only reliable when custom order is active and all groups are visible.
- `Run in Terminal` appears both in menus and editor tab context menus. Keep target population delegated to `ui/command_file_targets.py`.
- `QApplication` must exist for Qt widget tests. Follow existing test patterns with `QApplication.instance() or QApplication([])`.
- Avoid touching generated `__pycache__` files.
