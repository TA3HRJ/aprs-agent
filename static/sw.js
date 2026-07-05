/*
 * APRS-Agent Web GUI — Service Worker
 * Network-first for the app shell (always fresh when the server is reachable,
 * cached copy as offline fallback). Cache-first for immutable icons.
 * API, WebSocket and webhook traffic is never intercepted.
 *
 * Developed by TA3HRJ & TA3PKS
 */
const CACHE = "aprs-agent-v2";
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
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/webhook") || url.pathname === "/ws") return;

  if (e.request.mode === "navigate" || url.pathname === "/") {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put("/", copy));
          return r;
        })
        .catch(() => caches.match("/"))
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(
      (hit) =>
        hit ||
        fetch(e.request).then((r) => {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return r;
        })
    )
  );
});
