# Publishing a Windows release

Written 2026-08-26, when the last published release was v3.2.67 and the code
was at v3.2.97 — thirty versions of drift, because nothing here was written
down.

There is no CI for this. `.github/workflows/docker.yml` builds and smoke-tests
the container and does nothing else; the Windows binaries have always been
built by hand and uploaded by hand.

---

## 1 · Build, on the pinned environment

`requirements-build-win32.txt` is not a suggestion. It pins **32-bit** CPython
and exact dependency versions, and one of them is load-bearing:
`cryptography==45.0.7` is the newest release carrying a **win32 wheel** inside
atproto's cap. Build with anything else and the artefact silently stops being
what every previous release was.

```
C:\Python313-32\python.exe -m pip install -r requirements-build-win32.txt
C:\Python313-32\python.exe -m PyInstaller aprs_agent.spec --noconfirm
```

Output, three folder-mode targets:

```
dist/aprs-agent/aprs-agent.exe           CLI, headless
dist/aprs-agent-gui/aprs-agent-gui.exe   Desktop GUI (frozen at v2.8.0)
dist/aprs-agent-web/aprs-agent-web.exe   Web GUI — the one to recommend
```

**Check the architecture before shipping.** A 64-bit build looks fine and
breaks every 32-bit user silently:

```
C:\Python313-32\python.exe -c "import platform; print(platform.architecture()[0])"
```

Then zip **the three target folders and four files from the repository root**
as `aprs-agent-vX.Y.Z.zip`:

```
dist/aprs-agent  dist/aprs-agent-gui  dist/aprs-agent-web
README.md  LICENSE  HELP.html  aprsconfig.toml.template
```

The four root files are easy to miss — zipping `dist/` alone produces an
archive that looks complete and ships **without the licence text**, which is
what happened on the first attempt at v3.2.97 (F-2026-08-27-01). MIT requires
the licence to accompany the distribution.

**Before publishing, diff the archive against the last published one.** Not by
eye:

```
gh release download <previous-tag> --pattern "*.zip" --dir old
```

then compare the two file listings. It takes a minute and it is the only step
that catches a missing file, an unexpected inclusion, or a size change that
needs explaining. On v3.2.97 it caught the missing licence and explained a
61.8 → 94.3 MB jump as a CPython 3.8 → 3.13 move, itemised.

Check the new archive contains no `aprsconfig.toml` (it would carry API keys),
no `*.db`, no loose `.py`.

---

## 2 · Publish

Two routes. Both need a credential; **neither should ever be pasted into a
chat, a commit, or a shell command that lands in history.**

### Route A — `gh` CLI (fewer moving parts)

```
winget install --id GitHub.cli
gh auth login
```

`gh auth login` opens a browser and stores the token in the OS credential
store. Nothing is typed into the terminal.

```
gh release create v3.2.97 aprs-agent-v3.2.97.zip ^
  --title "v3.2.97 - the detector learns what it cannot see" ^
  --notes-file docs/RELEASE-v3.2.97-draft.md
```

The tag must already exist and be pushed — it does; `git push origin v3.2.97`
happened at release time. `gh` will not move it.

### Route B — the REST API directly

Needs a **fine-grained personal access token**, created at
<https://github.com/settings/personal-access-tokens/new>:

| field | value |
|---|---|
| Repository access | Only select repositories → `TA3HRJ/aprs-agent` |
| Permissions → Contents | **Read and write** |
| Expiration | the shortest that covers the job |

Contents: write is the only permission a release needs. Anything broader is
avoidable risk on a token that will sit in a file.

**Keep it out of the command line.** Arguments are visible to other processes
and land in shell history. Put it in a file readable only by you, or an
environment variable set for the one session:

```
$env:GH_TOKEN = (Get-Content C:\path\to\token.txt -Raw).Trim()
```

**Create the release** (returns JSON containing `upload_url` and `id`):

```
curl -sS -X POST ^
  -H "Authorization: Bearer %GH_TOKEN%" ^
  -H "Accept: application/vnd.github+json" ^
  -H "X-GitHub-Api-Version: 2022-11-28" ^
  https://api.github.com/repos/TA3HRJ/aprs-agent/releases ^
  -d "{\"tag_name\":\"v3.2.97\",\"name\":\"v3.2.97 - the detector learns what it cannot see\",\"body\":\"...\",\"draft\":true}"
```

`"draft": true` deliberately: it creates the release without announcing it, so
the asset can be attached and the page read over before anyone sees it.
Publish by flipping `draft` to `false` with a `PATCH` to
`/releases/{id}`, or in the web UI.

The body is long and full of quotes and newlines, so build the JSON from the
file rather than typing it:

```
python -c "import json,sys;print(json.dumps({'tag_name':'v3.2.97','name':'v3.2.97 - the detector learns what it cannot see','body':open('docs/RELEASE-v3.2.97-draft.md',encoding='utf-8').read(),'draft':True}))" > body.json
curl -sS -X POST -H "Authorization: Bearer %GH_TOKEN%" -H "Accept: application/vnd.github+json" --data-binary @body.json https://api.github.com/repos/TA3HRJ/aprs-agent/releases
```

**Attach the zip.** The upload host is `uploads.github.com`, not `api.`, and
the release id comes from the response above:

```
curl -sS -X POST ^
  -H "Authorization: Bearer %GH_TOKEN%" ^
  -H "Content-Type: application/zip" ^
  --data-binary @aprs-agent-v3.2.97.zip ^
  "https://uploads.github.com/repos/TA3HRJ/aprs-agent/releases/<ID>/assets?name=aprs-agent-v3.2.97.zip"
```

**Verify, from outside:**

```
curl -s https://api.github.com/repos/TA3HRJ/aprs-agent/releases/latest
```

The asset's `size` and `browser_download_url` should both be present. A
release with no asset is worse than no release: the README's download badge
points at it.

---

## 3 · Afterwards

- Confirm the badge in `README.md` resolves to the new tag.
- The README already warns that the download may lag the live demo. If the gap
  gets long again, that sentence is doing the work a release should be doing.

## Notes for next time

- Nothing about step 1 is automatable on this machine and nothing about step 2
  should be automated without a token, so the honest fix for the thirty-version
  gap is a scheduled reminder rather than a script.
- Keep `requirements-build-win32.txt` truthful. If a build is made on a
  different interpreter patch than the one recorded there, amend the header —
  the file's value is that it says what a release was *actually* built with.
