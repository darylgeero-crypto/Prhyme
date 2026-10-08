// Prhyme™ service worker — offline app shell, always fresh API/data.
// App shell (HTML pages, CSS, JS, icons) is cached on first visit so the app
// still opens on flaky connections. Anything under /api/ and job
// downloads always go to the network; nothing is cached.
const CACHE = 'prhyme-shell-v2';
const SHELL = [
  '/',
  '/static/manifest.webmanifest',
  '/static/css/style.css',
  '/static/css/rockdabus-buddy.css',
  '/static/js/app.js',
  '/static/js/onboard.js',
  '/static/js/ambient.js',
  '/static/js/rockdabus-buddy.js',
  '/static/js/studio.js',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/img/icon-maskable-512.png',
  '/static/img/apple-touch-icon.png',
  '/static/img/rockdabus.webp'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isApiOrDownload(url) {
  return url.pathname.startsWith('/api/') || url.pathname.startsWith('/jobs/') ||
         url.pathname.startsWith('/outputs/') || url.pathname.startsWith('/clips/') ||
         url.pathname.startsWith('/projects/') || url.pathname.startsWith('/uploads/');
}

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (isApiOrDownload(url)) return; // network only
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match('/')))
  );
});
