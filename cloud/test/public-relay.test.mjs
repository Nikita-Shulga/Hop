import test from 'node:test';
import assert from 'node:assert/strict';
import { relayIce, relayEnrollment, relayRegistry, cleanRelayRegistry, digest, configured } from '../src/public-relay.mjs';

const TOKEN = 'a'.repeat(64), ID = '123456789';
test('existing TURN names require explicit owner-selected migration to the managed admission flow', () => {
  const env = { RELAY_ENABLED: 'true', TURN_KEY_ID: 'existing', TURN_KEY_API_TOKEN: 'server-only' };
  assert.equal(configured(env), false);
  env.RELAY_USE_LEGACY_KEY = 'true';
  assert.equal(configured(env), true);
});
function registry() {
  const map = new Map();
  const ctx = { storage: {
    get: async key => map.get(key),
    put: async (key, value) => { if (typeof key === 'string') map.set(key, value); else Object.entries(key).forEach(([k, v]) => map.set(k, v)); },
    delete: async keys => { for (const key of Array.isArray(keys) ? keys : [keys]) map.delete(key); },
    list: async () => new Map(map), setAlarm: async () => {},
  } };
  return { ctx, map };
}
async function setup() {
  const { ctx, map } = registry();
  let online = true, expectedHostHash = null;
  const env = { RELAY_ENABLED: 'true', PUBLIC_TURN_KEY_ID: 'test-key', PUBLIC_TURN_KEY_API_TOKEN: 'server-only-token',
    RELAY_ADMISSIONS: JSON.stringify([{ role: 'browser', tokenHash: await digest(TOKEN), hostIds: [ID], expiresAt: Date.now() + 86400000 }]),
    ROOMS: { idFromName: x => x, get: name => ({ fetch: async (input, init) => {
      const r = new Request(input, init);
      if (name === '__public_relay__') return relayRegistry(r, ctx, env);
      const { hostHash } = await r.json();
      return Response.json({}, { status: online && (!hostHash || hostHash === expectedHostHash) ? 200 : 403 });
    } }) },
  };
  const request = (token = TOKEN, id = ID, extra = '') => new Request('https://hop.nikitashulga.com/api/ice?id=' + id + extra,
    { headers: { Authorization: 'Bearer ' + token } });
  return { env, ctx, map, request, offline: () => { online = false; }, setHostHash: h => { expectedHostHash = h; } };
}

test('TURN is fail-closed for anonymous, unapproved, expired, mismatched host or disabled access', async () => {
  const { env, request } = await setup();
  const original = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error('must not issue'); };
  try {
    for (const r of [request(''), request('b'.repeat(64)), request(TOKEN, '987654321')]) {
      const j = await (await relayIce(r, env)).json();
      assert.equal(j.relayAuthorized, false); assert.equal(j.iceServers.length, 1);
    }
    env.RELAY_ADMISSIONS = JSON.stringify([{ role: 'browser', tokenHash: await digest(TOKEN), hostIds: [ID], expiresAt: Date.now() - 1 }]);
    assert.equal((await (await relayIce(request(), env)).json()).relayAuthorized, false);
    env.RELAY_ENABLED = 'false';
    assert.equal((await (await relayIce(request(), env)).json()).relayAvailable, false);
    assert.equal(calls, 0);
  } finally { globalThis.fetch = original; }
});

test('approved online browser receives cached one-hour credentials, including TLS 443, never long-term token', async () => {
  const { env, request } = await setup();
  const original = globalThis.fetch; let calls = 0;
  globalThis.fetch = async (url, init) => {
    calls++; assert.match(url, /\/turn\/keys\/test-key\//);
    assert.equal(init.headers.Authorization, 'Bearer server-only-token');
    assert.equal(JSON.parse(init.body).ttl, 3600);
    return Response.json({ iceServers: [{ urls: ['turn:turn.cloudflare.com:3478?transport=udp',
      'turns:turn.cloudflare.com:443?transport=tcp', 'turn:turn.cloudflare.com:53?transport=udp', 'turn:evil.test:443'],
      username: 'short-user', credential: 'short-secret' }] });
  };
  try {
    const a = await (await relayIce(request(), env)).json();
    assert.equal(a.relayAuthorized, true);
    assert.deepEqual(a.iceServers[1].urls, ['turn:turn.cloudflare.com:3478?transport=udp', 'turns:turn.cloudflare.com:443?transport=tcp']);
    assert.ok(a.relayExpiresAt <= Date.now() + 3600000);
    assert.ok(!JSON.stringify(a).includes('server-only-token'));
    assert.deepEqual(await (await relayIce(request(), env)).json(), a);
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});

test('offline hosts, provider errors and global issuance limit cannot mint additional credentials', async () => {
  const { env, request, offline, map } = await setup();
  const original = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response('private provider diagnostic', { status: 500 }); };
  try {
    assert.equal((await relayIce(request(), env)).status, 503);
    env.RELAY_DAILY_ISSUANCE_LIMIT = '1';
    assert.equal((await relayIce(request(), env)).status, 429);
    assert.equal(calls, 1);
    offline(); map.clear();
    const j = await (await relayIce(request(), env)).json();
    assert.equal(j.relayError, 'Computer is offline'); assert.equal(calls, 1);
    assert.ok(!JSON.stringify(j).includes('diagnostic'));
  } finally { globalThis.fetch = original; }
});

test('a public host registration is insufficient; host capability must be owner-approved and match actual host', async () => {
  const s = await setup(), hash = await digest(TOKEN);
  assert.equal((await (await relayIce(s.request(TOKEN, ID, '&role=host'), s.env)).json()).relayAuthorized, false);
  s.env.RELAY_ADMISSIONS = JSON.stringify([{ role: 'host', tokenHash: hash, hostIds: [ID], expiresAt: Date.now() + 10000 }]);
  assert.equal((await (await relayIce(s.request(TOKEN, ID, '&role=host'), s.env)).json()).relayError, 'Computer is offline');
});

test('enrollment reveals only an expiring code; lookup hash does not grant relay admission', async () => {
  const { env, map } = await setup();
  const hash = await digest('b'.repeat(64));
  const enroll = () => new Request('https://hop.nikitashulga.com/api/relay/enroll', { method: 'POST',
    body: JSON.stringify({ tokenHash: hash, hostId: ID }) });
  const j = await (await relayEnrollment(enroll(), env)).json();
  assert.match(j.code, /^\d{6}$/); assert.equal(j.tokenHash, undefined);
  const lookup = new Request('https://hop.nikitashulga.com/api/relay/enroll?code=' + j.code);
  assert.equal((await (await relayEnrollment(lookup, env)).json()).tokenHash, hash);
  assert.deepEqual(await (await relayEnrollment(enroll(), env)).json(), j);
  map.get('code:' + j.code).expiresAt = Date.now() - 1;
  assert.equal((await relayEnrollment(lookup, env)).status, 404);
});

test('registry cleanup preserves its marker and current daily limit while expiring credentials and codes', async () => {
  const { ctx, map } = registry();
  map.set('isRelayRegistry', true);
  map.set('code:000000', { expiresAt: 1 });
  map.set('ice:test', { relayExpiresAt: 1 });
  map.set('count:2000-01-01', 99);
  const today = 'count:' + new Date().toISOString().slice(0, 10);
  map.set(today, 3);
  await cleanRelayRegistry(ctx);
  assert.deepEqual([...map], [['isRelayRegistry', true], [today, 3]]);
});
