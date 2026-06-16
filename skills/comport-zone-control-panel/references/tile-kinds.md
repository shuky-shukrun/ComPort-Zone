# Tile kinds — how to pick + minimal recipes

Six kinds. Pick by intent (read vs. write vs. multi-state), not by data type.

| Intent | Kind | Send? | Sparkline? | Master-arm gated? |
| --- | --- | --- | --- | --- |
| Live numeric / text readout | `value` | no | yes (numeric only) | no |
| Categorical state w/ color | `led` | no | no | no |
| One-shot send / latched on-off | `control` | yes | no | **yes** |
| Numeric write w/ readback | `setpoint` | yes | no | **yes** |
| Pick-one selector | `enum` | yes | no | **yes** |
| Multi-bit status / fault register | `bits` | no | no | no |

"Master-arm gated" means the user has to click the lock icon in the panel header before the tile can send anything — that's runtime UX, but it's why you don't make a setpoint tile when you really meant a value tile.

---

## `value` — live numeric / text readout

Most common kind. Polls a command, parses the response, paints the value. Numeric values automatically grow a 120 s in-tile sparkline; double-click opens a full chart page.

**Minimal:**
```json
{
  "id": "v-meas", "label": "Voltage", "unit": "V",
  "command": "MEAS:VOLT?", "interval_ms": 300,
  "parse": {"kind": "line", "value_type": "number"},
  "tile": {"col": 0, "row": 0, "span_w": 2, "span_h": 2, "kind": "value"}
}
```

**With color rules** (e.g. tile turns amber above 13 V, red above 14 V):
```json
"rules": [
  {"op": "gt", "operand": "14.0", "state": "fail"},
  {"op": "gt", "operand": "13.0", "state": "warn"},
  {"op": "between", "operand": "11", "operand2": "13", "state": "ok"}
]
```

**Run-once on bind** (identity / firmware): set `poll_mode: "on_connect"` and bump the timeout — those queries can be slow.

---

## `led` — state indicator

Same plumbing as `value` (it polls, it parses), but visually it's a lamp + caption — the color comes straight from the matched rule and the caption can be overridden by the rule's `label`.

**Numeric on/off (e.g. `OUTP?` returns `0` / `1`):**
```json
{
  "id": "outp-state", "label": "Output", "command": "OUTP?",
  "interval_ms": 500,
  "parse": {"kind": "line", "value_type": "number"},
  "rules": [
    {"op": "eq_num", "operand": "1", "state": "ok",   "label": "ON"},
    {"op": "eq_num", "operand": "0", "state": "warn", "label": "OFF"}
  ],
  "tile": {"col": 3, "row": 0, "span_w": 1, "span_h": 1, "kind": "led"}
}
```

**Text mode (e.g. `OUTP:MODE?` returns `CV` / `CC` / `OFF`):**
```json
"parse": {"kind": "line", "value_type": "text"},
"rules": [
  {"op": "contains", "operand": "CV",  "state": "ok",   "label": "CV"},
  {"op": "contains", "operand": "CC",  "state": "warn", "label": "CC"},
  {"op": "contains", "operand": "OFF", "state": "fail", "label": "OFF"}
]
```

Rules evaluate top-down — put specific matches before generic ones.

---

## `control` — one-shot button or on/off toggle

**Button** (single shot, e.g. *Clear faults*):
```json
{
  "id": "clear-faults", "label": "Clear faults",
  "tile": {"col": 5, "row": 5, "span_w": 1, "span_h": 1, "kind": "control"},
  "control": {"mode": "button", "on_command": "OUTP:PROT:CLE", "confirm": true}
}
```

