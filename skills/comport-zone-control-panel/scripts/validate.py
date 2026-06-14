#!/usr/bin/env python3
"""Validate a ComPort Zone Control Panel JSON file.

Checks the file against the bundled JSON Schema (Draft-7) and adds a
few semantic checks the schema can't express on its own:

  * panel must contain at least one entry
  * entry ids must be unique inside a panel
  * setpoint command_template must contain exactly one {value} token
  * enum specs must have at least one option, each with label + command
  * bits specs must have at least one bit, no duplicate positions,
    every bit must have a non-empty label
  * watch_entry_id targets must exist in the same panel
  * derived entries (source=derived) must carry an expression

Usage:
    python validate.py path/to/panel.json [more.json ...]

Exit code is 0 when every file passes, 1 otherwise.

Dependencies: jsonschema (pip install jsonschema). The bundled schema
travels with this script under ../assets/control-panel.schema.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft7Validator
except ImportError:
    sys.stderr.write(
        "validate.py needs the `jsonschema` package.\n"
        "Install it with:  pip install jsonschema\n"
    )
    raise SystemExit(2)


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "assets" / "control-panel.schema.json"


def _load_schema():
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _semantic_checks(payload) -> list[str]:
    """Rules JSON Schema can't express. Returns a list of human-readable
    error strings (empty list = OK)."""
    errors: list[str] = []
    panels = payload.get("control_panels") or []
    for panel_idx, panel in enumerate(panels):
        if not isinstance(panel, dict):
            continue
        panel_tag = f"panel[{panel_idx}] {panel.get('name', '<unnamed>')!r}"
        entries = panel.get("entries") or []
        if not entries:
            errors.append(f"{panel_tag}: must have at least one entry")
            continue

        ids = [e.get("id") for e in entries if isinstance(e, dict)]
        reported: set[str] = set()
        for entry_id in ids:
            if entry_id and entry_id not in reported and ids.count(entry_id) > 1:
                errors.append(f"{panel_tag}: duplicate entry id {entry_id!r}")
                reported.add(entry_id)
        id_set = {e.get("id") for e in entries if isinstance(e, dict) and e.get("id")}

        for entry_idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            entry_tag = (
                f"{panel_tag} entry[{entry_idx}] "
                f"{entry.get('id') or entry.get('label') or '<?>'!r}"
            )
            kind = (entry.get("tile") or {}).get("kind", "value")
            source = entry.get("source", "poll")

            # Derived entries need an expression.
            if source == "derived" and not (entry.get("expression") or "").strip():
                errors.append(f"{entry_tag}: source='derived' requires non-empty expression")

            # Polled entries need a command (writing tiles are exempt — they send).
            writing = kind in {"control", "setpoint", "enum"}
            if (
                not writing
                and source != "derived"
                and not (entry.get("command") or "").strip()
            ):
                errors.append(f"{entry_tag}: polled entry needs a command")

            if kind == "setpoint":
                spec = entry.get("setpoint") or {}
                template = spec.get("command_template", "")
                if template.count("{value}") != 1:
                    errors.append(
                        f"{entry_tag}: setpoint command_template must contain exactly one "
                        f"'{{value}}' token (got {template.count('{value}')} in {template!r})"
                    )
                if spec.get("min_value") is not None and spec.get("max_value") is not None:
                    if float(spec["min_value"]) >= float(spec["max_value"]):
                        errors.append(f"{entry_tag}: setpoint min_value must be < max_value")
                if spec.get("step") is not None and spec.get("step", 0) <= 0:
                    errors.append(f"{entry_tag}: setpoint step must be > 0")
                watch = spec.get("watch_entry_id", "")
                if watch and watch not in id_set:
                    errors.append(
                        f"{entry_tag}: setpoint watch_entry_id {watch!r} not in panel"
                    )

            if kind == "control":
                spec = entry.get("control") or {}
                if not (spec.get("on_command") or "").strip():
                    errors.append(f"{entry_tag}: control needs on_command")
                if spec.get("mode") == "toggle" and not (spec.get("off_command") or "").strip():
                    errors.append(f"{entry_tag}: toggle control needs off_command")
                watch = spec.get("watch_entry_id", "")
                if watch and watch not in id_set:
                    errors.append(
                        f"{entry_tag}: control watch_entry_id {watch!r} not in panel"
                    )

            if kind == "enum":
                spec = entry.get("enum_spec") or {}
                options = spec.get("options") or []
                if not options:
                    errors.append(f"{entry_tag}: enum needs at least one option")
                for opt_idx, opt in enumerate(options):
                    if not (opt.get("label") or "").strip():
                        errors.append(
                            f"{entry_tag}: enum option[{opt_idx}] needs a label"
                        )
                    if not (opt.get("command") or "").strip():
                        errors.append(
                            f"{entry_tag}: enum option[{opt_idx}] needs a command"
                        )
                watch = spec.get("watch_entry_id", "")
                if watch and watch not in id_set:
                    errors.append(
                        f"{entry_tag}: enum watch_entry_id {watch!r} not in panel"
                    )

            if kind == "bits":
                spec = entry.get("bits_spec") or {}
                bits = spec.get("bits") or []
                if not bits:
                    errors.append(f"{entry_tag}: bits tile needs at least one bit")
                seen_positions: set[int] = set()
                for bit_idx, bit in enumerate(bits):
                    pos = bit.get("bit")
                    if pos in seen_positions:
                        errors.append(
                            f"{entry_tag}: bit position {pos} is defined more than once"
                        )
                    seen_positions.add(pos)
                    if not (bit.get("label") or "").strip():
                        errors.append(
                            f"{entry_tag}: bit[{bit_idx}] (position {pos}) needs a label"
                        )

    return errors


def validate_file(path: Path) -> bool:
    """Validate ``path``; return True on success."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {path}: cannot parse JSON — {exc}")
        return False

    schema = _load_schema()
    validator = Draft7Validator(schema)
    schema_errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    semantic_errors = _semantic_checks(payload)

    if not schema_errors and not semantic_errors:
        panels = payload.get("control_panels", [])
        entries = sum(len(p.get("entries") or []) for p in panels)
        print(f"[OK]  {path}: {len(panels)} panel(s), {entries} entr{'y' if entries == 1 else 'ies'}")
        return True

    print(f"[FAIL] {path}:")
    for err in schema_errors:
        location = "/".join(str(p) for p in err.path) or "<root>"
        print(f"  schema · {location}: {err.message}")
    for err in semantic_errors:
        print(f"  semantic · {err}")
    return False


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python validate.py path/to/panel.json [more.json ...]", file=sys.stderr)
        return 2
    ok = True
    for arg in argv:
        if not validate_file(Path(arg)):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
