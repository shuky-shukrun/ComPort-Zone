# ComPort Zone tutorial transcript

## Connect. Inspect. Automate.

Welcome to ComPort Zone, a terminal and automation workbench for Windows. In this tutorial, we will identify a device, save useful commands, run a repeatable check, and build a live monitoring panel. Everything shown uses a local demonstration instrument. You can follow along without a physical board, a serial adapter, or a COM port.

## Install and open the application

Download the Windows installer or portable zip from the project's releases page. Run the installer, or extract the whole portable folder and open the application. The packaged desktop app includes its own runtime. If you are working from source, run the setup development batch file, followed by the launch app batch file. The illustrated manual covers both installation paths.

## Start the tutorial instrument

The tutorial device is a small Python script in the tools, media folder. Open PowerShell in the repository and run the command shown here. It uses only Python's standard library. Keep that terminal open while following the tutorial. The server listens on your own computer, on port fifty twenty five. Its voltage, current, temperature, and status readings are simulated.

## Find your way around

The center of the window is a workspace for terminal, editor, and Control Panel tabs. The drawer on the left keeps favorites, saved commands, files, and history close at hand. In a terminal, outgoing and incoming messages use separate rows and colors. The editable line begins with the transmit prompt. The connection indicator and footer help you confirm the current target.

## Connect to the local device

Open Connection Settings for your terminal tab. Choose TCP, enter the localhost address shown here, set the port to fifty twenty five, and select carriage return plus line feed. Accept the settings and connect. A green connection indicator means the socket is open. These settings belong to this tab, so another terminal can use a different connection and a different device.

## Send your first query

Click after the transmit prompt, type the identification query shown on screen, and press Enter. The demo replies with its name and serial number. You have now checked the complete path from the application to the target and back. Device commands depend on your instrument or firmware. ComPort Zone sends them; it does not require every device to understand this particular identification query.

## Read measurements and status

Try the voltage, current, temperature, and status queries. At the default settings, voltage is near twelve volts, current is near zero point four two amps, and status is ready. Small changes between readings are intentional. Notice how timestamps and message direction make it easy to associate a query with its reply. Keep this terminal connected for the automation and monitoring examples.

## Connect a real serial device

For a physical serial device, create another terminal and select Serial instead. Pick its COM port and match the baud rate, data bits, parity, stop bits, and flow control to the firmware documentation. Set the required line ending. DTR and RTS can affect the board, so choose their states intentionally. The local tutorial demonstrates traffic over TCP; this serial settings screen is a configuration example.

## Understand TCP and UDP

TCP provides a connected byte stream. UDP sends separate datagrams and does not establish a remote connection. For UDP, a green indicator means the local socket is available, not that a device has answered. The tutorial server supports both on the same port, so you can try a UDP terminal later. Serial and TCP support auto reconnect; UDP has no connection to reestablish.

## Write, then verify by reading back

Send the voltage setting command, followed by the voltage query. The write is silent; the query confirms the new setting. This is common for instrument protocols. A missing reply to a write is not automatically an error. Verify changes using the device's documented readback command. Reset the demonstration instrument before the next exercise so its output is enabled and its voltage returns to twelve volts.

## Recall and find commands

Use the up and down arrows to recall earlier commands. Control plus Space offers completions from history and saved commands. The History page provides another way to find and reuse what you sent. Control plus F searches the terminal. You can adjust text size with Control and the mouse wheel, and toggle timestamps or line wrapping from the View menu.

## Choose text or raw bytes

Text mode adds your selected line ending. Hex Bytes mode sends exactly the bytes entered, so include any required terminator yourself. The bytes shown here spell ping followed by carriage return and line feed; the demo answers pong. Receive display mode only changes how incoming bytes appear. It does not change the bytes sent. Return to text mode for the remaining exercises.

## Keep a record of communication

Use terminal logging when you need a record of communication. Select a file, confirm that logging is on, and stop logging when the capture is complete. Receive pause holds the display; it does not disconnect your device. Script pause controls command-file progress instead. Later, Control Panel CSV logging will record parsed measurements, which is useful for a different kind of analysis.

## Build a saved-command library

Open Saved Commands in the drawer and add a command with a useful label. For example, save the identification query as Identify in a Tutorial group. Star frequently used commands to put them in Favorites. Keep each command's text or hexadecimal send mode correct. Before sending from a library, check the active terminal so a useful shortcut goes to the intended device.

## Share commands and keep script shortcuts

The tutorial includes a command library in CSV format. Import it through the saved-command import action, reviewing the append or replace options. Export a CSV when sharing your own library. The Files page stores paths to command files, and those entries can be favorites too. A file shortcut does not include the file's contents, so copy the actual scripts when moving to another computer.

## Open the first-check script

Open the first check command file from the examples, tutorial folder. The editor shows line numbers and highlights the script language. Choose your connected tutorial terminal as the run target. This matters when several sessions are open. The prepared script identifies the device, repeats voltage measurements, checks the result, and writes a summary. Inspect a shared script before running it against your equipment.

## Parameters and runtime values

