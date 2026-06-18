# Control Panel — Feature Requirements

Status: Approved for implementation
Version: 3.0
Date: 2026-06-13
Applies to: ComPort Zone >= 0.5.0 (v1: settings schema v5; v2 features: schema v6; v3 features: schema v7)

v3.0 turns the feature **into Control Panel**. The user-visible surface renames from "ControlPanel View" to "Control Panel" everywhere a person sees it; internal symbols (`ControlPanelConfig`, `AppSettings.control_panels`, `control_panel_value_log.py`, `tests/test_control_panel_*`, every QSS selector starting with `#control_panel`) stay so existing user JSON, exports, and CSV logs load byte-for-byte. v3 adds two industrial write widgets — a numeric setpoint and an enum/dropdown selector — plus shared readback for all writing tiles, and wraps every writing tile in a master-arm safety gate that boots disarmed at every restart. The per-panel CSV log gains a `kind` column (`poll` / `derived` / `control`) so monitoring data and control actions land in one audit file (FR-63..FR-77).

v1.x requirements that talk about a "control_panel" describe the same feature the user now sees as a "control panel"; this doc keeps the old wording in places that document internal symbol names (e.g. "the bound terminal still labels poll TX with `source=\"control_panel\"`"). The interfaces, JSON keys, and class names are unchanged; only labels move.

## 1. Purpose

ComPort Zone users monitor live device values (voltages, temperatures, counters, fault flags) AND drive their gear (set voltages, switch modes, trip outputs) from one place. A Control Panel is a named collection of *entries*, each entry either a polled command whose response is parsed and rendered with rules, a derived/computed tile, or a writing tile (button, toggle, numeric setpoint, enum selector) that *sends* on user action. Polled traffic runs in the background over an existing terminal session's connection; writing tiles share the same connection and serialize against polls so commands never interleave on the wire. Control Panels are managed as a library, opened as workspace tabs, arranged with drag-and-drop, restored across application restarts, and gated by a master arm so the panel must be explicitly enabled before any write happens.

This document is the requirements contract for the feature. The companion implementation plan defines module design; `docs/ARCHITECTURE.md` and `docs/DESIGN.md` describe where the subsystem lands.

## 2. Definitions

| Term | Meaning |
| --- | --- |
| Control Panel (config) | A named, persisted collection of entries plus grid settings. Internally `ControlPanelConfig` (the class name stays for back-compat); lives in the panel library in settings under the `control_panels` key. *(Pre-v3 docs and code refer to this as a "control_panel".)* |
| Control Panel tab | An open workspace tab rendering one panel config (third tab type, beside terminal tabs and command-file editor tabs). Internally `ControlPanelTabWidget`. |
| Entry | One configured tile with its schedule, parse rule, display rules, write configuration, and grid placement (`ControlPanelEntry`). |
| Tile | The visual representation of one entry: value, LED, control button/toggle, setpoint, or enum selector. |
| Binding | The association between a Control Panel tab and one open terminal session whose connection is used for polling and sends. *(v2)* An entry may override the panel binding with its own target session (FR-54). |
| Poll transaction | One send→collect→parse cycle for one entry: drain stale RX, transmit the command, accumulate RX until the parse rule matches or the timeout elapses. |
| Pause reason | *(amended in v2)* Scheduler-level reasons are `user` and `unbound`; connection/batch conditions gate entries per target session at submit time (FR-55), so one unhealthy device pauses only its own entries. |
| Poll mode *(v2)* | `interval` (fixed-delay periodic) or `on_connect` (fires once per target-session connect edge; FR-52). |
| History *(v2)* | The bounded, in-memory ring of (time, numeric value) samples kept per entry while its tab is open; never persisted (FR-46). |
| Control tile *(v2)* | A tile that sends a command on click instead of polling (FR-59). Button or toggle. |
| Derived entry *(v2)* | An entry whose value is computed from other entries via a safe arithmetic expression instead of polling (FR-61). |
| Alert *(v2)* | A record created when an entry's state transitions into `fail` or `error` (FR-57). |
| Setpoint tile *(v3)* | A writing tile with an editable numeric field that sends a templated command with the chosen value; shared readback reflects the device's value back into that same field and warns when it differs from what was commanded (FR-63..67). |
| Enum tile *(v3)* | A writing tile with a dropdown of labeled options, each carrying its own send command; shared readback drives the dropdown selection to the option matching the current value and warns on a command/device mismatch (FR-68..71). |
| Writing tile *(v3)* | Any tile that sends on user action: control button, control toggle, setpoint, or enum (FR-72). Read-only tiles (value, LED, derived) are not writing tiles. |
| Master arm *(v3)* | A per-panel transient gate. While **Disarmed** (the boot state and the default after any unbind/restart), every writing tile refuses to send and renders visually inert. **Armed** unlocks sends for the session; per-tile confirmation (when configured) still applies. Esc on the focused panel disarms instantly (FR-72..75). |
| Audit row *(v3)* | The CSV value log gains a `kind` column (`poll` / `derived` / `control`). Control sends append one row per result with the sent command + ok/error state (FR-76..77). |

## 3. Locked product decisions

Decided with the product owner; v1/v2 decisions stand except where amended:

