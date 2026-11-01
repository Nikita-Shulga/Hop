import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { SourceTextModule, SyntheticModule, createContext } from 'node:vm';
import { webcrypto } from 'node:crypto';
import { isPublicService, publicServiceRequest } from '../src/public-service.mjs';
import { relayRegistry, cleanRelayRegistry, digest } from '../src/public-relay.mjs';

function environment() {
  const calls = [];
  const env = {
    ASSETS: { fetch: async () => new Response('<h1>Hop</h1>', { headers: { 'content-type': 'text/html' } }) },
    ROOMS: {
      idFromName: name => name,
      get: name => ({ fetch: async (request, options) => {
        calls.push({ name, request, options });
        if (name.startsWith('public-rate:')) return new Response('{}', { status: env.limited ? 429 : 200 });
        if (name === '__site__') return Response.json({ ok: false });
        return new Response(name);
      } }),
    },
  };
  return { env, calls };
}

const request = (path, headers = {}) => new Request('https://hop.nikitashulga.com' + path, { headers });

test('public portal serves HTML, cloud mode and an origin-scoped manifest without a URL key', async () => {
  const { env } = environment();
  const home = await publicServiceRequest(request('/'), env, 'test');
  assert.equal(home.status, 200);
  assert.match(await home.text(), /Hop/);
  assert.equal(home.headers.get('cache-control'), 'no-store');
  assert.equal(home.headers.get('x-frame-options'), 'DENY');
  const info = await (await publicServiceRequest(request('/api/info'), env, 'test')).json();
  assert.equal(info.publicService, true);
  assert.equal(info.cloud, true);
  assert.equal(info.server, 'https://hop.nikitashulga.com');
  const manifest = await (await publicServiceRequest(request('/manifest.webmanifest'), env, 'test')).json();
  assert.equal(manifest.start_url, '/');
  assert.equal(manifest.scope, '/');
});

test('only the explicitly managed hostname opts into the public service', () => {
  assert.ok(isPublicService(new URL('https://hop.nikitashulga.com'), {}));
  for (const host of ['localview.nikos1279.workers.dev', 'private.example.com', 'hop.nikitashulga.com.evil.test']) {
    assert.equal(isPublicService(new URL('https://' + host), {}), false);
  }
});

test('old generated links redirect to the public entry without retaining the obsolete key', async () => {
  const { env } = environment();
  const r = await publicServiceRequest(request('/k/obsolete-test-key-12345/'), env, 'test');
  assert.equal(r.status, 302);
  assert.equal(r.headers.get('location'), 'https://hop.nikitashulga.com/');
});

test('HTTP is upgraded to HTTPS with paths and query strings intact', async () => {
  const { env } = environment();
  const r = await publicServiceRequest(new Request('http://hop.nikitashulga.com/api/info?check=1'), env, 'test');
  assert.equal(r.status, 308);
  assert.equal(r.headers.get('location'), 'https://hop.nikitashulga.com/api/info?check=1');
});

test('invalid IDs, missing host secrets, non-WebSocket and cross-origin requests cannot join rooms', async () => {
  const { env, calls } = environment();
  for (const path of ['/ws/view?id=123', '/ws/view?id=abc123456789', '/ws/host?id=123456789']) {
    assert.equal((await publicServiceRequest(request(path, { Upgrade: 'websocket' }), env, 'test')).status, 400);
  }
  assert.equal((await publicServiceRequest(request('/ws/view?id=123456789'), env, 'test')).status, 426);
  assert.equal((await publicServiceRequest(request('/ws/view?id=123456789', {
    Upgrade: 'websocket', Origin: 'https://evil.example',
  }), env, 'test')).status, 403);
  assert.equal(calls.length, 0);
});

test('valid public hosts and viewers use isolated rooms, preserving per-host authentication', async () => {
  const { env, calls } = environment();
  const headers = { Upgrade: 'websocket', 'CF-Connecting-IP': '192.0.2.1' };
  const r = await publicServiceRequest(request('/ws/host?id=123456789&key=test-host-secret-24-characters', headers), env, 'test');
  assert.equal(await r.text(), 'public:123456789');
  const v = await publicServiceRequest(request('/ws/view?id=123456789', headers), env, 'test');
  assert.equal(await v.text(), 'public:123456789');
  assert.ok(calls[0].name.startsWith('public-rate:'));
  assert.ok(!calls[0].name.includes('192.0.2.1'));
  assert.equal(calls[1].request.url.includes('test-host-secret'), true, 'the original authenticated host request reaches the room');
});

