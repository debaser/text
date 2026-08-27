# text

El **texto del día** en **tailandés** (idioma principal) y **tagalo**, cada uno
con la traducción al **español** frase a frase (tooltip por frase), más el
**texto oficial en español**. Reescritura en Python de un proyecto PHP antiguo.

`https://text.joelgoncalves.es`

## Idiomas

| | Fuente (`wol.jw.org`) | Vista |
|---|---|---|
| TH | `/th/wol/h/r113/lp-si/YYYY/MM/DD` | frases con tooltip en español (por defecto) |
| TL | `/tl/wol/h/r27/lp-tg/YYYY/MM/DD` | frases con tooltip en español |
| ES | `/es/wol/h/r4/lp-s/YYYY/MM/DD` | texto oficial, plano, sin tooltips |

En caché, el día tagalo va en las claves de primer nivel (formato original),
el tailandés en `th` (misma forma) y el español en `es`. Si falta alguna parte
(día guardado antes de que existiera, o wol.jw.org/traducción caídos), se
completa la próxima vez que se abre el día (`_fill_in` en `main.py`).

**Segmentación del tailandés** (`segment_th()`): el tailandés no usa puntos ni
espacios entre palabras; un espacio separa frases *o* cláusulas/elementos de
lista. Se corta por espacios salvo junto a `ๆ` y dentro de citas (`(...)` o
`—cita` final), y se vuelven a unir los trozos que empiezan por และ/หรือ, los
que son solo un término entre comillas y los de menos de 20 caracteres. Salen
unos 12–15 trozos por día; el texto visible sigue siendo idéntico al original.

**Mostrar espacios** (botón `ก·ข`, solo en TH): wol.jw.org marca cada límite de
palabra tailandesa con U+200B (`&ZeroWidthSpace;`). Se conservan en el texto
tailandés (y se quitan antes de traducir); el filtro Jinja `zw` pone junto a
cada uno un `<span class="zw">` oculto que el botón muestra como `·`. La
preferencia se guarda en `localStorage` (`text_spaces`).

**Escuchar y palabra por palabra** (`app/study.py`, solo TH y TL): el tooltip de
cada frase (y el del texto temático) lleva `▶` y `Palabras`. wol.jw.org no tiene audio del texto diario
(la API de jw.org solo ofrece PDF/EPUB/JWPUB de `es26`), así que:

- `GET /api/tts?date&lang&i[&w]` — voz neuronal de Microsoft Edge vía
  `edge-tts` (gratis, no oficial): `th-TH-NiwatNeural` / `fil-PH-AngeloNeural`.
  Se genera la primera vez y se guarda como MP3 en `/app/data/tts/` (sha1 de
  voz+texto). `w` = palabra `w` de la frase.
- `GET /api/marks?date&lang&i` — tiempos de cada palabra en el audio de la
  frase: `edge-tts` los da (`WordBoundary`) y se guardan en un `.json` junto al
  MP3. Su división puede no coincidir con la de wol.jw.org (dice รู้จัก donde
  la fuente tiene รู้ + จัก), así que `align_marks()` compara ambas como una
  sola cadena de letras y un trozo hablado ilumina todas las palabras que cubre.
  En la ventana de palabras, al pulsar ▶ se ilumina cada palabra (en la frase y
  en su ficha) mientras se dice. Al pasar el ratón por una ficha (o por una
  palabra de la frase) se ilumina su pareja, y al tocar una ficha la palabra se
  ilumina en la frase mientras suena.
- `GET /api/words?date&lang&i` — palabras de la frase (tailandés: por los
  U+200B; tagalo: por espacios; sin citas), cada una traducida sola (una
  petición por frase) y, en tailandés, romanizada con `pythainlp` (RTGS
  "royin": oficial, basada en la escritura, **sin tonos**; `_ROM_OVERRIDES`
  para las que falla, p. ej. ก็ → ko). Se guarda en la caché del día
  (`words` en el bloque de ese idioma). También devuelve `parts`: la frase
  troceada por palabras (con los U+200B como marcadores), para pintarla en la
  ventana respetando "mostrar espacios". La romanización con tonos de Google
  (`gtx dt=rm`) está bloqueada desde casa y desde Cloudflare.
- **Escuchar todo**: botón ▶ en la barra inferior (solo TH/TL) que lee el tema
  (`i=-1`) y todas las frases seguidas, resaltando la que suena
  (`.is-reading`, con scroll automático), con barra de progreso y controles en
  la pantalla de bloqueo (Media Session). Precarga las 2 frases siguientes.
