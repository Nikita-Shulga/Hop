# Hop protocol (shared contract between host.py and static/index.html)

Hop = LAN-only remote desktop. `host.py` runs on a Mac or Windows PC, serves the
web viewer at `http://<ip>:8765/` and a WebSocket at `/ws`. Any browser (iPhone Safari,
Chrome, etc.) is the viewer/controller. Must run on Python 3.9+ (no `match`, no `X | Y` types).

## Files
- `host.py` — server (aiohttp + mss + Pillow + pynput + qrcode) and host app window (pywebview)
- `static/index.html` — single-file viewer (inline CSS/JS, no external deps)
- `static/host.html` — host app window UI (loopback only, see "Host window API")
- `static/theme.css`, `static/fonts/` — shared design system (from Quiet AI)
- `static/icon.png`, `static/icon.ico` — app icon (Dock / taskbar)
- `requirements.txt`, `start-mac.command`, `start-windows.bat`, `README.md`

## Host process modes
- Default: aiohttp runs on a background thread with its own event loop; the main thread runs a
  pywebview window (WKWebView on macOS, EdgeChromium on Windows) showing
  `http://127.0.0.1:<port>/host?shell=mac|win`. Closing the window stops the server.
- `--headless`, or automatically when pywebview can't be imported / the window fails: terminal only
  (QR code + URL + PIN printed, Ctrl+C to stop). Terminal logging is the same in both modes.

## HTTP
- `GET /` → `static/index.html`
- `GET /api/info` → `{"name": "<hostname>", "os": "mac"|"windows"|"linux", "port": 8765, "id": "<uuid>"}` (no auth)
- `GET /api/peers` → `{"peers": [{"name","os","ip","port","id","self":bool}]}` (no auth). Hosts found via
  UDP broadcast discovery (see below), seen in last 10 s, plus self.

## Discovery (host only)
Every 2 s each host broadcasts UDP to `255.255.255.255:8766` the JSON
`{"app":"hop","name","os","port","id"}` and listens on UDP 8766, recording sender IP.
Failures (no permission, no network) are logged once and ignored.

## Auth
Each host has a PIN (6 digits), stored in `~/.hop.json`, generated on first run, overridable
with `--pin 123456` (which also saves it) or from the host window (New PIN / Set PIN…). Users are told
to set the same PIN on all their machines so jumping between devices is seamless.
Brute force protection: per client IP, after 5 failures lock out for 60 s; each failure delays 1 s.

`~/.hop.json`: `{"pin": "...", "id": "...", "allowControl": true, "askBeforeConnect": false,
"theme": "system"|"light"|"dark", "notify": true}` (the last four are host-window settings; defaults shown).

## WebSocket `/ws`
First client message MUST be text `{"t":"auth","pin":"123456"}` within 10 s.
Server replies:
- `{"t":"hello","name","os","monitors":[{"index":1,"width":W,"height":H}, ...],"control":bool}` on success
  (monitor indexes are mss indexes, 1..N; W/H are the mss monitor dims; `control` is false when the
  host has "Allow control" off — view-only), or
