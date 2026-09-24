# Release draft — v3.2.130

The body for the GitHub release. Built 2026-09-24 on the pinned 32-bit
environment, CPython 3.13.15 32-bit, from a `git -c core.autocrlf=false
archive` export of the tag (`docs/RELEASE-HOWTO.md`), with one exception
stated here rather than hidden: `requirements-build-win32.txt` was taken from
commit `62578d1`, one commit after the tag, which moves httpx2 and httpcore2
from 2.10.0 to 2.13.1. The pin file is not shipped, so every shipped file
still comes from the tag. The artefact is `aprs-agent-v3.2.130.zip`,
59.7 MiB, 248 files, sha256
`CD8D8356A7A151BE32EB426B14F65924327B21A46AF5AE2BC6870821F660C156`.

All 92 exported files matched their blobs in the tag, and every shipped root
and static file in the archive matched the tag byte for byte. Both bundled
executables carry `config.VERSION` 3.2.130 and the WAL change, and the OpenAI
client on the build interpreter was exercised against httpx2 2.13.1 as far as
the network layer.

Against v3.2.125: 248 files in both. The only names that changed are the
`dist-info` folders of httpx2 and httpcore2 (2.10.0 out, 2.13.1 in, 13 files
each way). Six files differ by CRC: `README.md` (+3,030 bytes, the gateway
section), `static/index.html` (+2,627, the Messages merge, the plural, the
folding column), both executables, and both `base_library.zip` at identical
size with new internal timestamps, as on every rebuild. cryptography stays at
48.0.1, the 32-bit ceiling.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.130 — all fourteen days, and a map that does not wait**

Asset, to match every previous release: `aprs-agent-v3.2.130.zip`

---

## Body

Five releases since v3.2.125. Most of them came from screenshots sent in by
the people using the program, and the rest from an audit of the running
server.

### The Messages tab shows what it promises

The tab says it keeps fourteen days, and the database did hold them: 257
gateway messages. The tab showed 29. It asked for the newest 2,000 rows of
all traffic, and on a busy feed ordinary APRS messages had pushed the
gateway's own conversation out of that window. It now asks for the gateway's
conversation separately and merges the two, and all fourteen days are there.

### Smaller things the screenshots showed

- A position answer for a station that arrived over the internet named the
  core server that relayed it, as if it were an igate. It now says
  "internet-connected".
- "1 operators today" is "1 operator today".
- The public map offered a link to a Messages tab that visitors do not have.
  It is gone.
- The usage line is there from the first second after a restart instead of
  after the first minute.

### A settings column that folds away

The gear button already opened and closed the settings on a phone. It now
works at every width: on a wide screen it folds the column away and gives the
space to the map, and the choice is remembered.

### The map no longer waits for the database

Once a minute the program writes its whole station registry back to disk,
which takes 10 to 18 seconds on a quarter of a million stations. Until now
every read queued behind that write, so a request that needs 4 ms could take
8 or 9 when it landed at the wrong moment. The database now runs in SQLite's
WAL mode, where reads never wait for a writer. After the change, 90 requests
from outside all answered within 1.3 s.

The database file is now accompanied by `-wal` and `-shm` files while the
program runs. If you back it up by copying files, stop the program first or
copy all three.

### Quieter where nothing is wrong

An idle Telegram bot no longer writes an error every few minutes. The long
poll now has a real margin, a single failed poll is logged as what it is, and
only an outage of three polls or more counts as an error — once, however long
it lasts.

### Under the hood

- httpx2, which the AI providers' client library pulls in, moves from 2.10.0
  to 2.13.1, past one high and two moderate advisories.
- The server logs its memory use once a day.
- The guard rail is **thirty-three checks**, thirty-two of which run offline.
  Two are new (`check_telegram_poll`, `check_db_wal`), and each was watched
  failing against the code it replaced before being trusted.
