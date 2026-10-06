const CACHE = {{ cache_name|tojson }};
const PRECACHE = {{ precache|tojson }};
const OFFLINE_URL = {{ offline_url|tojson }};

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('holishared-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  if (url.pathname.startsWith('/static/') && url.searchParams.has('v')) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
  }
});

// Point d'extension B027 : les gestionnaires push, notificationclick et notificationclose s'ajoutent après ce commentaire.
