---
name: comport-zone-control-panel
description: Author, fix, or edit ComPort Zone "Control Panel" JSON files (formerly called "Dashboard View") — the importable layouts that drive live instrument readouts, setpoints, faults, and status registers over a serial / LAN session. Use this whenever the user wants to build, fix, share, tweak, debug, or migrate a control panel for ComPort Zone (e.g. SCPI bench instruments, power supplies, DMMs, function generators, programmable loads, electronic loads), or whenever they hand you a manual / command list and say "make me a panel" or "make me a dashboard for X". Also triggers when they paste a partial / broken JSON (especially ones with a `comport_zone_control_panels` or `comport_zone_dashboards` wrapper key) and ask to fix it, when they ask which tile kind fits a SCPI command, when they need a JSON Schema or a validator for a panel file, or when they want a starter template they can edit. Compatible with ComPort Zone ≥ 0.5.0 (panel schema version 3).
---

# ComPort Zone — Control Panel author

A control panel is a saved layout of **tiles** that ComPort Zone polls over a bound terminal session. One JSON file holds the panel's name, grid size, and the entries (one entry per tile). Users import these via **Control Panels → Import…** or `Ctrl+Shift+D`.

The schema is intentionally small but covers six tile kinds — `value`, `led`, `control`, `setpoint`, `enum`, `bits` — so a single file can read live measurements, drive setpoints, toggle outputs, and decode multi-bit status / fault registers.

This skill produces panel JSON without you needing to read the codebase. Follow the flow below; reach for the references for field-level detail.

## Compatibility

- App: **ComPort Zone ≥ 0.5.0** (the release that ships the "Control Panel" feature, formerly called "Dashboard View")
- Panel-file schema: **version 3** (top-level key `"comport_zone_control_panels": 3`)

Older 0.4.x ComPort Zone builds cannot import this schema — the wrapper key was `"comport_zone_dashboards"` there.

## How to use this skill

1. **Gather the instrument details from the user** (one short interview, not 20 questions):
   - Make / model (helps you pick conservative defaults)
   - The commands they care about (or a manual / SCPI doc)
   - Which values they want to **read** (live measurements, identity, mode strings)
   - Which controls they want to **write** (output on/off, setpoints, sequencer triggers)
   - Whether the instrument exposes **bit-mapped status / fault registers** (very common on SCPI gear: `STAT:OPER:COND?`, `STAT:QUES:COND?`, etc.). If yes — get the bit numbers + names.
   - Min/max ranges for setpoints
   - Per-tile poll rate (default 500–1000 ms is usually fine)

2. **Sketch a grid**. Default canvas: `columns=6, rows=8`. The grid auto-expands vertically when tiles overflow `rows`. Span limits: 1..5 per axis (`MAX_TILE_SPAN`), columns 1..12, rows 1..24. See `references/schema.md` for the per-field clamps.

3. **Pick a tile kind per entry** (see `references/tile-kinds.md`):
   - `value` — live numeric readout (V, A, W, °C). Numeric tiles automatically grow a 120 s sparkline.
   - `led` — text / number state with color rules (CV/CC/OFF, READY/BUSY).
   - `control` — button (one shot, e.g. *Clear faults*) or toggle (ON/OFF, with shared readback so visual state follows reality).
   - `setpoint` — editable numeric field + read-only readback field for a numeric write (`VOLT {value}`, etc.).
   - `enum` — labeled dropdown where each option sends its own command; shared readback can indicate the current option.
   - `bits` — per-bit lamp + label for status / fault registers (multiple bits can be active at once).

4. **Write the JSON**. Always wrap the panel(s) in the versioned envelope:
   ```json
   {
     "comport_zone_control_panels": 3,
     "control_panels": [ /* one or more panel configs */ ]
   }
   ```
   Save it as `examples/<name>.json` (or wherever the user prefers). UTF-8, two-space indent reads best.

5. **Validate** before declaring done — run the bundled script:
   ```
   python scripts/validate.py path/to/panel.json
   ```
   This checks the envelope + every entry against the JSON Schema in `assets/control-panel.schema.json`. Fix any reported error.

6. **Hand off** — tell the user the file path and the import path (Control Panels → Import…). If they asked for a starter template, point them at `assets/starter-panel.json`.

## Quick start: minimal panel

A good shape for "I just need to see one measurement and toggle output":

