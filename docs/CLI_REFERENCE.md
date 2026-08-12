# ComPort Zone CLI Reference

The ComPort Zone CLI is for headless sends, receive capture, command-file
runs, Quick Command automation, and settings inspection. It uses the same
settings file as the desktop app.

Run the desktop app with no subcommand:

```powershell
comport-zone
```

Run the CLI with a subcommand:

```powershell
comport-zone --help
comport-zone send --help
```

## Connection Targets

The connect-using commands support serial COM ports, raw TCP endpoints, and
UDP endpoints:

- `send`
- `hex`
- `listen`
- `run`
- `repl`
- `quick send`
- `files run`

Use serial flags for COM ports:

```powershell
comport-zone send "*IDN?" --port COM3 --baud 115200 --line-ending LF
```

Use TCP flags for raw TCP endpoints:

```powershell
comport-zone send ping --host 127.0.0.1 --tcp-port 5025 --line-ending LF
```

Use UDP flags for UDP endpoints:

```powershell
comport-zone send ping --udp-host 127.0.0.1 --udp-port 5025 --line-ending LF
```

`--port` always means a serial COM port. `--host`, `--tcp-port`, and
`--tcp-timeout` select raw TCP; `--udp-host`, `--udp-port`, and `--udp-timeout`
select UDP. Flags from two different transports cannot be combined in the same
command (exit code 2).

When no explicit endpoint flags are supplied, the CLI uses the default
transport saved in the ComPort Zone settings. Command-line flags win over
`COMPORTZONE_*` environment variables, which win over the selected settings
file and built-in profile defaults.

### Shared Endpoint Flags

| Flag | Meaning |
| --- | --- |
| `--line-ending none|CR|LF|CRLF` | Line ending appended by text sends. |
| `--auto-reconnect` / `--no-auto-reconnect` | Reconnect preference on the profile. Accepted and ignored for UDP. |

### Serial Flags

| Flag | Meaning |
| --- | --- |
| `--port COM` | Serial port, for example `COM3`. |
| `--baud N` | Baud rate. |
| `--data-bits 5|6|7|8` | Serial data bits. |
| `--parity N|E|O|M|S` | Serial parity. |
| `--stop-bits 1|1.5|2` | Serial stop bits. |
| `--flow-control none|xonxoff|rtscts|dsrdtr` | Serial flow control. |
| `--dtr on|off` | DTR line state. |
| `--rts on|off` | RTS line state. |
| `--wait SECONDS` | Retry a busy serial port until the deadline. |

### Raw TCP Flags

| Flag | Meaning |
| --- | --- |
| `--host HOST` | TCP host name or IP address. |
| `--tcp-port PORT` | TCP port. The profile default is `5025`. |
| `--tcp-timeout MS` | TCP connect and read timeout in milliseconds. |

### UDP Flags

| Flag | Meaning |
| --- | --- |
| `--udp-host HOST` | UDP host name or IP address. |
| `--udp-port PORT` | UDP port. The profile default is `5025`. |
| `--udp-timeout MS` | Default reply-wait window in milliseconds (default `1000`). |

UDP is client-only: datagrams go to the configured peer from an
OS-assigned local port, and replies are read back from that peer. Notes that
follow from UDP having no connection:

- `--wait` is accepted and ignored. Opening a datagram socket performs no
  network I/O, so it fails only for deterministic reasons and retrying cannot
  change the outcome.
- `--auto-reconnect` is accepted and ignored. There is no link loss to detect.
- `--udp-timeout` is **not** a connect timeout. It is how long `send` holds a
  read window open when you give it no `--expect` or `--read-after`.
- In `listen`, one output record is one datagram. A reply with no trailing
  CR/LF still gets its own line.
- A datagram larger than the path MTU (roughly 1472 bytes on Ethernet)
  fragments; one larger than the socket send buffer fails loudly.
- Pointing at a port nobody is listening on does not close the session — the
  resulting ICMP port-unreachable is ignored, as UDP requires.

Useful endpoint environment variables are:

