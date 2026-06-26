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
| 🖥️ | **Desktop GUI** | Form-based config editor, Start/Stop, minimize to system tray, EN/TR language |
| 🌐 | **Web GUI** | Browser-based interface — same features, runs on Windows, Linux, or remote server |
| 📡 | **Fixed Beacon** | Periodically sends your station's position — with visual APRS symbol picker and Maidenhead / QTH Locator support |
| 🪵 | **Logger** | Logs incoming APRS packets to the terminal, with type and keyword filters |
| 🐦 | **Twitter / X** | Forwards APRS messages addressed to `TWSEND` to your Twitter/X account |
| 🦋 | **Bluesky** | Forwards APRS messages addressed to `BSKYSEND` to your Bluesky account (free API) |
| 📥 | **IMAP Receive** | Polls email inbox and forwards new emails as APRS messages to the radio |
| 📧 | **SMTP Email** | Forwards APRS messages addressed to `EMAIL` to any email address via SMTP |
| 🤖 | **AI Gateway** | Auto-responds to APRS messages using AI (Puter/Groq/OpenRouter — free options available) |
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

**3. Run**

```bash
python web_gui.py           # Web GUI — opens browser to http://localhost:8080
python gui.py               # Desktop GUI (Windows, tkinter)
python main.py              # CLI only (headless)
```

First run creates a default `aprsconfig.toml` — enter your callsign and you're ready.

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

### Bluesky

Free alternative to Twitter/X — no API payment required.
Create an **App Password** at [bsky.app](https://bsky.app) → Settings → App Passwords.

```toml
[extensions.bluesky]
enabled      = true
username     = "yourname.bsky.social"
app_password = "xxxx-xxxx-xxxx-xxxx"   # App Password, NOT your main password
allowed_senders    = ["YOUR_CALLSIGN"]
allowed_recepients = ["BSKYSEND"]
```

To post to Bluesky via APRS, send this message from your radio or software:
```
BSKYSEND Hello from APRS!
```

The agent posts the message to your Bluesky account and sends an APRS ACK back.

### AI Gateway

Auto-responds to incoming APRS messages using AI. Free providers available.
Inspired by [aprs-ai-gateway](https://github.com/ArdaYalinOzkan/aprs-ai-gateway) by TA3EKM.

```toml
[extensions.ai_gateway]
enabled   = true
callsign  = "YOUR_CALLSIGN"
provider  = "puter"              # puter (free), groq, openrouter, custom
api_key   = "your-api-key"
extra_sms = 1                    # 0 = single 64-char reply, 1-5 = multi-part
```

To ask the AI via APRS, send a message to the configured callsign:
```
YOUR_CALLSIGN What is APRS?
```

The agent queries the AI and sends the response back as APRS message(s).

### IMAP Receive (Email → Radio)

Polls your email inbox and forwards new emails as APRS messages.
Bidirectional email: use SMTP to send, IMAP to receive.

```toml
[extensions.imap]
enabled      = true
imap_server  = "imap.gmail.com:993"
imap_username = "you@gmail.com"
imap_password = "your-app-password"
from_callsign = "EMAIL-5"
poll_interval_mins = 5
```

To send an APRS message via email, compose an email with subject:
```
TA3HRJ-7 Hello, your beacon is working fine!
```
First word = destination callsign, rest = message text.

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

## Web GUI — Universal Interface

The web-based GUI works on any operating system with a browser. Same features as the desktop GUI.

```bash
python web_gui.py                          # localhost:8080, auto-opens browser
python web_gui.py -p 9090                  # custom port
python web_gui.py --host 0.0.0.0 -p 8080  # listen on all interfaces (remote access)
```

**Local (Windows/Mac):** browser opens automatically to `http://localhost:8080`

**Remote (Linux server / VPS):** access via `http://YOUR_SERVER_IP:8080`

> For production use on a public server, put it behind a reverse proxy (nginx/caddy) with HTTPS.

---

## Command-line Options

### CLI (`main.py`)

```
python main.py [options]

  -c, --config PATH           Path to config file (default: ./aprsconfig.toml)
  -w, --write-default-config  Write a fresh template config file and exit
  -p, --print-config          Print loaded config (secrets masked) and exit
  -s, --sync-config-to-file   Add missing default values to existing config
  -h, --help                  Show this help
```

### Web GUI (`web_gui.py`)

```
python web_gui.py [options]

  -c, --config PATH     Path to config file (default: ./aprsconfig.toml)
  -p, --port PORT       Web server port (default: 8080)
  --host HOST           Listen address (default: 0.0.0.0)
  --no-browser          Don't auto-open browser on startup
```

---

## Building the Windows .exe

Requires [PyInstaller](https://pyinstaller.org):

```bash
pip install pyinstaller
pyinstaller aprs_agent.spec --noconfirm
```

Output (three targets):
- `dist/aprs-agent/aprs-agent.exe` — CLI headless
- `dist/aprs-agent-gui/aprs-agent-gui.exe` — Desktop GUI (tkinter)
- `dist/aprs-agent-web/aprs-agent-web.exe` — Web GUI (browser-based)

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
├── main.py                      # CLI entry point (headless)
├── gui.py                       # Desktop GUI (tkinter, Windows)
├── web_gui.py                   # Web GUI (aiohttp, universal)
├── config.py                    # Configuration loading and defaults
├── aprs_connection.py           # APRS-IS TCP connection with auto-reconnect
├── extension_server.py          # Local TCP server for external clients
├── extensions/
│   ├── __init__.py              # Extension base class and registry
│   ├── logger_ext.py            # Console logger
│   ├── twitter_ext.py           # Twitter/X integration
│   ├── bluesky_ext.py           # Bluesky integration
│   ├── ai_gateway_ext.py        # AI auto-responder
│   ├── imap_ext.py              # IMAP email receiver (email → radio)
│   ├── smtp_ext.py              # SMTP email sender (radio → email)
│   └── fixed_beacon.py          # Periodic position beacon
├── static/
│   └── index.html               # Web GUI frontend (HTML/CSS/JS)
├── aprsconfig.toml.template     # Annotated config template (safe to share)
├── aprs_agent.spec              # PyInstaller build spec (CLI + GUI + Web)
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
AI Gateway inspired by [aprs-ai-gateway](https://github.com/ArdaYalinOzkan/aprs-ai-gateway) by **[TA3EKM](https://github.com/ArdaYalinOzkan)**.
Original Rust implementation by TA3PKS · Python port and GUI by TA3HRJ.

---

## Contributing

Pull requests and issue reports are welcome.
Please test your changes before submitting.

73 de TA3HRJ
