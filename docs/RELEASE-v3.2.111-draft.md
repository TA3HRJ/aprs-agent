# Release draft — v3.2.111

The body for the GitHub release. Built 2026-09-16 on the pinned 32-bit
environment (`docs/RELEASE-HOWTO.md`), CPython 3.13.15 32-bit, **from a
`git -c core.autocrlf=false archive` export of the tag** rather than a
checkout. The artefact is `aprs-agent-v3.2.111.zip`, 59.6 MiB, 248 files,
sha256 `3354E5DDE2E1397DB6F8A4A951C96465E2766A13688C84E7CCF95C457C3BBC4F`.

Every exported file was compared with its blob in the tag, 79 of 79 identical,
and every shipped root and static file in the archive was compared the same
way, 10 of 10 identical. The built web binary's own `/api/info` reports
`3.2.111`.

Against v3.2.107: 36 files added and 28 removed, all of them dependency
metadata and binaries — `cryptography-45.0.7.dist-info` replaced by
`48.0.1.dist-info` (which adds two SBOM files), `pydantic-2.13.4.dist-info` by
`2.13.5.dist-info`, and two new `zstandard` extension modules, in each of the
two program folders. That is the whole of the +8 in the file count.

Seventeen files differ by CRC:

- the cryptography, propcache and pydantic_core binaries, from the version moves;
- both executables at +167 KB, which carry the pure-Python archive — measured
  inside it, the growth is `zstandard` and the atproto 0.0.72 client modules;
- `aprsconfig.toml.template` in all three places, the only shipped text file
  whose content changed: the login-callsign explanation from v3.2.108;
- both `base_library.zip`, identical size, as on every rebuild;
- **`README.md` and all three `HELP.html` copies, smaller by exactly their line
  counts.** Not a content change: the v3.2.107 archive carried those files, and
  the template, with CRLF line endings, so it did not match its own tag. This
  archive matches its tag byte for byte. How that happened, and how the build
  now avoids it, is in `docs/RELEASE-HOWTO.md`.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.111 — security fixes, and your own hotspot was hiding from you**

Asset, to match every previous release: `aprs-agent-v3.2.111.zip`

---

## Body

Four versions since v3.2.107. The newest is a security update; the two before
it fix something no error message would ever have told you.

### Security updates

**aiohttp 3.14.3.** The web server library had a request-smuggling bug in how
it handled WebSocket upgrades (CVE-2026-69243), plus two client-side issues
(CVE-2026-59881, CVE-2026-69244). aiohttp is what serves the Web GUI and its
live updates, so this is the one to take.

**cryptography 48.0.1 in this Windows build, 50.0.1 on the server.** Version
46 and earlier carry a vulnerable copy of OpenSSL (GHSA-537c-gmf6-5ccf) and
three further advisories (CVE-2026-69247, -69248, -69249). It could not be
updated sooner because the Bluesky library, atproto, capped it; atproto 0.0.72
lifts that cap, so both move together.

Stated plainly: **this Windows build closes the OpenSSL advisory but not the
other three.** Those are fixed only from cryptography 49, and cryptography
publishes no 32-bit Windows packages from 49 onward. The library is used by the
Bluesky extension; if you do not use Bluesky, it is never loaded.

Other dependencies moved by patch releases only. Larger upgrades are held back
on purpose.

### Your own hotspot could be invisible to your own agent

If the agent logs in to APRS-IS with your bare callsign — `TA1ABC` rather than
`TA1ABC-5` — and another device of yours, a hotspot or an igate, also sends to
APRS-IS under that same bare callsign, **the server never delivers that
device's packets to the agent.** APRS-IS treats a packet as belonging to the
connection whose login matches it and withholds it.

Nothing errors and nothing is logged. The device is simply missing from the
map, from silence detection and from the station registry, while it is plainly
visible on aprs.fi. On the station where this was found, a hotspot beaconing
every ten minutes produced zero packets in over five hours; with an SSID added
to the agent's login, its next beacon arrived 51 seconds later.

- The login callsign is now printed at startup, in the Live Log **and** in the
  service journal.
- A login without an SSID produces a warning naming it.
- Adding an SSID costs nothing: the APRS-IS passcode is calculated from the
  base callsign and does not change.
- `aprsconfig.toml.template` explains the same, next to the `callsign` setting.

**If you log in with a bare callsign and own other APRS-IS gear, add an SSID.**

### "Where am I?" is answered from the registry

Asking the AI gateway "my location?" or "where am I?" used to reach the
language model, which has no access to the station registry and said it did
not know — even when the asking station had beaconed minutes earlier.

The gateway now answers first-person position questions itself, from the
registry, using the sender's full callsign including its SSID. Turkish phrasing
is recognised too. Questions that only look similar, such as "where is the
nearest digi", still go to the model.

One known limit, recorded rather than hidden: a compound question such as
"time, date and my location?" is answered in part. The gateway answers the
first thing it can answer deterministically and stops there.

### Under the hood

The guard rail is **twenty-five checks**, twenty-four of which run offline.
Each was written from a live failure and watched failing against the broken
code before being trusted.
