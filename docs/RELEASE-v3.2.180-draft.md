# Release draft — v3.2.180

Built 2026-10-20 the same way as v3.2.179 (`docs/RELEASE-HOWTO.md`): CPython
3.13.15 32-bit, `git -c core.autocrlf=false archive` export of the tag, the
tag's own pin file. `aprs-agent-v3.2.180.zip`, 60.0 MiB, 250 files, sha256
`DD9435513A1907AE129D9EE2676FA1B8B45E86283795D0EB8F8FAD07CA149817`. Root files
identical to the tag; web executable reports 3.2.180 (smoke-tested).

Against v3.2.179: same 250 files; the two executables and `base_library.zip`
(both targets) differ. Nothing else.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.180 — compressed log rotation keeps every file**

---

## Body

Fixes one fault found while preparing v3.2.179.

- **Compressed packet log (`log_compress = true`).** A rotation that arrived
  before the previous file had finished compressing reused its temporary name
  and target, and one of the two copies was lost. Each rotated file now gets
  a name of its own and one worker compresses them in order. Only affects
  installations with `log_compress` on and a small `log_max_mb`; it is off by
  default.

Everything else is as in v3.2.179.
