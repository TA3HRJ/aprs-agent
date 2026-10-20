# Release draft — v3.2.179

The body for the GitHub release. Built 2026-10-20 on the pinned 32-bit
environment, CPython 3.13.15 32-bit, from a `git -c core.autocrlf=false
archive` export of the tag (`docs/RELEASE-HOWTO.md`). The artefact is
`aprs-agent-v3.2.179.zip`, 59.9 MiB, 250 files, sha256
`307947F7816C120942376D8F422E94996C533471DFDC50067E87DA54AE46E283`.
The four root files (`README.md`, `LICENSE`, `HELP.html`,
`aprsconfig.toml.template`) match the tag byte for byte; the web executable
reports `config.VERSION` 3.2.179 and serves the bundled Leaflet with its
published SRI hashes (smoke-tested on 127.0.0.1).

Against v3.2.165: 250 files against 248. Added: the two Leaflet files
(`static/leaflet-1.9.4.{js,css}`, web target) and the aiohttp 3.14.4
`dist-info` (both targets); removed: the aiohttp 3.14.3 `dist-info`. Changed
by CRC: `HELP.html`, `README.md`, `static/index.html`,
`aprsconfig.toml.template`, the aiohttp extensions, both executables, and the
files that change on every rebuild (`base_library.zip`, `RECORD`s).
cryptography stays at 48.0.1, the 32-bit ceiling; yarl is the pure-Python
wheel, as before.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.179 — a registered tocall, a quake ring, and a gateway that does its own arithmetic**

Asset, to match every previous release: `aprs-agent-v3.2.179.zip`

---

## Body

Fourteen releases since v3.2.165.

### On the air

- **Registered tocall.** Every packet the agent sends — replies, acks,
  bridged messages, status and the fixed beacon — now uses `APRAGT`,
  registered to APRS-Agent in the
  [APRS device identification list](https://github.com/aprsorg/aprs-deviceid).
  It replaces the generic `APRS` and the unregistered `AP4GNT`.
- **Bridge acks** (Telegram, WhatsApp, Bluesky, Twitter, e-mail) are sent as
  an ordinary message from the alias to the sender.

### AI gateway

- A provider call is limited to 30 seconds and one retry; a response without
  an answer fails cleanly, and the sender's retry of the same message is
  asked again.
- **Computed, not asked:** what an SWR figure means (reflected power,
  mismatch loss, a one-line verdict), and the nearest **digipeaters** heard in
  the last 7 days. Questions on how to lower SWR still go to the model.

### The map

- **Quake ring.** Around every quake USGS PAGER rates yellow or above, a
  dashed ring counts for 3 hours the fixed stations that went quiet, against
  the rest of the world at the same moment; orange when that is more than
  chance explains. Drawn for 24 hours, and kept across a restart.
- **Badges** count every station of the view heard in the last 24 hours,
  counted on the server; close up, every station ever heard is drawn, fainter
  the longer it has been silent.
- **Positions that are not places** are no longer drawn: 0/0, the 90/180
  pair, north of the map, the Pi-Star default (50 N 3 W) and latitudes read
  out of malformed digit runs. Such a station reads "position unreadable" in
  the search.
- A scale bar; stations stacked on one point open as a list of names.
- The page opens in the light paper theme of the aprsagent.com sites; the
  dark look is one click away and remembered.

### Silence alerts

- The hourly digest names the strongest nearby quake, and the AI note counts
  how many silent stations had stopped before it.
- One mains failure with stragglers on battery is no longer called
  "unknown" when the onset facts agree.

### Public page

- Leaflet is served by the agent itself, not by a third-party script host.
- `robots.txt`, `sitemap.xml`, `llms.txt` and an HTML 404 page.
- New settings: `public_base_url` (canonical address) and
  `public_privacy_url` (a privacy-notice link in the About box).

### Security

- aiohttp 3.14.3 → 3.14.4 (GHSA-2g87-pp6c-29x5, GHSA-5wr8-gcqf-gqf3,
  GHSA-494j-54xm-rwp3), with yarl 1.25.1, which it requires.

### Documentation

- README and HELP list what the gateway answers without the model.
