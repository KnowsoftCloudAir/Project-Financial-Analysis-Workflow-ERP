/* Churchgate offline shell — do not precache routes that 404 */
const CACHE = 'churchgate-offline-v6';
const PRECACHE = [
  '/',
  '/auth/login',
  '/static/manifest.json',
  '/static/sw.js',
  '/static/js/offline-store.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-512-maskable.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) =>
      Promise.all(PRECACHE.map((u) => cache.add(u).catch(() => null)))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isAsset(url) {
  return (
    url.pathname.startsWith('/static/') ||
    url.pathname.endsWith('.js') ||
    url.pathname.endsWith('.css') ||
    url.pathname.endsWith('.png') ||
    url.pathname.endsWith('.jpg') ||
    url.pathname.endsWith('.woff2') ||
    url.pathname.endsWith('.json')
  );
}

function isAppShell(url) {
  const p = url.pathname;
  return (
    p === '/' ||
    p.startsWith('/auth/') ||
    p.startsWith('/member/')
  );
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  // Never trap cross-origin book vendor traffic in this SW
  if (url.pathname.startsWith('/member/api/') || url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(JSON.stringify({ ok: false, offline: true }), {
          headers: { 'Content-Type': 'application/json' },
          status: 503,
        })
      )
    );
    return;
  }

  if (isAsset(url) || isAppShell(url)) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        try {
          const res = await fetch(event.request);
          if (res && res.ok) cache.put(event.request, res.clone()).catch(() => {});
          return res;
        } catch (e) {
          const cached = await cache.match(event.request);
          if (cached) return cached;
          if (url.pathname.startsWith('/member/')) {
            return cache.match('/member/portal') || cache.match('/') || new Response('Offline', { status: 503 });
          }
          return cache.match('/') || new Response('Offline', { status: 503 });
        }
      })
    );
    return;
  }

  event.respondWith(
    fetch(event.request).catch(() =>
      caches.match(event.request).then((r) => r || caches.match('/'))
    )
  );
});