1. **Bind to a terminal session.** A Control Panel never owns a serial/LAN connection. It binds to an existing terminal tab's session (the same targeting concept as the command-file editor's Run button). Polling pauses while the bound session is disconnected and resumes automatically on reconnect. Poll traffic shares the session's connection but is hidden from the terminal's transcript (FR-15) — continuous polling would otherwise flood the terminal and make manual use impossible. *(v2 amendment: an entry may target a different open terminal session than the panel default — FR-54 — but binding to terminal sessions remains the only transport path; panels still never open ports.)*
2. **Tile types.** *(v2/v3 supersede the v1 restriction)* Value tiles, LED/status indicators, control button/toggle tiles, **numeric setpoint tiles (v3)**, and **enum selector tiles (v3)**; numeric value tiles may show an in-tile sparkline and open a large chart page. All charting is custom-painted (QPainter) — no plotting dependency.
3. **Layout: uniform grid with drag-to-reposition and per-tile spans** (1x1, 2x1, 1x2, 2x2). Layout persistence is deterministic.
4. **Multi-panel via named library + tabs.** Control Panels are named saved configurations with JSON import/export. Opening a panel creates a workspace tab; open tabs are restored on restart.
5. **No new dependencies for v3.** Setpoint widget uses `QDoubleSpinBox` + a read-only `QLineEdit` from PySide6 (already in the wheel); enum widget uses `QComboBox`; master arm uses `QShortcut`. Charts/sparklines via QPainter (carried from v2); alert sound via QtMultimedia (carried from v2) with a `QApplication.beep()` fallback.
6. **Safety-first writes (v3).** Every Control Panel boots **Disarmed**. Writing tiles render visually inert and refuse to send until the user clicks Arm in the panel header. Disarm is instant via Esc on the focused panel. Master arm state is **transient** — never persisted, always Disarmed at restart and after the panel loses its binding. Per-tile confirmation (when configured) still fires after arming. Industrial-grade means belt AND suspenders.
7. **Names: user-facing migrates, internal stays (v3).** Menus, sidebar pages, dialogs, the shipped example, and this requirements doc all say "Control Panel". The settings JSON `"control_panels"` key, the `ControlPanelConfig` class, the `control_panel_value_log.py` module, every QSS selector starting with `#control_panel`, and every `tests/test_control_panel_*` file keep their names — that's where v1/v2 user data back-compat lives. Pre-v3 exports load unchanged; v3 exports use the same key set.

## 4. Functional requirements

### 4.1 Control Panel library (catalog)

- **FR-1** The app maintains a persistent library of named Control Panel configs in the settings file. Create, rename, duplicate, and delete are available from a Control Panel Manager dialog and from Control Panel tab menus.
- **FR-2** Control Panel names are unique; creating or importing a duplicate name auto-suffixes (e.g. `PSU Bench (2)`), mirroring quick-command behavior.
- **FR-3** Control Panels can be exported to and imported from JSON files (single or multiple panels per file, versioned payload `{"comport_zone_control_panels": N, "control_panels": [...]}` — the JSON key set is unchanged for back-compat). Import offers merge semantics: colliding ids are regenerated; name collisions are renamed (default) or replaced (explicit option).
- **FR-4** Deleting a Control Panel that is currently open closes its tab (after the same confirmation as the manager delete action).

### 4.2 Workspace integration

- **FR-5** Opening a Control Panel creates a Control Panel tab in the active pane. Control Panel tabs coexist with terminal and editor tabs: they can be reordered, moved between split panes, closed, and listed in the command palette's tab switcher.
- **FR-6** Opening a Control Panel that is already open focuses the existing tab instead of creating a second one. One config is never editable from two tabs simultaneously.
- **FR-7** *(amended in v3)* Entry points: File → New Control Panel; File → Open Control Panel → (list of saved panels); Tools → Control Panels… (manager, shortcut `Ctrl+Shift+D` — the shortcut is preserved for muscle memory); the tab strip's "+" menu; the command palette (`New Control Panel`, `Control Panels…`).
- **FR-8** A Control Panel tab shows its name as the tab title, a status summary in the footer (entry count, binding, paused/warn state, **armed/disarmed**), and a panel-specific context menu on the tab (rename, bind submenu, pause/resume, edit layout, split/move, close) — not the terminal tab menu.
- **FR-9** Edits to a Control Panel (entries, layout, rename, columns) are saved to the library immediately (live-save, like quick commands). There is no dirty/unsaved state and no confirm-on-close prompt. The panel header carries a save indicator ("Saved HH:MM:SS") that refreshes on every persisted change, so the auto-save is visible while editing. **Master arm state is NOT persisted** (FR-72).

### 4.3 Binding and connection lifecycle

- **FR-10** A control_panel tab can bind to any *open* terminal session, including a currently disconnected one (polling stays paused with reason `connection` until it connects). The bind menu lists all open terminal tabs with their endpoint and connection state.
- **FR-11** While bound and connected, polling runs automatically unless paused by the user. A visible chip on the control_panel header shows the binding and its state: polling / paused (with reason) / unbound.
- **FR-12** *(amended in v2)* When a target session disconnects, the entries targeting it stop being submitted within one tick and their tiles age toward stale; on reconnect (including auto-reconnect), those entries resume automatically with staggered first sends. Entries targeting other, healthy sessions are unaffected (FR-55).
- **FR-13** When a target terminal tab is closed, its entries stop (the control_panel unbinds when the default target closes, showing the one-click bind menu) and all per-session resources for that session are released (no orphan threads or event subscriptions).
- **FR-14** *(amended in v2)* While a command-file (batch) run is active on a target session, polling of the entries targeting that session suspends automatically and resumes when the run finishes; other sessions' entries are unaffected.
- **FR-15** ControlPanel poll traffic is hidden from the bound terminal's transcript: poll TX events carry a `source="control_panel"` tag, and RX received inside a poll-transaction window (tracked by a per-session traffic journal, with a short grace tail for late fragments) is not rendered. The traffic still flows through the session log and every event subscriber unchanged; manually typed commands and out-of-window device output render normally. Tile tooltips remain the diagnostic surface for raw poll RX.
- **FR-16** A user-initiated pause/resume toggle exists per control_panel tab; the user-pause state persists across restarts.
- **FR-17** Multiple control_panel tabs may bind to the same session. Their poll transactions are serialized on that session (never interleaved on the wire) and share one dispatcher; closing one control_panel does not disturb the other.

### 4.4 Entries: commands and scheduling