- **Velocidad**: botón `0.8×` en la barra inferior (0.6–1.2×), recordada por
  idioma en `localStorage` (`text_rate_th`, `text_rate_tl`); por defecto 0.8×.
- Frontend: tooltip interactivo (con ratón se coloca sobre la línea de la frase
  donde está el puntero, no sobre la frase entera, y tarda 0,25 s en cerrarse,
  para poder llegar a sus botones en frases largas). Nunca hay dos a la vez: al
  empezar a mostrarse uno, cualquier otro se quita al instante (`hideAll`
  con `duration: 0`); un solo `<audio>` (el `src` se pone en el
  mismo clic para que iOS deje reproducir); la ventana es un `<dialog>` nativo
  con ▶ para la frase entera, una ficha por palabra (tocarla la reproduce),
  fondo desenfocado y navegador de frases abajo (‹ Anterior · 3 / 14 ·
  Siguiente ›; también flechas ← → y deslizar a los lados) que recorre el tema
  y las frases del idioma visible. Alto fijo para que la barra no se mueva. El service worker guarda
  audios y listas de palabras (cache-first) para usarlos sin conexión.

## Qué hace

1. Descarga la página del día de `wol.jw.org` en los tres idiomas (ver tabla).
2. Extrae fecha, texto temático y comentario del 2º bloque `div.tabContent`.
3. **Descompone el comentario en frases.** `segment()` devuelve una lista de
   *tokens* en orden: `{"t":"s", tl, src, es}` (frase) y `{"t":"ref", tl}`
   (cita bíblica). Las **citas entre paréntesis se muestran tal cual** (el texto
   visible es idéntico al original de wol.jw.org, verificado carácter a
   carácter), pero **no se traducen** — traducir "(Jud. 4)" fuera de contexto
   daba ruido. El resto es prosa limpia y se corta con un segmentador de verdad
   (puntuación final + comillas/brackets de cierre + mayúscula/comilla
   siguiente); nunca parte dentro de un `(...)` y las comillas de cierre se
   quedan con su frase. Flag `TRANSLATE_PARENTHETICALS` para traducirlas.
4. Traduce `th → es` y `tl → es` con endpoints gratis de Google (sin API key). **El día
   entero va en una sola petición** (líneas unidas con `\n`); si la respuesta
   no trae el mismo número de líneas, se traduce frase a frase en paralelo.
   DeepL no sirve porque no soporta tagalo.
   **Bloqueos de IP:** Google bloquea la IP de casa de vez en cuando (429
   "Sorry...", no es un límite de ráfaga — una sola llamada suelta falla igual).
   Cadena de backends en `translate.py`:
   1. `google_free` — `deep-translator` (translate.google.com).
   2. `google_clients5` — `clients5.google.com` (el de la extensión de Chrome),
      limitado aparte del anterior.
   3. `worker_proxy` — los mismos endpoints llamados desde un Cloudflare Worker
      (`worker/`), para salir por IPs de Cloudflare. Algunas de esas IPs también
      están bloqueadas, pero rotan entre peticiones: se reintenta hasta 8 veces
      y nunca se da por bloqueado. Necesita `TEXT_PROXY_URL` y
      `TEXT_PROXY_KEY` en `.env`.
   4. Google Cloud Translation oficial, solo si hay `GOOGLE_TRANSLATE_API_KEY`
      en `.env` (de pago; ahora mismo no configurado).

   Los backends 1 y 2, si fallan, no se vuelven a intentar hasta el día
   siguiente (UTC). Un día que se guardó sin traducción se vuelve a traducir la
   próxima vez que alguien lo abre, y esas respuestas (y las de error) llevan
   `X-Text-Incomplete: 1` para que el service worker no las guarde.
   (Se probó primero Azure Translator, pero su nivel gratis F0 no aceptaba
   altas nuevas en la suscripción de Joel.)
5. Guarda el resultado en SQLite: hace de caché y lleva el contador de visitas.
6. Renderiza tailandés y tagalo; cada frase lleva su traducción en `data-tip`. Al final,
   `~<visitas>`.

## Frontend

- Diseño de lectura: serif *Newsreader* + *Noto Serif Thai* para el tailandés
  (ambas autoalojadas, `app/static/fonts/`; Noto Serif Thai de
  `@fontsource-variable/noto-serif-thai` 5.3.0, OFL), paleta papel/tinta con
  **modo oscuro** (`prefers-color-scheme`).
- **Selector de idioma** `TH · TL · ES` (arriba a la derecha, junto a la
  fecha). Las tres versiones van en el mismo fragmento (`data-v`), así que el
  cambio es instantáneo y funciona sin conexión. El último idioma elegido se
  recuerda en la cookie `lang` (1 año); el servidor la lee para pintar la
  página directamente en ese idioma. Sin cookie, tailandés.
