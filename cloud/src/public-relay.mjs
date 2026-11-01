// Owner-funded TURN is available only to explicitly enrolled browsers/hosts.
// A public room or a successful STUN join is not relay authorization.
export const STUN = [{ urls: ['stun:stun.cloudflare.com:3478', 'stun:stun.l.google.com:19302'] }];
const HASH = /^[a-f0-9]{64}$/;
const TOKEN = /^[a-f0-9]{64}$/;
const ID = /^\d{9}$/;
const TTL = 3600;

export async function digest(value) {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(bytes)].map(b => b.toString(16).padStart(2, '0')).join('');
}

function json(value, status = 200) {
  return Response.json(value, { status, headers: { 'cache-control': 'no-store',
    'referrer-policy': 'no-referrer', 'x-content-type-options': 'nosniff' } });
}

function entries(env) {
  try {
    const list = JSON.parse(env.RELAY_ADMISSIONS || '[]');
    return Array.isArray(list) ? list : [];
  } catch { return []; }
}

export function configured(env) {
  return env.RELAY_ENABLED === 'true' && !!key(env);
}

function key(env) {
  if (env.PUBLIC_TURN_KEY_ID && env.PUBLIC_TURN_KEY_API_TOKEN) return { id: env.PUBLIC_TURN_KEY_ID, token: env.PUBLIC_TURN_KEY_API_TOKEN };
  // Explicit migration of an owner's already-created key; do not duplicate or reveal secrets.
  if (env.RELAY_USE_LEGACY_KEY === 'true' && env.TURN_KEY_ID && env.TURN_KEY_API_TOKEN) return { id: env.TURN_KEY_ID, token: env.TURN_KEY_API_TOKEN };
  return null;
}

function registry(env) {
  return env.ROOMS.get(env.ROOMS.idFromName('__public_relay__'));
}

export async function relayViewerAdmission(request, env) {
  if (!configured(env)) return null;
  const protocol = (request.headers.get('Sec-WebSocket-Protocol') || '').split(',').map(x => x.trim());
  const token = (protocol.find(x => x.startsWith('hop-relay.')) || '').slice('hop-relay.'.length);
  if (!TOKEN.test(token)) return null;
  const id = new URL(request.url).searchParams.get('id'), hash = await digest(token), now = Date.now();
  return entries(env).some(e => e && e.role === 'browser' && e.tokenHash === hash &&
    Array.isArray(e.hostIds) && e.hostIds.includes(id) && Number.isFinite(e.expiresAt) && e.expiresAt > now) ? hash : null;
}

