# GENESYS+ TCP/SCPI Simulator — Bench Setup Guide

`tools/genesys_sim.py` is a Python TCP server that pretends to be a TDK-Lambda
GENESYS+ power supply. It listens on TCP/8003 and responds to the SCPI subset
the v1 firmware emits, so you can validate the board's LAN stack end-to-end
without the real PSU. Every command received and every reply sent is logged
with a timestamp.

It has zero third-party dependencies — Python 3.8+ stdlib only.

## 1. Configure the PC's ethernet adapter

The board's firmware defaults to PSU target **192.168.10.3 : 8003** and board
IP **192.168.10.10** (see `SettingsBlob::defaults` in
`core/include/nextgen/settings/SettingsBlob.hpp`). Match the PC to that:

1. Plug your PC into the same physical link as the board (direct cable, or
   both into the same unmanaged switch).
2. **Settings → Network & Internet → Ethernet → Change adapter options.**
3. Right-click the adapter the cable lives on → **Properties**.
4. Select **Internet Protocol Version 4 (TCP/IPv4)** → **Properties**.
5. Set:
   - IP address: `192.168.10.3`
   - Subnet mask: `255.255.255.0`
   - Default gateway: *(leave blank)*
   - Preferred DNS: *(leave blank)*
6. OK out. The change takes effect immediately — no reboot needed.

Verify in an admin PowerShell:

```powershell
ipconfig | Select-String "Ethernet" -Context 0,6
```

You should see `IPv4 Address . . . 192.168.10.3` on the right adapter.

> **Tip.** If you have Wi-Fi enabled simultaneously and Windows insists on
> routing everything through it, leave Wi-Fi alone — the static IP on the
> ethernet adapter is enough for the board ↔ PC subnet. The simulator binds
> to `0.0.0.0` so it accepts from any interface.

## 2. Allow the simulator through Windows Defender Firewall

The first time you run the script, Windows pops up an "Allow Python
through the firewall?" dialog. Allow **Private networks** at minimum
(the bench cable is a private network as far as Windows is concerned).

If you missed the prompt, add the rule manually in an **admin**
PowerShell:

```powershell
New-NetFirewallRule -DisplayName "GenesysSim 8003" `
    -Direction Inbound -Protocol TCP -LocalPort 8003 -Action Allow `
    -Profile Private
```

Or temporarily disable the private-profile firewall for the bench
session only:

```powershell
netsh advfirewall set privateprofile state off
# restore when done:
netsh advfirewall set privateprofile state on
```

> **Symptom of a firewall block:** the simulator process is running but
> the board's `LwIP select result` is `0` (SYN timed out) and you never
> see a `CONN open` line in the simulator log. Means SYN packets are
> being dropped by Windows.

## 3. Run the simulator

From the repo root, in any terminal:

```powershell
py tools/genesys_sim.py
```

Or pick a different port / bind address:

```powershell
py tools/genesys_sim.py --port 8003 --host 0.0.0.0
```

You'll see:

```
HH:MM:SS.mmm BOOT GEN+ simulator listening on 0.0.0.0:8003
HH:MM:SS.mmm BOOT Press Ctrl+C to stop. Every command/response will be logged below.
```

CLI options:

| Flag                | Effect                                                 |
|---------------------|--------------------------------------------------------|
| `--host`            | bind address (default `0.0.0.0`)                       |
| `--port`            | TCP port (default `8003`)                              |
| `--no-color`        | plain text output (no ANSI colours)                    |
| `--inject-ov`       | start with `STAT:QUES` bit 4 (over-voltage) asserted   |
| `--inject-ot`       | start with `STAT:QUES` bit 2 (over-temp) asserted      |

## 4. Wire up

Either:

- **Direct cable.** Any Cat5e/6 cable. Both ends are auto-MDIX so no
  crossover needed. PC at 192.168.10.3, board at 192.168.10.10.

- **Via switch.** Plug PC and board into the same unmanaged switch.
  Same subnet (192.168.10.x). No switch config required.

Verify L3 connectivity from the PC before involving the firmware:

```powershell
ping 192.168.10.10
```

The board's LWIP responds to ICMP echo. If pings fail, the cable, the
PC's static-IP config, or the firewall is wrong — fix that first.

## 5. Operate from the board

1. Power the board (or reset it).
2. Navigate **Menu → LAN Settings**.
3. Confirm:
   - Target IP `192.168.10.3`
   - Port `8003`
4. Tap **Connect**.

The simulator should log:

```
CONN open  ← 192.168.10.10:<ephemeral>
RX   192.168.10.10:...  *CLS
RX   192.168.10.10:...  INSTrument:NSELect 0
RX   192.168.10.10:...  *IDN?
TX   192.168.10.10:...  TDK-LAMBDA,GEN-SIM-60-10,SN-0001,FW-1.0
RX   192.168.10.10:...  MEASure:VOLTage?
TX   192.168.10.10:...  0.000
...
```

And, on the board, the **LAN Settings** status line flips to
`LAN SCPI session` and the **LAN Debug** log records:

```
LwIP socket open 192.168.10.3:8003
LwIP socket connected
v1 LAN connected
```

If you don't see `CONN open` in the simulator log but the board says it
tried, the SYN packets aren't reaching the simulator — re-check
firewall / static-IP / cable.

## 6. Exercise the SCPI surface

Once connected, every UI action that emits SCPI shows up in the log:

