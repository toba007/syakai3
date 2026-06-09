# ESP Motion Controller

Tkinter GUI for sending motion commands to an ESP board over USB serial.

The ESP side is expected to already have motion functions such as `motion1`,
`motion2`, and so on. The PC does not request a motion list from the ESP. It
only sends commands such as:

```text
PLAY motion1
QUEUE motion2
STOP
CLEAR
```

## Files

| File | Role |
| --- | --- |
| `motion_queue_gui.py` | Main Tkinter control panel |
| `preview_server.py` | Separate local web preview screen |
| `requirements.txt` | Python dependency list |

## Setup

```powershell
py -m pip install -r requirements.txt
py motion_queue_gui.py
```

If `py` is not configured, use the installed Python directly:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" motion_queue_gui.py
```

## Usage

1. Start `motion_queue_gui.py`.
2. Click `Open Web Preview` to open the separate preview screen in a browser.
3. Choose `PLAY` or `QUEUE`.
4. Press one of the large `motion1` to `motion12` buttons.
5. When the ESP is available, select the COM port and click `Connect`.

When the ESP is not connected, the GUI still updates the web preview and logs
the command as preview-only.

## Adding Motions

Use the `Add Motion` box in the GUI.

1. Enter the ESP-side motion name, for example `motion13` or `walkForward`.
2. Click `Add`.
3. A new large button appears immediately.
4. Pressing that button sends the exact same name to the ESP.

For example, adding `walkForward` and pressing it in `PLAY` mode sends:

```text
PLAY walkForward
```

The ESP should run the matching function or command handler for that name.

Motion names are saved in `motions.json`, so added buttons remain after restart.
Use letters, numbers, and underscores, starting with a letter.

## Serial Protocol

Commands are UTF-8 text lines terminated by `\n`.

| PC -> ESP | Meaning |
| --- | --- |
| `PLAY <motion_id>` | Run the matching ESP motion function immediately |
| `QUEUE <motion_id>` | Add the matching ESP motion function to the ESP queue |
| `STOP` | Stop playback |
| `CLEAR` | Clear the ESP queue |

Example ESP-side behavior:

```text
PLAY motion1
```

should call the ESP-side `motion1()` function.
