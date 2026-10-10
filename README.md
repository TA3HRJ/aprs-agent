# APRS-Agent

[![Release](https://img.shields.io/github/v/release/TA3HRJ/aprs-agent)](https://github.com/TA3HRJ/aprs-agent/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

An APRS-IS server agent with a graphical interface and extensible plugin system, written in Python.

Connects to the global [APRS-IS](http://www.aprs2.net/) network and provides
several automation features useful for amateur radio operators.

### 🔴 [aprsagent.com](https://aprsagent.com/) — project site and live demo

The site explains what the software does; the live instance runs at
[map.aprsagent.com](https://map.aprsagent.com/).

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
| 🌐 | **Web GUI** | Browser-based interface, installable PWA, live stats, Last Heard strip, Stations tab, Map tab. The map opens first; your own last choice of tab is remembered. A search box on the map finds callsigns the way aprs.fi does (`TA3HX*` for every SSID, `?` for one character) across the whole registry, not only the stations on screen, and goes straight to the one you pick; a station that sends a position we cannot read says so, apart from one that sends none. The same box takes a Maidenhead locator (`KM`, `KM38`, `KM38nk`) and frames that square, opening the silence cell drawn there; every row of the silence alert list leads to its cell on the map. Pages and JSON APIs are gzip-compressed. It opens in the light paper theme of the aprsagent.com sites; the dark look is one click away and remembered |
| 🗺️ | **Silence Map** | Leaflet map of all heard stations with real APRS symbols; detects regions where stations fall silent together (per-station beacon-cadence baseline, Maidenhead cell clustering, igate-failure discrimination) and paints affected cells. **An alert means the silence is news, not merely that the threshold was met.** A cell stays on the map but is kept out of the alert list, the notifications and the AI assessment when its silent stations are ones it habitually misses (*chronic*), when they belong to too few separate operators (several SSIDs of one callsign are one shack), or when no igate ever heard any of them over the air — an internet or app dropout, not a regional event. A station that is *unusual* in a cell keeps it alerting, and the popup names it: *"New here: YM1ABC-7 — normally not among this cell's missing stations."* The raw threshold result is still published as `threshold_met`. Cell colour: red for a regional silence, yellow when a shared igate was **seen** to go quiet, orange when one gate that cannot be seen carries every silent station, purple when nothing local ever heard them, grey for measured but not announced. Popups flag silent stations whose own position cannot be trusted. If the APRS-IS feed stops, or never starts, nothing is judged: the page says so and holds the last confirmed reading, and time the agent was not listening never counts as a station's silence. The timeline slider replays the last 14 days of alerts; new alerts get an AI assessment (via AI Gateway) shown in the popup and are sent to the Monitor notify channel (Telegram/email). The agent's own Fixed Beacon, APRS Objects and weather-service warnings never count as silence sensors. Scope it to your region with `monitor.silence_grids`, and batch worldwide alerts with `monitor.silence_digest_mins` — see [Repeater Monitor](#repeater-monitor) |
| 📡 | **RF Propagation Tracking** | Every qAR/qAO-gated packet is one realised RF link whose length is known exactly (sender's in-packet position to the igate's position). Per-gate baselines, kept across restarts, separate "this mountain-top gate always hears far" from "the band just opened"; abnormally long links draw as dashed great-circle lines on the map, colour-tiered by distance. A link judged against its gate's own history is drawn solid, one that only cleared the absolute distance floor faint, and the popup names the test that judged it. Suspect links — a position jump or a balloon — are drawn grey and dotted and kept out of baselines and openings. The exported bundle carries the gate's baseline as it stood when the link was flagged. A gate whose own bar has climbed past the 5000 km ceiling can no longer flag anything, and is reported as such. Two or more distinct senders in the same Maidenhead field within 30 minutes become a **band-opening event** — notified via Telegram/email with an optional AI read (tropo / sporadic-E / aurora) and replayable from the map timeline. Every position is checked against the area its callsign prefix is allocated to; a link whose position contradicts its own callsign is kept out of openings, and so is a link on a gate's fixed, repeated distance (a coordinate error, not propagation). Internet-origin, digipeated, object, balloon (>3000 m) and >5000 km (GPS garbage) packets are excluded |
| 💾 | **Persistence** | Station records, beacon-cadence history and the station's lifelong uptime survive restarts (SQLite `aprs_stations.db` next to the config, shared by both GUIs) |
| 💬 | **Messages Tab** | Every APRS message the agent hears or sends, in one panel — time, direction, from, to, text, and the bridge it belongs to (AI / Telegram / WhatsApp / Email / …). Outgoing messages are captured from the send loop, since APRS-IS never echoes our own traffic. Rolling buffer of the last 400 messages, pushed live over WebSocket; ack/telemetry chatter filtered out. Admin only — not exposed on the public view |
| 🚨 | **Still-missing stations** | When a silence alert clears because most of its cell recovered, the stations that never came back stop being counted — and those are the ones that matter. They are tracked individually instead, listed longest-silent first, and leave the list only by being heard again. Survives a restart. Wording is deliberately plain: no APRS signal is a weak welfare signal, not a confirmed emergency |
| 📤 | **Exportable evidence** | Any visitor, including on the public view, can download the raw evidence behind a silence popup (⬇ Raw data) or open it as a ready-made prompt (📋 Copy as AI prompt) and re-run the analysis on their own AI, at their cost. The prompt opens in a box with the text already selected; Ctrl+C or the box's own Copy button copies it. The bundle is self-describing: schema, generation time, the detection parameters, per-station silence detail, how often each silent station appears among the cell's past alerts, how many distinct operators and independent gates the silent set represents, nearby USGS quakes with time offset and hypocentral distance, and the provider/model behind the shown note. No keys, no config, no paths |
| 🌍 | **Earthquake correlation** | A regional silence cluster and a nearby earthquake look identical to the detector. Recent M4.5+ quakes (USGS, free, no API key) within 500 km are attached to the alert, from 24 h before the silence began to the last silent station's last packet — in the map popup, the Telegram/email notification and the hourly digest, so "shared infrastructure or power issue" becomes "M7.4, 165 km away, 10 minutes before the silence began". The AI assessment is told how many of the silent stations had already stopped before each quake, and names an M6+ or nearby one whatever it concludes |
| 🔶 | **Quake ring** | A large quake can silence a share of a region's stations spread over several squares, none of which meets the cell rule. Around every quake USGS PAGER rates yellow or above, the map draws a dashed ring (150 km below M7, 300 km to M7.9, 500 km from M8) and counts, for 3 hours, the fixed stations on the air when it struck that went quiet — against the share going quiet in the rest of the world at the same moment. Orange when that is more than chance explains, grey otherwise; the dot at the epicentre shows the numbers. A count, not an outage report, and it sends no notification |
| 👁️ | **Public View** | Optional read-only monitoring page on a separate port (`public_port`): Live Log / Stations / Map only — no settings, no start/stop, no API keys, log stream filtered to packet lines. Safe to expose to the internet while the admin port stays local |
| 📊 | **Stations Tab** | Live table of all heard stations — type, location, organization, frequency, online/offline status; Object packets parsed; location falls back to Maidenhead locator or coordinates |
| 🗄️ | **Turkey Repeaters DB** | Enriches station records with city, district, frequency, tone, band, mode from a local JSON database |
| 🔔 | **Repeater Monitor** | Detects when DB-matched repeaters go offline or come back; sends Telegram or email notification |
| 🧠 | **AI Station Analysis** | Periodically sends beacon comments to AI to extract organisation name and description — results shown in Stations tab; skips seasonal/greeting messages |
| 📡 | **Fixed Beacon** | Periodically sends your station's position — with APRS symbol picker and Maidenhead / QTH Locator support |
| 🪵 | **Logger** | Logs incoming APRS packets to the terminal, with type and keyword filters |
| 🤖 | **AI Gateway** | Answers APRS messages. Questions about the network are answered from the station registry without a model call at all — your own position, which igate heard you, the nearest igates or repeaters, the nearest APRS weather reading, the propagation openings this agent measured, and another station's last position (with `NOLOOKUP` for anyone who would rather be left out). Everything else goes to AI (ChatGPT/Claude/DeepSeek/Groq/OpenRouter/Puter/custom — free options available), carrying the last few exchanges with that station so a follow-up makes sense; a separate API key is stored per provider, recalled automatically when you switch |
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

The Desktop GUI (`aprs-agent-gui.exe`) is published on its own release line and
is not in this zip — see [Desktop GUI — feature freeze](#desktop-gui--feature-freeze).

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
The **feature level** is what is frozen, not the build: the Desktop line still
takes fixes, and its counter moves when it does. It stands at **v2.8.3** — v2.8.1
a config-save fix, v2.8.2 a Telegram/IMAP polling fix, v2.8.3 a config crash and
patched dependencies. The About window says which is which: *Desktop v2.8.3 ·
core 3.2.97*.

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

**Where to get it:** the Desktop build is published on its own release line and
is **not** included in the main `aprs-agent-vX.Y.Z.zip`, which carries the CLI and
the Web GUI. Download it from the newest
[`*-desktop-final`](https://github.com/TA3HRJ/aprs-agent/releases) release —
currently
[v2.8.3-desktop-final](https://github.com/TA3HRJ/aprs-agent/releases/tag/v2.8.3-desktop-final).

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

# Packet lines always go to the Web GUI Live Log, never to the process
# stderr that systemd/journald captures: on a full-feed instance they would
# push every other line out of the journal. Set log_file to keep a copy you
# can grep; it rotates on its own. Empty = Live Log only.
log_file    = ""                                 # e.g. "/var/log/aprs/packets.log"
log_max_mb  = 50                                 # rotate at this size
log_backups = 3                                  # keep this many rotated files
log_compress = false                             # gzip rotated files (about 2.6:1)
```

Startup lines, warnings and errors from every extension still go to the
journal — that is what `journalctl -u aprs-agent` is for, and keeping the
packet feed out of it is what makes those lines survive long enough to read.

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
public_title    = ""      # header title — empty = "APRS-Agent · CALLSIGN".
                          # Setting it replaces the whole thing, callsign
                          # included: a page you named yourself is not one
                          # we should be appending to.
public_subtitle = ""      # one-line description — empty = language-aware
                          # default. A value here is a single fixed string,
                          # so it stays in whichever language you wrote it
                          # even when the reader switches to the other.
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
🔴 YM1ABC is now OFFLINE (last heard 1h 23m ago)
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

Answers incoming APRS messages. Free providers available.

#### What it answers without asking the model

The agent already holds over 300,000 stations, the igate that
carried each of them, and the propagation openings it measured itself.
Sending someone to a website for facts that are in memory is a poor answer,
so these are served from the registry — no model call, no API cost, and no
chance of an invented number:

| Question | Answer |
|---|---|
| `where am I`, `my last position` | your own record: position, grid, age, and the igate that gated you |
| `which igate hears me` | the igate on your packet's own path — or that nobody is, if you arrived over the internet, since a `qAC` path names a core server rather than an igate |
| `nearest igate`, `nearest repeater` | the closest ones with distances, measured from a grid you name or from your last beacon |
| `propagation near me` | openings this agent measured within 400 km and three hours, or a plain statement that there were none |
| `weather`, `wx KM38` | the nearest APRS weather station, with its distance, its age, and **what it was measured from**; beyond 30 km the answer opens with the distance and says it is not local |
| `where is XX1YYY` | that station's last position, its age and its distance from you |
| `what can you do` | a fixed sentence, answered before the rate limiter because it costs nothing |
| `TEST` | what the packet itself says: who sent it, which igate gated it, whether it touched RF at all |

Two boundaries are deliberate. An answer about another station is **one
observation** — never a name, a licence record or an address — and a station
that sends **`NOLOOKUP`** is left out of other people's answers, and of the
map's callsign search, until it sends `LOOKUP`. And a refusal names its own reason: no data, no place names
(a postcode is not a Maidenhead square), or a station that opted out.

Everything else goes to the model, carrying the last three exchanges with
that station for ten minutes, in memory only, so that *"how long would it
take by car?"* still knows which journey you meant.

Automatic stations are not answered at all. APRS service names are not
callsign-shaped — `QRX`, `WXBOT`, `SMSGTE` carry no digit where a callsign
must — and answering one is how two machines end up talking to each other on
a shared channel.

> **⚠️ Everything that passes through this is public.**
> Amateur radio is conducted in the clear; encoding a transmission to obscure
> its meaning is not permitted (ITU Radio Regulations, Article 25, which governs
> the amateur service). Both the incoming question and the reply go out in the
> clear over RF and onto the internet through APRS-IS, and sites like aprs.fi
> aggregate that traffic, keep it searchable and retain it for years. If you run
> a gateway, that applies to **everyone who writes to it**, not only to you —
> tell them so where they will see it.
>
> Answers can be wrong; a language model can be confidently mistaken. APRS
> guarantees no delivery, so this is not an emergency tool. APRS-IS is for
> licensed amateur radio operators, and a sender's radio has to be able to
> send **and receive** APRS messages — a radio that beacons position but
> cannot display an incoming message will send the question and never show
> the answer.
Bidirectional design follows [aprs-ai-gateway](https://github.com/ArdaYalinOzkan/aprs-ai-gateway) by TA3EKM — the contribution that made an APRS station able to answer rather than only report.

#### Identification and responsibility

A gateway addressee such as `MYBOT` **is not a callsign**. It identifies a piece
of software, not a station: no authority issues it, and none needs to. Nor can
it be mistaken for one — an allocated callsign carries a digit, and these
service addressees do not.

The agent **operates no transmitter**. It is an APRS-IS client over TCP; the
session is authenticated with the operator's own callsign and passcode, and its
packets carry the `TCPIP*` path that marks internet origin. Where a reply
reaches RF, the transmitting station is an **igate**, keying up under its own
licence and its own callsign, and that operator is responsible for that
emission — the ordinary third-party model of APRS messaging.

What that leaves with you, as the person running a gateway:

- **Be findable.** `status_text` announces who operates the service as an APRS
  status packet, so somebody meeting it on aprs.fi can find you without asking.
- **Constrain the output.** Other licensees transmit your replies. `system_prompt`
  is where you keep them inside amateur rules — no commercial content, no
  profanity, nothing encoded to obscure meaning, no entertainment broadcast.
- **Be able to stop.** `enabled = false` takes effect within about five seconds,
  without a restart.

Running an AI over amateur radio is a **new application, not an unregulated
one**. The existing rules cover content whatever composed it, and the operator
is answerable for what the station emits. Treat it as experimental in ambition
and conventional in compliance.

```toml
[extensions.ai_gateway]
enabled        = true
callsign       = "YOUR_CALLSIGN"
provider       = "puter"              # openai, anthropic, deepseek, groq, openrouter, puter, or custom
base_url       = ""                   # leave empty for built-in providers
model          = ""                   # leave empty to use provider default
system_prompt  = ""                   # optional: custom system prompt
trigger_prefix = ""                   # optional: only respond if message starts with this

# Extra addressees this gateway also answers to, on top of "callsign" above.
# The APRS addressee field is a fixed 9 characters either way, so a short alias
# saves nothing on air — what it saves is key presses on a handheld keypad,
# where a digit costs four presses and a letter often costs one.
# Both the callsign and every alias are matched with the SSID ignored, so
# MYBOT-1 reaches the same gateway as MYBOT.
#
# Leave this EMPTY unless you mean it. APRS-IS is one worldwide feed: an
# addressee is not yours, it is first-come and unenforced. Pick something
# nobody else would plausibly choose, and never publish a name you did not
# pick yourself — two gateways answering the same addressee means a stranger's
# question gets two answers, and neither operator can tell it is happening.
trigger_aliases = []                  # e.g. ["MYBOT"] — see the warning above

extra_sms      = 1                    # 0 = single 64-char reply, 1–5 = multi-part
whitelist_enabled = false
whitelist      = []                   # callsigns allowed to use AI (wildcards OK: TA1*)
                                      # NOTE: enabled with an EMPTY list answers nobody.
                                      # Clearing the list closes the gate, it does not open it.

# Per-sender token bucket. A sender may ask `rate_burst` questions back to back,
# then one more per `rate_refill_s` seconds, refilling to the full burst once
# idle. Deliberately not a flat cooldown: the first people to try a new gateway
# ask several questions in a row, and freezing them out teaches the wrong thing.
# Someone who runs out is told once per episode, with the wait in minutes.
# Either setting at 0 switches the limiter off.
rate_burst     = 4
rate_refill_s  = 180
rate_notice    = "Too many questions - please wait {m} min, then ask again"

# Whole-instance ceiling per UTC day. 0 = none. Per-sender limits do nothing
# against a thousand strangers asking one question each, which is what happens
# the first time somebody posts about your gateway — set this to whatever you
# are willing to pay for in a day.
daily_limit    = 0
daily_notice   = "Daily question limit reached on this gateway - try tomorrow"

# Weather questions are answered from the nearest APRS weather station this
# agent has heard — not from the model, and not from a forecast service. This
# is how far away that station may be. APRS weather coverage is dense in some
# countries and almost absent in others, so the useful value is local: raise
# it if you get "no weather station in my records", lower it if the answers
# come from too far to mean anything. The reply always states the distance
# and the age of the reading, so nothing arrives sounding more current than
# it is. A reading from more than 30 km away is still given, but opens with
# the distance and says it is not local weather.
wx_radius_km   = 250

# One key per provider — switching "provider" above recalls that provider's
# own key automatically (required even on a provider's free tier)
[extensions.ai_gateway.api_keys]
puter = "your-puter-key"
# groq, openrouter, openai, anthropic, deepseek, custom = "..." as needed
```

Two small files live beside the config file and are written by the gateway
itself: `ai_gateway_msgid`, the last APRS message number used, so a restart
does not reuse numbers a client has already seen and discarded; and
`ai_gateway_nolookup`, the callsigns that have asked not to be looked up by
others. Neither needs editing; deleting the first costs numbering continuity,
deleting the second forgets people's wishes.

To ask the AI via APRS, send a message to the configured callsign:
```
YOUR_CALLSIGN What is APRS?
```

**Opening it to the whole feed, and closing it again.** Turning the whitelist off
makes the gateway answer anybody on APRS-IS, which is a reasonable thing to do
and a real cost: each question is one paid API call and up to `extra_sms + 1`
transmissions. The whitelist, the two bucket settings and the daily ceiling are
all fields in the admin screen, and the gateway re-reads them when the file
changes — **shutting the gate takes about five seconds and no restart**. A
broken edit keeps the previous settings rather than falling open.

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
TA1ABC-7 Hello, your beacon is working fine!
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
- **PWA — installable app** — on Chrome/Edge, use *Install* or *Add to Home Screen* to run without a browser tab; works on Android, iOS, Windows, and Mac. It does **not** work offline, deliberately: a page for a live radio feed has nothing useful to show without the feed, and a cached copy could keep running an old release
- **Efficient delivery** — `index.html` is served gzip-compressed (about 80 KB instead of 250 KB) with ETag caching; the page loads instantly on repeat visits
- **Bounded log** — the log panel keeps the last 10 000 lines; memory stays flat even after days of continuous operation
- **Full World Feed** — optional port 10152 mode receives all worldwide APRS traffic; built-in token-bucket rate limiter prevents CPU overload
- **Propagation layer** — anomalous RF links draw as dashed great-circle lines (green < 600 km, blue < 1200 km, purple beyond) with sender/gate/distance popups; recorded openings replay from the timeline slider
- **Scales to the worldwide feed** — above 2000 plotted stations the map switches to grid clustering: the server counts every station of the view heard in the last 24 hours into numbered badges (click to zoom). From zoom 9 it draws every station ever heard there, as this map always has — one silent for ten days is part of the local picture — fainter the longer it has been quiet (heard within 24 h full, 1-10 days half, older faint), so the full ones are what the badge counted; stations on one point are one badge listing their names; the stations API serves a slim capped list (~1.3 MB instead of 40+ MB) and the detail panel fetches the full record per station; below that threshold a regional setup looks exactly as before. A metric scale sits under the zoom buttons
- **Only real places are drawn** — "no position" placeholders (0°/0°, 90°/180°, the Pi-Star default 50°N 3°W), anything north of what the map can draw, and latitudes that can only be read out of a malformed field are not plotted, and do not count as silence sensors or propagation endpoints. Positions stored before this are dropped on start, and kept aside so they can be restored
- **Phone layout** — on screens ≤ 700 px the settings sidebar folds behind a ⚙ overlay, the silence-alert list collapses to a one-line tappable summary, the map legend folds behind a **Key** button (four cell colours are worth one tap rather than no explanation), and the stat bar wraps into two rows; safe-area aware for notched iPhones
- **Module status indicator** — a compact badge row under the tab bar shows which features are actually active right now (AI Gateway, Station AI, Repeater Monitor, World Feed, and each messaging extension), on both the admin and public views
- **Collapsible panels** — alert and missing-station lists are one clickable line each by default at every screen size, so they never crowd out the map; expand on click and your choice is remembered across reloads
- **Aimable timeline** — the map's history slider shows day gridlines and the oldest stored date, and its clock tracks the drag itself rather than waiting on the network, so you can land on a time instead of guessing at it
- **Exportable evidence** — every silence-cell popup ends with ⬇ *Raw data* and 📋 *Copy as AI prompt*; both fetch `/api/silence/evidence?cell=XXNN`, a self-describing JSON bundle (schema, provenance, detection parameters, per-station detail, quake candidates with time offset and hypocentral distance, caveats). Available on the public view too, and usable directly as an API by scripts
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
├── tools/                       # offline checks (every one runs in CI) and feed-replay tools
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

**[TA3HX](https://github.com/TA3HRJ)** (formerly TA3HRJ) — the original concept, the Python port, and the work since: the desktop and web interfaces, station intelligence, the silence map and its incident response, RF propagation tracking, and the Telegram, WhatsApp, Bluesky and IMAP extensions.

---

## Contributing

Pull requests and issue reports are welcome.
Please test your changes before submitting.

73 de TA3HX