- **FR-18** *(amended in v2)* Each entry defines: label, optional unit, command payload, send mode (`Text` or `Hex Bytes`), optional line-ending override (None/CR/LF/CRLF; default = session profile), poll interval (ms), response timeout (ms), staleness threshold (ms, 0 = automatic), parse rule, ordered color rules, tile kind, tile placement/span, and enabled flag. v2 adds: poll mode (FR-52), target-session override (FR-54), source + expression for derived entries (FR-61), control configuration (FR-59), sparkline visibility (FR-47), and per-entry alert opt-out (FR-58). All v2 fields serialize sparsely: an entry using no v2 feature persists byte-identical to its v1 shape.
- **FR-19** Poll interval has a floor of 100 ms; timeout range 50–30000 ms. Values outside ranges are clamped on load and rejected with messages in the editor dialog.
- **FR-20** *(amended in v2)* For `interval` entries, scheduling is fixed-delay: the next poll is scheduled `interval` after the previous transaction *completes* (success or timeout). A slow device therefore degrades the effective rate instead of building a backlog; at most one transaction per entry is outstanding at any time. `on_connect` entries are never time-due (FR-52); Poll Now (FR-53) arms an immediate poll for either mode.
- **FR-21** Poll transactions on one session execute strictly one at a time, FIFO across all entries and all control_panels bound to that session.
- **FR-22** Disabled entries are skipped by the scheduler but remain on the grid (rendered in a muted/disabled style).
- **FR-23** Send failures (port error mid-poll) render the tile in error state with the failure reason available in the tile tooltip; the scheduler continues with the next due entries (no crash, no permanent wedge).

### 4.5 Response parsing

