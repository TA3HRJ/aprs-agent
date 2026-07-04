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
| 🖥️ | **Desktop GUI** | Form-based config editor, Start/Stop, system tray, EN/TR language toggle, live stats bar |
| 🌐 | **Web GUI** | Browser-based interface, installable PWA, live stats, Last Heard strip, Stations tab, gzip-compressed |
| 📊 | **Stations Tab** | Live table of all heard stations — type, location, organization, frequency, online/offline status; Object packets parsed; location falls back to Maidenhead locator or coordinates |
| 🗄️ | **Turkey Repeaters DB** | Enriches station records with city, district, frequency, tone, band, mode from a local JSON database |
| 🔔 | **Repeater Monitor** | Detects when DB-matched repeaters go offline or come back; sends Telegram or email notification |
| 🧠 | **AI Station Analysis** | Periodically sends beacon comments to AI to extract organisation name and description — results shown in Stations tab; skips seasonal/greeting messages |
| 📡 | **Fixed Beacon** | Periodically sends your station's position — with APRS symbol picker and Maidenhead / QTH Locator support |
| 🪵 | **Logger** | Logs incoming APRS packets to the terminal, with type and keyword filters |
| 🤖 | **AI Gateway** | Auto-responds to APRS messages using AI (Puter/Groq/OpenRouter — free options available) |
| 🐦 | **Twitter / X** | Forwards APRS messages addressed to `TWSEND` to your Twitter/X account |
| 🦋 | **Bluesky** | Forwards APRS messages addressed to `BSKYSEND` to your Bluesky account (free API) |
| 📥 | **IMAP Receive** | Polls email inbox and forwards new emails as APRS messages to the radio |
| 📧 | **SMTP Email** | Forwards APRS messages addressed to `EMAIL` to any email address via SMTP |
| 📱 | **WhatsApp** | Bidirectional APRS ↔ WhatsApp via Meta Cloud API (webhook) |
| 💬 | **Telegram** | Bidirectional APRS ↔ Telegram messaging (free, no API payment) |
| 🔌 | **Extension Server** | Local TCP server — lets other programs subscribe to the live APRS stream and inject packets |

---

## Quick Start — Windows (.exe)