test('connection-rate limits reject before forwarding to a device room', async () => {
  const { env, calls } = environment(); env.limited = true;
  const r = await publicServiceRequest(request('/ws/view?id=123456789', { Upgrade: 'websocket' }), env, 'test');
  assert.equal(r.status, 429);
  assert.equal(r.headers.get('retry-after'), '60');
  assert.equal(calls.length, 1);
});

test('anonymous requests cannot receive paid relay credentials', async () => {
  const { env } = environment();
  env.TURN_KEY_ID = 'configured'; env.TURN_KEY_API_TOKEN = 'not-for-the-browser';
  env.PUBLIC_TURN_KEY_ID = 'configured'; env.PUBLIC_TURN_KEY_API_TOKEN = 'not-for-the-browser';
  const ice = await (await publicServiceRequest(request('/api/ice'), env, 'test')).json();
  assert.ok(ice.iceServers.every(s => !s.credential && s.urls.every(u => u.startsWith('stun:'))));
});

test('legacy origins still reject unkeyed requests and never use public rooms', async () => {
  const context = createContext({ Response, Request, URL, TextEncoder, crypto: webcrypto });
  const source = new SourceTextModule(readFileSync(new URL('../src/index.js', import.meta.url), 'utf8'), { context });
  await source.link(async specifier => {
    if (specifier === 'cloudflare:workers') return new SyntheticModule(['DurableObject'], function () {
      this.setExport('DurableObject', class {});
    }, { context });
    if (specifier === './public-relay.mjs') return new SyntheticModule(['relayRegistry', 'cleanRelayRegistry'], function () {
      this.setExport('relayRegistry', relayRegistry);
      this.setExport('cleanRelayRegistry', cleanRelayRegistry);
    }, { context });
    return new SyntheticModule(['isPublicService', 'publicServiceRequest'], function () {
      this.setExport('isPublicService', isPublicService);
      this.setExport('publicServiceRequest', publicServiceRequest);
    }, { context });
  });
  await source.evaluate();
  const { env, calls } = environment();
  for (const path of ['/', '/api/info', '/api/ice', '/ws/view?id=123456789', '/k/invalid-private-key-12345/']) {
    const r = await source.namespace.default.fetch(new Request('https://localview.nikos1279.workers.dev' + path), env);
    assert.equal(r.status, 404, path);
  }
  assert.ok(calls.every(c => !c.name.startsWith('public:')));
});

test('actual Room relay gate requires online host and its matching stored secret hash', async () => {
  let online = true;
  let viewerAdmission = { offered: true, relayAdmissionHash: 'approved-browser-hash' };
  const stored = new Map([['keyHash', 'owner-host-hash']]);
  const ctx = { setWebSocketAutoResponse() {}, getWebSockets: tag => tag === 'host' ? (online ? [{}] : []) :
    tag === 'v:0123456789abcdef' ? [{ deserializeAttachment: () => viewerAdmission }] : [],
    storage: { get: async k => stored.get(k), put: async (k, v) => stored.set(k, v) } };
  const context = createContext({ Response, Request, URL, TextEncoder, crypto: webcrypto,
    WebSocketRequestResponsePair: class {} });
  const source = new SourceTextModule(readFileSync(new URL('../src/index.js', import.meta.url), 'utf8'), { context });
  await source.link(async specifier => {
    if (specifier === 'cloudflare:workers') return new SyntheticModule(['DurableObject'], function () {
      this.setExport('DurableObject', class { constructor(ctx) { this.ctx = ctx; } });
    }, { context });
    const values = specifier === './public-relay.mjs' ? { relayRegistry, cleanRelayRegistry } : { isPublicService, publicServiceRequest };
    return new SyntheticModule(Object.keys(values), function () {
      Object.entries(values).forEach(([k, v]) => this.setExport(k, v));
    }, { context });
  });
  await source.evaluate();
  const room = new source.namespace.Room(ctx, {});
  const check = (hostHash, sid = '0123456789abcdef') => room.fetch(new Request('https://public-service/relay-host', {
    method: 'POST', body: JSON.stringify({ hostHash, sid }) }));
  assert.equal((await check('attacker-hash')).status, 403);
  assert.equal((await check('owner-host-hash', '')).status, 403);
  assert.equal((await check('owner-host-hash')).status, 200);
  assert.equal((await check(null)).status, 200, 'owner-approved browser still needs an online target');
  viewerAdmission = { offered: true, relayAdmissionHash: null };
  assert.equal((await check('owner-host-hash')).status, 403, 'unapproved viewer cannot trigger host-funded relay');
  online = false;
  assert.equal((await check(null)).status, 403);
  assert.equal((await check('owner-host-hash')).status, 403);
});

