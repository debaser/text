/* text service worker — app shell + per-day offline cache */
const CACHE = "text-%VER%";
const SHELL = [
    "/",
    "/static/main.css?v=%VER%",
    "/static/app.js?v=%VER%",
    "/static/vendor/popper.min.js",
    "/static/vendor/tippy-bundle.umd.min.js",
    "/static/vendor/tippy.css",
    "/static/fonts/newsreader-latin.woff2",
    "/static/fonts/newsreader-latin-ext.woff2",
    "/static/fonts/newsreader-italic-latin.woff2",
    "/static/fonts/newsreader-italic-latin-ext.woff2",
    "/static/favicon.svg",
    "/static/manifest.webmanifest"
];

self.addEventListener("install", (e) => {
    e.waitUntil(
        caches.open(CACHE)
            .then((c) => c.addAll(SHELL))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (e) => {
    e.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

const todayISO = () => new Date().toISOString().slice(0, 10);

self.addEventListener("fetch", (e) => {
    const req = e.request;
    if (req.method !== "GET") return;

    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;

    // Study aids (a sentence's audio / word list) never change → cache-first.
    // Audio is fetched and stored whole (no Range header) so it can be cached
    // and replayed offline; <audio> is happy with a full 200 response.
    if (url.pathname === "/api/tts" || url.pathname === "/api/words" || url.pathname === "/api/marks") {
        const key = url.href;
        e.respondWith(
            caches.open(CACHE).then((c) =>
                c.match(key).then((hit) => hit || fetch(key).then((res) => {
                    if (res.ok) c.put(key, res.clone());
                    return res;
                }))
            )
        );
        return;
    }

    // A day's content: past days are immutable → cache-first;
    // today / future → network-first, fall back to whatever we have.
    // Incomplete responses (error card, untranslated day) are never stored.
    if (url.pathname === "/fragment" || url.pathname === "/api/day") {
        const date = url.searchParams.get("date") || "";
        const immutable = date && date < todayISO();
        const keep = (c, res) => {
            if (res.ok && !res.headers.get("X-Text-Incomplete")) c.put(req, res.clone());
            return res;
        };
        e.respondWith(
            caches.open(CACHE).then((c) => {
                if (immutable) {
                    return c.match(req).then((hit) => hit || fetch(req).then((res) => keep(c, res)));
                }
                return fetch(req)
                    .then((res) => keep(c, res))
                    .catch(() => c.match(req));
            })
        );
        return;
    }

    if (req.mode === "navigate") {
        e.respondWith(
            fetch(req).catch(() =>
                caches.match(req).then((hit) => hit || caches.match("/"))
            )
        );
        return;
    }

    if (url.pathname.startsWith("/static/")) {
        e.respondWith(
            caches.open(CACHE).then((c) =>
                c.match(req).then((hit) => {
                    const net = fetch(req)
                        .then((res) => { c.put(req, res.clone()); return res; })
                        .catch(() => hit);
                    return hit || net;
                })
            )
        );
    }
});
