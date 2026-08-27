// text-translate: Cloudflare Worker that calls Google's no-key translate
// endpoints from Cloudflare's IPs, for when the home IP is blocked.
// Only answers POSTs carrying the shared secret (Worker secret PROXY_KEY).
// Deploy: see README ("Worker de traducción").

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)";

async function gtx(q, sl, tl) {
    const u = new URL("https://translate.googleapis.com/translate_a/single");
    u.search = new URLSearchParams({ client: "gtx", sl, tl, dt: "t", q });
    const r = await fetch(u, { headers: { "User-Agent": UA } });
    if (!r.ok) throw new Error(`gtx ${r.status}`);
    const data = await r.json();
    return data[0].map((seg) => seg[0]).join("");
}

async function clients5(q, sl, tl) {
    const u = new URL("https://clients5.google.com/translate_a/t");
    u.search = new URLSearchParams({ client: "dict-chrome-ex", sl, tl, q });
    const r = await fetch(u, { headers: { "User-Agent": UA } });
    if (!r.ok) throw new Error(`clients5 ${r.status}`);
    const first = (await r.json())[0];
    return Array.isArray(first) ? first[0] : first;
}

export default {
    async fetch(req, env) {
        if (req.method !== "POST" || !env.PROXY_KEY || req.headers.get("X-Proxy-Key") !== env.PROXY_KEY) {
            return new Response("Not found", { status: 404 });
        }
        const { q, sl, tl } = await req.json();
        const errors = [];
        for (const [via, fn] of [["gtx", gtx], ["clients5", clients5]]) {
            try {
                return Response.json({ text: await fn(q, sl, tl), via });
            } catch (e) {
                errors.push(String(e));
            }
        }
        return Response.json({ errors }, { status: 502 });
    },
};