test('public signaling authenticates relay subprotocol capability and strips forged admission headers', async () => {
  const { env, calls } = environment(), token = 'c'.repeat(64), hash = await digest(token);
  Object.assign(env, { RELAY_ENABLED: 'true', PUBLIC_TURN_KEY_ID: 'test', PUBLIC_TURN_KEY_API_TOKEN: 'test',
    RELAY_ADMISSIONS: JSON.stringify([{ role: 'browser', tokenHash: hash, hostIds: ['123456789'], expiresAt: Date.now() + 10000 }]) });
  await publicServiceRequest(request('/ws/view?id=123456789', { Upgrade: 'websocket', 'X-Hop-Relay-Admission': hash }), env, 'test');
  assert.equal(calls.at(-1).request.headers.get('X-Hop-Relay-Admission'), null);
  await publicServiceRequest(request('/ws/view?id=123456789', { Upgrade: 'websocket', 'Sec-WebSocket-Protocol': 'hop, hop-relay.' + token }), env, 'test');
  assert.equal(calls.at(-1).request.headers.get('X-Hop-Relay-Admission'), hash);
  assert.equal(calls.at(-1).request.url.includes(token), false);
  await publicServiceRequest(request('/ws/view?id=987654321', { Upgrade: 'websocket', 'Sec-WebSocket-Protocol': 'hop, hop-relay.' + token }), env, 'test');
  assert.equal(calls.at(-1).request.headers.get('X-Hop-Relay-Admission'), null);
});

test('actual Room forwards only one offer per sid, without trusting viewer-supplied relay flags', async () => {
  const forwarded = [];
  let pending = [];
  const ctx = { setWebSocketAutoResponse() {}, getWebSockets: tag => tag === 'host' ? [{ send: x => forwarded.push(JSON.parse(x)) }] : tag === 'view' ? pending : [] };
  const context = createContext({ Response, Request, URL, TextEncoder, crypto: webcrypto,
    WebSocketRequestResponsePair: class {}, WebSocketPair: class { constructor() { return { 0: {}, 1: {} }; } } });
  const source = new SourceTextModule(readFileSync(new URL('../src/index.js', import.meta.url), 'utf8'), { context });
  await source.link(async specifier => {
    const values = specifier === 'cloudflare:workers' ? { DurableObject: class { constructor(ctx) { this.ctx = ctx; } } } :
      specifier === './public-relay.mjs' ? { relayRegistry, cleanRelayRegistry } : { isPublicService, publicServiceRequest };
    return new SyntheticModule(Object.keys(values), function () { Object.entries(values).forEach(([k, v]) => this.setExport(k, v)); }, { context });
  });
  await source.evaluate();
  const room = new source.namespace.Room(ctx, {});
  let attachment = { role: 'view', sid: '0123456789abcdef', managedService: true, relayAdmissionHash: null };
  const ws = { deserializeAttachment: () => attachment, serializeAttachment: a => { attachment = a; }, send() {} };
  for (let i = 0; i < 12; i++) await room.webSocketMessage(ws, JSON.stringify({ t: 'offer', sdp: 'test-sdp', relayAllowed: true }));
  assert.equal(forwarded.length, 1);
  assert.equal(forwarded[0].relayAllowed, false);
  attachment = { role: 'view', sid: 'fedcba9876543210', managedService: true, relayAdmissionHash: 'approved-hash' };
  await room.webSocketMessage(ws, JSON.stringify({ t: 'offer', sdp: 'test-sdp' }));
  assert.equal(forwarded[1].relayAllowed, true);
  pending = [{}, {}, {}, {}];
  assert.equal((await room.fetch(new Request('https://room/ws/view'))).status, 429, 'four pending viewers cannot create a fifth negotiation');
});
