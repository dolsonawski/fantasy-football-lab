// Service worker: cache the app shell for instant repeat loads + offline
// launch. API and image requests always go to the network (never cached),
// since fantasy data is live and per-user.
const CACHE = "ffl-shell-v4";
const SHELL = [
  "/",
  "/css/style.css",
  "/js/main.js",
  "/js/router.js",
  "/js/api.js",
  "/js/util.js",
  "/js/player_detail.js",
  "/js/pages/auth.js",
  "/js/pages/rankings.js",
  "/js/pages/draft.js",
  "/js/pages/season.js",
  "/js/pages/roster.js",
  "/js/pages/trade.js",
  "/js/pages/import.js",
  "/icons/icon-192.png",
  "/icons/apple-touch-icon.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;
  // Never cache API or proxied images — always live.
  if (url.pathname.startsWith("/api/")) return;

  // App shell + static assets: network-first so updates land immediately,
  // falling back to cache when offline.
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        if (res.ok && url.origin === self.location.origin) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(event.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/")))
  );
});
