# Command-file scripting

Use a `.cpz` plain-text file to repeat device checks, capture replies, and choose
the next commands from the values you receive. The same scripts run in the
desktop app, `comport-zone run`, and the CLI REPL's `/run` command.

Many thanks to **[George Hanna (@georgehanna1993)](https://github.com/georgehanna1993)**
for his generous code donation of the scripting features introduced in v0.8.0.

## Try the bundled example without a device

The [scripting tour](../src/ComPort_Zone/assets/example-scripting.cpz) uses the
repository's TCP echo server. It sends `ping`, captures `PONG`, repeats a
parameterized number of checks, logs the server's time, and exits a `LOOP FOREVER`
with `BREAK` when the endpoint replies. It sends no instrument configuration commands.

1. From the repository root, start the server in one terminal:

   ```powershell
   python resources/tcp_echo_server.py
   ```

2. Leave it running. In another terminal with ComPort Zone installed, validate
   the example, then run it:

   ```powershell
   comport-zone validate src/ComPort_Zone/assets/example-scripting.cpz
   comport-zone run src/ComPort_Zone/assets/example-scripting.cpz --host 127.0.0.1 --tcp-port 5025 --line-ending CRLF --param COUNT=3 --non-interactive --log scripting.log
   ```

   Expect three `Ping passed: PONG` messages, a server timestamp, an endpoint-ready
   message, and `Scripting tour complete`. The run summary should report zero
   response failures. Add `--param MESSAGE=hello` to exercise the `ELSE` branch.

3. To try it in the desktop app, create a terminal tab, choose **TCP** in
   Connection Settings, enter host `127.0.0.1` and port `5025`, select **CRLF**,
   and connect. Open the example in the command-file editor, select that terminal
   as the run target, and run it. Fresh installations list **Scripting (loops and
   capture)** in the Files drawer. Existing installations can open the bundled
   `ComPort_Zone/assets/example-scripting.cpz` in the installation folder or
   download the linked example and add it to Files.

The echo server needs Python; the installed desktop app and portable build do
not. You can also adapt the example to a real device by replacing its commands
and response patterns with those described in the device's manual.

## Commands

Script keywords are case-insensitive. Variable names and text comparisons are
case-sensitive. Blank lines and `#` comment lines are ignored; `//` starts an
inline comment. Indentation helps readability but does not define a block.

| Command | What it does |
| --- | --- |
| `SEND text` or a bare command | Sends text with the connection's line ending. |
| `HEX 55 AA 0D` | Sends raw bytes without adding a line ending. |
| `WAIT 250` | Waits 250 milliseconds once. |
| `EXPECT READY` | Waits for received text containing `READY`. |
| `CAPTURE VALUE REGEX pattern` | Waits for a regex match and stores its first group, or the whole match when there is no group, in `$VALUE`. |
| `SET NAME value` | Creates or replaces a runtime variable; matching outer single or double quotes are removed. |
| `NAME:INCREMENT [amount]` | Adds `amount` to an existing numeric runtime variable; the default amount is `1`. |
| `NAME:DECREMENT [amount]` | Subtracts `amount` from an existing numeric runtime variable; the default amount is `1`. |
| `PAUSE [message]` | Pauses at an operator checkpoint until the user continues the run. |
| `LOG message` | Writes a progress message after substituting runtime variables. Desktop output uses a distinct `MSG` row; CLI `--log` files include the message. |
| `LOOP 3` ... `ENDLOOP` | Repeats the enclosed steps three times. Counts must be positive whole numbers. Blocks can be nested. |
| `LOOP FOREVER` ... `ENDLOOP` | Repeats until `BREAK`, desktop Stop, a stopping error, or CLI Ctrl+C. `INFINITE` is an alias for `FOREVER`. |
| `BREAK` | Leaves only the innermost loop. It must appear inside a loop. |
| `IF left operator right` ... `ELSE` ... `ENDIF` | Runs the matching branch; `ELSE` is optional. Conditions and loops may nest but their blocks must not cross. |

Use `SEND` explicitly if a device command begins with a scripting keyword or
matches a variable-action shape. For example, `SEND SET MODE FAST` sends the
literal device command instead of creating a script variable, and
`SEND VOLT:INCREMENT 1` sends that exact device command rather than changing
`$VOLT`; `SEND PAUSE` sends the literal device command instead of pausing the
script. Close every `LOOP` with `ENDLOOP` and every `IF` with
`ENDIF`; the editor and CLI validator report unbalanced blocks before a run.

## Parameters and runtime variables

`{{NAME}}` asks for a value before the desktop run; `{{NAME=default}}` offers a
default. The same parameter value is reused throughout that run. The CLI takes
`--param NAME=value`; use `--non-interactive` to fail instead of prompting when a
required parameter is missing. Parameters work in loop counts and other commands:

```text
LOOP {{COUNT=3}}
    SEND STATUS?
    EXPECT READY
    WAIT {{DELAY=250}}
ENDLOOP
```

`$NAME` is a separate value created by `SET` or `CAPTURE` during execution. It is
local to one run and does not change saved settings or parameter defaults. These
values can be used in `SEND`, `EXPECT`, `CAPTURE` patterns, `SET`, `LOG`, variable
action amounts, and IF operands. They cannot supply `WAIT` durations, `LOOP` counts, `HEX` bytes, or
`@@` settings; use parameters for those fields. Use `$$` in script text for a
literal dollar sign. Runtime substitution does not evaluate arithmetic.

Variable actions provide the intentional arithmetic operation. The target must
already exist, variable names remain case-sensitive, and both its current value
and the amount must be finite numbers. Amounts must be non-negative; choose the
action to select the direction. Actions are internal and produce no TX traffic:

```text
SET volt 0
SET curr 10
SET step 0.25
volt:increment             // $volt is now 1
volt:increment $step       // $volt is now 1.25
curr:decrement 2           // $curr is now 8
LOG volt=$volt curr=$curr
```

## Operator checkpoints

`PAUSE` stops before the next step. An optional message supports parameters and
runtime variables, which makes the reason for the checkpoint visible:

```text
SET VOLTAGE 1
LOOP 50
    LOG Testing Voltage = $VOLTAGE
    SEND volt $VOLTAGE
    PAUSE Inspect voltage $VOLTAGE, then continue
    VOLTAGE:INCREMENT 1
ENDLOOP
```

In the desktop app, a modal checkpoint popup displays the resolved message.
Press Return, Enter, or Space, or click **Continue**, to resume. Click **Stop
Script** or close the popup to cancel the run. A disconnect keeps the run paused
until the endpoint is reconnected. In the CLI, press Enter at the prompt;
`--non-interactive` rejects a script when it reaches `PAUSE` instead of hanging.
`PAUSE` consumes no RX data and sends nothing to the device.

```text
SET LIMIT {{LIMIT=12.5}}
SEND MEAS:VOLT?
CAPTURE VOLTAGE REGEX VOLT:\s*([0-9.]+)\s+V\r?\n
LOG Measured $VOLTAGE V; limit is $LIMIT V
IF $VOLTAGE > $LIMIT
    LOG Voltage is above the limit
ELSE
    LOG Voltage is within the limit
ENDIF
```

This snippet assumes a reply such as `VOLT: 13.7 V` followed by a newline.
Adapt the pattern to your device. Include a unit or delimiter after a number
when you need the complete value: a regex such as `([0-9.]+)` can match `13.`
before the rest of a fragmented reply has arrived. A match may span RX chunks.
Matching consumes received text through the end of the match, so a later
`EXPECT` or `CAPTURE` does not reuse the same reply. Sending another command
clears the previous response buffer. CAPTURE patterns use Python regex syntax;
substituted variable contents are inserted as regex text, not automatically escaped.

## Conditions

Put spaces around operators. Supported operators are `==`, `!=`, `<`, `<=`, `>`,
`>=`, `CONTAINS`, and `NOT CONTAINS`. Equality compares numerically when both
operands are numbers, otherwise it compares case-sensitive text. Relational
operators require numbers. Quote literal text containing spaces or operator text:

```text
IF "DEVICE READY" CONTAINS READY
    LOG Device is ready
ENDIF
IF "A > B" == "A > B"
    LOG Quoted operators are ordinary text
ENDIF
```

## Timeouts, errors, pause, and stop

Settings persist from their line until changed again or until the run ends:

| Directive | Effect |
| --- | --- |
| `@@wait 100` | Delays before every following SEND/HEX; `0` disables the delay. |
| `@@expect-timeout 2000` | Sets the following EXPECT/CAPTURE timeout to 2,000 milliseconds; the default is 1,000. |
| `@@on-error stop` | Stops on a failed step; this is the default. |
| `@@on-error continue` | Reports ordinary step failures and continues. A condition using an undefined variable still stops before either branch runs. |
| `@@send-mode hex` | Interprets following bare/SEND commands as hex bytes. Use `text` to switch back; explicit HEX always sends raw bytes. |

Place `@@` directives at the beginning of a line. If a CAPTURE times out, it
does not assign a new value; an existing value of the same name remains from an
earlier iteration. Prefer the default stop behavior when decisions must use a
fresh reply. Numeric-condition errors and malformed script structure also stop
the run.

On the desktop, **Pause** blocks the next step, including LOG, SET, and control
flow. **Resume** continues. A disconnected run waits for both a restored
connection and a manual Resume. **Stop** ends the run, including a paused or
infinite loop. Add a WAIT or response wait to repeating loops to control their
pace. The CLI uses **Ctrl+C** to interrupt; it has no interactive pause/resume.

CLI EXPECT/CAPTURE timeouts exit `11` by default. Choosing to continue can still
produce exit `0`, with the response failures counted in the summary. Check the
log or structured events when that distinction matters. Use `--json` for
structured CLI output and `--log PATH` for a readable run log. Validation checks
syntax and block structure without connecting; it cannot prove that a device
will reply or that a runtime variable will be assigned on every path.
