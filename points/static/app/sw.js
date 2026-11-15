// 会員アプリのサービスワーカー。
// 画面の部品（HTML・CSS・JS・アイコン）だけを端末に保存し、電波が弱いところでもアプリが開けるようにする。
// 会員のデータ（/api/）はここでは保存しない。最後に見た内容は app.js が端末に控えておく。
"use strict";
const CACHE = "bt-app-v1";
const SHELL = ["/app/", "/app/app.js", "/app/app.css", "/static/ui.css", "/app/manifest.webmanifest",
               "/app/icon-192.png", "/app/apple-touch-icon.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// 画面の部品は「まずサーバに取りに行き、つながらなければ保存しておいたもの」を使う（更新がすぐ反映される）
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  e.respondWith(
    fetch(e.request).then(res => {
      if (res.ok && SHELL.includes(url.pathname)) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
      }
      return res;
    }).catch(() => caches.match(e.request).then(hit => hit || caches.match("/app/")))
  );
});
