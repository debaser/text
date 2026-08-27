(function () {
    "use strict";
    var G = window.__TEXT__ || {};
    var app = document.getElementById("app");
    var content = document.getElementById("content");
    var pager = document.querySelector(".pager");
    var todayBtn = pager.querySelector('[data-nav="today"]');
    var prevBtn = pager.querySelector('[data-nav="prev"]');
    var nextBtn = pager.querySelector('[data-nav="next"]');
    var shareBtn = document.querySelector(".fab-share");
    var hint = document.querySelector(".hint");

    var current = G.initialDate;
    var tips = [];
    // The last language viewed is remembered in a cookie (the server also
    // reads it, to render the page straight in that language); without one,
    // the day's default is Thai.
    var lang = (document.cookie.match(/(?:^|;\s*)lang=(th|tl|es)\b/) || [])[1] || null;

    function rememberLang(code) {
        document.cookie = "lang=" + code + "; Path=/; Max-Age=31536000; SameSite=Lax; Secure";
    }

    function applyLang() {
        var daily = content.querySelector(".daily");
        if (!daily) return;
        var want = lang && daily.querySelector('[data-lang-btn="' + lang + '"]') ? lang
            : daily.getAttribute("data-default-lang");
        daily.setAttribute("data-lang", want);
        [].forEach.call(daily.querySelectorAll("[data-lang-btn]"), function (b) {
            b.setAttribute("aria-pressed", b.getAttribute("data-lang-btn") === want ? "true" : "false");
        });
        tips.forEach(function (t) { try { t.hide(); } catch (e) {} });
        syncSpaces();
        if (queue && queue.lang !== want) { audio.pause(); stopQueue(); }
        syncPlayer();
    }

    // "mostrar espacios" (Thai word boundaries): a learning preference, so it
    // is remembered on this device.
    var spaces = false;
    try { spaces = localStorage.getItem("text_spaces") === "1"; } catch (e) {}

    function syncSpaces() {
        document.body.classList.toggle("show-spaces", spaces);
        var b = content.querySelector("[data-spaces-toggle]");
        if (b) b.setAttribute("aria-pressed", spaces ? "true" : "false");
    }
    var statusEl = document.querySelector(".skeleton__status");

    function pollProgress(dateStr) {
        var stopped = false;
        function tick() {
            if (stopped) return;
            fetch("/api/progress?date=" + encodeURIComponent(dateStr))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (stopped) return;
                    if (statusEl) statusEl.textContent = data.message || "";
                    setTimeout(tick, 500);
                })
                .catch(function () { if (!stopped) setTimeout(tick, 800); });
        }
        tick();
        return function stop() {
            stopped = true;
            if (statusEl) statusEl.textContent = "";
        };
    }

    function dismissHint() {
        if (!hint || hint.hidden) return;
        hint.classList.add("is-out");
        setTimeout(function () { hint.hidden = true; }, 350);
        try { localStorage.setItem("text_hint", "1"); } catch (e) {}
    }

    function shift(dateStr, days) {
        var p = dateStr.split("-").map(Number);
        var d = new Date(Date.UTC(p[0], p[1] - 1, p[2]));
        d.setUTCDate(d.getUTCDate() + days);
        return d.toISOString().slice(0, 10);
    }

    var atToday = function (dateStr) { return !G.today || dateStr >= G.today; };

    // ---- study aids: listen to a sentence / word-by-word (Thai & Tagalog) ----
    var ICON = {
        play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z"/></svg>',
        pause: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg>',
        words: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6.5h7v4.5H3zM12 6.5h9v4.5h-9zM3 13h10v4.5H3zM15 13h6v4.5h-6z"/></svg>'
    };

    // where a sentence lives: {date, lang, i} for the API
    function sentenceRef(el) {
        var daily = el.closest(".daily"), block = el.closest("[data-v]");
        return daily && block && el.hasAttribute("data-i") ? {
            date: daily.getAttribute("data-date"),
            lang: block.getAttribute("data-v"),
            i: el.getAttribute("data-i")
        } : null;
    }
    function apiUrl(path, s, extra) {
        return path + "?date=" + s.date + "&lang=" + s.lang + "&i=" + s.i + (extra || "");
    }

    // One <audio> for everything; the element that started it shows the state.
    // src is set straight from the click (not after an await) so iOS allows play().
    var audio = new Audio(), audioOwner = null, audioLang = null;
    var playAllBtn = pager.querySelector("[data-playall]");
    var rateBtn = pager.querySelector("[data-rate]");
    var progressEl = pager.querySelector(".pager__progress");
    var progressBar = progressEl.firstElementChild;

    // playback speed, remembered per language on this device; 0.8× by default
    var RATES = [0.6, 0.7, 0.8, 0.9, 1, 1.2];
    function getRate(l) {
        var r = NaN;
        try { r = parseFloat(localStorage.getItem("text_rate_" + l)); } catch (e) {}
        return RATES.indexOf(r) >= 0 ? r : 0.8;
    }
    function applyRate(l) { audio.defaultPlaybackRate = audio.playbackRate = getRate(l); }
    function currentLang() {
        var d = content.querySelector(".daily");
        return d ? d.getAttribute("data-lang") : null;
    }
    // the play-all button and the speed only make sense for Thai / Tagalog
    function syncPlayer() {
        var l = currentLang(), can = l === "th" || l === "tl";
        playAllBtn.hidden = rateBtn.hidden = !can;
        if (can) rateBtn.textContent = getRate(l) + "×";
    }
    function cycleRate() {
        var l = currentLang();
        if (l !== "th" && l !== "tl") return;
        var r = RATES[(RATES.indexOf(getRate(l)) + 1) % RATES.length];
        try { localStorage.setItem("text_rate_" + l, String(r)); } catch (e) {}
        syncPlayer();
        if (audioLang === l) audio.playbackRate = r;
    }

    function setAudioState(el, state) {
        if (!el) return;
        el.classList.toggle("is-loading", state === "loading");
        el.classList.toggle("is-playing", state === "playing");
        if (el.hasAttribute("data-play") || el.hasAttribute("data-playall")) {
            el.innerHTML = state === "playing" ? ICON.pause : ICON.play;
            el.setAttribute("aria-label", state === "playing" ? "Pausar"
                : el.hasAttribute("data-playall") ? "Escuchar todo el texto" : "Escuchar");
        }
    }
    function startAudio(url, el, l) {
        setAudioState(audioOwner, "idle");
        audioOwner = el;
        audioLang = l;
        setAudioState(el, "loading");
        audio.src = url;
        applyRate(l);
        audio.play().catch(function () { setAudioState(el, "idle"); });
    }
    // one sentence (tooltip ▶) or one word (words dialog)
    function toggleAudio(url, el, l) {
        if (audioOwner === el && !audio.paused) { audio.pause(); return; }
        stopQueue();
        startAudio(url, el, l);
    }

    // ---- "play all": theme + every sentence, marking the one being read ----
    var queue = null;   // {items: [elements], k: current index, lang}
    function markReading(el) {
        [].forEach.call(content.querySelectorAll(".is-reading"), function (n) { n.classList.remove("is-reading"); });
        if (!el) return;
        el.classList.add("is-reading");
        var r = el.getBoundingClientRect();
        if (r.top < 60 || r.bottom > window.innerHeight - 120) {
            el.scrollIntoView({ block: "center", behavior: "smooth" });
        }
    }
    function updateProgress() {
        if (!queue) return;
        var d = audio.duration;
        var frac = audioOwner === playAllBtn && d && isFinite(d) ? Math.min(audio.currentTime / d, 1) : 0;
        progressBar.style.transform = "scaleX(" + ((queue.k + frac) / queue.items.length) + ")";
    }
    function playItem(k) {
        queue.k = k;
        markReading(queue.items[k]);
        startAudio(apiUrl("/api/tts", sentenceRef(queue.items[k])), playAllBtn, queue.lang);
        // warm up the next two so the server has them ready (no gap between sentences)
        for (var j = k + 1; j <= k + 2 && j < queue.items.length; j++) {
            fetch(apiUrl("/api/tts", sentenceRef(queue.items[j]))).catch(function () {});
        }
        updateProgress();
    }
    function stopQueue() {
        if (!queue) return;
        queue = null;
        markReading(null);
        progressEl.hidden = true;
        document.body.classList.remove("is-reading-all");
        try { navigator.mediaSession.playbackState = "none"; } catch (e) {}
    }
    function playAll() {
        if (queue) {                               // pause / resume
            if (audio.paused) { applyRate(queue.lang); audio.play().catch(function () {}); }
            else audio.pause();
            return;
        }
        var daily = content.querySelector(".daily"), l = currentLang();
        if (!daily || (l !== "th" && l !== "tl")) return;
        var items = [].slice.call(daily.querySelectorAll(
            '.theme[data-v="' + l + '"] [data-i], .comment[data-v="' + l + '"] .s[data-i]'));
        if (!items.length) return;
        tips.forEach(function (t) { try { t.hide(); } catch (e) {} });
        queue = { items: items, k: 0, lang: l };
        progressEl.hidden = false;
        document.body.classList.add("is-reading-all");
        document.body.classList.remove("chrome-hidden");
        mediaSession(daily.getAttribute("data-date"), l);
        playItem(0);
    }
    // lock-screen / headphone controls
    function mediaSession(dateStr, l) {
        if (!("mediaSession" in navigator)) return;
        try {
            var ms = navigator.mediaSession;
            ms.metadata = new MediaMetadata({
                title: "Texto del día",
                artist: (l === "th" ? "ภาษาไทย" : "Tagalog") + " · " + dateStr,
                artwork: [{ src: "/static/favicon-512.png", sizes: "512x512", type: "image/png" }]
            });
            ms.setActionHandler("play", function () { if (queue && audio.paused) playAll(); });
            ms.setActionHandler("pause", function () { audio.pause(); });
            ms.setActionHandler("previoustrack", function () { if (queue) playItem(Math.max(0, queue.k - 1)); });
            ms.setActionHandler("nexttrack", function () {
                if (queue && queue.k + 1 < queue.items.length) playItem(queue.k + 1);
            });
        } catch (e) {}
    }

    audio.addEventListener("playing", function () { setAudioState(audioOwner, "playing"); });
    audio.addEventListener("pause", function () { setAudioState(audioOwner, "idle"); });
    audio.addEventListener("timeupdate", updateProgress);
    audio.addEventListener("ended", function () {
        if (queue && audioOwner === playAllBtn && queue.k + 1 < queue.items.length) {
            playItem(queue.k + 1);
            return;
        }
        setAudioState(audioOwner, "idle");
        if (queue && audioOwner === playAllBtn) stopQueue();
    });
    audio.addEventListener("error", function () {
        setAudioState(audioOwner, "idle");
        if (audioOwner === playAllBtn) stopQueue();
    });

    function tipContent(ref) {
        var es = ref.getAttribute("data-tip") || "";
        var s = sentenceRef(ref);
        if (!s || s.lang === "es") return es;
        var box = document.createElement("div");
        box.className = "tip";
        var p = document.createElement("p");
        p.className = "tip__es";
        p.textContent = es;
        var bar = document.createElement("div");
        bar.className = "tip__bar";
        bar.innerHTML =
            '<button type="button" class="tip__btn" data-play aria-label="Escuchar">' + ICON.play + '</button>' +
            '<button type="button" class="tip__btn tip__btn--words" data-words>' + ICON.words + '<span>Palabras</span></button>';
        box.appendChild(p);
        box.appendChild(bar);
        box._ref = ref;
        return box;
    }

    var dlg = document.querySelector("dialog.words");
    // the sentences the lightbox can step through: theme + comment of that language
    function sentencesOf(ref) {
        var daily = ref.closest(".daily"), l = ref.closest("[data-v]").getAttribute("data-v");
        return [].slice.call(daily.querySelectorAll(
            '.theme[data-v="' + l + '"] [data-i], .comment[data-v="' + l + '"] .s[data-i]'));
    }
    function openWords(ref) {
        if (!dlg || !sentenceRef(ref)) return;
        tips.forEach(function (t) { try { t.hide(); } catch (e) {} });
        dlg._items = sentencesOf(ref);
        showWords(ref);
        if (!dlg.open) dlg.showModal();
    }
    function stepWords(delta) {
        var items = dlg._items || [], k = items.indexOf(dlg._ref) + delta;
        if (k >= 0 && k < items.length) showWords(items[k]);
    }
    function showWords(ref) {
        var s = sentenceRef(ref);
        if (audioOwner && dlg.contains(audioOwner) && !audio.paused) audio.pause();
        dlg._ref = ref;
        var items = dlg._items || [], pos = items.indexOf(ref);
        dlg.querySelector("[data-words-prev]").disabled = pos <= 0;
        dlg.querySelector("[data-words-next]").disabled = pos < 0 || pos >= items.length - 1;
        dlg.querySelector(".words__pos").textContent = pos < 0 ? "" : (pos + 1) + " / " + items.length;
        dlg.scrollTop = 0;
        var list = dlg.querySelector(".words__list"), status = dlg.querySelector(".words__status");
        var sentence = dlg.querySelector(".words__sentence");
        sentence.textContent = ref.textContent.replace(/​/g, "");
        sentence.setAttribute("lang", s.lang);
        dlg.querySelector(".words__es").textContent = ref.getAttribute("data-tip") || "";
        list.innerHTML = "";
        list.setAttribute("lang", s.lang);
        var play = dlg.querySelector(".words__play");
        play._url = apiUrl("/api/tts", s);
        play._lang = s.lang;
        dlg._s = s;
        dlg._marks = null;
        status.textContent = "Cargando…";
        fetch(apiUrl("/api/words", s))
            .then(function (r) { if (!r.ok) throw r; return r.json(); })
            .then(function (data) {
                if (dlg._s !== s) return;           // moved on to another sentence meanwhile
                status.textContent = "";
                list.innerHTML = data.words.map(function (w, k) {
                    return '<li><button type="button" class="word" data-word="' + k + '">' +
                        '<span class="word__src"></span>' +
                        (w.rom ? '<span class="word__rom"></span>' : "") +
                        '<span class="word__es"></span></button></li>';
                }).join("");
                [].forEach.call(list.querySelectorAll(".word"), function (b, k) {
                    var w = data.words[k];
                    b.querySelector(".word__src").textContent = w.w;
                    if (w.rom) b.querySelector(".word__rom").textContent = w.rom;
                    b.querySelector(".word__es").textContent = w.es;
                    b._url = apiUrl("/api/tts", s, "&w=" + k);
                    b._lang = s.lang;
                });
                // the sentence, word by word (Thai boundaries follow "mostrar espacios");
                // an older cached response has no parts: keep the plain sentence
                if (data.parts) sentence.innerHTML = "";
                (data.parts || []).forEach(function (p) {
                    if (p.zw) {
                        var z = document.createElement("span");
                        z.className = "zw";
                        z.setAttribute("aria-hidden", "true");
                        sentence.appendChild(z);
                        sentence.appendChild(document.createTextNode("​"));
                        return;
                    }
                    if (p.k == null) { sentence.appendChild(document.createTextNode(p.s)); return; }
                    var w = document.createElement("span");
                    w.className = "wd";
                    w.setAttribute("data-k", p.k);
                    w.textContent = p.s;
                    sentence.appendChild(w);
                });
                // when each word is spoken, to light it up while the sentence plays
                return fetch(apiUrl("/api/marks", s))
                    .then(function (r) { return r.ok ? r.json() : { marks: [] }; })
                    .then(function (m) { if (dlg._s === s) dlg._marks = m.marks; });
            })
            .catch(function () {
                if (dlg._s === s) status.textContent = "No se pudo traducir ahora mismo. Inténtalo más tarde.";
            });
    }

    // light up the word(s) being spoken while the dialog's ▶ plays the sentence
    function speakingWords() {
        if (!dlg || !dlg.open) return;
        var marks = dlg._marks, from = -1, to = -1;
        if (marks && audioOwner === dlg.querySelector(".words__play") && !audio.paused) {
            var ms = audio.currentTime * 1000;
            for (var n = 0; n < marks.length && marks[n][0] <= ms; n++) { from = marks[n][1]; to = marks[n][2]; }
        } else if (audioOwner && audioOwner.classList.contains("word") && dlg.contains(audioOwner) && !audio.paused) {
            from = to = +audioOwner.getAttribute("data-word");   // a single word playing
        }
        [].forEach.call(dlg.querySelectorAll(".wd, .word"), function (el) {
            var k = +(el.getAttribute("data-k") || el.getAttribute("data-word"));
            el.classList.toggle("is-speaking", k >= from && k <= to);
        });
    }
    // timeupdate only fires ~4×/s: follow the voice closely with rAF while playing
    function followVoice() {
        speakingWords();
        if (!audio.paused && dlg && dlg.open) requestAnimationFrame(followVoice);
    }
    audio.addEventListener("playing", followVoice);
    audio.addEventListener("pause", speakingWords);
    audio.addEventListener("ended", speakingWords);
    if (dlg) {
        dlg.addEventListener("click", function (e) {
            if (e.target === dlg || e.target.closest("[data-words-close]")) { dlg.close(); return; }
            if (e.target.closest("[data-words-prev]")) { stepWords(-1); return; }
            if (e.target.closest("[data-words-next]")) { stepWords(1); return; }
            // the whole sentence (▶ in the header) or a single word
            var btn = e.target.closest(".words__play, .word");
            if (btn && btn._url) toggleAudio(btn._url, btn, btn._lang);
        });
        // hovering a word (chip or in the sentence) lights up its pair
        function hoverWord(e, on) {
            var el = e.target.closest(".word, .wd");
            if (!el) return;
            var k = el.getAttribute("data-word") || el.getAttribute("data-k");
            [].forEach.call(dlg.querySelectorAll('.word[data-word="' + k + '"], .wd[data-k="' + k + '"]'),
                function (n) { n.classList.toggle("is-hover", on); });
        }
        dlg.addEventListener("keydown", function (e) {
            if (e.key === "ArrowLeft") { e.preventDefault(); stepWords(-1); }
            else if (e.key === "ArrowRight") { e.preventDefault(); stepWords(1); }
        });
        dlg.addEventListener("mouseover", function (e) { hoverWord(e, true); });
        dlg.addEventListener("mouseout", function (e) { hoverWord(e, false); });
        dlg.addEventListener("close", function () {
            if (!audio.paused && audioOwner && dlg.contains(audioOwner)) audio.pause();
        });
    }

    document.addEventListener("click", function (e) {
        if (e.target.closest("[data-playall]")) { playAll(); return; }
        if (e.target.closest("[data-rate]")) { cycleRate(); return; }
        var btn = e.target.closest(".tip [data-play], .tip [data-words]");
        if (!btn) return;
        var ref = btn.closest(".tip")._ref, s = sentenceRef(ref);
        if (!s) return;
        if (btn.hasAttribute("data-play")) toggleAudio(apiUrl("/api/tts", s), btn, s.lang);
        else openWords(ref);
    });

    function initTips() {
        tips.forEach(function (t) { try { t.destroy(); } catch (e) {} });
        tips = [];
        if (!window.tippy) return;
        tips = [].concat(window.tippy("[data-tip]", {
            content: tipContent,
            theme: "tg",
            trigger: "mouseenter focus",
            touch: true,
            interactive: true,
            // Reaching the tooltip of a long, wrapped sentence with the mouse:
            // place it at the hovered line (not above the whole sentence, see
            // onTrigger), give a moment before hiding, and don't open another
            // sentence's tooltip just for crossing it on the way.
            interactiveBorder: 12,
            delay: [80, 250],
            onTrigger: function (inst, e) {
                // the line of the sentence under the pointer (tippy's own
                // inlinePositioning always picks the first line for "top")
                var line = -1;
                if (e && typeof e.clientY === "number") {
                    var rects = inst.reference.getClientRects();
                    for (var n = 0; n < rects.length; n++) {
                        if (e.clientY >= rects[n].top - 2 && e.clientY <= rects[n].bottom + 2) { line = n; break; }
                    }
                }
                inst.setProps({
                    getReferenceClientRect: line < 0 ? null : function () {
                        var rs = inst.reference.getClientRects();
                        return rs[Math.min(line, rs.length - 1)] || inst.reference.getBoundingClientRect();
                    }
                });
            },
            appendTo: function () { return document.body; },
            maxWidth: 320,
            offset: [0, 8],
            onShow: function (inst) {
                var c = inst.props.content;
                if (!c || (typeof c !== "string" && !c.textContent && !c.querySelector("button"))) return false;
                // never two tooltips on screen: any other one goes away at once,
                // no fade, no hide delay
                window.tippy.hideAll({ exclude: inst, duration: 0 });
                inst.reference.classList.add("is-active");
                dismissHint();
            },
            onHide: function (inst) { inst.reference.classList.remove("is-active"); }
        }) || []);
    }

    function syncChrome(dateStr) {
        current = dateStr;
        prevBtn.href = "/?date=" + shift(dateStr, -1);
        nextBtn.href = "/?date=" + shift(dateStr, 1);
        todayBtn.hidden = atToday(dateStr);
        nextBtn.classList.toggle("is-disabled", atToday(dateStr));
    }

    function load(dateStr, push) {
        if (!audio.paused) audio.pause();
        stopQueue();
        app.classList.add("is-loading");
        var stopPoll = pollProgress(dateStr);
        return fetch("/fragment?date=" + encodeURIComponent(dateStr))
            .then(function (r) { return r.text(); })
            .then(function (html) { content.innerHTML = html; })
            .catch(function () {
                content.innerHTML =
                    '<div class="state"><p class="state__msg">Sin conexión y este día no está guardado.</p>' +
                    '<button type="button" class="state__retry" data-retry>Reintentar</button></div>';
            })
            .then(function () {
                stopPoll();
                app.classList.remove("is-loading");
                var node = content.querySelector(".daily");
                var real = node ? node.getAttribute("data-date") : dateStr;
                syncChrome(real);
                initTips();
                applyLang();
                if (push !== false) {
                    history.pushState({ date: real }, "", atToday(real) && real === G.today ? "/" : "/?date=" + real);
                }
                document.body.classList.remove("chrome-hidden");
                lastY = 0;
                window.scrollTo(0, 0);
            });
    }

    document.addEventListener("click", function (e) {
        var nav = e.target.closest("[data-nav]");
        if (nav) {
            if (nav.classList.contains("is-disabled")) { e.preventDefault(); return; }
            e.preventDefault();
            var k = nav.getAttribute("data-nav");
            load(k === "today" ? (G.today || current) : k === "prev" ? shift(current, -1) : shift(current, 1));
            return;
        }
        if (e.target.closest("[data-retry]")) { e.preventDefault(); load(current, false); return; }
        if (e.target.closest("[data-spaces-toggle]")) {
            spaces = !spaces;
            try { localStorage.setItem("text_spaces", spaces ? "1" : "0"); } catch (e2) {}
            syncSpaces();
            return;
        }
        var langBtn = e.target.closest("[data-lang-btn]");
        if (langBtn) {
            lang = langBtn.getAttribute("data-lang-btn");
            rememberLang(lang);
            applyLang();
            dismissHint();
        }
    });

    window.addEventListener("popstate", function (e) {
        load((e.state && e.state.date) || G.today || G.initialDate, false);
    });

    // horizontal swipe → change day
    var sx = 0, sy = 0, st = 0;
    document.addEventListener("touchstart", function (e) {
        var t = e.changedTouches[0]; sx = t.clientX; sy = t.clientY; st = Date.now();
    }, { passive: true });
    document.addEventListener("touchend", function (e) {
        var t = e.changedTouches[0], dx = t.clientX - sx, dy = t.clientY - sy;
        if (Date.now() - st < 600 && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 2) {
            if (dlg && dlg.open) { stepWords(dx < 0 ? 1 : -1); return; }   // in the lightbox: sentence
            if (dx < 0) { if (!atToday(current)) load(shift(current, 1)); }
            else { load(shift(current, -1)); }
        }
    }, { passive: true });

    // hide the floating chrome while reading down, bring it back on scroll up
    var lastY = 0, scrollQueued = false;
    window.addEventListener("scroll", function () {
        if (scrollQueued) return;
        scrollQueued = true;
        requestAnimationFrame(function () {
            var y = window.pageYOffset || document.documentElement.scrollTop;
            // keep the player in view while "play all" is on
            if (y > lastY + 6 && y > 90 && !queue) document.body.classList.add("chrome-hidden");
            else if (y < lastY - 6 || y < 90) document.body.classList.remove("chrome-hidden");
            lastY = y;
            scrollQueued = false;
            dismissHint();
        });
    }, { passive: true });

    if (navigator.share) {
        shareBtn.hidden = false;
        shareBtn.addEventListener("click", function () {
            navigator.share({ title: document.title, url: location.href }).catch(function () {});
        });
    }

    if (G.prerendered) {
        syncChrome(G.initialDate);
        initTips();
        applyLang();
        history.replaceState({ date: G.initialDate }, "", location.pathname + location.search);
    } else {
        load(G.initialDate, false);
    }

    try {
        if (hint && !localStorage.getItem("text_hint")) {
            hint.hidden = false;
            setTimeout(dismissHint, 7000);
        }
    } catch (e) {}

    if ("serviceWorker" in navigator) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/sw.js?v=" + (G.ver || "")).catch(function () {});
        });
    }
})();
