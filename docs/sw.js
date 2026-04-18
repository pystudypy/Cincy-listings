// CincyListings Service Worker
const CACHE = "cincy-v14";

// Derive base path from service worker location so this works on any
// deployment path (GitHub Pages /Cincy-listings/ or Cloud Run /)
const BASE = self.location.pathname.replace(/sw\.js$/, "");

const STATIC = [
  BASE,
  BASE + "index.html",
  BASE + "app.js",
  BASE + "style.css",
  BASE + "manifest.json",
  BASE + "icons/icon-192.png",
  BASE + "icons/icon-512.png",
];

// Install: cache all static assets
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

// Activate: remove old caches
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch strategy:
//   API calls (/analyze, /compare, /offer-strategy) → network only
//   Everything else → cache first, fall back to network
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  // Always go to network for API endpoints
  if (["/analyze", "/compare", "/offer-strategy"].some(p => url.pathname.endsWith(p))) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Cache-first for static assets
  e.respondWith(
    caches.match(e.request).then((cached) => {
      if (cached) return cached;
      return fetch(e.request).then((res) => {
        // Cache successful GET responses
        if (e.request.method === "GET" && res.status === 200) {
          const clone = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, clone));
        }
        return res;
      }).catch(() => {
        // Offline fallback for navigation
        if (e.request.mode === "navigate") return caches.match(BASE + "index.html");
      });
    })
  );
});
