const CACHE='wholesale-market-v5';
const STATIC_ASSETS=[
  '/login',
  '/static/css/app.css?v=20260921-6',
  '/static/js/app.js?v=20260921-6',
  '/static/icons/icon.svg',
  '/static/manifest.webmanifest'
];

self.addEventListener('install',event=>{
  event.waitUntil(
    caches.open(CACHE)
      .then(cache=>cache.addAll(STATIC_ASSETS))
      .then(()=>self.skipWaiting())
  );
});

self.addEventListener('activate',event=>{
  event.waitUntil(
    caches.keys()
      .then(keys=>Promise.all(
        keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))
      ))
      .then(()=>self.clients.claim())
  );
});

self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET') return;

  // Never keep authenticated HTML pages in the service-worker cache.
  // This prevents an old dashboard/menu/template from reappearing after deployment.
  if(event.request.mode==='navigate' || event.request.destination==='document'){
    event.respondWith(
      fetch(event.request).catch(()=>caches.match('/login'))
    );
    return;
  }

  // Static assets: cache-first, then network. Old cache generations are removed on activate.
  if(event.request.url.includes('/static/')){
    event.respondWith(
      caches.match(event.request).then(cached=>cached || fetch(event.request).then(response=>{
        const copy=response.clone();
        caches.open(CACHE).then(cache=>cache.put(event.request,copy));
        return response;
      }))
    );
  }
});
