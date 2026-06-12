# Dashboard View — Feature Requirements

Status: Approved for implementation
Version: 2.0
Date: 2026-06-11
Applies to: ComPort Zone >= 0.5.0 (v1: settings schema v5; v2 features: schema v6)

v2.0 adds: value history with in-tile sparklines and a chart page, CSV value
logging, run-once-on-connect polling with a Poll Now action, per-entry session
binding (multi-device dashboards), alerts on FAIL/ERROR, control tiles,
derived/math tiles, and per-rule custom colors (FR-46..FR-62). v1 requirements
are amended in place where v2 changes them; each amendment is marked.

## 1. Purpose

ComPort Zone users monitor live device values (voltages, temperatures, counters, fault flags) by manually re-sending the same commands in a terminal. The Dashboard View automates this: a dashboard is a named collection of *entries*, each entry a command that is sent automatically in the background at its own interval over an existing terminal session's connection. The response is parsed and rendered in a tile whose color/indicator reflects configurable rules. Dashboards are managed as a library, opened as workspace tabs, arranged with drag-and-drop, and restored across application restarts.

This document is the requirements contract for the feature. The companion implementation plan defines module design; `docs/ARCHITECTURE.md` and `docs/DESIGN.md` describe where the subsystem lands.

## 2. Definitions

| Term | Meaning |
| --- | --- |
| Dashboard (config) | A named, persisted collection of entries plus grid settings (`DashboardConfig`). Lives in the dashboard library in settings. |
| Dashboard tab | An open workspace tab rendering one dashboard config (third tab type, beside terminal tabs and command-file editor tabs). |
| Entry | One polled command with its schedule, parse rule, display rules, and tile placement (`DashboardEntry`). |
| Tile | The visual representation of one entry on the dashboard grid (value tile or LED tile). |
| Binding | The association between a dashboard tab and one open terminal session whose connection is used for polling. *(v2)* An entry may override the dashboard binding with its own target session (FR-54). |
| Poll transaction | One send→collect→parse cycle for one entry: drain stale RX, transmit the command, accumulate RX until the parse rule matches or the timeout elapses. |
| Pause reason | *(amended in v2)* Scheduler-level reasons are `user` and `unbound`; connection/batch conditions gate entries per target session at submit time (FR-55), so one unhealthy device pauses only its own entries. |
| Poll mode *(v2)* | `interval` (fixed-delay periodic) or `on_connect` (fires once per target-session connect edge; FR-52). |
| History *(v2)* | The bounded, in-memory ring of (time, numeric value) samples kept per entry while its tab is open; never persisted (FR-46). |
| Control tile *(v2)* | A tile that sends a command on click instead of polling (FR-59). |
| Derived entry *(v2)* | An entry whose value is computed from other entries via a safe arithmetic expression instead of polling (FR-61). |
| Alert *(v2)* | A record created when an entry's state transitions into `fail` or `error` (FR-57). |

## 3. Locked product decisions

Decided with the product owner; v1 decisions stand except where amended:

1. **Bind to a terminal session.** A dashboard never owns a serial/LAN connection. It binds to an existing terminal tab's session (the same targeting concept as the command-file editor's Run button). Polling pauses while the bound session is disconnected and resumes automatically on reconnect. Poll traffic shares the session's connection but is hidden from the terminal's transcript (FR-15) — continuous polling would otherwise flood the terminal and make manual use impossible. *(v2 amendment: an entry may target a different open terminal session than the dashboard default — FR-54 — but binding to terminal sessions remains the only transport path; dashboards still never open ports.)*
2. **Tile types.** *(v2 supersedes the v1 restriction)* Value tiles, LED/status indicators, and control tiles; numeric value tiles may show an in-tile sparkline and open a large chart page. All charting is custom-painted (QPainter) — no plotting dependency.
3. **Layout: uniform grid with drag-to-reposition and per-tile spans** (1x1, 2x1, 1x2, 2x2). Layout persistence is deterministic.
4. **Multi-dashboard via named library + tabs.** Dashboards are named saved configurations with JSON import/export. Opening a dashboard creates a workspace tab; open tabs are restored on restart.
5. **No new dependencies for v2.** Charts/sparklines via QPainter; alert sound via QtMultimedia (already in the PySide6 wheel) with a `QApplication.beep()` fallback.

