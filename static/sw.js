/*
 * APRS-Agent Web GUI — Service Worker: KILL SWITCH
 *
 * This file used to be an offline shell cache. It is now a self-destruct, and
 * it is deliberately left in place rather than deleted: a worker already
 * registered in someone's browser only goes away if the browser fetches a
 * replacement that unregisters it. Deleting the file would strand every
 * existing installation on the last shell it cached, permanently.
 *
 * Why it had to go, 2026-08-14. The worker served its cached shell whenever
 * the network lost a six-second race. On a home connection sharing one HTTP/2
 * connection with a megabyte of API traffic, that race was lost routinely — so
 * the operator's browser kept running an old build while the server answered
 * `/` in 0.012 s and Apache logged the full shell delivered. Two releases were
 * tested against code that was never running, a hard reload could not escape
 * it, and clearing site data did not either: the next page load registered the
 * worker again and the cycle restarted.
 *
 * The feature was never worth that. This is an admin page for a live radio
 * feed; it has nothing useful to show offline, and the offline shell bought
 * exactly one thing — a way to silently serve stale code.
 *
 * Developed by TA3HRJ & TA3PKS
 */
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
      .then(() => self.registration.unregister())
      // Reload whatever is open, so a tab stranded on an old build comes back
      // on the current one without anybody being asked to press anything.
      .then(() => self.clients.matchAll({ type: "window" }))
      .then((cs) => cs.forEach((c) => { try { c.navigate(c.url); } catch (_) {} }))
      .catch(() => {})
  );
});

// No fetch handler. Nothing is intercepted, nothing is cached, and the page
// talks to the server directly — which is what it needed all along.
