// Hop connection server.
//
// Computers ("hosts") keep one WebSocket open to /ws/host?id=<9 digits>&key=<secret>. Viewers open
// /ws/view?id=<9 digits>, send a WebRTC offer, and get the host's answer back. After that the video and
// the input/control channel go straight between the two devices (or through the optional TURN relay),
// encrypted end to end; this server never sees them. The password is checked by the host over that
// encrypted channel, so it never passes through here either.
//
// One Durable Object ("Room") per ID holds the sockets. WebSocket hibernation keeps idle hosts free.
//
// Private site: the page, the API and the sockets only answer with the server's private key — the page
// lives at /k/<key>/ and everything else needs ?k=<key>. Without it, every path is a plain 404, so a
// stranger who finds the address sees nothing. The first Hop computer to connect claims the key
// (it generates one); after that only that key works. Only /static/ (styles, fonts, icons) is public.
import { DurableObject } from 'cloudflare:workers';
import { isPublicService, publicServiceRequest } from './public-service.mjs';
import { relayRegistry, cleanRelayRegistry } from './public-relay.mjs';

const VERSION = '2.1.2';
const ID_RE = /^\d{9}$/;
const MSG_OFFLINE = 'That computer is offline. Make sure Hop is running on it with Internet access turned on.';
const MAX_SDP = 20000;
const KEY_RE = /^[A-Za-z0-9_-]{16,64}$/;
const SITE_ROOM = '__site__';
let siteHash = null; // cached sha256 of the claimed key (per isolate)
const JOINS_PER_MINUTE = 20;

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });
}