export async function relayIce(request, env) {
  const url = new URL(request.url), id = url.searchParams.get('id') || '';
  const fallback = { iceServers: STUN, relayAvailable: configured(env), relayAuthorized: false };
  if (!configured(env)) return json(fallback);
  const token = (request.headers.get('Authorization') || '').replace(/^Bearer /, '');
  const host = url.searchParams.get('role') === 'host';
  if (!ID.test(id) || !(host ? token.length >= 24 && token.length <= 200 : TOKEN.test(token))) return json(fallback);
  const hash = await digest(token), now = Date.now();
  const admission = entries(env).find(e => e && e.tokenHash === hash && e.role === (host ? 'host' : 'browser') &&
    Array.isArray(e.hostIds) && e.hostIds.includes(id) && Number.isFinite(e.expiresAt) && e.expiresAt > now);
  if (!admission) return json(fallback);
  // Only the actual online host may use its owner-approved host capability.
  const room = env.ROOMS.get(env.ROOMS.idFromName('public:' + id));
  const sid = url.searchParams.get('sid') || '';
  if (host && !/^[a-f0-9]{16}$/.test(sid)) return json(fallback);
  const state = await room.fetch('https://public-service/relay-host', { method: 'POST',
    body: JSON.stringify({ hostHash: host ? hash : null, sid: host ? sid : null }) });
  if (!state.ok) return json({ ...fallback, relayAuthorized: true, relayError: 'Computer is offline' });
  if (host) {
    const session = await state.json();
    if (!entries(env).some(e => e && e.role === 'browser' && e.tokenHash === session.viewerHash &&
      Array.isArray(e.hostIds) && e.hostIds.includes(id) && Number.isFinite(e.expiresAt) && e.expiresAt > now)) return json(fallback);
  }
  const gate = await registry(env).fetch('https://relay/issue', { method: 'POST',
    body: JSON.stringify({ hash, id }) });
  if (!gate.ok) return json({ ...fallback, relayAuthorized: true, relayError: 'Relay connection limit reached. Try again later.' }, 429);
  const cached = await gate.json();
  if (cached.ice) return json(cached.ice);
  try {
    const provider = key(env);
    const r = await fetch(`https://rtc.live.cloudflare.com/v1/turn/keys/${provider.id}/credentials/generate-ice-servers`, {
      method: 'POST', headers: { Authorization: `Bearer ${provider.token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ ttl: TTL }), signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) throw new Error('TURN provider unavailable');
    const j = await r.json(), list = Array.isArray(j.iceServers) ? j.iceServers : [j.iceServers];
    const turn = list.filter(s => s && s.username && s.credential).map(s => ({
      urls: (Array.isArray(s.urls) ? s.urls : [s.urls]).filter(u => typeof u === 'string' &&
        /^turns?:turn\.cloudflare\.com:(3478|443|80|5349)(\?transport=(udp|tcp))?$/.test(u)),
      username: s.username, credential: s.credential,
    })).filter(s => s.urls.length);
    if (!turn.length) throw new Error('Missing TURN servers');
    const ice = { iceServers: [...STUN, ...turn], relayAvailable: true, relayAuthorized: true, relayExpiresAt: now + TTL * 1000 };
    await registry(env).fetch('https://relay/cache', { method: 'POST', body: JSON.stringify({ hash, id, ice }) });
    return json(ice);
  } catch {
    // Never include provider responses or credentials in errors/logs.
    return json({ ...fallback, relayAuthorized: true, relayError: 'Relay is temporarily unavailable' }, 503);
  }
}

export async function relayEnrollment(request, env) {
  if (request.method === 'POST') {
    if (Number(request.headers.get('content-length') || 0) > 1024) return json({ error: 'Request too large' }, 413);
    let data; try {
      const raw = await request.text();
      if (raw.length > 1024) return json({ error: 'Request too large' }, 413);
      data = JSON.parse(raw);
    } catch { return json({ error: 'Invalid request' }, 400); }
    if (!data || typeof data !== 'object' || !HASH.test(data.tokenHash || '') || !ID.test(data.hostId || '')) return json({ error: 'Invalid request' }, 400);
    return registry(env).fetch('https://relay/enroll', { method: 'POST', body: JSON.stringify(data) });
  }
  const code = new URL(request.url).searchParams.get('code') || '';
  if (!/^\d{6}$/.test(code)) return json({ error: 'Invalid code' }, 400);
  // Hashes do not grant access. Only an authenticated Cloudflare owner can add them to admissions.
  return registry(env).fetch('https://relay/lookup?code=' + code);
}

// Runs inside the existing Room class; no new binding/migration or admin credential.
export async function relayRegistry(request, ctx, env) {
  const url = new URL(request.url), now = Date.now();
  if (url.pathname === '/enroll') {
    const { tokenHash, hostId } = await request.json();
    const key = 'enroll:' + tokenHash + ':' + hostId;
    const old = await ctx.storage.get(key);
    if (old && old.expiresAt > now) return json({ code: old.code, expiresAt: old.expiresAt });
    const pending = await ctx.storage.list({ prefix: 'code:', limit: 1000 });
    if ([...pending.values()].filter(v => v.expiresAt > now).length >= 1000) return json({ error: 'Try again later' }, 429);
    let code;
    for (let i = 0; i < 10; i++) {
      code = String(crypto.getRandomValues(new Uint32Array(1))[0] % 1000000).padStart(6, '0');
      const prior = await ctx.storage.get('code:' + code);
      if (!prior || prior.expiresAt <= now) break;
      code = null;
    }
    if (!code) return json({ error: 'Try again later' }, 503);
    const entry = { code, tokenHash, hostId, expiresAt: now + 600000 };
    await ctx.storage.put({ [key]: entry, ['code:' + code]: entry });
    await ctx.storage.setAlarm(now + 600000);
    return json({ code, expiresAt: entry.expiresAt });
  }
  if (url.pathname === '/lookup') {
    const entry = await ctx.storage.get('code:' + url.searchParams.get('code'));
    return entry && entry.expiresAt > now ? json(entry) : json({ error: 'Code expired' }, 404);
  }
  const { hash, id, ice } = await request.json();
  const key = 'ice:' + hash + ':' + id;
  if (url.pathname === '/cache') {
    await ctx.storage.put(key, ice);
    return json({ ok: true });
  }
  if (url.pathname === '/issue') {
    const cached = await ctx.storage.get(key);
    if (cached && cached.relayExpiresAt > now + 120000) return json({ ice: cached });
    const day = new Date(now).toISOString().slice(0, 10);
    const count = await ctx.storage.get('count:' + day) || 0;
    // Bounds issuance, not bytes or dollars. Issued TURN allocations remain usable until expiry/revocation.
    const limit = Math.min(100, Math.max(1, Number(env.RELAY_DAILY_ISSUANCE_LIMIT) || 24));
    if (count >= limit) return json({ error: 'Daily relay issuance limit' }, 429);
    await ctx.storage.put('count:' + day, count + 1);
    await ctx.storage.setAlarm(now + 600000);
    return json({});
  }
  return json({ error: 'Not found' }, 404);
}

export async function cleanRelayRegistry(ctx) {
  const now = Date.now(), today = new Date(now).toISOString().slice(0, 10);
  const all = await ctx.storage.list();
  const expired = [...all].filter(([k, v]) => k === 'isRelayRegistry' ? false : k.startsWith('count:') ? k !== 'count:' + today :
    (v.expiresAt || v.relayExpiresAt || 0) <= now).map(([k]) => k);
  if (expired.length) await ctx.storage.delete(expired);
  if (all.size > expired.length + 1) await ctx.storage.setAlarm(now + 600000);
}
