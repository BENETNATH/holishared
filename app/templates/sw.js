const CACHE = {{ cache_name|tojson }};
const PRECACHE = {{ precache|tojson }};
const OFFLINE_URL = {{ offline_url|tojson }};
const PUSH_ICON = {{ push_icon|tojson }};

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

// Notifications Web Push (B027) : le payload est déjà localisé et minimal (titre, corps, tag, url).
function safeUrl(value) {
  const target = new URL(typeof value === 'string' ? value : '/', self.location.origin);
  return target.origin === self.location.origin ? target.href : self.location.origin + '/';
}

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    data = {};
  }
  const options = {
    body: data.body || '',
    icon: PUSH_ICON,
    badge: PUSH_ICON,
    data: { url: safeUrl(data.url) },
  };
  if (data.tag) {
    options.tag = data.tag;
    options.renotify = data.renotify === true;
  }
  event.waitUntil(self.registration.showNotification(data.title || 'holishared', options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = event.notification.data && event.notification.data.url ? event.notification.data.url : safeUrl('/');
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (windows) => {
      for (const client of windows) {
        if (new URL(client.url).origin !== self.location.origin) continue;
        await client.focus();
        if ('navigate' in client) {
          try {
            await client.navigate(target);
          } catch (error) {
            // Client non contrôlé : la page reste affichée, l'onglet est déjà au premier plan.
          }
        }
        return undefined;
      }
      return self.clients.openWindow(target);
    })
  );
});

self.addEventListener('notificationclose', (event) => {
  event.notification.close(); // aucune télémétrie : rien n'est envoyé au serveur
});