| Board action                  | Simulator log                                    |
|-------------------------------|--------------------------------------------------|
| Change Voltage → keyboard OK  | `RX … SOURce:VOLTage 5.000`                      |
| Change Current → keyboard OK  | `RX … SOURce:CURRent 0.500`                      |
| Tap Output ON                 | `RX … OUTPut:STATe ON`                           |
| Tap Output OFF                | `RX … OUTPut:STATe OFF`                          |
| FaultPoller cycle (every 500 ms) | `STAT:QUES:COND?` / `STAT:OPER:COND?` pair    |
| OVP / UVL / Foldback edits    | `SOURce:VOLTage:PROTection:…`, `OUTPut:PROTection:FOLDback CC` |

Once `OUTPut:STATe ON` lands, the simulator pretends the output is live
— `MEASure:VOLTage?` returns the current setpoint, `MEASure:CURRent?`
returns `V/10 Ω` clamped to the current limit, and `OUTPut:MODE?`
reports `CV` or `CC` accordingly. Measurements should reflect on the
home screen within one FaultPoller cycle.

## 7. Inject faults

Want to verify the firmware's fault banner / output-auto-off behaviour?

- Start the simulator with `--inject-ov` — every `STAT:QUES:COND?`
  reply returns bit 4 set. The firmware's fault decoder should raise
  `FaultBit::OverVoltage`, the home banner should show, and (per safety
  invariants) `OUTPut:STATe` should be forced OFF.
- Or `--inject-ot` for over-temperature (bit 2).
- Combine: `py tools/genesys_sim.py --inject-ov --inject-ot`.

Both bits clear when the board sends `*CLS` or `OUTPut:PROTection:CLEar`
(triggered by the "Dismiss faults" UI action).

## 8. Shut down

Ctrl+C in the terminal stops the simulator cleanly. The board will see
the socket close and the v1 stack will fall back to its fast-retry
loop until you restart the simulator (or change the target IP).

## 9. Use the simulator as a library (project tests)

The same `tools/genesys_sim.py` is reused by the project's automated test
suite — see `tests/test_genesys_sim.py`. Two import surfaces are
exposed:

- **In-process dispatch** for unit-testing SCPI behaviour without a
  socket. Drive `Psu` state directly and assert on the dispatch
  return value:

  ```python
  from tools.genesys_sim import Psu, Handler        # if tools/ is on sys.path
  # or load by path:
  # import importlib.util; ...

  psu = Psu()
  handler = Handler(psu)
  assert handler.dispatch("*IDN?").startswith("TDK-LAMBDA")
  handler.dispatch("VOLT 5.0")
  handler.dispatch("OUTP ON")
  assert handler.dispatch("MEAS:VOLT?") == "5.000"
  ```

- **A live TCP server in a background thread** for end-to-end LAN
  tests. `serve_in_thread()` binds (`port=0` for an OS-assigned port),
  starts a daemon thread, and returns the server plus thread:

  ```python
  from tools.genesys_sim import serve_in_thread, Psu

  server, thread = serve_in_thread(host="127.0.0.1", port=0)
  port = server.server_address[1]
  psu  = server.psu                       # drive PSU state from the test
  psu.inject_fault(Psu.Q_OT)              # assert STAT:QUES bit 2 (OT)
  # ... open a TCP socket / LanClient against 127.0.0.1:port ...
  server.shutdown(); server.server_close()
  thread.join(timeout=2)
  ```

  `psu.clear_injected_faults(mask=None)` removes asserted bits at
  runtime (selective with a mask). The persistent `psu.questionable`
  register is still cleared only by `*CLS` / `OUTP:PROT:CLE`, which
  matches a real PSU's latched-fault semantics.

The test module loads the simulator via `importlib` from
`tools/genesys_sim.py` directly — no `__init__.py` is required in
`tools/`. Run it like any other project test:

```powershell
.\run_tests.bat tests.test_genesys_sim
```

### Latched OVP / UVP

`MEAS:VOLT?` driven above `SOUR:VOLT:PROT:LEV` (OVP) while the output
is on causes the simulator to (a) raise STAT:QUES bit 4 (`Q_OV`), and
(b) force `OUTP:STAT` to `0`. The bit is *persisted* in
`psu.questionable`, so `STAT:QUES:COND?` reports it on every later poll
until the firmware clears it with `*CLS` or `OUTP:PROT:CLE`. The same
applies to UVL (bit 9, `Q_UV`) when `v_set < uvl_level`.

This was a bug in earlier revisions of the simulator — the OV bit was
computed each call but never persisted, so a fast `STAT:QUES:COND?`
poll could miss it.

### Implicit `SOUR:` subsystem

SCPI lets clients drop the default subsystem prefix. The simulator's
dispatch tries `SOUR:<head>` whenever a command head isn't found in the
top-level table, so the example panel at
`examples/tdk-genplus-control-panel.json` can send raw
`VOLT:PROT:LEV 12.5` rather than `SOUR:VOLT:PROT:LEV 12.5` and still
hit the OVP setter.

## Troubleshooting flowchart

1. **Simulator log shows no `CONN open` at all.**
   - PC adapter not at 192.168.10.3 → fix step 1.
   - Firewall blocking 8003 → fix step 2.
   - Cable physically not connected / link LED off on switch → fix wiring.

2. **`CONN open` happens but disconnects immediately.**
   - Firmware closed the socket — check the board's LAN Debug log for
     `LwIP recv peer closed`, `LwIP send failed`, etc.

3. **Commands stream in but the board UI doesn't update.**
   - That's a UI / Model / DeviceState issue, not LAN. The bytes are
     getting through.

4. **`*IDN?` arrives but `OUTPut:STATe ON` is rejected by the board.**
   - Safety gate: the firmware refuses output-changing commands without
     a valid profile + setpoint + user-confirmation. See SDD §3.3.