- **FR-24** Parse rule kinds: `line` — the first complete line received after the send (terminated by CR, LF, or CRLF); `regex` — a regular expression searched over the accumulated post-send RX window, with a configurable capture group (index or name; group 0 = whole match).
- **FR-25** Parsed values have a declared type: `text` or `number`. For `number`, the captured string is converted to float; conversion failure is reported as a parse error on the tile (distinct from timeout).
- **FR-26** Parsing evaluates only RX received *after* the entry's send within that transaction (stale pre-send RX is discarded), bounded by a rolling window of 4096 characters (tail-kept).
- **FR-27** If the rule does not match before the entry timeout, the result is a timeout: the tile shows its last good value with a stale/timeout marker and the timestamp of the last success.
- **FR-28** Invalid regexes are rejected at edit time with a human-readable error; the entry editor provides a live tester (paste sample RX → see extracted value and resulting rule state).
- **FR-28a** *(added in v2.0)* The entry editor fits a 1366×768 work area with OK/Cancel always on screen: fields are grouped into General / Polling / Response & Rules tabs (pages that do not apply to the entry's shape are hidden), and a live tile preview above the tabs renders the entry through the real tile widgets — fed by the same parse/evaluate pipeline as the tester — so the user sees what will be added before accepting.

### 4.6 Color/indicator rules

- **FR-29** Each entry has an ordered list of rules evaluated first-match-wins against the parsed value. Operators: numeric `lt, le, gt, ge, eq_num, ne_num, between` (inclusive bounds) and textual `eq_text, contains, matches` (regex). Each rule maps to a semantic state `ok`, `warn`, or `fail`, with an optional display label override (e.g. `FAULT`).
- **FR-30** *(amended in v2)* Numeric operators are skipped when the parsed value is not numeric; if no rule matches, the state is `neutral`. Timeout/staleness produces `stale`; parse/send errors produce `error`. Semantic states map to theme colors centrally; a rule may carry an explicit custom color that overrides the theme mapping for its matches (FR-62).
- **FR-31** Value tiles render: label, latest value with unit, last-update timestamp, and state coloring. LED tiles render: a large state lamp, the state label (rule override or OK/WARN/FAIL/STALE), label, and last-update timestamp.
- **FR-32** A tile whose entry has not succeeded within its staleness threshold (default: `max(3*interval, interval + timeout + 1000ms)`) degrades to `stale` regardless of last state.

### 4.7 Grid layout

- **FR-33** The control_panel grid has a configurable column count (2–6, default 4); row height adapts to available width within fixed bounds. Tiles occupy `span_w × span_h` cells (each 1 or 2).
- **FR-34** An explicit edit-layout mode enables drag-and-drop repositioning with a visible drop-target highlight, and span changes via the tile context menu. Outside edit mode, tiles are static (no accidental drags).
- **FR-35** Layout changes normalize deterministically (overlaps resolved by pushing tiles down; out-of-range positions clamped; same input always yields the same layout) and are live-saved.
- **FR-36** Entry create/edit/remove is available from the control_panel header (Add Entry) and per-tile context menus. Removing an entry frees its cells without disturbing other tiles' coordinates.

### 4.8 Persistence and restore

- **FR-37** The control_panel library persists in the settings file under the libraries section; open control_panel tabs persist in the workspace layout (pane, position, active state) with per-tab state: control_panel id, bound endpoint hint, bound target title, and user-pause flag.
- **FR-38** On restart, open control_panel tabs are restored in their panes. Binding is re-established automatically only when the endpoint hint matches exactly one open terminal session; otherwise the tab restores unbound with an actionable bind menu.
- **FR-39** *(amended in v2 and v3)* Settings schema: v1 introduced v5 (files containing panels declare minimum-compatible 5; files without stay ≤ 4). v2 bumped the schema to v6 with a `CONTROL_PANEL_V2_SCHEMA_FLOOR = 6` applied only when any saved panel actually uses a v2 feature (poll mode ≠ interval, target override, derived source, control kind, any rule custom color, or CSV-log configuration). **v3 bumps the schema to v7** with a `CONTROL_PANEL_V3_SCHEMA_FLOOR = 7` applied only when any saved panel uses a v3 feature (setpoint tile kind, enum tile kind, any non-default `SetpointSpec`, or any non-empty `EnumSpec.options`). An untouched v1-shaped library keeps floor 5; a v2-shaped library keeps floor 6; only panels that actually use v3 widgets push to floor 7. Panel JSON exports stamp payload version 1/2/3 under the matching predicate, so older builds keep importing payloads they can fully represent.
- **FR-40** A restored control_panel tab whose config id no longer exists in the library is skipped with a footer notice (no crash, no placeholder tab).

### 4.9 Sidebar and favorites integration

- **FR-41** *(amended in v3)* The left drawer's activity rail has a **Control Panels** page listing every saved panel (name + entry count), with inline row actions matching commands/files: open (▶), star (favorite toggle), rename (pencil), delete (✕, confirmed), plus a matching right-click menu and double-click-to-open.
- **FR-42** *(amended in v3)* The Control Panels page header offers "+" (new panel) and an overflow menu with Manage…, Import JSON…, and Export JSON… (the same operations as the menu bar).
- **FR-43** *(amended in v3)* Control Panels carry a `favorite` flag (persisted with the config and included in JSON export). The Favorites page shows a third collapsible **Favorite Control Panels** panel beside favorite commands and files, sharing the same resizable splitter; its rows offer the same open/star/rename/delete actions.
- **FR-44** Sidebar lists refresh immediately after any library mutation, from any surface (tab rename, manager dialog, sidebar actions, import).
- **FR-45** The panel header's pause control always shows the action a click would take (pause icon while polling, play icon while paused, with matching tooltips), and all header controls give hover/pressed/checked visual feedback.

### 4.10 Value history, sparklines, and chart (v2)

- **FR-46** While its tab is open, each numeric entry (polled or derived) keeps a bounded in-memory history of (time, value) samples — at most 600 samples and at most 1 hour of age, whichever evicts first. History is runtime-only: it is never persisted, and it clears when the entry is edited or removed.
- **FR-47** Numeric value tiles paint an in-tile sparkline of the recent history (default window 120 s) behind/below the value, colored by the tile's current verdict (custom rule color when set, else the theme state color). Sparklines can be disabled per entry (`show_sparkline`, default on). Paint input is downsampled (min/max-preserving) so a full history never costs more than ~half the tile width in points.
- **FR-48** Double-clicking a numeric tile (outside edit-layout mode) or its context-menu "Open Chart…" opens a chart page inside the control_panel tab: value axis with rounded ticks, time axis, min/max/last readout, span presets (1/5/30/60 min), follow-live mode, and a hover crosshair showing the nearest sample's value and time. Back/Esc returns to the grid; deleting the entry closes the chart; the chart repaints only while visible (~10 Hz).

### 4.11 CSV value logging (v2)

- **FR-49** Each Control Panel can log parsed values to a CSV file. The toggle and file path persist in the panel config (so unattended capture survives restarts); a header button toggles logging and prompts for a path when none is set.
- **FR-50** *(amended in v3 — see also FR-76)* Rows are `timestamp,control_panel,entry_id,label,kind,value_text,value_number,state` (ISO milliseconds timestamp, UTF-8 with BOM). The header row is written only when the file is new/empty; reopening appends. Polled entries write `kind="poll"`; derived entries write `kind="derived"`; control sends write `kind="control"` (FR-77). Only completed results land — timeouts and send errors during polls are not value rows; control errors DO land (with `state="error"`) so the audit trail is honest. Pre-v3 logs (no `kind` column) read back without raising — `csv.DictReader` treats missing columns as missing keys.
- **FR-51** A write failure disables logging (config + toggle), reports via the footer status, and never interrupts polling or writes. No rotation is performed; the path is reused until changed.

### 4.12 Poll modes: run-once-on-connect and Poll Now (v2)

- **FR-52** Entry poll mode `on_connect`: the entry is polled once each time its target session transitions to connected (and once when it first resolves to an already-connected session — bind, restore-rebind, or override resolution). Multiple on_connect entries fire staggered. on_connect entries are exempt from staleness aging (their values are event-driven, not periodic).
- **FR-53** Every pollable entry's tile context menu offers "Poll Now": an immediate one-shot poll (suppressed while a transaction for that entry is already in flight). For interval entries the fixed-delay cycle continues from the manual poll's completion.

### 4.13 Per-entry session binding (v2)

- **FR-54** An entry may override the control_panel's binding with its own target endpoint ("" = control_panel default). Resolution follows FR-38 semantics: the override resolves only to a *unique* matching open terminal session; unresolved overrides leave the entry visibly stale/unsubmitted with the reason in its tooltip. The entry dialog lists open terminals plus the stored endpoint when it is not currently open (so editing never silently clears an override).
- **FR-55** Health gating is per target session: entries whose target is missing, disconnected, or running a command file are simply not submitted (they stay due and retry next tick); entries on healthy sessions are unaffected. When a gated session becomes healthy, its entries resume with staggered sends. Scheduler-level pause reasons reduce to `user` (manual pause, all entries) and `unbound` (nothing resolves at all).
- **FR-56** The binding chip aggregates: with no overrides it reads exactly as v1; with overrides it summarizes ("Polling COM7 · +2 targets") and its tooltip lists each endpoint with its state. Each target session gets its own shared, refcounted dispatcher with its own traffic journal (terminal transcript suppression works on every involved terminal), all released on tab close/unbind/edit-away (NFR-4).

### 4.14 Alerts (v2)

- **FR-57** An alert fires when an entry's state transitions *into* `fail` or `error` from any other state; the matching recovery transition is recorded silently. Timeouts and staleness never alert (a dead device must not generate notification storms — its first send error still alerts once). Repeated results in the same state do not re-fire.
- **FR-58** Alert surfaces: a header bell button with an unseen-count badge opening a bounded alert-history panel (200 records: time, entry, old→new state, value; Clear action; opening marks seen); a "● " prefix on the tab title while unseen alerts exist; a footer status line per alert; a taskbar attention request; and an optional sound (~debounced to ≥ 2 s). Per-entry opt-out via `alerts_enabled` (default on). Global Preferences toggles: master enable (default on) and sound (default off); master off suppresses records, badge, and sound entirely.

### 4.15 Control tiles (v2)

- **FR-59** Tile kind `control` sends instead of polling. Modes: `button` (one command per click) and `toggle` (ON/OFF commands; an optimistic local flag flips the visual on a successful send when no readback is set). With a readback configured, the toggle derives ON/OFF from the watched/queried **value**: a numeric reading is ON when non-zero (so a `0`/`1` status query like `OUTP?` reads correctly regardless of how its color rules map verdict states), a textual reading is ON for the usual truthy tokens (`on`/`1`/`true`/…), and only a value with no clear on/off signal falls back to the verdict state (`ok` = ON). When the reported state differs from the last commanded direction, the toggle adds a mismatch warning highlight (the device did not end up where the click asked). Optional per-tile confirmation shows the standard Yes/No prompt (default No) naming the command and target. Control entries are never scheduled, never stale, never alert, and keep no history.
- **FR-60** Control sends serialize through the same per-session FIFO dispatcher as polls (never interleaved with control_panel traffic on the wire) inside a traffic-journal window (device acks stay out of the terminal transcript). A click is refused with a status message when the target is unresolved, disconnected, or running a command file; clicks are allowed while polling is user-paused (an explicit click is explicit intent). The tile shows pending / success-flash / error feedback per send.

### 4.16 Derived/math tiles (v2)

- **FR-61** An entry with source `derived` computes its value from other entries via an arithmetic expression referencing them as `{Label}`. Expressions support + − × ÷ % ** , unary minus, numeric literals, and the functions abs/min/max/round/sqrt — nothing else (no comparisons, attributes, subscripts, or names outside references); inputs are capped (256 chars, 64 AST nodes) and evaluated without Python `eval`/code objects. References must resolve uniquely to *polled numeric* entries (single level — derived-of-derived is rejected; cycles are impossible by construction). Renaming a referenced entry rewrites referring expressions. The computed value flows through the standard pipeline: rules, colors, sparkline, chart, CSV, alerts. Missing inputs render neutral "—" with an explanatory tooltip; an input going stale makes the derived tile stale; evaluation errors (including division by zero) render the error state. Derived entries generate no serial traffic.

### 4.17 Per-rule custom colors (v2)

- **FR-62** A color rule may carry an explicit color (`#rrggbb`). When that rule matches, the custom color overrides the theme state color everywhere the verdict is rendered: value text, LED lamp and caption, sparkline stroke, and chart series. An empty color keeps the theme mapping. The entry dialog's rules table offers a color swatch (system color picker) with a clear-to-theme action; invalid color strings are dropped on load.

### 4.18 Numeric setpoint widget (v3)

- **FR-63** Tile kind `setpoint` is a writing tile that sends a single command derived from a user-chosen numeric value. Its `SetpointSpec` carries `min_value`, `max_value`, `step` (all floats), `decimals` (int, render precision), `unit` (display-only string, e.g. "V" / "°C"), `command_template` (string containing exactly one `{value}` placeholder, e.g. `"VOLT {value}"`), and `confirm` (per-tile confirmation toggle, same semantics as control tiles). Readback is shared across writing tiles through `ControlPanelEntry.readback`.
- **FR-64** The tile renders an editable `QDoubleSpinBox` (range = `min..max`, single-step = `step`, decimals = `decimals`) for the commanded value. There is no separate readback field: the spinbox itself *is* the readback display. When readback is configured, the latest readback value is reflected into the spinbox whenever the user is not actively editing it (see FR-66). A Send button (▶) submits exactly one command per click. Typing a value outside `[min, max]` clamps the field to the bound and flashes the input briefly so the user sees the clamp.
- **FR-65** The command is `command_template.replace("{value}", formatted)`, where `formatted = f"{value:.{decimals}g}"`. Validation at edit time and configure time: `min < max`; `step > 0`; `step <= max - min`; `command_template` contains exactly one `{value}`; in Hex Bytes mode the templated command with a sample value passes the existing hex-payload validator. Validation failures gate the editor dialog's OK and, for configure-time failures (e.g. a stale config), render an error tile.
- **FR-66** Writing-tile readback uses `ReadbackSpec`: `source="entry"` follows another polled tile, while `source="command"` sends a direct readback command with its own parse/rule configuration. Default behavior is `mode="once"`, `delay_ms=20`: after a write succeeds, the readback transaction is sent next on the same dispatcher FIFO when it targets the same session. `mode="interval"` schedules further readbacks every `interval_ms` after each readback completes. **Readback reflects into the tile's own input control, not a separate area:** every readback value is written back into the spinbox (setpoint), the dropdown selection (enum), or the ON/OFF state (toggle) — *except while the user is actively editing that control* (the setpoint spinbox has focus and has been typed into / stepped; the enum dropdown is open or focused). **Mismatch warning:** the tile records the value it last commanded (on Send). When a later readback differs from that commanded value (compared at the setpoint's display precision, by matched enum option, or by ON/OFF state), the input control shows a warning color — e.g. a user commands 100 V, the device clamps to 60, the spinbox snaps to 60 in amber to show the command was not accepted. The warning clears when a readback matches the commanded value or the user edits/sends again. With no command issued (pure monitoring), readback reflects with no warning.
- **FR-67** All writing tiles with readback configured pull it once when their target session connects, including the initial bind to an already-connected session. For setpoint tiles, that connect-time readback seeds the editable commanded-value field without sending a set command; later post-write and interval readbacks keep reflecting into that same field (FR-66) whenever the user is not editing it. Setpoint tiles never participate in the normal poll scheduler, never alert, keep no history, and never appear in derived expressions; only their readback transactions may query the device.