**Toggle** (mirrors a polled tile's verdict so the button color tracks reality):
```json
{
  "id": "output-toggle", "label": "Output",
  "tile": {"col": 0, "row": 5, "span_w": 3, "span_h": 1, "kind": "control"},
  "control": {
    "mode": "toggle",
    "on_command": "OUTP ON", "off_command": "OUTP OFF"
  },
  "readback": {"source": "entry", "watch_entry_id": "outp-state"}
}
```

The `readback` block can follow another entry (`source: "entry"`) or send its own query (`source: "command"`). It runs once on connect for initial state and again after each write; `mode: "interval"` keeps it refreshing periodically.

`confirm: true` adds a "Are you sure?" prompt before each send — recommended for protective / destructive commands.

---

## `setpoint` — slider + spinbox + readback

For numeric writes (output voltage, current limit, OVP threshold). The widget gives you a slider above a `QDoubleSpinBox`; both edit the same float. The send-string is a template with `{value}` filled in at submit.

**Minimal:**
```json
{
  "id": "v-set", "label": "Output voltage",
  "tile": {"col": 0, "row": 3, "span_w": 3, "span_h": 1, "kind": "setpoint"},
  "setpoint": {
    "min_value": 0.0, "max_value": 30.0, "step": 0.1,
    "decimals": 2, "unit": "V",
    "command_template": "VOLT {value}"
  },
  "readback": {"source": "entry", "watch_entry_id": "v-meas"}
}
```

`readback` is optional — when set, the tile shows the followed or directly queried value as a readback line ("commanded vs. measured" — the killer feature for ops). The followed tile or direct query should produce a numeric value.

`{value}` is required in the template **exactly once**. If you need an instrument-specific format, hand it a different `decimals` value rather than wrapping the token.

---

## `enum` — labeled dropdown

Each row is a label + the command it sends. Optional `match_value` lights an indicator pill on the row whose value matches readback (so the operator sees current mode while the dropdown stays free).

```json
{
  "id": "regulation", "label": "Regulation",
  "tile": {"col": 3, "row": 5, "span_w": 2, "span_h": 1, "kind": "enum"},
  "enum_spec": {
    "options": [
      {"label": "OFF", "command": "OUTP OFF",   "match_value": "OFF"},
      {"label": "CV",  "command": "MODE CV",    "match_value": "CV"},
      {"label": "CC",  "command": "MODE CC",    "match_value": "CC"}
    ]
  },
  "readback": {"source": "entry", "watch_entry_id": "mode"}
}
```

Use enums for **discrete** parameters with a handful of choices: regulation mode, current range, trigger source, line frequency. For sweeps (1..N integers) reach for a setpoint instead.

---

## `bits` — multi-bit status / fault register

For SCPI status registers (`STAT:OPER:COND?`, `STAT:QUES:COND?`, `*STB?`) or any integer-encoded multi-flag value. Each `BitDefinition` becomes one lamp + label; any number of bits can be lit at once. Bit positions 0..31.

```json
{
  "id": "faults", "label": "Faults — STAT:QUES:COND?",
  "command": "STAT:QUES:COND?", "interval_ms": 500,
  "parse": {"kind": "line", "value_type": "number"},
  "tile": {"col": 0, "row": 6, "span_w": 3, "span_h": 2, "kind": "bits"},
  "bits_spec": {
    "bits": [
      {"bit": 1, "label": "AC fail",      "state": "fail", "description": "AC input out of spec"},
      {"bit": 2, "label": "Over-temp",    "state": "fail"},
      {"bit": 3, "label": "Foldback",     "state": "warn"},
      {"bit": 4, "label": "Over-voltage", "state": "fail"},
      {"bit": 9, "label": "Under-voltage","state": "fail"}
    ]
  }
}
```

- **Bit positions are 0-indexed.** Bit 0 = least significant bit.
- **No duplicate `bit` values** — the importer rejects the spec.
- **State per bit** picks the lamp color when set: `ok` (green), `warn` (amber), `fail` (red), `neutral` (gray; useful for informational bits like "local mode" you want to render but not call out).
- Instruments returning **hex literals** (`0x81`) are handled automatically — the widget falls back to `int(text, 0)` when the numeric parse can't grab a value.

For long manuals, define only the bits the operator should care about. Reserved / model-specific bits can stay out of the spec — the importer doesn't require all 32 to be defined.

---

## Derived (computed) tiles

Not a separate kind — set `source: "derived"` on a `value` tile and put a formula in `expression`. References to siblings use `{Label}` and resolve at configure time.

```json
{
  "id": "power", "label": "Power", "unit": "W",
  "source": "derived",
  "expression": "{Voltage} * {Current}",
  "tile": {"col": 4, "row": 1, "span_w": 2, "span_h": 2, "kind": "value"}
}
```

Safe-AST evaluator: arithmetic + `abs / min / max / round / sqrt`. No string ops, no funcs, no I/O. Cycles are structurally impossible (single-level depth).

---

## Common compound patterns

- **CV/CC indicator + manual toggle**: a `led` tile polling `OUTP:MODE?` with text rules, *and* a `control` toggle whose `readback` follows that LED. Two tiles, one source of truth.
- **Commanded vs. measured side-by-side**: a `setpoint` tile whose `readback` follows the corresponding `MEAS:VOLT?` value tile. The setpoint's readback line shows the live measurement next to your commanded value.
- **Fault summary**: one `bits` tile decoding `STAT:QUES:COND?`, and a small `value` tile next to it polling `SYST:ERR?` to surface the last error string.
- **Per-channel layout**: repeat the same 3-row block (V_meas / I_meas + V_set / I_set + ON-toggle) horizontally across columns 0–2 and 3–5 for a 2-channel supply.

When in doubt, model after the bundled `examples/tdk-genplus-control-panel.json` in the ComPort Zone repo — it exercises every kind in one panel.
