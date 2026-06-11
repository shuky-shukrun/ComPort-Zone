# Dashboard View — Feature Requirements

Status: Approved for implementation
Version: 1.0
Date: 2026-06-11
Applies to: ComPort Zone >= 0.5.0 (settings schema v5)

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
| Binding | The association between a dashboard tab and one open terminal session whose connection is used for polling. |
| Poll transaction | One send→collect→parse cycle for one entry: drain stale RX, transmit the command, accumulate RX until the parse rule matches or the timeout elapses. |
| Pause reason | One of `user`, `connection`, `unbound`, `batch`. Polling runs only when the set of active pause reasons is empty. |

## 3. Locked product decisions

These were decided with the product owner and are fixed for v1:

1. **Bind to a terminal session.** A dashboard never owns a serial/LAN connection. It binds to an existing terminal tab's session (the same targeting concept as the command-file editor's Run button). Polling pauses while the bound session is disconnected and resumes automatically on reconnect. Poll traffic shares the session's connection but is hidden from the terminal's transcript (FR-15) — continuous polling would otherwise flood the terminal and make manual use impossible.
2. **Tile types v1: Value tile and LED/status indicator.** Charts, sparklines, and history plots are out of scope for v1.
3. **Layout: uniform grid with drag-to-reposition and per-tile spans** (1x1, 2x1, 1x2, 2x2). Layout persistence is deterministic.
4. **Multi-dashboard via named library + tabs.** Dashboards are named saved configurations with JSON import/export. Opening a dashboard creates a workspace tab; open tabs are restored on restart.

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
- **FR-12** When the bound session disconnects, polling pauses within one tick and tiles begin aging toward stale; on reconnect (including auto-reconnect), polling resumes automatically with staggered first sends.
- **FR-13** When the bound terminal tab is closed, the dashboard unbinds, shows an "unbound" state with a one-click bind menu, and releases all per-session resources (no orphan threads or event subscriptions).
- **FR-14** While a command-file (batch) run is active on the bound session, dashboard polling suspends automatically (pause reason `batch`) and resumes when the run finishes.
- **FR-15** Dashboard poll traffic is hidden from the bound terminal's transcript: poll TX events carry a `source="dashboard"` tag, and RX received inside a poll-transaction window (tracked by a per-session traffic journal, with a short grace tail for late fragments) is not rendered. The traffic still flows through the session log and every event subscriber unchanged; manually typed commands and out-of-window device output render normally. Tile tooltips remain the diagnostic surface for raw poll RX.
- **FR-16** A user-initiated pause/resume toggle exists per dashboard tab; the user-pause state persists across restarts.
- **FR-17** Multiple dashboard tabs may bind to the same session. Their poll transactions are serialized on that session (never interleaved on the wire) and share one dispatcher; closing one dashboard does not disturb the other.

### 4.4 Entries: commands and scheduling

- **FR-18** Each entry defines: label, optional unit, command payload, send mode (`Text` or `Hex Bytes`), optional line-ending override (None/CR/LF/CRLF; default = session profile), poll interval (ms), response timeout (ms), staleness threshold (ms, 0 = automatic), parse rule, ordered color rules, tile kind, tile placement/span, and enabled flag.
- **FR-19** Poll interval has a floor of 100 ms; timeout range 50–30000 ms. Values outside ranges are clamped on load and rejected with messages in the editor dialog.
- **FR-20** Scheduling is fixed-delay: the next poll of an entry is scheduled `interval` after the previous transaction *completes* (success or timeout). A slow device therefore degrades the effective rate instead of building a backlog; at most one transaction per entry is outstanding at any time.
- **FR-21** Poll transactions on one session execute strictly one at a time, FIFO across all entries and all dashboards bound to that session.
- **FR-22** Disabled entries are skipped by the scheduler but remain on the grid (rendered in a muted/disabled style).
- **FR-23** Send failures (port error mid-poll) render the tile in error state with the failure reason available in the tile tooltip; the scheduler continues with the next due entries (no crash, no permanent wedge).