async function sha256(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

// STUN is free and unlimited. TURN (relay for connections that can't go direct) is optional: it is only
// offered when the TURN_KEY_ID / TURN_KEY_API_TOKEN secrets are set on this Worker.
async function iceServers(env) {
  const servers = [{ urls: ['stun:stun.cloudflare.com:3478', 'stun:stun.l.google.com:19302'] }];
  if (env.RELAY_USE_LEGACY_KEY !== 'true' && env.TURN_KEY_ID && env.TURN_KEY_API_TOKEN) {
    try {
      const r = await fetch(
        `https://rtc.live.cloudflare.com/v1/turn/keys/${env.TURN_KEY_ID}/credentials/generate-ice-servers`,
        {
          method: 'POST',
          headers: { Authorization: `Bearer ${env.TURN_KEY_API_TOKEN}`, 'content-type': 'application/json' },
          body: JSON.stringify({ ttl: 86400 }),
        },
      );
      if (r.ok) {
        const j = await r.json();
        const list = Array.isArray(j.iceServers) ? j.iceServers : j.iceServers ? [j.iceServers] : [];
        for (const s of list) {
          // Browsers block port 53; keep the other relay addresses.
          const urls = (Array.isArray(s.urls) ? s.urls : [s.urls]).filter((u) => !/:53(\?|$)/.test(u));
          if (urls.length && s.username) servers.push({ urls, username: s.username, credential: s.credential });
        }
      }
    } catch (e) {
      console.log('TURN credentials failed', String(e));
    }
  }
  return servers;
}

function notFound() {
  return new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain', 'cache-control': 'no-store' } });
}

// Is `key` this server's private key? `claim` lets a Hop computer set it on a fresh server.
async function checkKey(env, key, claim) {
  if (!key || !KEY_RE.test(key)) return false;
  const h = await sha256('site:' + key);
  if (siteHash && siteHash === h) return true;
  const r = await env.ROOMS.get(env.ROOMS.idFromName(SITE_ROOM)).fetch('https://site/check', {
    method: 'POST', body: JSON.stringify({ hash: h, claim: !!claim }),
  });
  const j = await r.json();
  if (j.ok) siteHash = h;
  return !!j.ok;
}

function withCors(resp) {
  // Hop on a computer opens its own copy of the viewer (http://127.0.0.1) and calls these.
  resp.headers.set('access-control-allow-origin', '*');
  return resp;
}

function manifest(key) {
  const base = '/k/' + key + '/';
  return new Response(JSON.stringify({
    name: 'Hop', short_name: 'Hop', id: base, start_url: base, scope: base,
    display: 'standalone', orientation: 'any', theme_color: '#0A0A0B', background_color: '#0A0A0B',
    icons: [
      { src: '/static/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/static/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
    ],
  }), { headers: { 'content-type': 'application/manifest+json', 'cache-control': 'no-store' } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Styles, fonts and icons only: nothing in them identifies you or your computers.
    if (path.startsWith('/static/') && !path.endsWith('.html')) return env.ASSETS.fetch(request);

    // The managed hostname is an opt-in public meeting point. Its hosts use a separate namespace
    // and still require the device password, first-device pairing and any host approval setting.
    // Existing private origins, links, host keys and rooms retain their original authorization.
    if (isPublicService(url, env)) return publicServiceRequest(request, env, VERSION);

    // The private page: /k/<key>/  (and its manifest for "Add to Home Screen")
    const m = path.match(/^\/k\/([A-Za-z0-9_-]{16,64})(\/.*)?$/);
    if (m) {
      if (!(await checkKey(env, m[1], false))) return notFound();
      const rest = m[2] || '';
      if (rest === '') return Response.redirect(url.origin + '/k/' + m[1] + '/' + url.search + url.hash, 302);
      if (rest === '/' || rest === '/index.html') {
        const page = await env.ASSETS.fetch(new Request(url.origin + '/index.html'));
        const resp = new Response(page.body, page);
        resp.headers.set('cache-control', 'no-store');
        resp.headers.set('referrer-policy', 'no-referrer'); // never leak the key to other sites
        return resp;
      }
      if (rest === '/manifest.webmanifest') return manifest(m[1]);
      return notFound();
    }

    const key = url.searchParams.get('k') || '';
    if (request.method === 'OPTIONS') return withCors(new Response(null, { status: 204 }));
    if (path === '/api/info') {
      if (!(await checkKey(env, key, false))) return withCors(notFound());
      return withCors(json({ cloud: true, app: 'hop', version: VERSION }));
    }
    if (path === '/api/ice') {
      if (!(await checkKey(env, key, false))) return withCors(notFound());
      return withCors(json({ iceServers: await iceServers(env) }));
    }
    if (path === '/ws/host' || path === '/ws/view') {
      // Computers may claim a fresh server; viewers never can.
      if (!(await checkKey(env, key, path === '/ws/host'))) {
        return path === '/ws/host' ? json({ error: 'This server belongs to a different private address' }, 403) : notFound();
      }
      const id = (url.searchParams.get('id') || '').replace(/\D/g, '');
      if (!ID_RE.test(id)) return json({ error: 'The ID has 9 digits' }, 400);
      if ((request.headers.get('Upgrade') || '').toLowerCase() !== 'websocket') {
        return json({ error: 'Expected a WebSocket' }, 426);
      }
      const headers = new Headers(request.headers);
      headers.delete('X-Hop-Relay-Admission');
      headers.delete('X-Hop-Managed-Service');
      return env.ROOMS.get(env.ROOMS.idFromName(id)).fetch(new Request(request, { headers }));
    }
    return notFound();
  },
};

export class Room extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.relayEnv = env;
    // Host keep-alives are answered without waking the object.
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'));
    this.joins = []; // timestamps of recent viewer joins (in memory; resets on hibernation)
    this.ownerJoins = [];
  }

  host() {
    return this.ctx.getWebSockets('host')[0] || null;
  }

  pendingViewers(now = Date.now()) {
    return this.ctx.getWebSockets('view').filter(ws => {
      if (ws.readyState === 2 || ws.readyState === 3) return false;
      const a = ws.deserializeAttachment() || {};
      if (!Number.isFinite(a.expiresAt) || a.expiresAt <= now) {
        try { ws.close(4008, 'Connection setup timed out. Please retry.'); } catch {}
        return false;
      }
      return true;
    });
  }

  canAcceptViewer(admitted, now = Date.now()) {
    const pending = this.pendingViewers(now);
    if (pending.length < 4) return true;
    // An enrolled owner may replace an unapproved pending negotiation, never an owner session.
    const replace = admitted && pending.find(ws => !(ws.deserializeAttachment() || {}).relayAdmissionHash);
    if (!replace) return false;
    try { replace.close(4009, 'An approved browser is connecting. Please retry.'); } catch {}
    return true;
  }

  async armViewerDeadline(deadline) {
    const alarm = await this.ctx.storage.getAlarm();
    if (!Number.isFinite(alarm) || alarm > deadline) await this.ctx.storage.setAlarm(deadline);
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (url.hostname === 'relay') {
      await this.ctx.storage.put('isRelayRegistry', true);
      return relayRegistry(request, this.ctx, this.relayEnv);
    }
    if (url.hostname === 'public-service' && url.pathname === '/relay-host') {
      const { hostHash, sid } = await request.json();
      const stored = await this.ctx.storage.get('keyHash');
      const viewer = sid && this.ctx.getWebSockets('v:' + sid)[0];
      const admission = viewer && viewer.deserializeAttachment();
      const allowed = this.host() && (!hostHash || (hostHash === stored && admission && admission.offered &&
        admission.expiresAt > Date.now() && admission.relayAdmissionHash));
      return json({ online: !!this.host(), viewerHash: admission && admission.relayAdmissionHash }, allowed ? 200 : 403);
    }
    if (url.hostname === 'public-service' && url.pathname === '/rate') {
      const now = Date.now();
      const hits = (await this.ctx.storage.get('publicJoins') || []).filter(t => now - t < 60000);
      if (hits.length >= JOINS_PER_MINUTE) return json({ error: 'Too many connection attempts' }, 429);
      hits.push(now);
      await this.ctx.storage.put('publicJoins', hits);
      await this.ctx.storage.setAlarm(now + 60000);
      return json({ ok: true });
    }
    if (url.hostname === 'site' && url.pathname === '/check') {
      const { hash, claim } = await request.json();
      const stored = await this.ctx.storage.get('siteHash');
      if (stored) return json({ ok: stored === hash });
      if (claim && typeof hash === 'string') {
        await this.ctx.storage.put('siteHash', hash);
        return json({ ok: true, claimed: true });
      }
      return json({ ok: false });
    }
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    if (url.pathname === '/ws/host') {
      const key = url.searchParams.get('key') || '';
      if (key.length < 24 || key.length > 200) return json({ error: 'Bad host key' }, 400);
      const hash = await sha256(key);
      const stored = await this.ctx.storage.get('keyHash');
      if (stored && stored !== hash) return json({ error: 'This ID belongs to another computer' }, 409);
      if (!stored) await this.ctx.storage.put('keyHash', hash);
      for (const old of this.ctx.getWebSockets('host')) {
        try { old.close(4000, 'Replaced by a newer connection'); } catch (e) { /* already closed */ }
      }
      this.ctx.acceptWebSocket(server, ['host']);
      server.serializeAttachment({ role: 'host' });
      return new Response(null, { status: 101, webSocket: client });
    }

    // Viewer
    const now = Date.now();
    const relayAdmissionHash = request.headers.get('X-Hop-Relay-Admission') || null;
    if (!this.canAcceptViewer(!!relayAdmissionHash, now)) return json({ error: 'Too many connection attempts. Try again shortly.' }, 429);
    const rateKey = relayAdmissionHash ? 'ownerJoins' : 'joins';
    this[rateKey] = this[rateKey].filter((t) => now - t < 60000);
    if (this[rateKey].length >= JOINS_PER_MINUTE) return json({ error: 'Too many attempts. Wait a minute.' }, 429);
    this[rateKey].push(now);

    const sid = crypto.randomUUID().replace(/-/g, '').slice(0, 16);
    this.ctx.acceptWebSocket(server, ['view', 'v:' + sid]);
    server.serializeAttachment({
      role: 'view',
      sid,
      ip: request.headers.get('CF-Connecting-IP') || '',
      ua: (request.headers.get('User-Agent') || '').slice(0, 400),
      relayAdmissionHash,
      managedService: request.headers.get('X-Hop-Managed-Service') === '1',
      offered: false,
      expiresAt: now + 60000,
      hardDeadline: now + 90000,
    });
    await this.armViewerDeadline(now + 60000);
    if (this.host()) server.send(JSON.stringify({ t: 'ready' }));
    else {
      server.send(JSON.stringify({ t: 'error', msg: MSG_OFFLINE }));
      server.close(4004, 'offline');
    }
    const protocol = (request.headers.get('Sec-WebSocket-Protocol') || '').split(',').map(x => x.trim());
    return new Response(null, { status: 101, webSocket: client,
      headers: protocol.includes('hop') ? { 'Sec-WebSocket-Protocol': 'hop' } : {} });
  }

  async alarm() {
    if (await this.ctx.storage.get('isRelayRegistry')) return cleanRelayRegistry(this.ctx);
    await this.ctx.storage.delete('publicJoins');
    const pending = this.pendingViewers();
    if (pending.length) await this.ctx.storage.setAlarm(Math.min(...pending.map(ws => ws.deserializeAttachment().expiresAt)));
  }

  async webSocketMessage(ws, message) {
    if (typeof message !== 'string' || message.length > MAX_SDP + 2000) return;
    let d;
    try { d = JSON.parse(message); } catch (e) { return; }
    if (!d || typeof d !== 'object') return;
    const a = ws.deserializeAttachment() || {};

    if (a.role === 'view') {
      if (!Number.isFinite(a.expiresAt) || a.expiresAt <= Date.now()) {
        try { ws.close(4008, 'Connection setup timed out. Please retry.'); } catch {}
        return;
      }
      if (d.t !== 'offer' || typeof d.sdp !== 'string' || d.sdp.length > MAX_SDP) return;
      if (a.offered) return;
      const host = this.host();
      if (!host) {
        ws.send(JSON.stringify({ t: 'error', msg: MSG_OFFLINE }));
        return;
      }
      a.offered = true;
      a.expiresAt = a.hardDeadline;
      ws.serializeAttachment(a);
      await this.armViewerDeadline(a.expiresAt);
      host.send(JSON.stringify({ t: 'offer', sid: a.sid, sdp: d.sdp, ip: a.ip, ua: a.ua,
        relayAllowed: a.managedService ? !!a.relayAdmissionHash : undefined }));
      return;
    }

    if (a.role === 'host' && typeof d.sid === 'string') {
      const viewer = this.ctx.getWebSockets('v:' + d.sid)[0];
      if (!viewer) return;
      if (d.t === 'answer' && typeof d.sdp === 'string' && d.sdp.length <= MAX_SDP) {
        viewer.send(JSON.stringify({ t: 'answer', sdp: d.sdp }));
      } else if (d.t === 'error' && typeof d.msg === 'string') {
        viewer.send(JSON.stringify({ t: 'error', msg: d.msg.slice(0, 300) }));
      }
    }
  }

  async webSocketClose(ws, code) {
    const a = ws.deserializeAttachment() || {};
    if (a.role === 'view') {
      // Lets the host drop a half-finished negotiation; established sessions don't depend on this socket.
      const host = this.host();
      if (host) {
        try { host.send(JSON.stringify({ t: 'bye', sid: a.sid })); } catch (e) { /* host went away */ }
      }
    }
    try { ws.close(code === 1005 ? 1000 : code, 'bye'); } catch (e) { /* already closed */ }
  }

  async webSocketError(ws) {
    try { ws.close(1011, 'error'); } catch (e) { /* already closed */ }
  }
}
