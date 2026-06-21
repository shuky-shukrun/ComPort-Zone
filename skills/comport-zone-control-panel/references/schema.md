# Control-Panel JSON — field reference

App: ComPort Zone ≥ 0.5.0 · Panel schema: 3

Numbers in `<…>` are clamps the importer enforces. Anything you write is silently coerced into range, so over-shoots become bounds rather than rejections.

## Envelope

```jsonc
{
  "comport_zone_control_panels": 3,        // schema version. 1 / 2 also load.
  "control_panels": [ /* one or more panel configs */ ]
}
```

The importer rejects files where the wrapper key is missing, the version is not an integer, or `"control_panels"` is empty.

## Panel config

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `id` | string (uuid hex) | random | Stable identifier. Collisions on import auto-resolve. |
| `name` | string | `"ControlPanel"` | Shown in tab title + library list. Blank falls back to default. |
| `description` | string | `""` | Free text; shown in the manager dialog tooltip. |
| `columns` | int | `4` | Grid columns. Range `1..12`. |
| `rows` | int | `5` | Minimum visible rows; the grid auto-expands when tiles overflow. Range `1..24`. |
| `favorite` | bool | `false` | Pins the panel to the sidebar "Favorites" rail. |
| `csv_log_enabled` | bool | `false` | Persisted CSV-log toggle. Path lives in `csv_log_path`. |
| `csv_log_path` | string | `""` | Destination file when logging is on. |
| `entries` | list | `[]` | The tiles. Each entry maps to one tile on the grid. |
| `created_at`, `updated_at` | ISO-8601 string | now (UTC) | Touch timestamps. Omit and the importer fills them. |

## Entry

Each entry is one tile. The same dataclass holds every shape — fields that don't apply to the chosen `tile.kind` are simply ignored on render. Be sparse where you can: omit defaults, write the rest.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `id` | string | random | Unique inside the panel. Used by `readback.watch_entry_id` and derived expressions. |
| `label` | string | `""` | Tile title. Falls back to `command` / `expression` if blank. |
| `unit` | string | `""` | Appended to the numeric value on the tile (e.g. `"V"`). |
| `command` | string | `""` | Send-string for polled / bits tiles. Empty for writing / derived tiles. |
| `send_mode` | enum | `"Text"` | `"Text"` or `"Hex Bytes"`. Hex mode parses the command as hex bytes. |
| `line_ending_override` | enum | `""` | `""` (use session default), `"None"`, `"CR"`, `"LF"`, `"CRLF"`. |
| `interval_ms` | int | `1000` | Poll period. Range `100..3_600_000`. |
| `timeout_ms` | int | `500` | RX window. Range `50..30_000`. |
| `stale_after_ms` | int | `0` | 0 = auto (≈ `max(3*interval, interval+timeout+1000)`). |
| `parse` | `ParseRule` | line / number | See below. |
| `tile` | `TilePlacement` | (0,0,1,1,value) | See below. |
| `rules` | list of `ColorRule` | `[]` | Evaluated top-down; first match wins. |
| `enabled` | bool | `true` | When false the tile renders dim and never polls / sends. |
| `poll_mode` | enum | `"interval"` | `"interval"` or `"on_connect"` (run once per bind). |
| `target_endpoint` | string | `""` | Optional per-entry override of the panel's bound session (rare). |
| `source` | enum | `"poll"` | `"poll"` or `"derived"` (derived tiles use `expression`). |
| `expression` | string | `""` | Derived-tile formula: `"{Volts} * {Amps}"`. Max 256 chars. |
| `show_sparkline` | bool | `true` | Numeric tiles paint a 120 s sparkline by default. |
| `alerts_enabled` | bool | `true` | Whether transitions into `fail`/`error` ring the bell. |
| `control` | `ControlSpec` | empty | Required when `tile.kind == "control"`. |
| `setpoint` | `SetpointSpec` | empty | Required when `tile.kind == "setpoint"`. |
| `enum_spec` | `EnumSpec` | empty | Required when `tile.kind == "enum"`. |
| `bits_spec` | `BitsSpec` | empty | Required when `tile.kind == "bits"`. |
| `readback` | `ReadbackSpec` | empty | Optional for writing tiles; follows another tile or sends a direct readback command. |
| `created_at`, `updated_at` | ISO-8601 string | now | Omit; importer fills. |

## TilePlacement

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `col` | int | 0 | Range `0..columns-1`. |
| `row` | int | 0 | Range `0..10_000` (the grid expands vertically). |
| `span_w` | int | 1 | Range `1..5` (clamped further by panel `columns`). |
| `span_h` | int | 1 | Range `1..5`. |
| `kind` | enum | `"value"` | One of `value / led / control / setpoint / enum / bits`. |

Layout is normalized at load: ties go to (row, col, id) order; overlaps push later tiles down one row at a time. Lay them out cleanly to avoid surprises.

