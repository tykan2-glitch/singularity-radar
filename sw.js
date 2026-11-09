const CACHE='singularity-shell-v5';
self.addEventListener('install',event=>{self.skipWaiting();event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(['./','./manifest.webmanifest','./icons/icon-192.png','./icons/icon-512.png'])))});
self.addEventListener('activate',event=>{event.waitUntil(Promise.all([self.clients.claim(),caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))]))});
self.addEventListener('fetch',event=>{const url=new URL(event.request.url);if(event.request.method!=='GET'||url.origin!==self.location.origin)return;if(url.pathname.endsWith('market-data.json')){event.respondWith(fetch(event.request,{cache:'no-store'}));return}event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)))});