- `{"t":"error","msg":...}` then close, where msg is one of `"Wrong PIN"`, `"Locked out, try again in N s"`,
  `"Sharing is paused on this computer"` (host paused; checked before the PIN),
  `"Connection declined on the host"` (approval denied or not answered in 30 s),
  `"Disconnected by the host"` (refused once, within 60 s, after the host clicked Disconnect for this IP —
  this stops the viewer's automatic reconnect).

### Approval ("Ask before someone connects" on the host)
After a correct PIN the server sends `{"t":"pending","msg":"Waiting for approval on the host…"}` and holds
the `hello` until the host allows (then `hello` as usual) or denies / 30 s pass (then the
"Connection declined on the host" error and close). Text messages the viewer sends meanwhile are queued and
applied after `hello`. Viewers that don't know `pending` just keep waiting — but note a viewer must not give
up on `hello` sooner than ~35 s after receiving `pending` (the current `index.html` closes the socket if no
`hello` arrives within 10 s, which cancels the request on the host).

### Host-initiated close of a running session
`{"t":"error","msg":"Sharing is paused on this computer"|"Disconnected by the host"}` then close. A viewer
that auto-reconnects gets the same message as an auth error on its next attempt and should stop.

### Server → client
- **Binary message** = one JPEG frame of the selected monitor (already downscaled).
- `{"t":"cursor","x":0..1,"y":0..1,"visible":bool}` — host mouse position normalized to the selected
  monitor (visible=false if outside it). Sent whenever it changes (checked each frame tick).
- `{"t":"error","msg":...}`

### Flow control
Server sends a frame, then waits for `{"t":"ack"}` (timeout 2 s, then continues anyway) before sending
the next. If the downscaled frame is byte-identical to the last sent one, it is skipped (no ack wait).
Target fps default 20.

### Client → server (all text JSON). Coordinates x,y are normalized 0..1 on the selected monitor.
When the host has "Allow control" off, the server silently ignores `move`, `down`, `up`, `click`,
`scroll`, `key` and `text` (`ack`, `settings`, `releaseall` still work).
- `{"t":"ack"}`
- `{"t":"settings","monitor":1,"quality":60,"maxw":1600,"fps":20}` (any subset; quality 20..95, maxw 640..3840, fps 1..30)
- `{"t":"move","x","y"}`
- `{"t":"down","b":"left"|"right"|"middle","x","y"}` / `{"t":"up","b":..., "x","y"}`
- `{"t":"click","b":"left"|"right"|"middle","x","y","n":1|2}` — n=2 double click
- `{"t":"scroll","dx":int,"dy":int}` — integer notches; dy>0 = scroll content DOWN (like browser deltaY>0),
  dx>0 = right. Server converts to pynput sign (pynput dy>0 is up).
- `{"t":"key","k":"<key>","down":true|false}` — `<key>` is either a single character ("a","A","1","/")
  or a browser `KeyboardEvent.key` name: Enter, Backspace, Tab, Escape, Delete, ArrowUp/Down/Left/Right,
  Home, End, PageUp, PageDown, Shift, Control, Alt, Meta, CapsLock, " " (space), F1..F12, Insert.
  Client is responsible for Ctrl<->Cmd swapping (it sends already-swapped names).
- `{"t":"text","s":"hello"}` — type a string (mobile keyboard).
- `{"t":"releaseall"}` — release every key/button this connection holds.

Server tracks keys/buttons held per connection and releases them on disconnect.
Server prints connect/disconnect lines with client IP.

## Host window API (loopback only)
`GET /host` serves `static/host.html` with a random per-process token substituted for `__LV_TOKEN__`
and the saved theme for `__LV_THEME__`. `/host`, `/static/host.html` and every `/api/host/*` route return
**403** unless the TCP peer is loopback (`127.0.0.1`/`::1`) **and** the `Host` header is
`127.0.0.1`/`localhost`/`[::1]` (blocks LAN access and DNS rebinding — these routes expose the PIN).
`/api/host/*` also requires header `X-Hop-Token: <token>`; POSTs with an `Origin` header must come
from `http://127.0.0.1|localhost|[::1]:<port>`. The page polls status once a second.

- `GET /api/host/status` →
  `{"name","os","version","port","id","paused","pin","url","urls":[...],"qr":"<svg…>",
  "viewers":[{"id","ip","device","ua","connectedAt","seconds","fps","kbps"}],
  "pending":[{"id","ip","device","expiresIn"}], "peers":[{"name","os","ip","port","id","self":false}],
  "settings":{"allowControl","askBeforeConnect","theme","notify"},
  "permissions":{"screen":bool|null,"accessibility":bool|null,"app":"Terminal"}|null,
  "totals":{"fps","kbps"}}` — `qr` is an SVG (fill=currentColor, no quiet zone) of `url`; `device` is
  guessed from the User-Agent (iPhone, iPad, Android, Mac, Windows PC, …; iPadOS Safari reports "Mac");
  `fps`/`kbps` are averaged over the last 3 s; `permissions` is macOS only
  (`CGPreflightScreenCaptureAccess`, `AXIsProcessTrusted`).
- `POST /api/host/pause` — refuse new connections, decline pending ones, disconnect current viewers.
- `POST /api/host/resume`
- `POST /api/host/pin/new` — random new PIN (saved). `POST /api/host/pin` `{"pin":"123456"}` (400 if not 6 digits).
- `POST /api/host/viewers/{id}/disconnect`
- `POST /api/host/pending/{id}/approve`, `POST /api/host/pending/{id}/deny` (404 when expired)
- `POST /api/host/settings` — any subset of `{"allowControl":bool,"askBeforeConnect":bool,
  "theme":"system"|"light"|"dark","notify":bool}` (saved). Turning control off releases held keys/buttons.
- `POST /api/host/open` `{"pane":"screen"|"accessibility"}` — opens the macOS Privacy pane.

All POSTs return the new status object (or `{"error": "..."}` with 4xx).

## Platform notes
- mss monitor dims are logical points on macOS (Retina image is 2x — irrelevant since we normalize) and
  physical pixels on Windows (mss makes process DPI-aware, which also makes pynput use physical pixels).
  Target pixel = monitor.left + x*monitor.width, monitor.top + y*monitor.height.
- macOS: needs Screen Recording + Accessibility permission for the terminal app running Python.
- macOS double-click: pynput press/release don't set click count; use `mouse.click(button, 2)` for n=2.

---------------------------------------------------------------------------------------------------
# v1.1 additions (binding contract for the 1.1 work — host.py/host.html, index.html, packaging)

## Easy addresses
- Host setting `shortName` (saved in config): default `"mac"` on macOS, `"pc"` on Windows, `"linux"` otherwise;
  lowercase `[a-z0-9-]{1,30}`. If a discovered peer with a different id already uses it, the host uses
  `<short>-2`, `-3`, … (effective name is reported as `short`). Settable from the host window
  (`POST /api/host/settings {"shortName":"studio"}`) and `--short` CLI flag.
- mDNS (python-zeroconf): advertise an A record `<short>.local` → this host's LAN IPv4 plus service
  `_http._tcp.local.` named `"Hop on <name>"` (port = easy port if bound, else main port, TXT
  `path=/`, `id=<id>`). Failure is logged once and ignored.
- Ports: always listen on the main port (default 8765). Additionally try to bind port **80** (the "easy
  port") on 0.0.0.0, serving the same app; if it fails (in use / not permitted) log once and continue.
  `--no-easy-port` disables. The easy port serves the viewer, `/ws`, `/api/info`, `/api/peers`, files —
  never the loopback host API (that is only on the main port, still loopback-only).
- Primary URL shown everywhere: `http://<short>.local` if port 80 is bound, else `http://<short>.local:8765`.
  Also list `http://<lan-ip>:8765` as fallback. Status `urls` = [primary, ip-url].
- `/api/info` adds `"short"`, `"url"` (primary). Discovery broadcast + `/api/peers` entries add
  `"short"`, `"easy": bool` (port 80 bound). Peer viewer links use `http://<ip>:<port>/#pin=...`
  (IP-based: most reliable).

## Session token (for HTTP features)
`hello` adds `"token": "<random 32 hex>"`, valid while that WebSocket is open. HTTP feature endpoints
below require it in header `X-LV-Session` (or query `s=` for plain download links). 401 otherwise.
`hello` also adds `"short"`, `"url"`, `"features": ["clipboard","files"]`.

## Clipboard (text) — over the WebSocket
- client → `{"t":"clip.set","s":"text"}` sets the host clipboard (ignored when control is off; max 1 MB).
  Server replies `{"t":"clip.ok"}`.
- client → `{"t":"clip.get"}` → server `{"t":"clip","s":"<host clipboard text>"}`.
- Server pushes `{"t":"clip","s":"...","auto":true}` when the host clipboard text changes (polled ~1 s,
  only while ≥1 viewer, max 1 MB, not for the change the viewer itself caused).
- Host side: pyperclip (pbcopy/pbpaste on macOS, win32 on Windows).

## Files
Shared folder on the host: `~/Downloads/Hop/` (created on demand). Viewers can upload into it and
download anything in it; the host user drops files there (or uses "Send a file…" in the host window,
which copies the picked file in) to offer them to viewers.
- `GET /api/files` (X-LV-Session) → `{"files":[{"name","size","mtime"}], "folder":"<display path>"}`
  (top level only, newest first, hidden files skipped).
- `GET /api/files/download?name=<name>&s=<token>` → the file as attachment. Reject names with `/`, `\`,
  `..`, or resolving outside the folder.
- `POST /api/files/upload` (X-LV-Session, multipart field `file`, may repeat) → `{"saved":[names]}`.
  Requires control allowed (403 otherwise). Max 4 GB per file, streamed to disk. Name collisions →
  `name (1).ext`. The host window shows a notice "Received <name> from <device>" with "Show".
- Server pushes `{"t":"files"}` over the WebSocket when the folder listing changes (polled ~2 s while ≥1 viewer)
  so open file lists refresh.

## Host window additions (loopback API)
- Status adds: `"short"`, `"easyPort": bool`, `"folder": "<shared folder path>"`, `"received":[{"name","from","at"}]`
  (last 5), `"settings"` adds `"shortName"`, `"startAtLogin"`, `"keepAwake"`, and `"frozen": bool`.
- `POST /api/host/connect` `{"peer":"<id>"}` or `{"url":"http://..."}` → opens a new app window (pywebview)
  titled with the peer name at `http://<ip>:<port>/#pin=<this host's PIN>`; in headless mode opens the system
  browser instead. Returns status.
- `POST /api/host/files/open` → reveal shared folder in Finder/Explorer. `POST /api/host/files/send` → native
  file picker (pywebview), copy picked files into the shared folder.
- Settings: `startAtLogin` (macOS: LaunchAgent `~/Library/LaunchAgents/com.hop.host.plist`;
  Windows: HKCU `Software\Microsoft\Windows\CurrentVersion\Run` value `Hop`), launched with
  `--background` (window starts minimized); `keepAwake` (default true: prevent system sleep while ≥1
  viewer is connected — macOS `caffeinate -di -w <pid>` child, Windows `SetThreadExecutionState`).
- Frozen (PyInstaller) support: resources from `sys._MEIPASS` when frozen; config still `~/.hop.json`.

## Viewer additions
- PWA: `/static/manifest.webmanifest` (name "Hop", display standalone, theme/background #0A0A0B,
  icons /static/icon-192.png, /static/icon-512.png), `apple-touch-icon` /static/icon-180.png,
  `apple-mobile-web-app-capable`. Tip in the connect screen on iOS Safari (not standalone): "Add to Home Screen".
- Toolbar gains: Clipboard (sheet: "Send text to <host>" textarea + Send; "Host clipboard" with Copy button;
  auto toast when host copies), Files (sheet: upload button + drag & drop onto viewer; list with download
  links; refresh on `{"t":"files"}`), Shortcuts menu (OS-aware combos sent as key down/up sequences).

## v1.1 implementation notes / clarifications (host.py, as built)
- `shortName` must also not start or end with `-` (DNS label rule): `^[a-z0-9]([a-z0-9-]{0,28}[a-z0-9])?$`.
  Input is lowercased and a trailing `.local` is stripped. Bad value → 400.
- Conflict rule (deterministic, no flapping): a name is blocked if a live peer holds it and either it is not
  our current name or that peer's id sorts lower than ours (incumbent keeps it; on a tie the smaller id wins).
  Before claiming a new name the host also asks mDNS who answers `<name>.local`; an answer from an address
  that isn't one of ours blocks that name for 60 s. Effective name = first unblocked of `base`, `base-2`, ….
- mDNS: zeroconf A record + `_http._tcp` service, plus a small helper on UDP 5353 that answers AAAA queries for
  `<short>.local` with a correct NSEC (python-zeroconf names its NSEC after the service instance, so
  getaddrinfo()/curl/Chrome/Windows otherwise wait ~5 s for AAAA). Re-checked every 3 s (IP change → re-register).
- If mDNS fails, the primary URL falls back to the LAN IP (`http://<ip>` with port 80 bound, else `:<port>`).
- The easy port refuses `/host`, `/static/host.html` and `/api/host/*` (403), decided by the socket's local port.
- Discovery broadcast adds `"short"` (effective) and `"easy"`. `/api/peers` self entry also has `"easy"`.
- `hello.features` contains `"clipboard"` only when pyperclip is importable.
- `clip.get` failure / too large → `{"t":"clip","s":"","error":"<message>"}`. `clip.set` over 1 MB is ignored.
  Auto pushes skip empty text (e.g. an image was copied) and go to every viewer except the one that set it.
  WebSocket max message size is 4 MB (JSON escaping of 1 MB text).
- Files: download name rejected (400) when empty, `.`/`..`, starting with `..`, containing `/`, `\` or NUL;
  missing or resolving outside the folder (symlinks) → 404. Upload names are sanitised (basename only, `%22`→`"`,
  control chars and `<>:"|?*` → `_`, leading/trailing dots stripped, Windows reserved names prefixed `_`,
  ≤200 bytes) and written via a hidden temp file `.lv-upload-*.part`. Errors: 401, 403 (view-only),
  413 (>4 GB), 507 (disk error). Listing skips hidden files (dot files, desktop.ini, Windows hidden attr) and
  symlinks pointing outside. Windows uses the real Downloads known folder (may be relocated).
- Host status also has `"mdns": bool` and `"windowed": bool` (false → `files/send` unavailable, 400).
  `frozen` is top-level. `files/send` response adds `"sent": [names]`. `POST /api/host/files/open`
  accepts optional `{"name": "<file>"}` to select that file in Finder/Explorer.
- `POST /api/host/connect {"url"}` accepts `host`, `host:port`, or a URL. Without a port it probes
  `/api/info` on port 80 then 8765 (2.5 s each, in parallel); 404 if no Hop answers, 400 if it is this
  host. Window URL uses the address as typed. In headless mode the system browser opens instead
  (env `HOP_DRY_OPEN=1` only logs — for tests).
- `POST /api/host/activate` (loopback, main port, **no Origin header**, no token): brings the window forward.
  A second launch that can't bind the port calls it and exits 0 (single-instance behaviour).
- Settings `keepAwake` (default true) is stored in config; `startAtLogin` is not stored — it reflects whether
  the LaunchAgent plist / Run value exists. A frozen app re-points an existing login item at startup if it moved.
  macOS login item for an App-Translocated (unmoved, quarantined) app is refused: "Move Hop to Applications".
- `--background` starts the window minimized; `--short NAME`, `--no-easy-port` as specified.
- Logging: when stdout/stderr are None (windowed PyInstaller, pythonw) both go to `~/.hop.log`
  (rotated at 2 MB); a frozen app with a console also logs there. Startup port failure in a console-less app
  shows a native alert.

---------------------------------------------------------------------------------------------------
# v1.2: Internet access (remote.py, cloud/)

## Pieces
- **Connection server** (`cloud/`, a Cloudflare Worker + one Durable Object per ID): serves the viewer
  (`cloud/public/` = a copy of `static/` without `host.html`) over HTTPS and relays WebRTC offers/answers.
  It never sees video, input, files or passwords.
- **Host** (`remote.CloudLink`): while "Internet access" is on, keeps `wss://<server>/ws/host?id=<9 digits>&key=<secret>`
  open, pings every 25 s (`"ping"` → `"pong"`, answered without waking the object), reconnects with backoff.
  The first host to use an ID stores `sha256(key)`; another key gets HTTP 409 and the host picks a new ID.
- **Viewer** (`index.html` when `/api/info` says `{"cloud": true}`): Computer ID + password form, recent
  computers (localStorage `lv.recent`: id, name, os, optional password), `#id=<9 digits>` prefills the ID.

## Server API
- `GET /api/info` → `{"cloud": true, "app": "hop", "version"}`
- `GET /api/ice` → `{"iceServers": [...]}` — STUN (Cloudflare, Google); plus Cloudflare TURN when the Worker has
  the secrets `TURN_KEY_ID` + `TURN_KEY_API_TOKEN`.
- `WS /ws/host?id&key` (host), `WS /ws/view?id` (viewer; 20 joins/minute per ID).
- Viewer ← `{"t":"ready"}` (host online) or `{"t":"error","msg":"That computer is offline…"}` then close.
- Viewer → `{"t":"offer","sdp"}` → host gets `{"t":"offer","sid","sdp","ip","ua"}` (ip = CF-Connecting-IP).
- Host → `{"t":"answer","sid","sdp"}` / `{"t":"error","sid","msg"}` → viewer gets `{"t":"answer","sdp"}` / error.
- Viewer socket closes → host gets `{"t":"bye","sid"}` (drops the negotiation only if not yet answered).
- No trickle ICE: both sides send complete SDP (viewer waits ≤ 3 s for gathering).

## Session (WebRTC, DTLS-encrypted end to end)
- Viewer offers one recvonly video transceiver + data channel `"lv"` (ordered). Host answers with a VP8-first
  video track (`ScreenTrack`: black 64×36 frames until sign-in, then the selected monitor at the viewer's
  `fps`/`maxw`; aiortc VP8 bitrate 2.5 Mbit/s default, 8 Mbit/s max, adapted by congestion control).
- The data channel carries exactly the WebSocket JSON protocol above (auth with `{"t":"auth","pin":"<internet password>"}`,
  hello, cursor, input, clipboard, settings, pending/approval, errors). Lockout counts internet attempts per
  public IP separately from Wi-Fi ones. `hello.features` = clipboard (if available) + files; no `token`
  needed. "Wrong password" replaces "Wrong PIN"; `"Internet access is turned off on that computer"` is sent
  before internet viewers are disconnected when the host turns it off.
- **Chunking**: data-channel messages are capped at 64 KiB. Longer JSON is sent as
  `{"t":"chunk","id","i","n","s"}` pieces (host → viewer 30000 chars of ASCII JSON; viewer → host ≤ 15000
  UTF-16 units, never splitting a surrogate pair; host accepts ≤ 300 pieces, ≤ 4 partial messages).
- **Files** (same shared folder as Wi-Fi):
  - `{"t":"files.list"}` → `{"t":"files.list","files":[{"name","size","mtime"}],"folder"}`; `{"t":"files"}` pushes still apply.
  - Download: `{"t":"down","id","name"}` → `down.start {id,name,size}`, `down.data {id,d: base64 ≤ 40000 bytes}`…,
    `down.end {id}` or `down.err {id,msg}`; viewer may send `down.abort {id}`. Host waits while the channel
    buffer exceeds 1 MiB.
  - Upload (needs control): `up.start {id,name,size}` → `up.ready {id}` | `up.err {id,msg}`; then
    `up.data {id,d: base64 ≤ 36000 bytes}`… (viewer waits while bufferedAmount > 1 MiB), `up.end {id}` →
    `up.done {id,name}`; `up.abort {id}` cancels. 4 GB limit; written to a hidden `.part` file, renamed at the end.

## Host window (loopback API)
- Status adds `"cloud": {"available","unavailableReason","enabled","url","defaultUrl","id","idFormatted",
  "password","state": "off|connecting|online|error","error","link"}`; viewers carry `"remote": bool`.
- `POST /api/host/settings` accepts `cloudEnabled` (bool) and `cloudUrl` (https URL; `http://localhost`/`127.0.0.1`
  for testing). `POST /api/host/cloud/password/new`, `POST /api/host/cloud/password {"password"}` (6–64 chars).
- `POST /api/host/connect {"cloud": "<9 digits>"}` opens a viewer window at `<server>/#id=<id>`.
- Config keys: `cloudEnabled`, `cloudUrl`, `cloudId`, `cloudKey`, `cloudPassword` (file is chmod 600 on macOS).
  `static/cloud.json` `{"url": "https://…"}` sets the default server for a build.

---------------------------------------------------------------------------------------------------
# v1.3: Second screen, opening other computers

## Second screen ("extend")
- `hello.features` includes `"extend"` when the host can create displays itself (macOS: CoreGraphics
  `CGVirtualDisplay`, needs `pyobjc-framework-libdispatch`). `hello.monitors[]` entries carry `"virtual": bool`.
- client → `{"t":"extend","w":points,"h":points,"hidpi":bool,"side":"right"|"left"|"above"}` (needs control).
  Host creates a display of w×h points (clamped 640–3840 × 480–2400) beside the main one, refreshes its monitor
  list and switches the session to it → `{"t":"extend.ok","monitor":index,"monitors":[…],"width","height"}`
  or `{"t":"extend.err","msg"}`. One virtual display per session; it is removed when the session ends.
- client → `{"t":"extend.stop"}` → display removed, session back to the main display →
  `{"t":"extend.off","monitor":index,"monitors":[…]}`.
- The viewer sends a temporary `settings` (maxw = width, fps 30, quality 70) while extended and restores the
  saved ones afterwards. Links may carry `mode=extend` in the fragment (`#pin=…&mode=extend`,
  `#id=…&mode=extend`) to start second-screen mode right after connecting (and again after reconnects).
- Windows hosts: no `extend` feature; a display added by a virtual display driver or an HDMI dummy plug is an
  ordinary monitor the viewer can pick.

## Opening other computers (host window)
- Setting `openIn`: `"window"` (default) | `"fullscreen"` | `"browser"`. `POST /api/host/connect` accepts
  `"mode": "extend"` (adds `mode=extend`; "window" is upgraded to "fullscreen") and an optional `"openIn"`.
- Viewer windows expose `window.pywebview.api.toggle_fullscreen()` / `is_fullscreen()`; the viewer's ⛶ button
  uses them inside Hop windows and the browser Fullscreen API elsewhere.
- No connection server is built in: `cloudUrl` comes from Settings (or a git-ignored `static/cloud.json`).

---------------------------------------------------------------------------------------------------
# v1.3.1: smoother setup
- Discovery broadcasts add `"cloud": "<https server url>"|null`; the host window offers peers' servers
  (`status.cloud.suggest` = [{name, url}]) when this computer has none. `status.cloud` also has `qr` (SVG of
  `link`) and `deployUrl` (Cloudflare's Deploy button for `<repo>/tree/main/cloud`).
- `POST /api/host/permission {"which": "screen"|"accessibility"}` shows macOS's permission prompt
  (CGRequestScreenCaptureAccess / AXIsProcessTrustedWithOptions) and then the Privacy pane.
  `status.permissionsAtStart` tells the window when a restart is needed (Screen Recording granted after launch).
- `POST /api/host/restart` (macOS) relaunches the app (`open -n` the bundle, or re-exec from source) and quits.
- `POST /api/host/link {"which": "deploy"|"guide"}` opens one of the app's fixed help URLs in the browser.
- `cloud/` is self-contained for one-click deploys: `public/` (a copy of the viewer) is committed and
  `build.mjs` keeps it as is when `../static` isn't there.

---------------------------------------------------------------------------------------------------
# v1.4: device pairing and stronger sign-in (internet)
- Viewer `auth` adds `"device": {"id": 16 hex, "token": 48 hex}` (created once per browser, localStorage `lv.device`).
- Host keeps `trustedDevices` [{id, hash: sha256(token), name, added, seen}] in its config. After the right password,
  an unknown device gets `{"t":"pending","code":"123456","timeout":120,"msg"}`; the host window shows a card asking
  for the code (status `pending[].pair = true`, the code itself is never in status). `POST /api/host/pending/{id}/approve
  {"code"}`: wrong → 400 (3 tries, then declined), right → device trusted and the session continues. Deny/timeout →
  `"This device wasn't confirmed on the computer"`. `POST /api/host/trusted/{id}/forget`; status has `trusted[]`.
- Internet passwords: ≥ 8 characters, not all digits, ≥ 4 different characters (weak stored ones are replaced when
  internet access starts). > 20 wrong internet passwords from any addresses within 10 min pauses internet sign-ins for
  5 min ("Too many wrong passwords…"), notifies the user; status `netPausedFor` (seconds).
- Hop app windows keep web storage (pywebview `private_mode=False`, `~/.hop-web`) so pairings and recent
  computers survive restarts.

---------------------------------------------------------------------------------------------------
# v1.5: private server, computer-to-computer without the website
- The Worker runs first for every request (`assets.run_worker_first`). Public: `/static/*` (not .html) only.
  The viewer is served at `/k/<key>/` (+ `/k/<key>/manifest.webmanifest`, start_url = that path); `/api/info`,
  `/api/ice`, `/ws/view` need `?k=<key>`; anything else is a plain 404. `/ws/host?…&k=<key>` may *claim* a fresh
  server (the `__site__` Durable Object stores sha256("site:"+key)); a different key on a claimed server → 403.
- Host config `siteKey` (generated when internet access starts and none is set). The private address
  `<cloudUrl>/k/<siteKey>` is shown in Settings, used for the phone link/QR and broadcast to your other computers
  (discovery `cloud`), whose "Use it" adopts it. Pasted addresses may include `/k/<key>`.
- Computer to computer: `POST /api/host/connect {"cloud": id}` opens `http://127.0.0.1:<port>/remote#id=…` —
  `index.html` served by this computer (loopback only), which reads `{base, key}` from `GET /api/remote-config`
  (loopback only) and talks to the server cross-origin (CORS on `/api/*`).