1. Download the latest release from the [Releases](https://github.com/TA3HRJ/aprs-agent/releases) page
2. Extract the zip and run **`aprs-agent-web.exe`** (Web GUI) or **`aprs-agent-gui.exe`** (Desktop GUI)
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

## Port Reference

| Port | Direction | Purpose |
|------|-----------|---------|
| 14580 | OUT | APRS-IS server (filtered) |
| 10152 | OUT | APRS-IS full-feed (optional) |
| 8080 | IN | Web GUI (aiohttp) |
| 65080 | IN | Extension Server (if enabled) |
| 443 | OUT | Bluesky / AI API / WhatsApp / Telegram |
| 587 | OUT | SMTP email |
| 993 | OUT | IMAP email |

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
allowed_callsigns = ["N0CALL*"]       # Station filter — wildcards OK (b/ exact, p/ prefix)
full_feed = false                     # Set true to receive all worldwide traffic (port 10152)
```

### Logger

Logs all incoming packets to the terminal. Enabled by default.

```toml
[extensions.logger]
enabled = true
log_comments = true
filter_by_message_type = ["!", "/", "@", "_"]   # only log these APRS types (empty = all)
exclude_by_message_type = []                     # always exclude these types
keyword_filter = []                              # only log packets containing these words
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

### Turkey Repeaters DB

Enriches the Stations tab with location, frequency, tone, and band data for known repeaters.
Download the latest database from the [Turkey Repeaters](https://github.com/TA3HRJ/turkey-repeaters) project.

```toml
repeater_db_path = "C:/path/to/repeaters.json"
```

Once set, every station whose base callsign matches a DB record is automatically enriched —
city, district, frequency, CTCSS tone, band, and mode are filled in without requiring a live packet.

### Repeater Monitor

Watches DB-matched repeaters and sends a notification when one goes offline or comes back online.
Requires `repeater_db_path` to be set and at least one notification channel configured.

```toml
[monitor]
enabled             = true
notify_channel      = "telegram"     # "telegram" or "smtp"
check_interval_mins = 10
watch_callsigns     = []             # empty = watch all DB repeaters
```

Notification example:
```
🔴 YM5KAD is now OFFLINE (last heard 1h 23m ago)
Adana · 145.7000 MHz · FM
```

### AI Station Analysis

Periodically sends APRS beacon comments to AI to extract the station's organisation name and description.
Results appear in the Stations tab **Organization** column and detail panel.

Requires **AI Gateway** to be configured first (same provider and API key are reused).

```toml
[station_ai]
enabled        = true
interval_hours = 24     # run every N hours
max_batch      = 20     # max stations analysed per run
```

- DB-matched repeaters are prioritised in each batch
- Transient comments (holiday greetings, seasonal messages) are skipped automatically to avoid wasting tokens
- Each station is analysed once per session; results are cached in memory

### AI Gateway

Auto-responds to incoming APRS messages using AI. Free providers available.
Inspired by [aprs-ai-gateway](https://github.com/ArdaYalinOzkan/aprs-ai-gateway) by TA3EKM.

```toml
[extensions.ai_gateway]
enabled        = true
callsign       = "YOUR_CALLSIGN"
provider       = "puter"              # puter, groq, openrouter, or custom
api_key        = "your-api-key"       # from provider dashboard (required even on free tier)
base_url       = ""                   # leave empty for built-in providers
model          = ""                   # leave empty to use provider default
system_prompt  = ""                   # optional: custom system prompt
trigger_prefix = ""                   # optional: only respond if message starts with this
extra_sms      = 1                    # 0 = single 64-char reply, 1–5 = multi-part
whitelist_enabled = false
whitelist      = []                   # callsigns allowed to use AI (empty = everyone)
```

To ask the AI via APRS, send a message to the configured callsign:
```
YOUR_CALLSIGN What is APRS?
```

The agent queries the AI and sends the response back as APRS message(s).

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

### Telegram

Bidirectional APRS ↔ Telegram messaging. Completely free.

```toml
[extensions.telegram]
enabled      = true
bot_token    = "123456:ABC-DEF..."   # from @BotFather
chat_id      = "123456789"           # from @userinfobot
allowed_senders    = ["YOUR_CALLSIGN"]
allowed_recepients = ["TGSEND"]
poll_enabled       = true            # enable Telegram → APRS direction
poll_interval_secs = 5
from_callsign      = ""              # SSID used when sending from Telegram to APRS
aprs_destination   = ""             # default destination callsign for Telegram → APRS
```

Send APRS to Telegram: address a message to `TGSEND`.
Send Telegram to APRS: type `CALLSIGN-7 Hello!` in the bot chat.

### WhatsApp

Bidirectional APRS ↔ WhatsApp via Meta Cloud API.

```toml
[extensions.whatsapp]
enabled          = true
phone_number_id  = "123456789"     # from Meta dashboard
access_token     = "EAAx..."       # from Meta dashboard
verify_token     = "my-secret"     # for webhook verification
app_secret       = "..."           # for HMAC signature verification
recipient_phone  = "+905551234567"
from_callsign    = ""              # SSID used when sending from WhatsApp to APRS
aprs_destination = ""             # default destination callsign for WhatsApp → APRS
allowed_phones   = []             # phone numbers allowed to trigger APRS (empty = anyone)
```

Webhook URL: `https://YOUR_SERVER/webhook/whatsapp`

### IMAP Receive (Email → Radio)

Polls your email inbox and forwards new emails as APRS messages.
Bidirectional email: use SMTP to send, IMAP to receive.

```toml
[extensions.imap]
enabled           = true
imap_server       = "imap.gmail.com:993"
imap_username     = "you@gmail.com"
imap_password     = "your-app-password"   # Gmail: use an App Password
from_callsign     = "EMAIL-5"
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

### Extension Server

Exposes a local TCP server that external programs can connect to.
Connected clients receive every incoming APRS packet and can inject packets back to APRS-IS
by sending `send <raw APRS packet>`.

```toml
[extension_server]
enabled = true
host    = "127.0.0.1"
port    = 65080
```

Protocol: line-based text. Server sends `ping` every 30 s; client must reply `pong`.
Incoming packets arrive as `data <raw line>`. Inject a packet with `send <raw packet>`.

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

### Web GUI Features

- **Live stats bar** — RX / TX / Errors / Packets / Stations / Callsigns / Uptime, updated every 2 seconds via WebSocket
- **Last Heard strip** — callsign chips above the stats bar; click a chip to filter the log to that station
- **Stations tab** — live table of all heard stations with type/status/callsign filters and an Organization column (filled by AI analysis); APRS Object packets are correctly attributed to the object callsign; Location column falls back to Maidenhead locator or lat/lon; click any row for a detail panel showing coordinates, frequency, tone, EchoLink, weather data, AI-extracted org/description, and packet history; auto-refreshes every 5 seconds
- **PWA — installable app** — on Chrome/Edge, use *Install* or *Add to Home Screen* to run without a browser tab; works on Android, iOS, Windows, and Mac
- **Efficient delivery** — `index.html` is served gzip-compressed (~14 KB instead of 55 KB) with ETag caching; the page loads instantly on repeat visits
- **Bounded log** — the log panel keeps the last 10 000 lines; memory stays flat even after days of continuous operation
- **Full World Feed** — optional port 10152 mode receives all worldwide APRS traffic; built-in token-bucket rate limiter prevents CPU overload

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
2. **Action:** `aprs-agent-web.exe` (or `python main.py`)
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
├── packet_parser.py             # Rule-based APRS packet parser (coord→locator, freq, tone, Object packets, wx…)
├── station_db.py                # In-memory station registry; Turkey Repeaters DB enrichment; online/offline detection; AI analysis queue
├── extensions/
│   ├── __init__.py              # Extension base class and registry
│   ├── logger_ext.py            # Console logger
│   ├── twitter_ext.py           # Twitter/X integration
│   ├── bluesky_ext.py           # Bluesky integration
│   ├── whatsapp_ext.py          # WhatsApp bidirectional (webhook)
│   ├── telegram_ext.py          # Telegram bidirectional
│   ├── ai_gateway_ext.py        # AI auto-responder
│   ├── imap_ext.py              # IMAP email receiver (email → radio)
│   ├── smtp_ext.py              # SMTP email sender (radio → email)
│   └── fixed_beacon.py          # Periodic position beacon
├── static/
│   ├── index.html               # Web GUI frontend (HTML/CSS/JS)
│   ├── manifest.json            # PWA install manifest
│   ├── sw.js                    # Service worker (offline shell cache)
│   ├── icon-192.png             # PWA icon 192 px
│   └── icon-512.png             # PWA icon 512 px
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

Developed by **[TA3HRJ](https://github.com/TA3HRJ)**.
Based on the Rust work of **[TA3PKS](https://github.com/TA3PKS)**.
Bidirectional AI Gateway concept by **[TA3EKM](https://github.com/ArdaYalinOzkan)** — [aprs-ai-gateway](https://github.com/ArdaYalinOzkan/aprs-ai-gateway).

---

## Contributing

Pull requests and issue reports are welcome.
Please test your changes before submitting.

73 de TA3HRJ