## 4. Functional requirements

### 4.1 Dashboard library (catalog)

- **FR-1** The app maintains a persistent library of named dashboard configs in the settings file. Create, rename, duplicate, and delete are available from a Dashboard Manager dialog and from dashboard tab menus.
- **FR-2** Dashboard names are unique; creating or importing a duplicate name auto-suffixes (e.g. `PSU Bench (2)`), mirroring quick-command behavior.
- **FR-3** Dashboards can be exported to and imported from JSON files (single or multiple dashboards per file, versioned payload `{"comport_zone_dashboards": 1, "dashboards": [...]}`). Import offers merge semantics: colliding ids are regenerated; name collisions are renamed (default) or replaced (explicit option).
- **FR-4** Deleting a dashboard that is currently open closes its tab (after the same confirmation as the manager delete action).

### 4.2 Workspace integration

- **FR-5** Opening a dashboard creates a dashboard tab in the active pane. Dashboard tabs coexist with terminal and editor tabs: they can be reordered, moved between split panes, closed, and listed in the command palette's tab switcher.
- **FR-6** Opening a dashboard that is already open focuses the existing tab instead of creating a second one. One config is never editable from two tabs simultaneously.
- **FR-7** Entry points: File → New Dashboard; File → Open Dashboard → (list of saved dashboards); Tools → Dashboards… (manager, shortcut `Ctrl+Shift+D`); the tab strip's "+" menu; the command palette (`New Dashboard`, `Dashboards…`).
- **FR-8** A dashboard tab shows its name as the tab title, a status summary in the footer (entry count, binding, paused/warn state), and a dashboard-specific context menu on the tab (rename, bind submenu, pause/resume, edit layout, split/move, close) — not the terminal tab menu.
- **FR-9** Edits to a dashboard (entries, layout, rename, columns) are saved to the library immediately (live-save, like quick commands). There is no dirty/unsaved state and no confirm-on-close prompt. The dashboard header carries a save indicator ("Saved HH:MM:SS") that refreshes on every persisted change, so the auto-save is visible while editing.

### 4.3 Binding and connection lifecycle

- **FR-10** A dashboard tab can bind to any *open* terminal session, including a currently disconnected one (polling stays paused with reason `connection` until it connects). The bind menu lists all open terminal tabs with their endpoint and connection state.
- **FR-11** While bound and connected, polling runs automatically unless paused by the user. A visible chip on the dashboard header shows the binding and its state: polling / paused (with reason) / unbound.
- **FR-12** *(amended in v2)* When a target session disconnects, the entries targeting it stop being submitted within one tick and their tiles age toward stale; on reconnect (including auto-reconnect), those entries resume automatically with staggered first sends. Entries targeting other, healthy sessions are unaffected (FR-55).
- **FR-13** When a target terminal tab is closed, its entries stop (the dashboard unbinds when the default target closes, showing the one-click bind menu) and all per-session resources for that session are released (no orphan threads or event subscriptions).
- **FR-14** *(amended in v2)* While a command-file (batch) run is active on a target session, polling of the entries targeting that session suspends automatically and resumes when the run finishes; other sessions' entries are unaffected.
- **FR-15** Dashboard poll traffic is hidden from the bound terminal's transcript: poll TX events carry a `source="dashboard"` tag, and RX received inside a poll-transaction window (tracked by a per-session traffic journal, with a short grace tail for late fragments) is not rendered. The traffic still flows through the session log and every event subscriber unchanged; manually typed commands and out-of-window device output render normally. Tile tooltips remain the diagnostic surface for raw poll RX.
- **FR-16** A user-initiated pause/resume toggle exists per dashboard tab; the user-pause state persists across restarts.
- **FR-17** Multiple dashboard tabs may bind to the same session. Their poll transactions are serialized on that session (never interleaved on the wire) and share one dispatcher; closing one dashboard does not disturb the other.

### 4.4 Entries: commands and scheduling