| Variable | Target |
| --- | --- |
| `COMPORTZONE_PORT` | Serial COM port. |
| `COMPORTZONE_BAUD` | Serial baud rate. |
| `COMPORTZONE_HOST` | TCP host. |
| `COMPORTZONE_TCP_PORT` | TCP port. |
| `COMPORTZONE_TCP_TIMEOUT_MS` | TCP timeout. |
| `COMPORTZONE_UDP_HOST` | UDP host. |
| `COMPORTZONE_UDP_PORT` | UDP port. |
| `COMPORTZONE_UDP_TIMEOUT_MS` | UDP reply-wait window. |
| `COMPORTZONE_LINE_ENDING` | Text line ending. |
| `COMPORTZONE_AUTO_RECONNECT` | Reconnect preference. |

## Global Options

Global options appear before the subcommand:

| Option | Use |
| --- | --- |
| `--json` | Emit machine-readable newline-delimited JSON output. |
| `--no-color` | Disable ANSI color. |
| `--quiet` | Suppress status messages. |
| `--verbose` | Include debug-style events when a command emits them. |
| `--config PATH` | Use a specific `settings.json` file. |

Examples:

```powershell
comport-zone --json send ping --port COM3 --read-after 250
comport-zone --config C:\bench\settings.json ports list
```

## TCP Echo Server Smoke Test

The repo ships a tiny localhost echo server you can use as a target. Start it
in one shell (it listens on `127.0.0.1:5025` — the TCP profile default, so
`--tcp-port` is optional):

```powershell
python resources/tcp_echo_server.py
```

It returns `PONG` for `ping`, the current time for `time`, and echoes any other
text. Then, from another shell, exercise the raw-TCP commands (adjust the host,
port, and line ending to match your own server):

```powershell
comport-zone send ping --host 127.0.0.1 --tcp-port 5025 --line-ending LF --expect PONG
```

```powershell
comport-zone send time --host 127.0.0.1 --tcp-port 5025 --line-ending LF --read-after 500
```

```powershell
comport-zone send "hello echo" --host 127.0.0.1 --tcp-port 5025 --line-ending LF --expect "hello echo"
```

```powershell
comport-zone --json send ping --host 127.0.0.1 --tcp-port 5025 --line-ending LF --expect PONG
```

```powershell
comport-zone send "round trip 123" --host 127.0.0.1 --tcp-port 5025 --line-ending LF --read-after 500
```

## UDP Echo Server Smoke Test

The UDP twin of the above. Start it in one shell (it binds `127.0.0.1:5025` —
the UDP profile default, so `--udp-port` is optional):

```powershell
python resources/udp_echo_server.py
```

It returns `PONG` for `ping`, the current time for `time`, and echoes anything
else — deliberately **without** a trailing CR/LF, which is what most datagram
devices do. Then, from another shell:

```powershell
comport-zone send ping --udp-host 127.0.0.1 --udp-port 5025 --expect PONG
```

```powershell
comport-zone send time --udp-host 127.0.0.1 --udp-port 5025 --read-after 500
```

```powershell
comport-zone --json send ping --udp-host 127.0.0.1 --udp-port 5025 --expect PONG
```

```powershell
comport-zone listen --udp-host 127.0.0.1 --udp-port 5025 --duration 5
```

To see the no-connection behaviour, aim at a port with no listener — the
command still opens and simply times out waiting for a reply:

```powershell
comport-zone send ping --udp-host 127.0.0.1 --udp-port 5099 --read-after 500
```

## Commands

### `version`

Print the installed ComPort Zone version:

```powershell
comport-zone version
comport-zone --json version
```

### `ports`

List or inspect serial ports:

```powershell
comport-zone ports list
comport-zone ports info COM3
```

`ports` is serial-only because TCP and UDP endpoints are supplied explicitly.

### `send`

Open an endpoint, send one text payload, optionally read RX, then close:

```powershell
comport-zone send ping --port COM3 --expect PONG --expect-timeout 1000
comport-zone send time --host instrument.local --tcp-port 5025 --read-after 500
comport-zone send time --udp-host instrument.local --udp-port 5025 --read-after 500
```

Useful options:

| Option | Use |
| --- | --- |
| `--expect REGEX` | Require received text to match before the timeout. |
| `--expect-timeout MS` | Timeout used by `--expect`. |
| `--read-after MS` | Print RX collected after the send. |
| `--hex` | Parse the `TEXT` argument as hex bytes. |

