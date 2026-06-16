# Worked examples

Three complete panels of increasing complexity. Each is a copy-pasteable JSON file you can drop in and adapt.

## 1 — DMM (read-only)

Bench DMM that just streams a single measurement. Perfect first panel for a new user.

```json
{
  "comport_zone_control_panels": 3,
  "control_panels": [{
    "id": "dmm-basic",
    "name": "Bench DMM",
    "description": "Single-channel read-only panel: identity + live measurement + last error.",
    "columns": 4, "rows": 3, "favorite": true,
    "entries": [
      {
        "id": "ident", "label": "Identity", "command": "*IDN?",
        "poll_mode": "on_connect", "timeout_ms": 1500,
        "parse": {"kind": "line", "value_type": "text"},
        "tile": {"col": 0, "row": 0, "span_w": 4, "span_h": 1, "kind": "value"}
      },
      {
        "id": "meas", "label": "Measurement", "unit": "V",
        "command": "READ?", "interval_ms": 250,
        "parse": {"kind": "line", "value_type": "number"},
        "tile": {"col": 0, "row": 1, "span_w": 3, "span_h": 2, "kind": "value"}
      },
      {
        "id": "err", "label": "Last error",
        "command": "SYST:ERR?", "interval_ms": 2000,
        "parse": {"kind": "line", "value_type": "text"},
        "rules": [
          {"op": "contains", "operand": "No error", "state": "ok"},
          {"op": "contains", "operand": "0,",       "state": "ok"}
        ],
        "tile": {"col": 3, "row": 1, "span_w": 1, "span_h": 2, "kind": "value"}
      }
    ]
  }]
}
```

Everything in this panel is read-only — the master arm doesn't matter.

## 2 — Programmable DC supply (read + write)

Adds setpoints, an output toggle, and an OVP fault LED. Mirrors what most lab supplies expose.

```json
{
  "comport_zone_control_panels": 3,
  "control_panels": [{
    "id": "psu-basic",
    "name": "Bench PSU",
    "columns": 6, "rows": 6, "favorite": true,
    "entries": [
      {
        "id": "v-meas", "label": "Voltage", "unit": "V",
        "command": "MEAS:VOLT?", "interval_ms": 300,
        "parse": {"kind": "line", "value_type": "number"},
        "tile": {"col": 0, "row": 0, "span_w": 2, "span_h": 2, "kind": "value"}
      },
      {
        "id": "i-meas", "label": "Current", "unit": "A",
        "command": "MEAS:CURR?", "interval_ms": 300,
        "parse": {"kind": "line", "value_type": "number"},
        "tile": {"col": 2, "row": 0, "span_w": 2, "span_h": 2, "kind": "value"}
      },
      {
        "id": "mode", "label": "Mode", "command": "OUTP:MODE?",
        "interval_ms": 500,
        "parse": {"kind": "line", "value_type": "text"},
        "rules": [
          {"op": "contains", "operand": "CV",  "state": "ok",   "label": "CV"},
          {"op": "contains", "operand": "CC",  "state": "warn", "label": "CC"},
          {"op": "contains", "operand": "OFF", "state": "fail", "label": "OFF"}
        ],
        "tile": {"col": 4, "row": 0, "span_w": 2, "span_h": 1, "kind": "led"}
      },
      {
        "id": "ovp-state", "label": "OVP", "command": "STAT:QUES:COND?",
        "interval_ms": 500,
        "parse": {"kind": "line", "value_type": "number"},
        "rules": [
          {"op": "between", "operand": "0", "operand2": "15", "state": "ok",   "label": "OK"},
          {"op": "gt",      "operand": "15", "state": "fail", "label": "FAULT"}
        ],
        "tile": {"col": 4, "row": 1, "span_w": 2, "span_h": 1, "kind": "led"}
      },
      {
        "id": "v-set", "label": "Set voltage",
        "tile": {"col": 0, "row": 2, "span_w": 3, "span_h": 1, "kind": "setpoint"},
        "setpoint": {
          "min_value": 0.0, "max_value": 30.0, "step": 0.01,
          "decimals": 2, "unit": "V",
          "command_template": "VOLT {value}"
        },
        "readback": {"source": "entry", "watch_entry_id": "v-meas"}
      },
      {
        "id": "i-set", "label": "Set current limit",
        "tile": {"col": 3, "row": 2, "span_w": 3, "span_h": 1, "kind": "setpoint"},
        "setpoint": {
          "min_value": 0.0, "max_value": 5.0, "step": 0.001,
          "decimals": 3, "unit": "A",
          "command_template": "CURR {value}"
        },
        "readback": {"source": "entry", "watch_entry_id": "i-meas"}
      },
      {
        "id": "output", "label": "Output",
        "tile": {"col": 0, "row": 3, "span_w": 4, "span_h": 1, "kind": "control"},
        "control": {
          "mode": "toggle",
          "on_command": "OUTP ON", "off_command": "OUTP OFF"
        },
        "readback": {"source": "entry", "watch_entry_id": "mode"}
      },
      {
        "id": "clear", "label": "Clear faults",
        "tile": {"col": 4, "row": 3, "span_w": 2, "span_h": 1, "kind": "control"},
        "control": {"mode": "button", "on_command": "*CLS", "confirm": true}
      }
    ]
  }]
}
```

Notice the toggle readback follows the LED (`readback.watch_entry_id: "mode"`) so the button color tracks the actual output state, even when somebody turns the supply on from the front panel.

## 3 — SCPI bench: status registers + derived power