### 4.19 Enum / dropdown selector widget (v3)

- **FR-68** Tile kind `enum` is a writing tile that sends one of N labeled commands chosen from a dropdown. Its `EnumSpec` carries `options: list[EnumOption]` (each option: `label`, `command`, optional `match_value`) and `confirm`. At least one option is required.
- **FR-69** The tile renders a `QComboBox` (full width) plus a Send button (▶). The user picks an option from the dropdown; clicking Send submits exactly the chosen option's `command`. Each click is one send, even on rapid clicks (de-bounced through the pending-state mechanism shared with control toggles).
- **FR-70** When readback is configured, the funnel compares the readback value text (trimmed, case-insensitive) against each option's `match_value`; the first match drives the combo's selection (FR-66) so the dropdown reflects the device's reported option — except while the user is actively choosing (the dropdown is open or focused), so an in-progress selection is never yanked away. If the reflected option differs from the option the user last sent, the combo shows a mismatch warning color. When no `match_value` matches (or no readback is set), the selection is left as-is and no warning is shown.
- **FR-71** Editor validation: at least one option; each option needs non-empty `label` AND non-empty `command`; `match_value` is optional; in Hex Bytes mode each `command` passes the hex-payload validator. Duplicate labels render but the dialog shows a warning (operators sometimes want two paths to the same outcome). Enum tiles never poll, never alert, keep no history.

### 4.20 Master arm safety gate (v3)