- **FR-18** *(amended in v2)* Each entry defines: label, optional unit, command payload, send mode (`Text` or `Hex Bytes`), optional line-ending override (None/CR/LF/CRLF; default = session profile), poll interval (ms), response timeout (ms), staleness threshold (ms, 0 = automatic), parse rule, ordered color rules, tile kind, tile placement/span, and enabled flag. v2 adds: poll mode (FR-52), target-session override (FR-54), source + expression for derived entries (FR-61), control configuration (FR-59), sparkline visibility (FR-47), and per-entry alert opt-out (FR-58). All v2 fields serialize sparsely: an entry using no v2 feature persists byte-identical to its v1 shape.
- **FR-19** Poll interval has a floor of 100 ms; timeout range 50–30000 ms. Values outside ranges are clamped on load and rejected with messages in the editor dialog.
- **FR-20** *(amended in v2)* For `interval` entries, scheduling is fixed-delay: the next poll is scheduled `interval` after the previous transaction *completes* (success or timeout). A slow device therefore degrades the effective rate instead of building a backlog; at most one transaction per entry is outstanding at any time. `on_connect` entries are never time-due (FR-52); Poll Now (FR-53) arms an immediate poll for either mode.
- **FR-21** Poll transactions on one session execute strictly one at a time, FIFO across all entries and all dashboards bound to that session.
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

- **FR-33** The dashboard grid has a configurable column count (2–6, default 4); row height adapts to available width within fixed bounds. Tiles occupy `span_w × span_h` cells (each 1 or 2).
- **FR-34** An explicit edit-layout mode enables drag-and-drop repositioning with a visible drop-target highlight, and span changes via the tile context menu. Outside edit mode, tiles are static (no accidental drags).
- **FR-35** Layout changes normalize deterministically (overlaps resolved by pushing tiles down; out-of-range positions clamped; same input always yields the same layout) and are live-saved.
- **FR-36** Entry create/edit/remove is available from the dashboard header (Add Entry) and per-tile context menus. Removing an entry frees its cells without disturbing other tiles' coordinates.

### 4.8 Persistence and restore

- **FR-37** The dashboard library persists in the settings file under the libraries section; open dashboard tabs persist in the workspace layout (pane, position, active state) with per-tab state: dashboard id, bound endpoint hint, bound target title, and user-pause flag.
- **FR-38** On restart, open dashboard tabs are restored in their panes. Binding is re-established automatically only when the endpoint hint matches exactly one open terminal session; otherwise the tab restores unbound with an actionable bind menu.
- **FR-39** *(amended in v2)* Settings schema: v1 introduced v5 (files containing dashboards declare minimum-compatible 5; files without stay ≤ 4). v2 bumps the schema to v6 with a `DASHBOARD_V2_SCHEMA_FLOOR = 6` applied only when any saved dashboard actually uses a v2 feature (poll mode ≠ interval, target override, derived source, control kind, any rule custom color, or CSV-log configuration) — an untouched v1-shaped library keeps floor 5 and remains readable by v1 builds. Dashboard JSON exports stamp payload version 2 only under the same predicate, so v1-shaped exports stay importable by v1 builds.
- **FR-40** A restored dashboard tab whose config id no longer exists in the library is skipped with a footer notice (no crash, no placeholder tab).

### 4.9 Sidebar and favorites integration

- **FR-41** The left drawer's activity rail gains a **Dashboards** page listing every saved dashboard (name + entry count), with inline row actions matching commands/files: open (▶), star (favorite toggle), rename (pencil), delete (✕, confirmed), plus a matching right-click menu and double-click-to-open.
- **FR-42** The Dashboards page header offers "+" (new dashboard) and an overflow menu with Manage…, Import JSON…, and Export JSON… (the same operations as the menu bar).
- **FR-43** Dashboards carry a `favorite` flag (persisted with the config and included in JSON export). The Favorites page shows a third collapsible **Favorite Dashboards** panel beside favorite commands and files, sharing the same resizable splitter; its rows offer the same open/star/rename/delete actions.
- **FR-44** Sidebar lists refresh immediately after any library mutation, from any surface (tab rename, manager dialog, sidebar actions, import).
- **FR-45** The dashboard header's pause control always shows the action a click would take (pause icon while polling, play icon while paused, with matching tooltips), and all header controls give hover/pressed/checked visual feedback.

### 4.10 Value history, sparklines, and chart (v2)