### 4.5 Response parsing

- **FR-24** Parse rule kinds: `line` — the first complete line received after the send (terminated by CR, LF, or CRLF); `regex` — a regular expression searched over the accumulated post-send RX window, with a configurable capture group (index or name; group 0 = whole match).
- **FR-25** Parsed values have a declared type: `text` or `number`. For `number`, the captured string is converted to float; conversion failure is reported as a parse error on the tile (distinct from timeout).
- **FR-26** Parsing evaluates only RX received *after* the entry's send within that transaction (stale pre-send RX is discarded), bounded by a rolling window of 4096 characters (tail-kept).
- **FR-27** If the rule does not match before the entry timeout, the result is a timeout: the tile shows its last good value with a stale/timeout marker and the timestamp of the last success.
- **FR-28** Invalid regexes are rejected at edit time with a human-readable error; the entry editor provides a live tester (paste sample RX → see extracted value and resulting rule state).

### 4.6 Color/indicator rules

- **FR-29** Each entry has an ordered list of rules evaluated first-match-wins against the parsed value. Operators: numeric `lt, le, gt, ge, eq_num, ne_num, between` (inclusive bounds) and textual `eq_text, contains, matches` (regex). Each rule maps to a semantic state `ok`, `warn`, or `fail`, with an optional display label override (e.g. `FAULT`).
- **FR-30** Numeric operators are skipped when the parsed value is not numeric; if no rule matches, the state is `neutral`. Timeout/staleness produces `stale`; parse/send errors produce `error`. Semantic states map to theme colors centrally (no per-entry custom colors in v1).
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
- **FR-39** Settings schema bumps to v5. v4 files load cleanly (no dashboards). Files saved *without* any dashboard content remain readable by schema-v4-era builds (minimum-compatible stays ≤ 4); files containing dashboards declare minimum-compatible 5.
- **FR-40** A restored dashboard tab whose config id no longer exists in the library is skipped with a footer notice (no crash, no placeholder tab).

### 4.9 Sidebar and favorites integration

- **FR-41** The left drawer's activity rail gains a **Dashboards** page listing every saved dashboard (name + entry count), with inline row actions matching commands/files: open (▶), star (favorite toggle), rename (pencil), delete (✕, confirmed), plus a matching right-click menu and double-click-to-open.
- **FR-42** The Dashboards page header offers "+" (new dashboard) and an overflow menu with Manage…, Import JSON…, and Export JSON… (the same operations as the menu bar).
- **FR-43** Dashboards carry a `favorite` flag (persisted with the config and included in JSON export). The Favorites page shows a third collapsible **Favorite Dashboards** panel beside favorite commands and files, sharing the same resizable splitter; its rows offer the same open/star/rename/delete actions.
- **FR-44** Sidebar lists refresh immediately after any library mutation, from any surface (tab rename, manager dialog, sidebar actions, import).
- **FR-45** The dashboard header's pause control always shows the action a click would take (pause icon while polling, play icon while paused, with matching tooltips), and all header controls give hover/pressed/checked visual feedback.

## 5. Non-functional requirements

