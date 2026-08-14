/*
 * APRS-Agent Web GUI — Service Worker
 * Network-first for the app shell (always fresh when the server is reachable,
 * cached copy as offline fallback). Cache-first for immutable icons.
 * API, WebSocket and webhook traffic is never intercepted.
 *
 * Developed by TA3HRJ & TA3PKS
 */
// Bumping this name is what evicts every client's old entries: activate()
// deletes each cache whose key differs. Bump it whenever a stale shell could
// strand someone.
const CACHE = "aprs-agent-v29";
// A server that accepts the connection but never answers (which is exactly
// how the v3.1.2 event-loop livelock presented) leaves fetch() hanging with
// no timeout of its own, so the page spins forever instead of falling back
// to a perfectly good cached shell.
//
// This was 6000, and six seconds is not "the server is broken", it is "the
// operator is on a home connection". Measured 2026-08-14 through the live
// admin site: the server answered `/` in 0.012 s and Apache logged the full
// 55 KB delivered — while the page went on running the PREVIOUS release,
// because the shell fetch was sharing one HTTP/2 connection with 1.3 MB of
// /api/stations and lost the six second race at the last mile. The cached
// shell then answered, so a reload could not escape the old build: clearing
// site data removed the worker, the next load registered it again, and the
// cycle repeated. Two releases were tested against code that was never
// running.
//
// A slow network is not a reason to run old code. The fallback now exists
// for a server that has genuinely stopped answering, and the ceiling is set
// far above any plausible slow load rather than in the middle of one.
const SHELL_TIMEOUT_MS = 20000;
const ICONS = ["/icon-192.png", "/icon-512.png", "/manifest.json", "/favicon.ico"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) =>
      Promise.all(ICONS.map((u) => c.add(u).catch(() => null)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  // Never cache cross-origin traffic (map tiles, CDN) — the browser's own
  // HTTP cache handles those; caching tiles here would balloon storage.
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/webhook") || url.pathname === "/ws") return;

  if (e.request.mode === "navigate" || url.pathname === "/") {
    // Losing the race below used to leave this fetch running forever. An
    // un-aborted request keeps its stream on the origin's HTTP/2 session, and
    // enough of those make every request to the origin queue client-side —
    // the freeze recorded as F-19. Racing a timeout is not enough on its own;
    // the loser has to actually be cancelled.
    const ctl = ("AbortController" in self) ? new AbortController() : null;
    const net = fetch(e.request, ctl ? { signal: ctl.signal } : undefined).then((r) => {
      // Only cache a genuinely-loaded shell. Caching a 401 (Basic Auth not
      // yet satisfied — happens on cold launches of the iOS Home-Screen
      // standalone app) would trap every future offline fallback on that
      // error page, with no browser chrome available in standalone mode to
      // force a reload out of it.
      //
      // r.ok is NOT enough: an expired admin session answers 302 and the
      // browser follows it to the login page, which arrives as a perfectly
      // ok 200. Cached as the shell, that login page becomes what every
      // later offline fallback serves — the same trap by a different door,
      // which is why redirected responses are refused here.
      if (r.ok && !r.redirected) {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put("/", copy));
      }
      return r;
    });
    e.respondWith(
      Promise.race([
        net,
        new Promise((_, rej) => setTimeout(() => rej(new Error("slow")), SHELL_TIMEOUT_MS)),
      ]).catch(() =>
        // Prefer a cached shell over waiting on a stalled server, but if
        // nothing is cached keep waiting on the request already in flight
        // rather than failing outright.
        caches.match("/").then((hit) => {
          // Only abort once the cached shell is in hand: with nothing cached
          // this request is still the only way to answer, so cancelling it
          // would turn a slow load into a failed one.
          if (hit && ctl) { try { ctl.abort(); } catch (_) {} }
          return hit || net;
        })
      )
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(
      (hit) =>
        hit ||
        fetch(e.request).then((r) => {
          if (r.ok) {
            const copy = r.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
          }
          return r;
        })
    )
  );
});
