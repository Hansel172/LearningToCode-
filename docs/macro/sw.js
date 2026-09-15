// v2: the shell files (app.js, boot.js, styles.css, index.html) were
// cache-first, which meant a code or content change never reached an
// already-installed phone until the SW file itself changed — nothing
// forces a browser to re-check a service worker otherwise. Same bug, same
// fix already applied to the earnings tracker's sw.js: network-first
// everywhere, same as data.json already was. The cache name bump below is
// also required — it's what makes the browser notice this file changed at
// all.
const SHELL = 'macro-shell-v2';
const FILES = ['./', 'index.html', 'styles.css', 'app.js', 'boot.js',
               'manifest.webmanifest'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  e.respondWith(
    fetch(e.request)
      .then(r => {
        const copy = r.clone();
        caches.open(SHELL).then(c => c.put(e.request, copy));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