- **FR-72** Every Control Panel maintains a transient `armed` state. The default is **Disarmed** at every load: panel construction, tab restore, app launch, and after any unbind / target-session close. The state never persists to settings.
- **FR-73** While Disarmed, every writing tile (control button, control toggle, setpoint, enum) refuses to send. Each tile renders disarmed visuals (muted setpoint input, muted combo border, disabled Send button with tooltip explaining the state). Click attempts on disarmed tiles produce a single clear status message ("<entry label>: panel is disarmed") — no chain of refusal messages.
- **FR-74** Arming is explicit: the panel header carries an Arm/Disarm button (lock icon when disarmed, unlock icon when armed; accent-amber and accent-red surface colors respectively). Clicking Arm flips the state to Armed and emits an `armingChanged` signal that every writing tile observes to re-render. **Per-tile `confirm` is NOT bypassed by arming** — arming just opens the gate; per-tile confirmation still fires.
- **FR-75** Esc on the focused Control Panel disarms instantly with a status notify. The Esc shortcut is scoped to the grid widget so it does not collide with the chart page's existing back/close behavior (chart's Esc closes the chart first; grid-level Esc only fires when the grid is the visible page). Auto-disarm also fires on: unbind from the default session, default session's terminal tab closing, `apply_imported_settings`, panel `shutdown`. Each path produces one status message naming the trigger.

### 4.21 Audit CSV — kind column + control rows (v3)

- **FR-76** The CSV value log adds a `kind` column at fixed position (between `label` and `value_text`) with values `"poll"`, `"derived"`, or `"control"`. The column is written for every row in v3 builds; pre-v3 logs that lack it read back without error. The complete header is `timestamp,control_panel,entry_id,label,kind,value_text,value_number,state` — see FR-50.
- **FR-77** Control sends append exactly one row per `ControlResult` (success or send error). The row uses: `kind="control"`; `value_text` = the post-template-substitution command actually sent (e.g. `"VOLT 12.50"`); `value_number` = empty; `state` = `"ok"` on success, `"error"` on send failure. Confirmation cancellations (user picks No) do NOT log — only sends that left the queue are auditable. The hook lives in `_handle_control_result`, so all writing tiles share it.

## 5. Non-functional requirements

