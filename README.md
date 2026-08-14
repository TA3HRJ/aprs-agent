# APRS-Agent

[![Release](https://img.shields.io/github/v/release/TA3HRJ/aprs-agent)](https://github.com/TA3HRJ/aprs-agent/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

An APRS-IS server agent with a graphical interface and extensible plugin system, written in Python.

Connects to the global [APRS-IS](http://www.aprs2.net/) network and provides
several automation features useful for amateur radio operators.

### 🔴 Live demo — [ta3hrj.duckdns.org](https://ta3hrj.duckdns.org/)

A real instance in **World Mode**, carrying the full worldwide APRS-IS feed:
the live log, every station heard, the Silence Map with its AI assessments,
and RF propagation openings as they happen. This is the read-only **Public
View** — the same page the software serves on `public_port`, with no settings
and no admin endpoints exposed.

> **Note:** Using this software requires a valid amateur radio license.
> The APRS-IS network is for licensed amateur radio operators only.

> **Desktop GUI is feature-frozen as of v2.8.0.** It still works and is still
> shipped, but new development happens in the **Web GUI**.
> See [Desktop GUI — feature freeze](#desktop-gui--feature-freeze).

This document describes what is running on the live demo; the download badge
tracks the latest Windows build, which may be older. For what changed
between versions, see the
[Releases](https://github.com/TA3HRJ/aprs-agent/releases) page.

---

## Features

| | Feature | Description |
|---|---|---|
| 🖥️ | **Desktop GUI** *(frozen at v2.8.0)* | Form-based config editor, Start/Stop, system tray, EN/TR language toggle, live stats bar (RX/TX/Errors/Packets/Stations/Callsigns/Uptime), Live Log + Stations bottom panel with real APRS symbol icons and type/status/search filters |
| 🌐 | **Web GUI** | Browser-based interface, installable PWA, live stats, Last Heard strip, Stations tab, Map tab, gzip-compressed |
| 🗺️ | **Silence Map** | Leaflet map of all heard stations with real APRS symbols; detects regions where stations fall silent together (per-station beacon-cadence baseline, Maidenhead cell clustering, igate-failure discrimination) and paints affected cells. **An alert means the silence is news, not merely that the threshold was met.** Three things demote a cell out of the alert list — and off the notifications and the AI spend — while leaving it on the map: a *chronic* cell, whose silent stations are all ones it habitually misses; a cell whose silent callsigns belong to too few separate operators, since three SSIDs of one base callsign are three radios in one shack on one power strip and cannot fail independently; and a cell where **no igate ever heard any of them** — every station either gated itself or dialled an APRS-IS backbone server directly, which makes their silence an internet or app dropout rather than anything about a region. That last one is not rare: on the worldwide feed it accounted for 23 of 36 cells, all of them previously reported as regional outages. What keeps a cell alerting is a station that is *unusual there* — one present in under 35 % of that cell's own past alerts — and the popup names it, so the reason is a callsign rather than a colour: *"New here: PY2GR-D — normally not among this cell's missing stations."* The raw threshold result is still reported as `threshold_met` and is still what gets stored, so nothing is hidden and fourteen days of history keep the meaning they were written with. Cell colour separates the cases: red for a regional silence, yellow when a shared igate was **seen** to go quiet, orange when one gate carries every silent station but cannot be seen at all, purple when nothing local ever observed them, grey for measured but not announced. Popups also flag silent stations whose own beacon cannot be trusted about where they are — a US callsign transmitting an eastern longitude is a well-known hotspot misconfiguration, and a cell built out of those is not describing the region it is drawn on. If the APRS-IS feed itself stops, nothing is judged at all: the page says so and holds the last confirmed reading rather than reporting the world as silent. Timeline slider replays the last 14 days of snapshots; new alerts get an AI assessment (via AI Gateway) shown in cell popups and are sent to the Monitor notify channel (Telegram/email). The agent's own Fixed Beacon is shown on the map but excluded from silence detection (it is self-generated and would otherwise be a phantom "still active" vote). Detection can be scoped to your own region with `monitor.silence_grids` (Maidenhead fields, e.g. `["KM","KN","LM","LN"]` for Turkey) — a prefix station filter such as `p/TA` also matches callsigns abroad, and without this their outages raise alerts too. For worldwide monitoring, `monitor.silence_digest_mins` batches alerts into one combined notification per interval. APRS Object packets (event advisories that expire by design) are never counted as silence sensors |
| 📡 | **RF Propagation Tracking** | Every qAR/qAO-gated packet is one realised RF link whose length is known exactly (sender's in-packet position to the igate's position). Per-gate baselines separate "this mountain-top gate always hears far" from "the band just opened"; abnormally long links draw as dashed great-circle lines on the map, colour-tiered by distance. Two or more distinct senders in the same Maidenhead field within 30 minutes become a **band-opening event** — notified via Telegram/email with an optional AI read (tropo / sporadic-E / aurora) and replayable from the map timeline. Internet-origin, digipeated, object, balloon (>3000 m) and >5000 km (GPS garbage) packets are excluded |
| 💾 | **Persistence** | Station records, beacon-cadence history and the station's lifelong uptime survive restarts (SQLite `aprs_stations.db` next to the config, shared by both GUIs) |
| 💬 | **Messages Tab** | Every APRS message the agent hears or sends, in one panel — time, direction, from, to, text, and the bridge it belongs to (AI / Telegram / WhatsApp / Email / …). Outgoing messages are captured from the send loop, since APRS-IS never echoes our own traffic. Rolling buffer of the last 400 messages, pushed live over WebSocket; ack/telemetry chatter filtered out. Admin only — not exposed on the public view |
| 🚨 | **Still-missing stations** | When a silence alert clears because most of its cell recovered, the stations that never came back stop being counted — and those are the ones that matter. They are tracked individually instead, listed longest-silent first, and leave the list only by being heard again. Survives a restart. Wording is deliberately plain: no APRS signal is a weak welfare signal, not a confirmed emergency |
| 📤 | **Exportable evidence** | The note on a silence popup comes from whatever model is cheap enough to run unattended over every alerting cell — which also caps how well anyone can read that cell, since the detail behind it exists only on the server. Any visitor, including on the public view, can download the raw bundle behind a popup (⬇ Raw data) or open it as a ready-made prompt (📋 Copy as AI prompt) and re-run the analysis on their own AI, at their cost. The prompt opens in a box with the text already selected rather than being written to the clipboard from the click: a browser only grants a page about five seconds of clipboard access after a click, this endpoint has been measured at nearly eight, and a copy that loses that race fails silently. Ctrl+C, or the box's own Copy button, needs neither the race nor the permission. The bundle is self-describing: schema, generation time, the detection parameters that selected the cluster, per-station silence detail, how often each silent station appears among that cell's past alerts and which of them are unusual for it, how much of the cell's recorded history was already alerting, how many distinct operators and independent gates the silent set actually represents, full USGS quake fields including the time offset and hypocentral distance, and the provider/model behind the shown note. No keys, no config, no paths — the same facts the station APIs already serve |
| 🌍 | **Earthquake correlation** | A regional silence cluster and a nearby earthquake look identical to the detector. Recent M4.5+ quakes (USGS, free, no API key) within 500 km and 24 h of a silence are attached to the alert — feeding the AI assessment, the Telegram/email notification and the map popup, so "shared infrastructure or power issue" becomes "M7.4, 165 km away, 10 minutes before the silence began" |
| 👁️ | **Public View** | Optional read-only monitoring page on a separate port (`public_port`): Live Log / Stations / Map only — no settings, no start/stop, no API keys, log stream filtered to packet lines. Safe to expose to the internet while the admin port stays local |
| 📊 | **Stations Tab** | Live table of all heard stations — type, location, organization, frequency, online/offline status; Object packets parsed; location falls back to Maidenhead locator or coordinates |
| 🗄️ | **Turkey Repeaters DB** | Enriches station records with city, district, frequency, tone, band, mode from a local JSON database |
| 🔔 | **Repeater Monitor** | Detects when DB-matched repeaters go offline or come back; sends Telegram or email notification |
| 🧠 | **AI Station Analysis** | Periodically sends beacon comments to AI to extract organisation name and description — results shown in Stations tab; skips seasonal/greeting messages |
| 📡 | **Fixed Beacon** | Periodically sends your station's position — with APRS symbol picker and Maidenhead / QTH Locator support |
| 🪵 | **Logger** | Logs incoming APRS packets to the terminal, with type and keyword filters |
| 🤖 | **AI Gateway** | Auto-responds to APRS messages using AI (ChatGPT/Claude/DeepSeek/Groq/OpenRouter/Puter/custom — free options available); a separate API key is stored per provider, recalled automatically when you switch |
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
2. Extract the zip and run **`aprs-agent-web.exe`** — this is the recommended interface
3. Enter your callsign in the **Connection** tab and click **Save Config**
4. Click **▶ Start**

No Python installation required for the pre-built Windows executable.

The Desktop GUI (`aprs-agent-gui.exe`) is published separately as a final build —
see [Desktop GUI — feature freeze](#desktop-gui--feature-freeze).

---

## Quick Start — Docker (Linux / Windows / macOS)

```bash
git clone https://github.com/TA3HRJ/aprs-agent.git
cd aprs-agent
docker compose up -d
```

Open `http://localhost:8080`, enter your callsign, **Save Config**, **▶ Start**.
Configuration and the station database persist in `./data`.

Without compose:

```bash
docker build -t aprs-agent .
docker run -d --name aprs-agent \
  -p 127.0.0.1:8080:8080 -p 8082:8082 \
  -v "$(pwd)/data:/data" aprs-agent
```

> ⚠️ The admin panel on port 8080 has **no built-in authentication** — keep it
> published to `127.0.0.1` (as above) or put it behind a reverse proxy with
> auth. Port 8082 serves the read-only public page once `public_port = 8082`
> is set in the config, and is safe to expose.

---

## Desktop GUI — feature freeze

The Desktop GUI (`gui.py` / `aprs-agent-gui.exe`) is **feature-frozen as of v2.8.0**.

**It is not abandoned and it is not broken.** It remains fully functional:
configuration editor, Start/Stop, system tray, EN/TR toggle, live log, live stats
and the Stations panel with real APRS symbols all work. Because it imports the same
`packet_parser` and `station_db` modules as the Web GUI, it automatically keeps the
shared improvements — packet parsing, SQLite persistence, beacon-cadence tracking
and the station registry.

**What it will not get:** the Map / Silence Map, the Messages panel, silence alerts
with AI assessment, the public monitoring view, and anything added after v2.8.0.

**Why:** the Web GUI runs everywhere — Windows, Linux servers, and phones as an
installable PWA — while the tkinter desktop app is Windows-only. Maintaining two
interfaces in parallel doubled the work for features (maps, live pushes) that the
browser does better. Development continues in the Web GUI.

**If you use the Desktop GUI:** keep using it, or switch to `aprs-agent-web.exe`
and open `http://localhost:8080` — the configuration file is identical and both
share the same station database.

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
| 8080 | IN | Web GUI — admin (aiohttp) |
| 8082 | IN | Public View — read-only page (if `public_port` is set) |
| 65080 | IN | Extension Server (if enabled) |
| 443 | OUT | Bluesky / AI API / WhatsApp / Telegram |
| 587 | OUT | SMTP email |
| 993 | OUT | IMAP email |

---

## Configuration

All settings are in `aprsconfig.toml`.
The file is fully self-documented with comments.
In the GUI, all settings can be edited in the form — no manual file editing needed.

> **Save writes the file, it doesn't restart the agent.** If the agent is already running, a changed setting (a new AI provider, a different notify channel, …) only takes effect after you Stop and Start it again — the Web GUI shows a reminder in the log when you Save while running.

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

### Public View (read-only page)

Serves a second, read-only web page on its own port: Live Log / Stations / Map only —
no settings, no Start/Stop, no API keys, and the log stream filtered to packet lines.
Admin endpoints are not registered on this port at all, so it is safe to forward to
the internet while the admin port on 8080 stays local. Web GUI only.

```toml
public_port     = 8082    # 0 = disabled
public_title    = ""      # header title    — empty = "APRS-Agent · CALLSIGN"
public_subtitle = ""      # one-line description — empty = language-aware default
```

> ⚠️ Forward **only** this port. The admin port has no built-in authentication —
> keep it on `127.0.0.1` or behind a reverse proxy with auth.

### Repeater Monitor

Watches DB-matched repeaters and sends a notification when one goes offline or comes back online.
Requires `repeater_db_path` to be set and at least one notification channel configured.

```toml
[monitor]
enabled             = true
notify_channel      = "telegram"     # "telegram" or "smtp"
check_interval_mins = 10
watch_callsigns     = []             # empty = watch all DB repeaters
silence_grids       = []             # Maidenhead fields silence detection is scoped to
                                     # (e.g. ["KM","KN","LM","LN"] = Turkey; empty = worldwide)
silence_digest_mins = 0              # batch silence alerts into one combined message
                                     # every N minutes (0 = send each alert immediately;
                                     # recommended for worldwide monitoring)
prop_notify_grids   = []             # Maidenhead fields a band-opening NOTIFICATION is
                                     # limited to — matches if EITHER end of a link falls
                                     # in them (empty = notify on every opening worldwide)
```

> `prop_notify_grids` scopes only the Telegram/email message — the map and the
> timeline always show every opening worldwide. Leaving it empty while running the
> full world feed will notify on openings anywhere on the planet.

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
Bidirectional design follows [aprs-ai-gateway](https://github.com/ArdaYalinOzkan/aprs-ai-gateway) by TA3EKM — the contribution that made an APRS station able to answer rather than only report.

```toml
[extensions.ai_gateway]
enabled        = true
callsign       = "YOUR_CALLSIGN"
provider       = "puter"              # openai, anthropic, deepseek, groq, openrouter, puter, or custom
base_url       = ""                   # leave empty for built-in providers
model          = ""                   # leave empty to use provider default
system_prompt  = ""                   # optional: custom system prompt
trigger_prefix = ""                   # optional: only respond if message starts with this
extra_sms      = 1                    # 0 = single 64-char reply, 1–5 = multi-part
whitelist_enabled = false
whitelist      = []                   # callsigns allowed to use AI (empty = everyone)

# One key per provider — switching "provider" above recalls that provider's
# own key automatically (required even on a provider's free tier)
[extensions.ai_gateway.api_keys]
puter = "your-puter-key"
# groq, openrouter, openai, anthropic, deepseek, custom = "..." as needed
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

- **Live stats bar** — RX / TX / Errors / Packets / Stations / Callsigns / Uptime / Lifetime, updated every 2 seconds via WebSocket. *Uptime* is the current session; *Lifetime* is the station's total service time, accumulated in the database across restarts, so releases and reboots no longer zero it
- **Last Heard strip** — callsign chips above the stats bar; click a chip to filter the log to that station
- **Stations tab** — live table of all heard stations with type/status/callsign filters and an Organization column (filled by AI analysis); APRS Object packets are correctly attributed to the object callsign; Location column falls back to Maidenhead locator or lat/lon; click any row for a detail panel showing coordinates, frequency, tone, EchoLink, weather data, AI-extracted org/description, and packet history; auto-refreshes every 5 seconds
- **PWA — installable app** — on Chrome/Edge, use *Install* or *Add to Home Screen* to run without a browser tab; works on Android, iOS, Windows, and Mac. It does **not** work offline, deliberately: the offline shell cache was removed in 3.2.31 because it kept serving a stale copy of the page whenever the network was merely slow, which meant a browser could go on running an old release with no way to reload out of it. An admin page for a live radio feed has nothing useful to show without the feed
- **Efficient delivery** — `index.html` is served gzip-compressed (~14 KB instead of 55 KB) with ETag caching; the page loads instantly on repeat visits
- **Bounded log** — the log panel keeps the last 10 000 lines; memory stays flat even after days of continuous operation
- **Full World Feed** — optional port 10152 mode receives all worldwide APRS traffic; built-in token-bucket rate limiter prevents CPU overload
- **Propagation layer** — anomalous RF links draw as dashed great-circle lines (green < 600 km, blue < 1200 km, purple beyond) with sender/gate/distance popups; recorded openings replay from the timeline slider
- **Scales to the worldwide feed** — above 2000 plotted stations the map switches to grid clustering (numbered badges, click to zoom) with viewport-only markers at high zoom, fetching every station of the visible area from the server; the stations API serves a slim capped list (~1.3 MB instead of 40+ MB) and the detail panel fetches the full record per station; below that threshold a regional setup looks exactly as before
- **Phone layout** — on screens ≤ 700 px the settings sidebar folds behind a ⚙ overlay, the silence-alert list collapses to a one-line tappable summary, the map legend folds behind a **Key** button (four cell colours are worth one tap rather than no explanation), and the stat bar wraps into two rows; safe-area aware for notched iPhones
- **Module status indicator** — a compact badge row under the tab bar shows which features are actually active right now (AI Gateway, Station AI, Repeater Monitor, World Feed, and each messaging extension), on both the admin and public views
- **Collapsible panels** — alert and missing-station lists are one clickable line each by default at every screen size, so they never crowd out the map; expand on click and your choice is remembered across reloads
- **Aimable timeline** — the map's history slider shows day gridlines and the oldest stored date, and its clock tracks the drag itself rather than waiting on the network, so you can land on a time instead of guessing at it
- **Exportable evidence** — every silence-cell popup ends with ⬇ *Raw data* and 📋 *Copy as AI prompt*; both fetch `/api/silence/evidence?cell=XXNN`, a self-describing JSON bundle (schema, provenance, detection parameters, per-station detail, quake candidates with time offset and hypocentral distance, caveats). The popup stops being a verdict and becomes a citation — the reading is no longer capped by the model the server can afford to run automatically. Available on the public view too, and usable directly as an API by scripts
- **AI-call cooling-off** — a silence or propagation cell that clears and re-alerts within 3 hours reuses its previous AI assessment instead of spending a fresh API call, so a flapping region doesn't multiply AI usage

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
│   ├── sw.js                    # Service worker: kill switch only (unregisters itself; no caching)
│   ├── icon-192.png             # PWA icon 192 px
│   └── icon-512.png             # PWA icon 512 px
├── aprsconfig.toml.template     # Annotated config template (safe to share)
├── Dockerfile                   # Container build (Web GUI, /data volume)
├── docker-compose.yml           # One-command Docker deployment example
├── aprs_agent.spec              # PyInstaller build spec (CLI + GUI + Web)
├── aprs-symbols-24-0.png        # APRS symbol sprites — primary table
├── aprs-symbols-24-1.png        # APRS symbol sprites — alternate table
├── aprs-symbols-24-2.png        # APRS symbol sprites — overlay characters
├── HELP.html                    # User guide (bilingual EN/TR)
├── requirements.txt             # Python dependencies
└── LICENSE                      # MIT License
```

---

## License

MIT License — see [LICENSE](LICENSE) file.

APRS-Agent is built on three contributions:

**[TA3PKS](https://github.com/TA3PKS)** — the [original Rust implementation](https://github.com/ta3pks/aprs-agent) and its extension system: the Extension interface, the registry, the extension server, and the own-writer channel that lets an extension transmit without having been spoken to first. The first logger, beacon, Twitter and email extensions are that work too. The Python port kept the design unchanged, and every extension written since plugs into it.

**[TA3EKM](https://github.com/ArdaYalinOzkan)** — the bidirectional [AI Gateway](https://github.com/ArdaYalinOzkan/aprs-ai-gateway). A station that could answer, and not merely report, is what turned this project from a one-way logger into a two-way service; it is the hinge the architecture turns on, and every extension added afterwards follows that pattern.

**[TA3HRJ](https://github.com/TA3HRJ)** — the original concept, the Python port, and the work since: the desktop and web interfaces, station intelligence, the silence map and its incident response, RF propagation tracking, and the Telegram, WhatsApp, Bluesky and IMAP extensions.

---

## Contributing

Pull requests and issue reports are welcome.
Please test your changes before submitting.

73 de TA3HRJ
