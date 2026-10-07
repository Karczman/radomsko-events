"use strict";
// Cache-first dla statyki, network-first dla danych (events.json, status.json, events.ics).
const CACHE = "radomsko-static-v1";
const STATIC = ["./", "index.html", "app.js", "style.css", "manifest.json", "icon.svg", "bricolage-latin.woff2",
  "bricolage-latin-ext.woff2"];
const DATA = /(?:events\.json|status\.json|events\.ics)$/;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(STATIC)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  if (DATA.test(new URL(req.url).pathname)) {
    e.respondWith(fetch(req).then((res) => {
      const copy = res.clone();
      if (res.ok) caches.open(CACHE).then((c) => c.put(req, copy));  // błędów (404, 5xx) nie zapamiętujemy
      return res;
    }).catch(() => caches.match(req)));
    return;
  }
  e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
    const copy = res.clone();
    if (res.ok) caches.open(CACHE).then((c) => c.put(req, copy));  // błędów (404, 5xx) nie zapamiętujemy
    return res;
  })));
});