Full set, including a derived `value` tile and two `bits` registers. This is the shape you want for instruments with rich status reporting.

```json
{
  "comport_zone_control_panels": 3,
  "control_panels": [{
    "id": "scpi-full",
    "name": "SCPI bench",
    "columns": 6, "rows": 8, "favorite": true,
    "entries": [
      {
        "id": "ident", "label": "Identity", "command": "*IDN?",
        "poll_mode": "on_connect", "timeout_ms": 1500,
        "parse": {"kind": "line", "value_type": "text"},
        "tile": {"col": 0, "row": 0, "span_w": 6, "span_h": 1, "kind": "value"}
      },
      {
        "id": "voltage", "label": "Voltage", "unit": "V",
        "command": "MEAS:VOLT?", "interval_ms": 250,
        "parse": {"kind": "line", "value_type": "number"},
        "tile": {"col": 0, "row": 1, "span_w": 2, "span_h": 2, "kind": "value"}
      },
      {
        "id": "current", "label": "Current", "unit": "A",
        "command": "MEAS:CURR?", "interval_ms": 250,
        "parse": {"kind": "line", "value_type": "number"},
        "tile": {"col": 2, "row": 1, "span_w": 2, "span_h": 2, "kind": "value"}
      },
      {
        "id": "power", "label": "Power", "unit": "W",
        "source": "derived",
        "expression": "{Voltage} * {Current}",
        "tile": {"col": 4, "row": 1, "span_w": 2, "span_h": 2, "kind": "value"}
      },
      {
        "id": "v-set", "label": "Set V",
        "tile": {"col": 0, "row": 3, "span_w": 3, "span_h": 1, "kind": "setpoint"},
        "setpoint": {
          "min_value": 0, "max_value": 60, "step": 0.01,
          "decimals": 2, "unit": "V",
          "command_template": "VOLT {value}"
        },
        "readback": {"source": "entry", "watch_entry_id": "voltage"}
      },
      {
        "id": "i-set", "label": "Set I",
        "tile": {"col": 3, "row": 3, "span_w": 3, "span_h": 1, "kind": "setpoint"},
        "setpoint": {
          "min_value": 0, "max_value": 10, "step": 0.001,
          "decimals": 3, "unit": "A",
          "command_template": "CURR {value}"
        },
        "readback": {"source": "entry", "watch_entry_id": "current"}
      },
      {
        "id": "output", "label": "Output",
        "tile": {"col": 0, "row": 4, "span_w": 4, "span_h": 1, "kind": "control"},
        "control": {"mode": "toggle", "on_command": "OUTP ON", "off_command": "OUTP OFF"},
        "readback": {
          "source": "command",
          "command": "OUTP?",
          "parse": {"kind": "line", "value_type": "number"},
          "rules": [{"op": "eq_num", "operand": "1", "state": "ok", "label": "ON"}]
        }
      },
      {
        "id": "clear", "label": "Clear faults",
        "tile": {"col": 4, "row": 4, "span_w": 2, "span_h": 1, "kind": "control"},
        "control": {"mode": "button", "on_command": "*CLS", "confirm": true}
      },
      {
        "id": "operation", "label": "Operation — STAT:OPER:COND?",
        "command": "STAT:OPER:COND?", "interval_ms": 500,
        "parse": {"kind": "line", "value_type": "number"},
        "tile": {"col": 0, "row": 5, "span_w": 3, "span_h": 3, "kind": "bits"},
        "bits_spec": {
          "bits": [
            {"bit": 0, "label": "Calibrating",  "state": "neutral"},
            {"bit": 4, "label": "Measuring",    "state": "ok"},
            {"bit": 8, "label": "Configuring",  "state": "neutral"},
            {"bit": 9, "label": "Voltage avg",  "state": "neutral"},
            {"bit": 10, "label": "Trigger wait","state": "neutral"}
          ]
        }
      },
      {
        "id": "questionable", "label": "Questionable — STAT:QUES:COND?",
        "command": "STAT:QUES:COND?", "interval_ms": 500,
        "parse": {"kind": "line", "value_type": "number"},
        "tile": {"col": 3, "row": 5, "span_w": 3, "span_h": 3, "kind": "bits"},
        "bits_spec": {
          "bits": [
            {"bit": 0, "label": "Voltage",     "state": "fail",
             "description": "Voltage measurement out of range"},
            {"bit": 1, "label": "Current",     "state": "fail"},
            {"bit": 4, "label": "Temperature", "state": "warn"},
            {"bit": 8, "label": "Calibration", "state": "fail"},
            {"bit": 9, "label": "Self-test",   "state": "fail"}
          ]
        }
      }
    ]
  }]
}
```

The `power` tile is **derived** — no command, no poll. Whenever `Voltage` or `Current` updates, the funnel recomputes `{Voltage} * {Current}` and refreshes the power tile. Sparkline + chart history come for free.

## Patterns that show up across all three

- **Polled-text + rules → LED**. If the device reports state as a string, model it as a `value` or `led` tile with `value_type: "text"` and `contains` rules. Don't try to convert the string to a number first.
- **OVP / fault summary** as a single LED tile with one rule `gt 0 → fail` is enough for many panels; reach for `bits` when the operator needs to see *which* bit triggered.
- **Toggles should have readback** from a polled state tile or direct state query. Without readback, the toggle becomes a "fire-and-forget" button that can lie about whether the output is on.
- **Setpoints should use readback** from their measurement counterpart when one exists — the readback line makes commanded-vs-measured comparison instant.