- **FR-46** While its tab is open, each numeric entry (polled or derived) keeps a bounded in-memory history of (time, value) samples — at most 600 samples and at most 1 hour of age, whichever evicts first. History is runtime-only: it is never persisted, and it clears when the entry is edited or removed.
- **FR-47** Numeric value tiles paint an in-tile sparkline of the recent history (default window 120 s) behind/below the value, colored by the tile's current verdict (custom rule color when set, else the theme state color). Sparklines can be disabled per entry (`show_sparkline`, default on). Paint input is downsampled (min/max-preserving) so a full history never costs more than ~half the tile width in points.
- **FR-48** Double-clicking a numeric tile (outside edit-layout mode) or its context-menu "Open Chart…" opens a chart page inside the dashboard tab: value axis with rounded ticks, time axis, min/max/last readout, span presets (1/5/30/60 min), follow-live mode, and a hover crosshair showing the nearest sample's value and time. Back/Esc returns to the grid; deleting the entry closes the chart; the chart repaints only while visible (~10 Hz).

### 4.11 CSV value logging (v2)

- **FR-49** Each dashboard can log parsed values to a CSV file. The toggle and file path persist in the dashboard config (so unattended capture survives restarts); a header button toggles logging and prompts for a path when none is set.
- **FR-50** Rows are `timestamp,entry_id,label,value_text,value_number,state` (ISO milliseconds timestamp, UTF-8 with BOM). The header row is written only when the file is new/empty; reopening appends. Only successful parses are logged (timeouts/send errors are not values); derived entries log like polled ones.
- **FR-51** A write failure disables logging (config + toggle), reports via the footer status, and never interrupts polling. No rotation is performed; the path is reused until changed.

### 4.12 Poll modes: run-once-on-connect and Poll Now (v2)

- **FR-52** Entry poll mode `on_connect`: the entry is polled once each time its target session transitions to connected (and once when it first resolves to an already-connected session — bind, restore-rebind, or override resolution). Multiple on_connect entries fire staggered. on_connect entries are exempt from staleness aging (their values are event-driven, not periodic).
- **FR-53** Every pollable entry's tile context menu offers "Poll Now": an immediate one-shot poll (suppressed while a transaction for that entry is already in flight). For interval entries the fixed-delay cycle continues from the manual poll's completion.

### 4.13 Per-entry session binding (v2)

- **FR-54** An entry may override the dashboard's binding with its own target endpoint ("" = dashboard default). Resolution follows FR-38 semantics: the override resolves only to a *unique* matching open terminal session; unresolved overrides leave the entry visibly stale/unsubmitted with the reason in its tooltip. The entry dialog lists open terminals plus the stored endpoint when it is not currently open (so editing never silently clears an override).
- **FR-55** Health gating is per target session: entries whose target is missing, disconnected, or running a command file are simply not submitted (they stay due and retry next tick); entries on healthy sessions are unaffected. When a gated session becomes healthy, its entries resume with staggered sends. Scheduler-level pause reasons reduce to `user` (manual pause, all entries) and `unbound` (nothing resolves at all).
- **FR-56** The binding chip aggregates: with no overrides it reads exactly as v1; with overrides it summarizes ("Polling COM7 · +2 targets") and its tooltip lists each endpoint with its state. Each target session gets its own shared, refcounted dispatcher with its own traffic journal (terminal transcript suppression works on every involved terminal), all released on tab close/unbind/edit-away (NFR-4).

### 4.14 Alerts (v2)

- **FR-57** An alert fires when an entry's state transitions *into* `fail` or `error` from any other state; the matching recovery transition is recorded silently. Timeouts and staleness never alert (a dead device must not generate notification storms — its first send error still alerts once). Repeated results in the same state do not re-fire.
- **FR-58** Alert surfaces: a header bell button with an unseen-count badge opening a bounded alert-history panel (200 records: time, entry, old→new state, value; Clear action; opening marks seen); a "● " prefix on the tab title while unseen alerts exist; a footer status line per alert; a taskbar attention request; and an optional sound (~debounced to ≥ 2 s). Per-entry opt-out via `alerts_enabled` (default on). Global Preferences toggles: master enable (default on) and sound (default off); master off suppresses records, badge, and sound entirely.

### 4.15 Control tiles (v2)