`--expect` failure exits with code `11`.

### `hex`

`hex` is a convenience alias for sending byte tokens:

```powershell
comport-zone hex 55 AA 03 --port COM3 --read-after 250
comport-zone hex 01 02 FF --host 127.0.0.1 --tcp-port 5025
```

### `listen`

Stream received data until `Ctrl+C` or a duration deadline:

```powershell
comport-zone listen --port COM3
comport-zone listen --host 127.0.0.1 --tcp-port 5025 --duration 10
comport-zone listen --port COM3 --filter "^ERR" --timestamps --log C:\logs\rx.log
comport-zone listen --port COM3 --hex
```

### `run`

Execute a command file against an endpoint:

```powershell
comport-zone run C:\bench\smoke.txt --port COM3
comport-zone run C:\bench\tcp-smoke.txt --host 127.0.0.1 --tcp-port 5025
comport-zone run C:\bench\set-voltage.txt --port COM3 --param VOLT=3.3 --non-interactive
```

Command files can contain `SEND`, `HEX`, `WAIT`, and `EXPECT` steps. The run
command also supports `--log`, `--expect-timeout`, and
`--continue-on-expect-fail`.

### `validate`

Validate a command file without connecting:

```powershell
comport-zone validate C:\bench\smoke.txt
```

### `repl`

Start an interactive prompt on the selected endpoint:

```powershell
comport-zone repl --port COM3
comport-zone repl --host 127.0.0.1 --tcp-port 5025
```

Text typed at `TX> ` is sent to the connected endpoint. REPL meta commands
include:

| Meta command | Use |
| --- | --- |
| `/help` | Show REPL help. |
| `/connect`, `/disconnect`, `/reconnect` | Control the current endpoint. |
| `/set KEY VALUE` | Change a current serial or TCP endpoint setting. |
| `/show settings`, `/show endpoint` | Inspect the current profile or connection. |
| `/hex BYTES` | Send raw hex bytes. |
| `/quick LABEL_OR_ID` | Send a saved Quick Command. |
| `/run FILE --param K=V` | Run a command file without leaving the REPL. |
| `/log start PATH`, `/log stop` | Mirror RX and TX to a log file. |
| `/timestamps on|off` | Toggle timestamps for printed RX. |
| `/quit` | Exit. |

### `quick`

Manage saved Quick Commands and send them through the same endpoint flags:

```powershell
comport-zone quick list
comport-zone quick add --label Ping --command ping --line-ending LF
comport-zone quick send Ping --host 127.0.0.1 --tcp-port 5025
comport-zone quick edit Ping --group Smoke
comport-zone quick export C:\bench\quick-commands.csv
comport-zone quick import C:\bench\quick-commands.csv --mode append
comport-zone quick remove Ping
```

### `files`

Manage saved Quick Files and run a saved label, id, or direct path:

```powershell
comport-zone files list
comport-zone files add --label Smoke --path C:\bench\smoke.txt
comport-zone files run Smoke --port COM3
comport-zone files run C:\bench\tcp-smoke.txt --host 127.0.0.1 --tcp-port 5025
comport-zone files export C:\bench\quick-files.csv
```

### `settings`

Inspect or transfer app settings:

```powershell
comport-zone settings show
comport-zone settings show --section transport
comport-zone settings get transport.profile.line_ending
comport-zone settings set app.timestamps_enabled false
comport-zone settings export C:\bench\app-settings.json
comport-zone settings import C:\bench\app-settings.json --dry-run
```

### `history`

Inspect or clear the command history shared with the app:

```powershell
comport-zone history list
comport-zone history clear
```

### `update`

Check for a newer GitHub release:

```powershell
comport-zone update check
```

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Generic error, including a raw TCP connect failure. |
| `2` | Usage error. |
| `10` | Serial port busy. |
| `11` | `EXPECT` pattern not seen. |
| `12` | Required command-file parameter missing. |
| `13` | Command-file parse error. |
| `14` | Serial port not found. |
| `15` | Settings save/load error. |
| `130` | Interrupted. |