Double braces mark a parameter supplied before the run. Count has a default of three. A dollar-prefixed name is a runtime variable, created while the script runs. Capture extracts a value from the device reply using a regular expression. Wait delays use milliseconds. The response timeout also uses milliseconds, so fifteen hundred means one and a half seconds, rather than fifteen hundred seconds.

## Run and inspect the result

Run the script and keep the count parameter at three. With the demo at its defaults, you should see three passing checks and a completion summary. The loop repeats the measurement, capture saves its numeric value, and the condition compares it with the threshold. Log messages explain the result without sending their text to the device. Read the run status as well as the individual replies.

## Pause, stop, and handle failures

Pause and Resume control a running command file. Stop ends the run. A Pause instruction creates an operator checkpoint, while Break leaves a loop. By default, a response check that times out stops the script. Increase the timeout only when the device needs more time. The continue-on-error setting changes this behavior deliberately. The manual links to the complete scripting reference for these options.

## Open Tutorial Bench

Open the Control Panel manager with Control, Shift, and D. Import the tutorial panel JSON and open Tutorial Bench. Bind it to the connected tutorial terminal. The panel shares that terminal's connection instead of opening a competing one. Confirm the target in its binding chip. The prepared panel includes measurements, a status indicator, calculated power, an output toggle, and a numeric voltage setpoint.

## Poll and parse live values

Each measurement tile sends a query on its own schedule, collects the response, and applies a parse rule. The voltage tile reads the first reply line as a number and adds the volts unit. For replies containing labels, use a regular expression to extract the value. Choose intervals and timeouts appropriate to your hardware. Poll traffic stays out of the normal terminal transcript, keeping manual work readable.

## Use rules and calculated values

Color rules turn a reply into an understandable state. The tutorial temperature tile reports failure above fifty degrees. Rules are evaluated in order, so place specific conditions before broad ones. The power tile combines voltage and current with an expression. It calculates a value from other tiles rather than sending another device command. Clear labels make these references easier to understand and maintain.

## Inspect recent history

Numeric tiles can show a sparkline beneath the current value. Double-click one to open its larger chart. Select a time span and use the hover readout to inspect points. A newly opened panel needs time to gather a useful history. This chart is for live inspection. Enable CSV logging when you need measurement records that remain available after the session ends.

## Demonstrate a fault and recovery

Send the demo fault command from the terminal. Status changes to fault and temperature rises above the configured threshold. The panel records transitions into failure or error states in its alert history. You can control alert sounds per tile or globally. Send the fault-off command to recover. Acknowledging or silencing an alert changes the notification; it does not repair or reset the device.

## Arm writing tiles intentionally

Writing tiles start disarmed. Enable Master Arm before using the output toggle or voltage setpoint, and press Escape to disarm afterward. Readback should confirm the device's actual state. Disarming blocks further panel writes; it does not undo a setting or send an output-off command. Master Arm applies to panel controls, while terminal and script sends retain their own workflows.

## Log values and recognize paused polling

Choose a file and enable CSV logging to record parsed values. The kind column distinguishes polled values, calculated values, and control sends. Keep the application open and the PC awake during an unattended run. Polling normally pauses when the target disconnects or a command file uses its connection. Check the binding chip to understand a pause, and verify each target when using a panel across multiple devices.

## Keep the script beside the terminal

Split the workspace to keep the command-file editor beside its terminal. You can also compare two devices, then join panes when the extra view is no longer useful. Give tabs recognizable names. The command palette opens with Control, Shift, and P and helps you find actions quickly. Preferences and the View menu provide themes, terminal fonts, wrapping, and timestamp options.

## Use the same workflow from the CLI

The command-line interface uses the same application settings and scripting engine. Send runs a one-shot query. Validate checks a command file without contacting a device. Run executes the saved check, and parameter flags provide values for unattended operation. These commands are shown against the same local tutorial server. The manual explains how to activate the source environment if the command is not on your path.

## Make automation check the exit code

An automation script should check the process exit code, not just look for familiar text. Zero indicates success, while eleven indicates a failed response check. Supply required parameters and use noninteractive operation in unattended jobs. Avoid opening a physical COM port from the GUI and CLI at the same time. The CLI reference lists all commands, connection flags, and stable exit codes.

## Share each kind of work

Export application settings as JSON, saved commands as CSV, and Control Panels through their JSON export. Share command files themselves, together with a description of the target. A quick-file export shares paths, not script contents. App-settings transfer intentionally keeps quick-action libraries separate. Import a panel, bind the correct terminal, and verify commands and ranges before adapting a tutorial to real equipment.

## Work from the symptom

If a device does not reply, check its address, command, line ending, and connection settings. Garbled serial text usually calls for checking line configuration. A busy port may belong to another tab or program. For a script failure, inspect the actual response and timeout. For a stopped panel, check its binding and pause reason. The manual includes a symptom table with the next action for each case.

## Your next bench workflow

You have now used a terminal, built a reusable command library, run a repeatable check, and monitored a device with a Control Panel. Start your own workflow with one known query, verify the reply, and add automation a step at a time. The user manual, scripting guide, CLI reference, and tutorial examples are linked from the repository. Stop the demo server with Control C when you finish.
