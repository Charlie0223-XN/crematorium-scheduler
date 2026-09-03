const CACHE_NAME = "scheduler-shell-v3";
const SCOPE_URL = self.registration.scope;
const APP_SHELL = [
  "",
  "static/style.css",
  "static/app.js",
  "static/scheduler.js",
  "static/excel.js",
  "static/manifest.webmanifest",
  "static/icon.svg",
  "static/icon-192.png",
  "static/icon-512.png",
  "static/apple-touch-icon.png",
].map((path) => new URL(path, SCOPE_URL).href);

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(SCOPE_URL, copy));
          return response;
        })
        .catch(() => caches.match(SCOPE_URL)),
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request)),
  );
});