- **NFR-1 (GUI responsiveness)** No serial/LAN I/O ever executes on the GUI thread. Dashboard sends happen exclusively on a per-session dispatcher thread. The GUI tick (drain results, health check, schedule) completes in < 1 ms typically and < 5 ms with 64 entries (smoke-tested).
- **NFR-2 (Timing accuracy)** Poll intervals are honored within ±1 scheduler tick (100 ms) plus device response time. This is the documented contract on Windows (coarse timer resolution); no busy-waiting anywhere.
- **NFR-3 (Bounded memory)** All runtime buffers are bounded: RX correlation window ≤ 4096 chars (tail-kept), dispatcher request queue ≤ 64, idle RX continuously drained and discarded. A chatty device cannot grow dashboard memory without bound. No runtime values, RX transcripts, or history are written to the settings file.
- **NFR-4 (Resource lifecycle)** Closing a dashboard tab, closing the bound terminal, applying imported settings, and quitting the app all stop dispatcher threads (join ≤ 1.5 s) and unsubscribe event queues. Tests assert no `dashboard-dispatch` threads survive teardown.
- **NFR-5 (Isolation)** A misbehaving entry (catastrophic regex, slow device) can stall at most its own session's polling — never the GUI and never other sessions. Regex input is bounded by NFR-3; patterns are validated and smoke-run at edit time.
- **NFR-6 (Theming)** All dashboard colors derive from the active `ThemePalette` (semantic state → palette mapping in one place) and spacing/sizing from `ui/tokens.py`. All 6 built-in themes render distinct ok/warn/fail/stale states. No hardcoded color literals outside `themes.py`.
- **NFR-7 (Qt-free domain)** Dashboard models, parsing, rules, scheduling, and catalog logic are Qt-free, re-exported through `core/`, and enforced by the existing `tests/test_core_no_pyside.py` isolation check.
- **NFR-8 (Compatibility)** Existing behavior is unchanged for users who never open a dashboard: schema migration is additive, terminal/editor flows untouched, settings min-compat rules per FR-39.
- **NFR-9 (Testability)** Scheduler and parse logic are deterministic under an injected clock (no real sleeps in unit tests); dispatcher logic is testable threadless via a factored transaction method; integration tests run against `FakeSerialTransport`.
- **NFR-10 (Documentation)** All new public APIs carry docstrings; `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, and `docs/LLM_CHANGE_GUIDE.md` gain dashboard sections (ownership, invariants, change recipes); README and CHANGELOG updated.

## 6. Out of scope (v1)

- Charts, sparklines, gauges, or any value-history visualization (v2 candidate; would add a plotting dependency or custom painting).
- Dashboards owning their own serial/LAN connection (decision 1 explicitly rejects this for v1).
- CLI access to dashboards.
- Alarm sounds, desktop notifications, or alert acknowledgement flows.
- Logging/recording of polled values to file (session logging of the bound terminal continues to capture the raw traffic).
- Write-command safety flows (confirmation before sending "dangerous" commands); entries are assumed to be read/query commands.
- Per-entry custom colors (semantic states map to theme colors only).

## 7. Accepted limitations (shared medium)

The bound session is a shared, unframed byte stream. While a poll transaction's RX window is open, traffic from other sources (user-typed commands, device echo, unsolicited async output) can satisfy or pollute an entry's parse rule. Mitigations: stale RX is drained before each send; the window exists only during a transaction; polls are serialized so at most one entry can mis-attribute per foreign event; the entry editor encourages anchored patterns and provides a live tester; the tile tooltip exposes the raw RX window for diagnosis. This limitation is inherent to decision 1 and is documented to users.

The transcript filter (FR-15) has the mirrored limitation: device output that happens to arrive *during* a poll window is treated as poll traffic and kept out of the terminal display (it still reaches the session log). With typical poll timeouts of a few hundred milliseconds this affects only chatty devices that emit unsolicited output continuously.

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
| NFR-7 (Qt-free domain) | `tests/test_core_no_pyside.py` |

## 9. References

- Binding precedent: `src/ComPort_Zone/command_run_targets.py`, `src/ComPort_Zone/ui/command_file_targets.py`
- RX fan-out: `SerialClient.subscribe_events` (`src/ComPort_Zone/serial_core.py`)
- Correlation idiom: `BatchRunner._expect_text` (`src/ComPort_Zone/batch.py`)
- Settings schema: `src/ComPort_Zone/models.py`, `src/ComPort_Zone/settings_service.py`
- Implementation plan: see the approved Dashboard View implementation plan (T1–T12).
