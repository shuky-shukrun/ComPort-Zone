# ComPort Zone hands-on tutorial transcript

## Let's talk to a device

Let's take ComPort Zone through a real workflow. We'll connect to a simulated instrument, send commands, automate a test, and watch a live dashboard. The tutorial device runs locally, so you can follow along without any hardware.

## Open connection settings

Start with Connection, then Connection Settings. Each terminal tab has its own connection. For this walkthrough, the demonstration server is already running on this computer. The manual explains how to start it.

## Choose the endpoint

Choose TCP. Enter the local address shown here, and port fifty twenty five. Select carriage return plus line feed. For your own instrument, use its address and required line ending.

## Make the connection

Accept the settings to connect. Watch the connection indicator turn green. Before sending anything, check the target shown in the terminal header. This keeps commands going to the device you intended.

## Identify the instrument

Click the transmit prompt and type the identification query. Press Enter. The outgoing command appears, followed by the device's reply. Here, the model and serial number confirm that we're talking to the tutorial instrument.

## Read live values

Now ask for voltage, current, and status. Each reply appears in the terminal as it arrives. The simulated instrument returns changing measurements and a ready state. You can inspect the conversation while continuing to type.

## Recall a command

To repeat a command, press the Up arrow at the prompt. The previous command comes back into the editable line. Press Enter to send it again. This is useful when you're checking a changing value.

## Complete while typing

Start typing a familiar command prefix and press Control Space to open completion suggestions. You can choose a suggestion or dismiss the popup with Escape. Let's clear the prompt before the next example.

## Search the conversation

Press Control F and enter part of a command to search the terminal. Matching text is highlighted in the conversation. Escape closes the search and returns you to your work.

## Send exact bytes

Switch the input mode to Hex Bytes. These byte pairs spell ping followed by carriage return and line feed. Send them and look for PONG. Then switch back to Text for normal commands.

## Write, then verify

A write command may produce no reply. Set the voltage to fifteen, then query the voltage separately. The returned value confirms the change. Finally, reset the demonstration instrument so the remaining examples start from a known state.

## Save a useful command

Let's turn the identification query into a reusable action. Open Tools and choose Add Saved Command. This saves typing and makes a common operation available from the drawer.

## Name and group the action

Give the command a short label, enter the identification query, and put it in a Tutorial group. Confirm the dialog. The label helps you recognize the action without reading the entire command.

## Send from the drawer

Open Saved Commands in the drawer. Click the send action beside Identify. The actual query runs in the selected terminal, and its reply appears just as it did when we typed it.

## Keep favorites close

Click the star beside the saved command. Now open Favorites. The same action is available here, ready for repeated checks. Use favorites for a small set of commands you reach for most often.

## Export the command library

To share these commands, open File, Import and Export, then choose Export Saved Commands. Save the CSV file in a location you can find. Your teammate can import that library into their own installation.

## Open a command file

Next, let's automate a check. Use File, Open Command File Editor, and select the tutorial's first check file. This opens an editable script in a workspace tab beside the terminal.

## Inspect and save the script

The script identifies the device, repeats a voltage measurement, checks the value, and prints a summary. Add a comment and press Control S to save. We're editing a working copy of the supplied example.

## Choose where to run

Check the run target above the editor. It should be the connected tutorial terminal. Click Run. Because this script contains a parameter, ComPort Zone asks for its value before execution starts.

## Start and pause a run

Set the repeat count to five and click Start. Switch to the terminal to watch the commands execute. Click Pause during the run. The controls now offer Resume, so you can inspect progress before continuing.

## Resume execution

Click Resume and watch the remaining measurements arrive. The script handles the repeated commands and checks for us. Wait for the run to finish before starting another operation on this connection.

## Read the result

The final log reports five passing checks. Read the terminal output as well as the completion status. Together they show what was sent, what came back, and whether the script's conditions were satisfied.

## Work side by side

Return to the editor and choose Split Right from View. Drag the divider to give each pane enough space. A split workspace is useful when you want the command file and a terminal visible together.

## Use the command palette

Open the command palette from Tools. Search for Join Tabs and press Enter. The workspace returns to one pane. The palette gives you a quick route to actions without navigating menus.

## Open panel management

