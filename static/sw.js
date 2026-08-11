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
const CACHE = "aprs-agent-v5";
// A server that accepts the connection but never answers (which is exactly
// how the v3.1.2 event-loop livelock presented) leaves fetch() hanging with
// no timeout of its own, so the page spins forever instead of falling back
// to a perfectly good cached shell.
const SHELL_TIMEOUT_MS = 6000;
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
    const net = fetch(e.request).then((r) => {
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
        caches.match("/").then((hit) => hit || net)
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