## ParseRule

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `kind` | enum | `"line"` | `"line"` (first complete RX line) or `"regex"`. |
| `pattern` | string | `""` | Regex pattern when `kind="regex"`. |
| `group` | int or string | `1` | Capture group index or name. `0` = whole match. |
| `value_type` | enum | `"text"` | `"text"` or `"number"`. Numeric powers sparkline / chart / bits decoding. |

## ColorRule

Used on `value` and `led` tiles to convert the parsed value into a state color.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `op` | enum | `"eq_num"` | `lt / le / gt / ge / eq_num / ne_num / between / eq_text / contains / matches`. |
| `operand` | string | `"0"` | First comparand. For `between` this is the low edge. |
| `operand2` | string | `""` | Only used by `between` (high edge). |
| `state` | enum | `"ok"` | `"ok"`, `"warn"`, or `"fail"`. |
| `label` | string | `""` | Optional caption to show in place of the raw value (LED tiles). |
| `color` | string | `""` | Optional `#rrggbb` override of the state color. |

Numeric ops compare the parsed number. `eq_text` / `contains` compare the raw value text (case-insensitive). `matches` runs a regex against the value text.

## ControlSpec (kind = `control`)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `mode` | enum | `"button"` | `"button"` (single shot) or `"toggle"` (alternates on/off). |
| `on_command` | string | `""` | Sent on click / on-toggle. Required. |
| `off_command` | string | `""` | Sent on off-toggle. Required for toggles. |
| `confirm` | bool | `false` | Show a confirmation prompt before sending. |

## SetpointSpec (kind = `setpoint`)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `min_value` | float | `0.0` | Slider / spinbox minimum. |
| `max_value` | float | `100.0` | Maximum. Must be > min. |
| `step` | float | `1.0` | Slider step + spinbox step. Must be > 0 and ≤ max-min. |
| `decimals` | int | `2` | Display precision. Range `0..6`. |
| `unit` | string | `""` | Suffix on the spinbox (e.g. `"V"`). |
| `command_template` | string | `""` | Send-string with exactly one `{value}` token. Required. |
| `confirm` | bool | `false` | Confirmation prompt before each send. |

## EnumSpec (kind = `enum`)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `options` | list of `EnumOption` | `[]` | At least one option required. |
| `confirm` | bool | `false` | Confirmation prompt before each send. |

`EnumOption`:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `label` | string | `""` | Dropdown row text. Required. |
| `command` | string | `""` | Sent when this option is selected + Send. Required. |
| `match_value` | string | `""` | When equal (trimmed, case-insensitive) to the readback value, this row gets the indicator pill. |

## ReadbackSpec (writing entries: `control`, `setpoint`, `enum`)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `source` | enum | `"none"` | `"entry"` follows another tile; `"command"` sends this tile's readback command. |
| `watch_entry_id` | string | `""` | Required when `source="entry"`; must be another entry id in the same panel. |
| `command` | string | `""` | Required when `source="command"`; sent once on connect and after writes. |
| `mode` | enum | `"once"` | `"once"` pulls after each write; `"interval"` keeps polling periodically. |
| `delay_ms` | int | `20` | Delay before the post-write readback. Range `0..60000`. |
| `interval_ms` | int | `1000` | Repeat period when `mode="interval"`. Range `20..3600000`. |
| `timeout_ms` | int | `500` | Readback response timeout. Range `50..30000`. |
| `parse` | `ParseRule` | line/text | Used for direct command readbacks. |
| `rules` | list of `ColorRule` | `[]` | Direct readback state rules; toggles treat `ok` as ON and enums match option `match_value`. |

## BitsSpec (kind = `bits`)

A status / fault register tile. The entry has a regular `command` + `parse` (use `value_type: "number"`); the int is decoded per bit.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `bits` | list of `BitDefinition` | `[]` | At least one bit required. |

`BitDefinition`:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `bit` | int | `0` | Bit position, `0..31`. **No duplicates** in the same spec. |
| `label` | string | `""` | Indicator caption. Required. |
| `state` | enum | `"warn"` | `"ok" / "warn" / "fail" / "neutral"` — lamp color when the bit is set. |
| `description` | string | `""` | Tooltip text. Optional but recommended. |

Multiple bits can be active simultaneously — that's the whole point. Bit 0 is the least-significant bit. If the instrument returns a hex literal like `0xFF`, the bits widget falls back to `int(text, 0)` so you don't need to change the parse rule.

## Validation summary

The importer rejects an entry when:
- it's a control / setpoint / enum tile with missing or malformed spec fields (no command, no `{value}` token, no options, …);
- it's a derived tile with empty / oversize / unresolved-reference expression;
- it's any other entry with an empty command, an invalid hex payload (in Hex Bytes mode), a malformed regex, or invalid color-rule operands;
- it's a bits tile with no bits, a duplicate bit position, or a label-less bit.

Numeric clamps (interval, timeout, span, columns, …) are silently clamped, not rejected.

## Re-export round-trip

Once your panel imports cleanly, **re-exporting it from ComPort Zone is the canonical form** — the app writes the same fields in stable order with the schema version stamp. If your hand-written JSON survives an import + re-export round-trip without changes you didn't intend, you're done.