- **NFR-1 (GUI responsiveness)** No serial/LAN I/O ever executes on the GUI thread. ControlPanel sends happen exclusively on a per-session dispatcher thread. The GUI tick (drain results, health check, schedule) completes in < 1 ms typically and < 5 ms with 64 entries (smoke-tested).
- **NFR-2 (Timing accuracy)** Poll intervals are honored within ±1 scheduler tick (100 ms) plus device response time. This is the documented contract on Windows (coarse timer resolution); no busy-waiting anywhere.
- **NFR-3 (Bounded memory)** *(amended in v2)* All runtime buffers are bounded: RX correlation window ≤ 4096 chars (tail-kept), dispatcher request queue ≤ 64, idle RX continuously drained and discarded, per-entry history ≤ 600 samples / 1 hour, alert history ≤ 200 records. A chatty device cannot grow control_panel memory without bound. No runtime values, RX transcripts, or history are written to the settings file (CSV logging is the explicit durable record).
- **NFR-4 (Resource lifecycle)** Closing a control_panel tab, closing the bound terminal, applying imported settings, and quitting the app all stop dispatcher threads (join ≤ 1.5 s) and unsubscribe event queues. Tests assert no `control_panel-dispatch` threads survive teardown.
- **NFR-5 (Isolation)** A misbehaving entry (catastrophic regex, slow device) can stall at most its own session's polling — never the GUI and never other sessions. Regex input is bounded by NFR-3; patterns are validated and smoke-run at edit time.
- **NFR-6 (Theming)** *(amended in v2)* All control_panel colors derive from the active `ThemePalette` (semantic state → palette mapping in one place) and spacing/sizing from `ui/tokens.py`. All 6 built-in themes render distinct ok/warn/fail/stale states. No hardcoded color literals outside `themes.py` — user-chosen rule colors (FR-62) are runtime data, not source literals, and fall back to the theme when unset.
- **NFR-7 (Qt-free domain)** ControlPanel models, parsing, rules, scheduling, and catalog logic are Qt-free, re-exported through `core/`, and enforced by the existing `tests/test_core_no_pyside.py` isolation check.
- **NFR-8 (Compatibility)** Existing behavior is unchanged for users who never open a control_panel: schema migration is additive, terminal/editor flows untouched, settings min-compat rules per FR-39.
- **NFR-9 (Testability)** Scheduler and parse logic are deterministic under an injected clock (no real sleeps in unit tests); dispatcher logic is testable threadless via a factored transaction method; integration tests run against `FakeSerialTransport`.
- **NFR-10 (Documentation)** All new public APIs carry docstrings; `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, and `docs/LLM_CHANGE_GUIDE.md` gain control_panel sections (ownership, invariants, change recipes); README and CHANGELOG updated.
- **NFR-11 (Expression safety, v2)** Derived-tile expressions are parsed to an AST and evaluated by a whitelisting interpreter — no `eval`, `exec`, or compiled code objects; node and length caps bound work; every failure surfaces as an error tile, never as an exception escaping the GUI tick.
- **NFR-12 (v2 tick budget)** The GUI tick stays under the v1 budget with v2 load: 64 entries including derived tiles, full histories, alerts enabled, and two target sessions average < 5 ms per tick (benchmarked). Sparkline repaints are coalesced (≤ 1 per tile per result + 1 Hz window slide); the chart repaints only while visible.
- **NFR-13 (Sound robustness, v2)** Alert sound degrades gracefully: missing QtMultimedia or a missing wav asset falls back to the system beep; sound failures never affect alert records or polling.
- **NFR-14 (v3 tick budget)** The GUI tick stays under the v2 budget with v3 load: the v2 reference mix (64 entries incl. derived + full histories + alerts + 2 sessions) plus 6 setpoint tiles and 6 enum tiles with active readbacks averages < 5 ms per tick (benchmarked). Writing tiles repaint only when their state or readback value changes; the master-arm visual broadcast fires only on Arm/Disarm transitions, not per tick.
- **NFR-15 (Master-arm robustness, v3)** Master arm state is transient. Tests assert: every panel construction starts Disarmed; every restart starts Disarmed; auto-disarm on unbind / session close / `apply_imported_settings` / `shutdown`; the `armingChanged` signal reaches every writing tile in the panel.

## 6. Out of scope (v3)

Carried forward from earlier versions and confirmed for v3:

- CLI access to Control Panels.
- Control Panels owning their own serial/LAN connection (binding to terminal sessions remains the only transport path).
- Persisted value history (history is runtime-only; CSV logging is the durable record).
- Chart image/data export, multi-series or multi-axis charts.
- Alert acknowledgement workflows beyond the history panel's Clear; per-entry alert sounds or custom sound files.
- Derived-of-derived expressions (single level is locked).
- Scripting or conditional automation driven by Control Panel values.

Explicitly considered for v3 and **declined for this release**:

- **Interlocks** ("Tile X can only send if Tile Y's state is OK") — recognized as the next natural step but adds rule engine surface; revisit in v3.1+.
- **Role-based access with PIN** (Viewer / Operator / Engineer) — master arm covers the safety floor without the auth complexity.
- **Momentary / deadman button** (send ON on press, OFF on release) — useful but requires a different keyboard/touch model; revisit when there's a concrete user need.
- **Sequence / macro tile** (one click runs a series of commands with optional waits) — overlaps with the existing command-file editor; cleaner to keep that as the sequence surface and let panels invoke command files instead, if requested.
- **In-app control history view** beyond the CSV row — the CSV is the audit record; loading it into a panel widget can come later if asked.
- **Multi-step undo of a sent command** — sends are not reversible at the protocol level; pretending they are would mislead operators.

## 7. Accepted limitations (shared medium)

The bound session is a shared, unframed byte stream. While a poll transaction's RX window is open, traffic from other sources (user-typed commands, device echo, unsolicited async output) can satisfy or pollute an entry's parse rule. Mitigations: stale RX is drained before each send; the window exists only during a transaction; polls are serialized so at most one entry can mis-attribute per foreign event; the entry editor encourages anchored patterns and provides a live tester; the tile tooltip exposes the raw RX window for diagnosis. This limitation is inherent to decision 1 and is documented to users.

The transcript filter (FR-15) has the mirrored limitation: device output that happens to arrive *during* a poll window is treated as poll traffic and kept out of the terminal display (it still reaches the session log). With typical poll timeouts of a few hundred milliseconds this affects only chatty devices that emit unsolicited output continuously.

v2 additions to the accepted-limitations list:

- **Multi-session summaries.** A single chip cannot fully represent three sessions' states; the aggregate text plus per-endpoint tooltip lines (FR-56) and per-tile tooltips are the contract. Gated entries simply age to stale — no synthetic per-entry "paused" state is invented.
- **Control click vs. batch start race.** The click-time gate refuses sends while a command file runs (FR-60), but a batch started after a control request was queued can still interleave on the wire — the same tick-granular window v1 accepted for polling. Panel-vs-panel serialization remains absolute (one FIFO per session).

v3 additions to the accepted-limitations list:

- **Audit-log gap on crash.** Control rows are written when the result lands (FR-77); a process crash between queue and result leaves no row for that send. The CSV captures what completed, not what was attempted. Pre-write at submit time was considered and declined — it would either require a two-row scheme (more complex) or in-place file edits (loses crash safety).
- **Master arm covers writing tiles only.** A misconfigured *polled* entry (e.g. a poll command that has side effects on a device — `OUTP 0` masquerading as a query) is not gated by arming because the polling subsystem doesn't know it's a write. The remedy is to model side-effect commands as control tiles. The requirements doc warns against this in the editor copy.
- **Readback latency.** Readback that follows another tile mirrors that tile's most recent value and may lag by up to one poll interval plus the transport round-trip. Direct command readback runs immediately after writes by default, but it still reflects what the device reports, not a closed-loop guarantee.

## 8. Acceptance criteria → test mapping

| Requirement(s) | Proving test module |
| --- | --- |
| FR-18, FR-19, FR-33, FR-35 (model validity, clamping, layout math) | `tests/test_control_panel_models.py` |
| FR-24–FR-28 (parse kinds, window, number errors), FR-29, FR-30 (rule semantics) | `tests/test_control_panel_parse.py` |
| FR-20, FR-21, FR-23 (fixed-delay, serialization, send-error), NFR-3 (bounded queues/window), NFR-9 (injected clock) | `tests/test_control_panel_engine.py` |
| FR-1–FR-3 (catalog CRUD, dedupe, import/export), FR-37, FR-39 (schema v5, min-compat matrix) | `tests/test_control_panel_catalog.py`, `tests/test_models_and_storage.py` |
| FR-10 (targets incl. disconnected), FR-13/FR-17 partial (dispatcher refcount), FR-14 (batch detection) | `tests/test_control_panel_targets.py` |
| FR-31, FR-34, FR-35 (tile rendering, spans, drag), NFR-6 (theme matrix) | `tests/test_control_panel_tiles.py` |
| FR-11, FR-12, FR-16, FR-22, FR-27, FR-32 (tick loop, pause reasons, staleness), FR-28 (dialog validation/tester) | `tests/test_control_panel_tab.py` |
| FR-2, FR-4 (manager flows) | `tests/test_control_panel_manager.py` |
| FR-5–FR-8 (menus, palette, context menus, tab plumbing) | `tests/test_command_registry.py`, `tests/test_main_window_menus.py`, `tests/test_tab_context_menus.py`, `tests/test_command_palette_entries.py`, `tests/test_tab_workspace.py`, `tests/test_workspace_status.py` |
| FR-37, FR-38, FR-40 (capture/restore/rebind) | `tests/test_workspace_state.py`, `tests/test_app_control_panels.py` |
| FR-9, FR-15, FR-17, NFR-1 (tick budget), NFR-4 (thread lifecycle) end-to-end | `tests/test_app_control_panels.py` |
| FR-15 (journal windows, TX tagging, terminal filter) | `tests/test_control_panel_engine.py`, `tests/test_control_panel_targets.py`, `tests/test_app_control_panels.py` |
| FR-41..FR-44 (sidebar page, favorites panel, list refresh) | `tests/test_control_panel_sidebar.py`, `tests/test_app_control_panels.py` |
| FR-45 (pause control state, save indicator) | `tests/test_control_panel_tab.py` |
| FR-46 (history bounds), FR-47 partial (downsampling), FR-48 partial (ticks/nearest-sample math) | `tests/test_control_panel_history.py` |
| FR-47 (sparkline presence/coalescing/theming) | `tests/test_control_panel_tiles.py` |
| FR-48 (chart page open/close, spans, readout, follow-live) | `tests/test_control_panel_chart.py`, `tests/test_control_panel_tab.py` |
| FR-49..FR-51 (CSV schema, header-once, append, error path, persistence) | `tests/test_control_panel_value_log.py`, `tests/test_control_panel_tab.py` |
| FR-52, FR-53 (on_connect scheduling, connect-edge triggers, Poll Now) | `tests/test_control_panel_engine.py`, `tests/test_control_panel_tab.py` |
| FR-54..FR-56 (per-entry targets, gating, chip aggregation, multi-dispatcher lifecycle) | `tests/test_control_panel_tab.py`, `tests/test_control_panel_targets.py`, `tests/test_app_control_panels.py` |
| FR-57, FR-58 (alert edges, surfaces, preferences) | `tests/test_control_panel_alerts.py`, `tests/test_control_panel_tab.py`, `tests/test_models_and_storage.py` |
| FR-59, FR-60 (control tiles, FIFO serialization, gating, confirm) | `tests/test_control_panel_engine.py`, `tests/test_control_panel_tiles.py`, `tests/test_control_panel_tab.py` |
| FR-61 (expressions: safety, resolution, recompute, staleness) | `tests/test_control_panel_expr.py`, `tests/test_control_panel_tab.py` |
| FR-62 (custom colors plumbing + rendering) | `tests/test_control_panel_parse.py`, `tests/test_control_panel_tiles.py` |
| FR-39 v2 (schema v6 floor matrix, export version stamping) | `tests/test_models_and_storage.py`, `tests/test_control_panel_catalog.py` |
| FR-39 v3 (schema v7 floor matrix, export version 3 stamping, sparse v1/v2 floor preservation) | `tests/test_models_and_storage.py`, `tests/test_control_panel_catalog.py`, `tests/test_control_panel_models.py` |
| FR-63..FR-67 (setpoint model + widget + readback + send + validation) | `tests/test_control_panel_models.py`, `tests/test_control_panel_tiles.py`, `tests/test_control_panel_tab.py` |
| FR-68..FR-71 (enum model + widget + indicator + send + validation) | `tests/test_control_panel_models.py`, `tests/test_control_panel_tiles.py`, `tests/test_control_panel_tab.py` |
| FR-72..FR-75 (master arm gate, Esc disarm, auto-disarm matrix, visual broadcast, transience) | `tests/test_control_panel_tab.py` |
| FR-76, FR-77 (CSV kind column, control rows, pre-v3 read-back compat) | `tests/test_control_panel_value_log.py`, `tests/test_control_panel_tab.py` |
| FR-50 v3 (audit row format, error rows for control, no row for confirm-cancel) | `tests/test_control_panel_value_log.py`, `tests/test_control_panel_tab.py` |
| NFR-7 (Qt-free domain incl. v2 modules) | `tests/test_core_no_pyside.py` |
| NFR-11 (expression safety rejection matrix) | `tests/test_control_panel_expr.py` |
| NFR-12 (v2 tick budget) | `tests/test_app_control_panels.py` |
| NFR-14 (v3 tick budget with 6 setpoint + 6 enum + readbacks) | `tests/test_app_control_panels.py` |
| NFR-15 (master arm transience: boot-disarmed, auto-disarm matrix, signal coverage) | `tests/test_control_panel_tab.py`, `tests/test_app_control_panels.py` |

## 9. References

- Binding precedent: `src/ComPort_Zone/command_run_targets.py`, `src/ComPort_Zone/ui/command_file_targets.py`
- RX fan-out: `SerialClient.subscribe_events` (`src/ComPort_Zone/serial_core.py`)
- Correlation idiom: `BatchRunner._expect_text` (`src/ComPort_Zone/batch.py`)
- Settings schema: `src/ComPort_Zone/models.py`, `src/ComPort_Zone/settings_service.py`
- Logging precedents: `src/ComPort_Zone/session_log.py`, CSV writer in `src/ComPort_Zone/quick_actions.py`
- Implementation plans: v1 (T1–T12), v2 (V2-T1–T14), and v3 (V3-T1–T8) — all approved.
- v3 widget precedents: `QDoubleSpinBox` is already used by control-panel configuration fields; `QComboBox` is widely used (line-ending menus, theme combos, etc.); `QShortcut` precedent in command-editor search.

## 10. Naming migration (v3)

| Surface | v2 wording | v3 wording |
| --- | --- | --- |
| Tab kind | "ControlPanel" | "Control Panel" |
| Tab title | user-chosen | user-chosen (unchanged) |
| Menu: File > New | "New ControlPanel" | "New Control Panel" |
| Menu: File > Open submenu | "Open ControlPanel" | "Open Control Panel" |
| Menu: Tools | "ControlPanels…" | "Control Panels…" |
| Keyboard shortcut | `Ctrl+Shift+D` | `Ctrl+Shift+D` (unchanged, muscle memory) |
| Sidebar rail page | "ControlPanels" | "Control Panels" |
| Favorites panel | "Favorite ControlPanels" | "Favorite Control Panels" |
| Manager dialog title | "ControlPanels" | "Control Panels" |
| Shipped example name | "Example ControlPanel" | "Example Control Panel" |
| Requirements doc | `docs/control_panel-view-requirements.md` | `docs/control-panel-requirements.md` |
| Settings JSON key | `"control_panels": [...]` | `"control_panels": [...]` (unchanged) |
| Python class `ControlPanelConfig` | unchanged | unchanged |
| Python class `ControlPanelTabWidget` | unchanged | unchanged |
| Settings field `AppSettings.control_panels` | unchanged | unchanged |
| Module `control_panel_value_log.py` | unchanged | unchanged |
| Tests under `tests/test_control_panel_*.py` | unchanged | unchanged |
| QSS selectors `#controlPanelHeader`, `#controlPanelBindChip`, ... | unchanged | unchanged |

Pre-v3 user JSON loads byte-for-byte; pre-v3 CSV logs (no `kind` column) read back without raising; v1/v2 exports import unchanged.
