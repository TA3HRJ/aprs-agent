# Release draft — v3.2.116

The body for the GitHub release. Built 2026-09-19 on the pinned 32-bit
environment, CPython 3.13.15 32-bit, from a `git -c core.autocrlf=false
archive` export of the tag (`docs/RELEASE-HOWTO.md`). The artefact is
`aprs-agent-v3.2.116.zip`, 59.6 MiB, 248 files, sha256
`D38B6731B948D534E439CCBF088E1A488FAC993672AFCA79FD6AB0D5401C141F`.

All 83 exported files matched their blobs in the tag, and every shipped root
and static file in the archive matched the tag byte for byte. The `config`
module bundled in both executables carries `3.2.116`.

Against v3.2.115: nothing added, nothing removed, thirteen files differing by
CRC — the credit lines in `README.md` (+16 bytes), `LICENSE` (+34),
`HELP.html` (−2, three copies), `aprsconfig.toml.template` (−1, three copies)
and `static/sw.js` (−1), both executables (+10 and +11 bytes, carrying the
changed headers and version), and both `base_library.zip` at identical size
with new internal timestamps, as on every rebuild. Dependencies are unchanged.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.116 — TA3HRJ is now TA3HX**

Asset, to match every previous release: `aprs-agent-v3.2.116.zip`

---

## Body

The maintainer's callsign changed from TA3HRJ to **TA3HX** on 16 September
2026. This release carries the new callsign everywhere the program names its
author: the licence, the README, the help page footer and the desktop About
dialog. The licence and README keep "formerly TA3HRJ" so the earlier copyright
stays traceable. Sample callsigns in hints and examples are now `TA1ABC`.

The GitHub address stays `github.com/TA3HRJ/aprs-agent`; links and the update
source are unchanged.

No change in behaviour. If you run v3.2.115 there is nothing here you need.