Now let's build a live view of the same device. Open Tools, then Control Panels, to manage your saved panels. Panels collect measurements, status indicators, and device controls in one workspace tab.

## Import the example panel

Click Import and select the tutorial control panel JSON file. The imported panel appears in the list. The repository includes this example so you can reproduce the dashboard without entering every tile by hand.

## Watch the dashboard start

Select the imported panel and click Open. Measurements begin updating from the connected instrument. Notice the numeric readings, the ready indicator, and the controls grouped together in the same view.

## Check the connection binding

Open the connection selector and choose the tutorial device. The binding chip shows which terminal supplies the panel's connection. Always check this before using a panel with multiple devices open.

## Edit a measurement tile

Right click the voltage tile and choose Edit. A tile defines the command to send, how to interpret the reply, and when to poll. You can adjust an existing tile as your workflow changes.

## Adjust the polling interval

Change the polling interval to seven hundred fifty milliseconds and save. Choose a rate your device can handle. Faster updates can be helpful, but every poll still consumes time on the underlying connection.

## Follow changing readings

Watch the voltage and power readings update. The device simulator varies its measurements, so these are fresh responses rather than a static display. The panel keeps polling while we watch.

## Open a live trend

Double click the voltage tile to open its chart. Change the visible time span to one minute. The trace makes it easier to spot movement over time than reading individual numbers alone.

## Inspect the trace

Move the pointer across the chart to inspect values along the trace. This helps you compare earlier readings with the current measurement. Use Back to return to the tile dashboard.

## Trigger a visible fault

Let's deliberately enable a fault on the simulator. Send the demonstration fault command in the terminal, then return to the panel. The status indicator changes, showing how an unexpected device state appears during monitoring.

## Review panel alerts

Click the bell to inspect the panel's alerts. Use this view to see what needs attention while the dashboard continues updating. Close the alert view when you're ready to investigate the device.

## Clear the fault

Return to the terminal and clear the simulated fault. Back on the panel, wait for the next status response. The indicator returns to its normal state, confirming the device has recovered.

## Arm the panel controls

A panel can arm automatically when its bound device connects. Check the lock control. Click to disarm, then click again to arm before writing. This makes the difference between monitoring and changing the instrument visible.

## Switch the output off

Click the output control to switch the simulated supply off. Watch the related measurements respond. You're sending a real command to the local simulator through the panel's bound connection.

## Restore the output

Click again to restore the output. The measurements recover on subsequent polls. For your own hardware, understand the effect of each write command before using its panel control.

## Change a setpoint

Enter fifteen in the voltage setpoint control and press Enter to send. Watch the measured voltage move to the new level. A separate readback is useful confirmation that the device accepted the requested setting.

## Return to monitoring

Disarm the controls when you're finished changing settings. The write buttons become unavailable while monitoring continues. This is a useful habit when leaving a dashboard open for observation.

## Start a value log

Click the panel's CSV logging control and choose an output file. Logging records measurement events for later analysis. Save the file somewhere separate from the application files so you can find it easily.

## Finish the capture

Let a few polls arrive, then click the logging control again to stop. The CSV now contains recorded values. You can open it in a spreadsheet or use it in your own analysis tools.

## Query from PowerShell

The same device is available from the command line. In this PowerShell console, run a single identification query against localhost. The actual reply appears below the command, and a zero exit code confirms success.

## Validate before running

Run validate on the tutorial command file. This checks the script without opening a device connection. Use validation after editing a file and before adding it to an automated workflow.

## Run a scripted check

Now run that file against the local device with the repeat count set to three. Non interactive mode keeps parameter handling explicit. Watch the measurements and the summary report three passing checks.

## Try a UDP exchange

For a datagram example, send ping to the simulator's UDP endpoint and expect PONG. The command checks the reply and exits successfully. The tutorial server supports both transports on the same local port.

## Return to the dashboard

Return to the desktop app and reset the demonstration instrument. The panel continues to reflect the live device state. You've now used the terminal, reusable commands, scripts, charts, controls, logging, and the command line.

## Disconnect when finished

Disconnect the terminal when you're finished. To repeat this walkthrough, use the example files and instructions linked with the project. The English manual provides the detailed reference, and the release includes captions and chapter timestamps for this video.