- `/` se renderiza en el servidor si el día ya está en caché (sin parpadeo);
  si no, muestra un esqueleto y pide `/fragment` por fetch.
- Navegación entre días tipo SPA (fetch + `history.pushState`), **swipe**
  horizontal en móvil, botón «Hoy», sin pasar de hoy. La barra flotante se
  esconde al bajar y reaparece al subir.
- Tooltips con tippy.js (vendorizado, `app/static/vendor/`).
- **PWA instalable**: `manifest.webmanifest`, iconos (incl. maskable), service
  worker (`app/static/sw.js`, servido por FastAPI en `/sw.js` con `%VER%`
  sustituido). El SW precachea el shell y guarda cada día visitado → los días
  ya vistos funcionan sin conexión (días pasados: cache-first; hoy:
  network-first).

## Cache-busting

`STATIC_VER` = hash de `main.css` + `app.js` + `sw.js` + `manifest`. Se añade
como `?v=` a los assets y al nombre de caché del SW. Cada build con cambios
genera URLs nuevas, así que Cloudflare nunca sirve una versión vieja. **No hace
falta purgar la caché de Cloudflare al desplegar.** Excepción: los iconos
(`favicon*`, `apple-touch-icon.png`, `icon-maskable-512.png`) van sin versión;
si se cambian, purgar esas URLs en Cloudflare.

Los iconos salen de un SVG (libro abierto + bocadillo de traducción, morado
`#5E3A87`): `favicon.svg` con esquinas redondeadas, variante cuadrada para
`apple-touch-icon.png` (iOS redondea solo) y variante con el dibujo al 80 % para
`icon-maskable-512.png` (zona segura de Android). PNG generados con
`rsvg-convert`.

## Rutas

| Ruta | Qué es |
|---|---|
| `GET /?date=YYYY-MM-DD` | página; contenido inline si está cacheado |
| `GET /fragment?date=…` | solo el contenido (lo usan la nav SPA y el SW) |
| `GET /api/day?date=…` | JSON: tagalo (`heading`, `theme`, `comment`, `sentences`), `th` (misma forma), `official_es`, `hits` |
| `GET /api/words?date=…&lang=th\|tl&i=N` | palabras de la frase `N`: `[{w, rom, es}]` (`rom` solo en tailandés) |
| `GET /api/tts?date=…&lang=th\|tl&i=N[&w=K]` | MP3 de la frase `N` o de su palabra `K` (`i=-1` = el texto temático, también en `/api/words` y `/api/marks`) |
| `GET /api/marks?date=…&lang=th\|tl&i=N` | cuándo se dice cada palabra en el audio: `[[ms, k_primera, k_última]]` |
| `GET /api/progress?date=…` | mensaje de progreso mientras se genera un día nuevo |
| `GET /sw.js` | service worker (con versión inyectada) |
| `GET /health` | healthcheck |

`date` por defecto = hoy en `Europe/Madrid`.

## Deploy

```bash
cd C:/docker/text
docker compose up -d --build
docker logs text --tail 50
```

- Puerto host **8086** → 8000 contenedor. Red `shared-net`. Volumen
  `text_data` → `/app/data/text.db`.
- Proxy: bloque `text.joelgoncalves.es` en `C:\nginx\conf\nginx.conf` →
  `proxy_pass http://localhost:8086`.
- Código (`app/`) y volumen `text_data` montados en `filebrowser-shared` /
  `sftp-shared` / `ssh-tools` como `text` y `text-data`.

### Worker de traducción (Cloudflare)

`worker/worker.js` está publicado como Worker `text-translate` en
`https://text-tr.joelgoncalves.es/`. Solo responde a POST con la cabecera
`X-Proxy-Key` correcta (si no, 404). Para (re)desplegarlo:

```powershell
pwsh -File C:\docker\text\worker\deploy.ps1   # PowerShell 7 (usa .NET 5+)
```

Usa `CF_API_TOKEN` (variable de entorno de usuario, permiso *Workers Scripts:
Edit*). Si `.env` no tiene `TEXT_PROXY_KEY`, genera una clave nueva y la
añade; la misma clave se sube como secreto `PROXY_KEY` del Worker. Tras
cambiarla hay que recrear el contenedor (`docker compose up -d`).

### Purgar la caché de un día

```bash
docker exec text python -c "import db; c=db._connect(); c.execute(\"DELETE FROM daily_text WHERE date='2026-08-27'\"); c.commit()"
```