```json
{
  "comport_zone_control_panels": 3,
  "control_panels": [{
    "id": "starter",
    "name": "My instrument",
    "columns": 4,
    "rows": 3,
    "favorite": true,
    "entries": [
      {
        "id": "ident", "label": "Identity", "command": "*IDN?",
        "poll_mode": "on_connect",
        "parse": {"kind": "line", "value_type": "text"},
        "tile": {"col": 0, "row": 0, "span_w": 4, "span_h": 1, "kind": "value"}
      },
      {
        "id": "v-meas", "label": "Voltage", "unit": "V",
        "command": "MEAS:VOLT?", "interval_ms": 300,
        "parse": {"kind": "line", "value_type": "number"},
        "tile": {"col": 0, "row": 1, "span_w": 2, "span_h": 2, "kind": "value"}
      },
      {
        "id": "output", "label": "Output",
        "tile": {"col": 2, "row": 1, "span_w": 2, "span_h": 1, "kind": "control"},
        "control": {"mode": "toggle", "on_command": "OUTP ON", "off_command": "OUTP OFF"},
        "readback": {
          "source": "command",
          "command": "OUTP?",
          "parse": {"kind": "line", "value_type": "number"},
          "rules": [{"op": "eq_num", "operand": "1", "state": "ok", "label": "ON"}]
        }
      }
    ]
  }]
}
```

The richer worked examples in `references/examples.md` cover SCPI bench instruments, multi-bit fault registers, derived (computed) tiles, and per-rule custom colors.

## Field reference & deeper material

- **Field-by-field schema**: see `references/schema.md` — every wrapper, panel, entry, parse, tile, rule, control/setpoint/enum/bits spec, with allowed values and defaults.
- **Tile-kind patterns**: see `references/tile-kinds.md` — when to pick which kind, the must-have fields, and live patterns (sparkline, readback, indicator pill, master-arm gating).
- **Worked examples**: see `references/examples.md` — a bench-power-supply panel, an SCPI status-register panel, a derived-power panel.
- **JSON Schema** (for downstream tooling): `assets/control-panel.schema.json` — vendored Draft-7 schema for the full envelope.
- **Validator**: `scripts/validate.py` — runs the schema check + a few semantic rules (unique ids, no out-of-range bit positions, etc.). Only needs `pip install jsonschema`.

## Things that trip people up

- **Sparse fields, not optional.** Most fields have defaults. Omit a field and the importer uses the default; write the default explicitly if you prefer readability. Either way it round-trips.
- **`{value}` token** in a setpoint's `command_template` is *required exactly once* — otherwise the importer rejects the entry. Use `"VOLT {value}"`, not `"VOLT"` or `"VOLT {value} {value}"`.
- **Readback IDs.** `readback: {"source": "entry", "watch_entry_id": "..."}` must point to another entry's `id` in the same panel. The watched entry has to be a polled tile that actually produces a verdict (use a `value` or `led` tile, with rules if needed).
- **Direct readback.** `readback: {"source": "command", "command": "OUTP?", ...}` sends that query once on connect and after each write. For setpoints, the connect-time readback seeds the editable command field without sending a set command. Default timing is one pull after 20 ms; set `"mode": "interval"` plus `"interval_ms"` when the device should be refreshed periodically.
- **Bit positions** are 0..31 and **must not repeat** in the same `bits_spec`. State per bit is one of `ok / warn / fail / neutral`.
- **LED text-rule order matters.** Rules evaluate top-down; the first hit wins. Put more-specific matches above more-general ones.
- **Don't overlap tiles.** The importer normalizes overlaps deterministically by pushing later tiles down, but the result may not match what you sketched. Lay them out cleanly the first time.
- **Master arm.** A panel boots **disarmed**, so writing tiles (`control` / `setpoint` / `enum`) refuse to send until the user clicks the lock icon in the header. This is a runtime behaviour, not something you put in the JSON.
- **CSV column.** If the user enables CSV logging in-app, the log gets `kind=poll|derived|control` rows automatically — no JSON change needed.

## When to spend extra effort on layout

If the user says "make it look good" or "for split-screen", set `columns` smaller (4) and use 2×1 / 2×2 tiles for measurements so the responsive measure font has room to breathe. The measure font auto-scales with cell width — narrow grids stay readable.

For a status-heavy panel (many bits / many setpoints), bump `columns` to 6 or 8 and put the bits register as a 3×2 or 4×2 tile so its labels don't crowd.

## Sharing the panel

A panel file is plain JSON — just send it. The receiver opens **Control Panels → Import…** (`Ctrl+Shift+D` → Import button) and picks the file. IDs auto-resolve: name collisions get renamed, id collisions get a fresh id.
