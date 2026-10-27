# Release draft — v3.2.198

Built 2026-10-27 the same way as v3.2.180 (`docs/RELEASE-HOWTO.md`): CPython
3.13.15 32-bit, `git -c core.autocrlf=false archive` export of the tag (155 of
155 files identical to their blobs), the tag's own pin file (pillow 13.0.0,
setuptools 84.2.1, cryptography 48.0.1). `aprs-agent-v3.2.198.zip`, 60.2 MiB, 248 files, sha256
`BE38EB5FA4FD5F017989893ACE04440B57F4DB2988A1BC104DCAC796D614E25B`. Root files
identical to the tag; the web executable reports 3.2.198 and serves the
bundled Leaflet with its published SRI hashes; the CLI starts (smoke-tested
on 127.0.0.1).

Against v3.2.180: 248 files against 250. Removed: `PIL/_imagingmath`
(both targets; Pillow 13 ships no separate module). Changed by CRC: the
other Pillow extension modules, `certifi/cacert.pem`, `HELP.html`,
`README.md`, `LICENSE`, `aprsconfig.toml.template`, `static/index.html`,
`static/sw.js`, both executables and `base_library.zip`. Nothing added.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.198 — person-to-person bridges, STATUS from the radio, and Pillow 13**

Asset, to match every previous release: `aprs-agent-v3.2.198.zip`

---

## Body

Eighteen releases since v3.2.180.

### Security

- **Telegram bridge:** only the configured chat is relayed to APRS. Until
  v3.2.191 anyone who found the bot and wrote to it was put on air under the
  operator's callsign. Update if you run the Telegram bridge with polling on.
- **Pillow 13.0.0** (closes the advisories open on 12.3.0), **certifi
  2026.10.19** (GHSA-6q48-6c7w-9gw2), setuptools 84.2.1.

### Bridges between licensed amateurs

- **Telegram and e-mail, person to person**, both off by default
  (`allow_links`, "Person to person" in the panel). A Telegram chat or an
  e-mail address is linked to a callsign only when its owner proves that
  callsign from the radio with a six-digit code (`/link CALL` in the bot or
  `LINK address` to the e-mail alias, then `LINK <code>` from the radio).
  Linked users then send and receive under their own callsign, 20 messages
  an hour. `/unlink` or `UNLINK` from the radio removes the link at once.
  Links are kept in `bridge_links.json` beside the config: callsign, chat id
  or address, time.
- E-mail for links goes through its own server setting
  (`links_smtp_server`, `links_from_email`, default `localhost:25`), never
  through the operator's mail account.
- **Who appears as the sender** is chosen per bridge: the originator's own
  callsign (default), or the gateway's callsign with "CALL: " opening the
  text. Either way the originator is named.
- The status row shows all six bridges, the ones that are off in grey;
  bridge traffic is always kept in the Messages history.

### AI gateway (DMWGPT)

- **`SERVICES` / `SERVIS`** answers from the configuration which bridges this
  gateway carries, the alias to send to, and whether they are open to the
  asker; with Telegram links open it names the bot. `HELP` points to it.
- **`STATUS [grid]` / `DURUM [grid]`**: the silence state of your locator
  square (or the one you name) and any quake ring reaching it, from the
  server's own data.
- Message text never carries `{` (APRS 1.2: it starts the message number);
  `{` and `}` become `(` and `)`.
- **AI providers:** Google Gemini is the default (free tier,
  `gemini-3.5-flash-lite`); current models for Groq, OpenRouter, OpenAI and
  Anthropic; reasoning models get their reasoning settings. DeepSeek is
  unchanged.
- Delivery counts: each answer is counted as fully acknowledged or not, per
  day, and `/api/counters` reports the last 30 days.

### The map and its feeds

- **Atom feed** `/feed/silence.atom`: announced silence alerts and quake
  rings, newest first, filterable by locator (`?grid=KM,KN41`), in Turkish
  with `?lang=tr`.
- **Embeddable status card** `/embed/status?grid=KM38` for an iframe: silence
  state, a quake ring reaching the square, nearby propagation openings.
  No scripts; `&lang=tr`, `&theme=dark`.
- `/?q=<square>` opens the map on that square.

### Fixes

- The repeater database matches a listing to the right station: exactly
  with an SSID, and without one only to a station whose own symbol is a
  repeater; a beaconed position is never overwritten.
- The station analysis no longer stores "null" or a bare callsign as an
  organisation (stored rows are cleaned once).

Everything else is as in v3.2.180.