- **FR-59** Tile kind `control` sends instead of polling. Modes: `button` (one command per click) and `toggle` (ON/OFF commands; the visual state follows an optional watch entry's verdict — `ok` renders ON — or an optimistic local flag when no watch entry is set). Optional per-tile confirmation shows the standard Yes/No prompt (default No) naming the command and target. Control entries are never scheduled, never stale, never alert, and keep no history.
- **FR-60** Control sends serialize through the same per-session FIFO dispatcher as polls (never interleaved with dashboard traffic on the wire) inside a traffic-journal window (device acks stay out of the terminal transcript). A click is refused with a status message when the target is unresolved, disconnected, or running a command file; clicks are allowed while polling is user-paused (an explicit click is explicit intent). The tile shows pending / success-flash / error feedback per send.

### 4.16 Derived/math tiles (v2)

- **FR-61** An entry with source `derived` computes its value from other entries via an arithmetic expression referencing them as `{Label}`. Expressions support + − × ÷ % ** , unary minus, numeric literals, and the functions abs/min/max/round/sqrt — nothing else (no comparisons, attributes, subscripts, or names outside references); inputs are capped (256 chars, 64 AST nodes) and evaluated without Python `eval`/code objects. References must resolve uniquely to *polled numeric* entries (single level — derived-of-derived is rejected; cycles are impossible by construction). Renaming a referenced entry rewrites referring expressions. The computed value flows through the standard pipeline: rules, colors, sparkline, chart, CSV, alerts. Missing inputs render neutral "—" with an explanatory tooltip; an input going stale makes the derived tile stale; evaluation errors (including division by zero) render the error state. Derived entries generate no serial traffic.

### 4.17 Per-rule custom colors (v2)

- **FR-62** A color rule may carry an explicit color (`#rrggbb`). When that rule matches, the custom color overrides the theme state color everywhere the verdict is rendered: value text, LED lamp and caption, sparkline stroke, and chart series. An empty color keeps the theme mapping. The entry dialog's rules table offers a color swatch (system color picker) with a clear-to-theme action; invalid color strings are dropped on load.

## 5. Non-functional requirements

- **NFR-1 (GUI responsiveness)** No serial/LAN I/O ever executes on the GUI thread. Dashboard sends happen exclusively on a per-session dispatcher thread. The GUI tick (drain results, health check, schedule) completes in < 1 ms typically and < 5 ms with 64 entries (smoke-tested).
- **NFR-2 (Timing accuracy)** Poll intervals are honored within ±1 scheduler tick (100 ms) plus device response time. This is the documented contract on Windows (coarse timer resolution); no busy-waiting anywhere.
- **NFR-3 (Bounded memory)** *(amended in v2)* All runtime buffers are bounded: RX correlation window ≤ 4096 chars (tail-kept), dispatcher request queue ≤ 64, idle RX continuously drained and discarded, per-entry history ≤ 600 samples / 1 hour, alert history ≤ 200 records. A chatty device cannot grow dashboard memory without bound. No runtime values, RX transcripts, or history are written to the settings file (CSV logging is the explicit durable record).
- **NFR-4 (Resource lifecycle)** Closing a dashboard tab, closing the bound terminal, applying imported settings, and quitting the app all stop dispatcher threads (join ≤ 1.5 s) and unsubscribe event queues. Tests assert no `dashboard-dispatch` threads survive teardown.
- **NFR-5 (Isolation)** A misbehaving entry (catastrophic regex, slow device) can stall at most its own session's polling — never the GUI and never other sessions. Regex input is bounded by NFR-3; patterns are validated and smoke-run at edit time.
- **NFR-6 (Theming)** *(amended in v2)* All dashboard colors derive from the active `ThemePalette` (semantic state → palette mapping in one place) and spacing/sizing from `ui/tokens.py`. All 6 built-in themes render distinct ok/warn/fail/stale states. No hardcoded color literals outside `themes.py` — user-chosen rule colors (FR-62) are runtime data, not source literals, and fall back to the theme when unset.
- **NFR-7 (Qt-free domain)** Dashboard models, parsing, rules, scheduling, and catalog logic are Qt-free, re-exported through `core/`, and enforced by the existing `tests/test_core_no_pyside.py` isolation check.
- **NFR-8 (Compatibility)** Existing behavior is unchanged for users who never open a dashboard: schema migration is additive, terminal/editor flows untouched, settings min-compat rules per FR-39.
- **NFR-9 (Testability)** Scheduler and parse logic are deterministic under an injected clock (no real sleeps in unit tests); dispatcher logic is testable threadless via a factored transaction method; integration tests run against `FakeSerialTransport`.
- **NFR-10 (Documentation)** All new public APIs carry docstrings; `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, and `docs/LLM_CHANGE_GUIDE.md` gain dashboard sections (ownership, invariants, change recipes); README and CHANGELOG updated.
- **NFR-11 (Expression safety, v2)** Derived-tile expressions are parsed to an AST and evaluated by a whitelisting interpreter — no `eval`, `exec`, or compiled code objects; node and length caps bound work; every failure surfaces as an error tile, never as an exception escaping the GUI tick.
- **NFR-12 (v2 tick budget)** The GUI tick stays under the v1 budget with v2 load: 64 entries including derived tiles, full histories, alerts enabled, and two target sessions average < 5 ms per tick (benchmarked). Sparkline repaints are coalesced (≤ 1 per tile per result + 1 Hz window slide); the chart repaints only while visible.
- **NFR-13 (Sound robustness, v2)** Alert sound degrades gracefully: missing QtMultimedia or a missing wav asset falls back to the system beep; sound failures never affect alert records or polling.

## 6. Out of scope (v2)

- CLI access to dashboards.
- Dashboards owning their own serial/LAN connection (binding to terminal sessions remains the only transport path).
- Persisted value history (history is runtime-only; CSV logging is the durable record).
- Chart image/data export, multi-series or multi-axis charts.
- Alert acknowledgement workflows beyond the history panel's Clear; per-entry alert sounds or custom sound files.
- Derived-of-derived expressions (single level is locked).
- Gauge, slider, or free-form input control kinds (button/toggle only).
- Scripting or conditional automation driven by dashboard values.

## 7. Accepted limitations (shared medium)

The bound session is a shared, unframed byte stream. While a poll transaction's RX window is open, traffic from other sources (user-typed commands, device echo, unsolicited async output) can satisfy or pollute an entry's parse rule. Mitigations: stale RX is drained before each send; the window exists only during a transaction; polls are serialized so at most one entry can mis-attribute per foreign event; the entry editor encourages anchored patterns and provides a live tester; the tile tooltip exposes the raw RX window for diagnosis. This limitation is inherent to decision 1 and is documented to users.

The transcript filter (FR-15) has the mirrored limitation: device output that happens to arrive *during* a poll window is treated as poll traffic and kept out of the terminal display (it still reaches the session log). With typical poll timeouts of a few hundred milliseconds this affects only chatty devices that emit unsolicited output continuously.

v2 additions to the accepted-limitations list:

- **Multi-session summaries.** A single chip cannot fully represent three sessions' states; the aggregate text plus per-endpoint tooltip lines (FR-56) and per-tile tooltips are the contract. Gated entries simply age to stale — no synthetic per-entry "paused" state is invented.
- **Control click vs. batch start race.** The click-time gate refuses sends while a command file runs (FR-60), but a batch started after a control request was queued can still interleave on the wire — the same tick-granular window v1 accepted for polling. Dashboard-vs-dashboard serialization remains absolute (one FIFO per session).

## 8. Acceptance criteria → test mapping

| Requirement(s) | Proving test module |
| --- | --- |
| FR-18, FR-19, FR-33, FR-35 (model validity, clamping, layout math) | `tests/test_dashboard_models.py` |
| FR-24–FR-28 (parse kinds, window, number errors), FR-29, FR-30 (rule semantics) | `tests/test_dashboard_parse.py` |
| FR-20, FR-21, FR-23 (fixed-delay, serialization, send-error), NFR-3 (bounded queues/window), NFR-9 (injected clock) | `tests/test_dashboard_engine.py` |
| FR-1–FR-3 (catalog CRUD, dedupe, import/export), FR-37, FR-39 (schema v5, min-compat matrix) | `tests/test_dashboard_catalog.py`, `tests/test_models_and_storage.py` |
| FR-10 (targets incl. disconnected), FR-13/FR-17 partial (dispatcher refcount), FR-14 (batch detection) | `tests/test_dashboard_targets.py` |
| FR-31, FR-34, FR-35 (tile rendering, spans, drag), NFR-6 (theme matrix) | `tests/test_dashboard_tiles.py` |
| FR-11, FR-12, FR-16, FR-22, FR-27, FR-32 (tick loop, pause reasons, staleness), FR-28 (dialog validation/tester) | `tests/test_dashboard_tab.py` |
| FR-2, FR-4 (manager flows) | `tests/test_dashboard_manager.py` |
| FR-5–FR-8 (menus, palette, context menus, tab plumbing) | `tests/test_command_registry.py`, `tests/test_main_window_menus.py`, `tests/test_tab_context_menus.py`, `tests/test_command_palette_entries.py`, `tests/test_tab_workspace.py`, `tests/test_workspace_status.py` |
| FR-37, FR-38, FR-40 (capture/restore/rebind) | `tests/test_workspace_state.py`, `tests/test_app_dashboards.py` |
| FR-9, FR-15, FR-17, NFR-1 (tick budget), NFR-4 (thread lifecycle) end-to-end | `tests/test_app_dashboards.py` |
| FR-15 (journal windows, TX tagging, terminal filter) | `tests/test_dashboard_engine.py`, `tests/test_dashboard_targets.py`, `tests/test_app_dashboards.py` |
| FR-41..FR-44 (sidebar page, favorites panel, list refresh) | `tests/test_dashboard_sidebar.py`, `tests/test_app_dashboards.py` |
| FR-45 (pause control state, save indicator) | `tests/test_dashboard_tab.py` |
| FR-46 (history bounds), FR-47 partial (downsampling), FR-48 partial (ticks/nearest-sample math) | `tests/test_dashboard_history.py` |
| FR-47 (sparkline presence/coalescing/theming) | `tests/test_dashboard_tiles.py` |
| FR-48 (chart page open/close, spans, readout, follow-live) | `tests/test_dashboard_chart.py`, `tests/test_dashboard_tab.py` |
| FR-49..FR-51 (CSV schema, header-once, append, error path, persistence) | `tests/test_dashboard_value_log.py`, `tests/test_dashboard_tab.py` |
| FR-52, FR-53 (on_connect scheduling, connect-edge triggers, Poll Now) | `tests/test_dashboard_engine.py`, `tests/test_dashboard_tab.py` |
| FR-54..FR-56 (per-entry targets, gating, chip aggregation, multi-dispatcher lifecycle) | `tests/test_dashboard_tab.py`, `tests/test_dashboard_targets.py`, `tests/test_app_dashboards.py` |
| FR-57, FR-58 (alert edges, surfaces, preferences) | `tests/test_dashboard_alerts.py`, `tests/test_dashboard_tab.py`, `tests/test_models_and_storage.py` |
| FR-59, FR-60 (control tiles, FIFO serialization, gating, confirm) | `tests/test_dashboard_engine.py`, `tests/test_dashboard_tiles.py`, `tests/test_dashboard_tab.py` |
| FR-61 (expressions: safety, resolution, recompute, staleness) | `tests/test_dashboard_expr.py`, `tests/test_dashboard_tab.py` |
| FR-62 (custom colors plumbing + rendering) | `tests/test_dashboard_parse.py`, `tests/test_dashboard_tiles.py` |
| FR-39 v2 (schema v6 floor matrix, export version stamping) | `tests/test_models_and_storage.py`, `tests/test_dashboard_catalog.py` |
| NFR-7 (Qt-free domain incl. v2 modules) | `tests/test_core_no_pyside.py` |
| NFR-11 (expression safety rejection matrix) | `tests/test_dashboard_expr.py` |
| NFR-12 (v2 tick budget) | `tests/test_app_dashboards.py` |

## 9. References

- Binding precedent: `src/ComPort_Zone/command_run_targets.py`, `src/ComPort_Zone/ui/command_file_targets.py`
- RX fan-out: `SerialClient.subscribe_events` (`src/ComPort_Zone/serial_core.py`)
- Correlation idiom: `BatchRunner._expect_text` (`src/ComPort_Zone/batch.py`)
- Settings schema: `src/ComPort_Zone/models.py`, `src/ComPort_Zone/settings_service.py`
- Logging precedents: `src/ComPort_Zone/session_log.py`, CSV writer in `src/ComPort_Zone/quick_actions.py`
- Implementation plans: v1 (T1–T12) and v2 (V2-T1–T14), both approved.
