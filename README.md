# APRS-Agent

An APRS-IS server agent with a graphical interface and extensible plugin system, written in Python.

Connects to the global [APRS-IS](http://www.aprs2.net/) network and provides
several automation features useful for amateur radio operators.

> **Note:** Using this software requires a valid amateur radio license.
> The APRS-IS network is for licensed amateur radio operators only.

---

## Features

| | Feature | Description |
|---|---|---|
| 🖥️ | **GUI** | Form-based config editor, Start/Stop, minimize to system tray, EN/TR language |
| 📡 | **Fixed Beacon** | Periodically sends your station's position — with visual APRS symbol picker and Maidenhead / QTH Locator support |
| 🪵 | **Logger** | Logs incoming APRS packets to the terminal, with type and keyword filters |
| 🐦 | **Twitter / X** | Forwards APRS messages addressed to `TWSEND` to your Twitter/X account |
| 📧 | **SMTP Email** | Forwards APRS messages addressed to `EMAIL` to any email address via SMTP |
| 🔌 | **Extension Server** | Local TCP server — lets other programs subscribe to the live APRS stream |

---

## Quick Start — Windows (.exe)

1. Download the latest release from the [Releases](https://github.com/TA3HRJ/aprs-agent/releases) page
2. Extract the zip and run **`aprs-agent-gui.exe`**
3. Enter your callsign in the **Connection** tab and click **Save Config**
4. Click **▶ Start**

No Python installation required for the pre-built Windows executable.

---

## Installation from Source

**1. Clone or download this repository**

```bash
git clone https://github.com/TA3HRJ/aprs-agent.git
cd aprs-agent
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Run the GUI**

```bash
python gui.py
```

Or run headless (CLI only):

```bash
python main.py --write-default-config   # create config template
python main.py                          # start agent
```

---

## Configuration

All settings are in `aprsconfig.toml`.
The file is fully self-documented with comments.
In the GUI, all settings can be edited in the form — no manual file editing needed.

### Minimum required settings

```toml
callsign = "YOUR_CALLSIGN"
allowed_callsigns = ["YOUR_CALLSIGN*"]
```

### Main connection settings

```toml
server = "rotate.aprs2.net"          # APRS-IS server
port   = 14580                        # Standard filtered port
callsign = "N0CALL"                   # Your callsign (SSID optional: N0CALL-5)
allowed_callsigns = ["N0CALL*"]       # Packet filter — wildcards OK
```

### Fixed Beacon

```toml
[extensions.fixed_beacon]
enabled  = true
ssid     = "YOUR_CALLSIGN-5"
lat      = "4100.00N"          # Latitude:  DDMM.MMN
lon      = "02900.00E"         # Longitude: DDDMM.MME
symbol_table = "/"
symbol       = "-"             # Use the GUI symbol picker for a visual list
comment  = "My APRS station"
beacon_interval_mins = 15
```

> 💡 In the GUI, enter your **QTH Locator** (e.g. `KM38nk`) and lat/lon fills automatically.

### Twitter / X

You need Twitter API credentials with **read+write** access.
Get them at [developer.twitter.com](https://developer.twitter.com).

```toml
[extensions.twitter]
enabled = true
api_key             = "..."
api_secret          = "..."
access_token_key    = "..."
access_token_secret = "..."
allowed_senders     = ["YOUR_CALLSIGN"]
allowed_recepients  = ["TWSEND"]
```

### SMTP Email

```toml
[extensions.smtp]
enabled        = true
smtp_server    = "smtp.gmail.com:587"
smtp_username  = "you@gmail.com"
smtp_password  = "your-app-password"   # Gmail: use an App Password
allowed_senders    = ["YOUR_CALLSIGN"]
allowed_recipients = ["EMAIL"]
```

To send an email via APRS, send this message from your radio or software:
```
EMAIL friend@example.com Hello, sent via APRS!
```

---

## Command-line Options

```
python main.py [options]

  -c, --config PATH           Path to config file (default: ./aprsconfig.toml)
  -w, --write-default-config  Write a fresh template config file and exit
  -p, --print-config          Print loaded config (secrets masked) and exit
  -s, --sync-config-to-file   Add missing default values to existing config
  -h, --help                  Show this help
```

---

## Building the Windows .exe

Requires [PyInstaller](https://pyinstaller.org):

```bash
pip install pyinstaller
pyinstaller aprs_agent.spec --noconfirm
```

Output: `dist/aprs-agent-gui/aprs-agent-gui.exe`

---

## Running as a Background Service

### Linux (systemd)

Create `/etc/systemd/system/aprs-agent.service`:

```ini
[Unit]
Description=APRS-Agent
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/aprs-agent
ExecStart=/usr/bin/python3 /opt/aprs-agent/main.py -c /opt/aprs-agent/aprsconfig.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable aprs-agent
sudo systemctl start aprs-agent
sudo journalctl -fu aprs-agent
```

### Windows (Task Scheduler)

1. Open **Task Scheduler** → Create Basic Task
2. **Action:** `aprs-agent-gui.exe` (or `python main.py`)
3. **Trigger:** At startup
4. Check **Run whether user is logged in or not**

---

## Project Structure

```
aprs-agent/
├── main.py                      # CLI entry point
├── gui.py                       # Graphical interface (tkinter)
├── config.py                    # Configuration loading and defaults
├── aprs_connection.py           # APRS-IS TCP connection with auto-reconnect
├── extension_server.py          # Local TCP server for external clients
├── extensions/
│   ├── __init__.py              # Extension base class and registry
│   ├── logger_ext.py            # Console logger
│   ├── twitter_ext.py           # Twitter/X integration
│   ├── smtp_ext.py              # SMTP email forwarding
│   └── fixed_beacon.py          # Periodic position beacon
├── aprsconfig.toml.template     # Annotated config template (safe to share)
├── aprs_agent.spec              # PyInstaller build spec
├── aprs-symbols-24-0.png        # APRS symbol sprites — primary table
├── aprs-symbols-24-1.png        # APRS symbol sprites — alternate table
├── HELP.html                    # User guide (bilingual EN/TR)
├── requirements.txt             # Python dependencies
└── LICENSE                      # MIT License
```

---

## License

MIT License — see [LICENSE](LICENSE) file.

Developed by **[TA3HRJ](https://github.com/TA3HRJ)** and **[TA3PKS](https://github.com/TA3PKS)**.
Original Rust implementation by TA3PKS · Python port and GUI by TA3HRJ.

---

## Contributing

Pull requests and issue reports are welcome.
Please test your changes before submitting.

73 de TA3HRJ
