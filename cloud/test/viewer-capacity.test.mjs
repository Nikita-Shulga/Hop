import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { SourceTextModule, SyntheticModule, createContext } from 'node:vm';
import { webcrypto } from 'node:crypto';
import { relayRegistry, cleanRelayRegistry } from '../src/public-relay.mjs';
import { isPublicService, publicServiceRequest } from '../src/public-service.mjs';

async function setup() {
  let now = Date.now(), alarm = null;
  const sockets = [], closes = [], offers = [];
  class Socket {
    readyState = 1;
    attachment = {};
    serializeAttachment(a) { this.attachment = { ...a }; }
    deserializeAttachment() { return { ...this.attachment }; }
    send() {}
    close(code) { this.readyState = 3; closes.push(code); }
  }
  class WorkerResponse extends Response {
    constructor(body, init) {
      if (init?.status === 101) { super(null, { status: 200, headers: init.headers }); Object.defineProperty(this, 'status', { value: 101 }); }
      else super(body, init);
    }
  }
  const ctx = { setWebSocketAutoResponse() {},
    getWebSockets: tag => tag === 'host' ? [{ send: x => offers.push(JSON.parse(x)) }] :
      sockets.filter(s => s.readyState === 1 && (tag === 'view' || tag === 'v:' + s.attachment.sid)),
    acceptWebSocket: s => sockets.push(s),
    storage: { get: async () => undefined, delete: async () => {}, getAlarm: async () => alarm,
      setAlarm: async value => { alarm = value; } },
  };
  class Clock extends Date { static now() { return now; } }
  const context = createContext({ Response: WorkerResponse, Request, URL, TextEncoder, crypto: webcrypto,
    Date: Clock, WebSocketRequestResponsePair: class {},
    WebSocketPair: class { constructor() { return { 0: new Socket(), 1: new Socket() }; } },
  });
  const source = new SourceTextModule(readFileSync(new URL('../src/index.js', import.meta.url), 'utf8'), { context });
  await source.link(async name => {
    const values = name === 'cloudflare:workers' ? { DurableObject: class { constructor(ctx) { this.ctx = ctx; } } } :
      name === './public-relay.mjs' ? { relayRegistry, cleanRelayRegistry } : { isPublicService, publicServiceRequest };
    return new SyntheticModule(Object.keys(values), function () { Object.entries(values).forEach(([k, v]) => this.setExport(k, v)); }, { context });
  });
  await source.evaluate();
  const room = new source.namespace.Room(ctx, {});
  const join = admitted => room.fetch(new Request('https://room/ws/view', { headers: {
    'X-Hop-Managed-Service': '1', ...(admitted ? { 'X-Hop-Relay-Admission': 'validated-owner-hash' } : {}),
  } }));
  return { room, join, sockets, closes, offers, advance: ms => { now += ms; }, now: () => now, alarm: () => alarm };
}

test('four idle anonymous joins cannot indefinitely deny the owner; expiry is cleaned before capacity counting', async () => {
  const s = await setup();
  for (let i = 0; i < 4; i++) assert.equal((await s.join(false)).status, 101);
  assert.equal((await s.join(false)).status, 429);
  assert.equal(s.alarm(), s.now() + 60000);
  s.advance(600000);
  assert.equal((await s.join(true)).status, 101);
  assert.equal(s.closes.filter(x => x === 4008).length, 4);
});

test('owner can preempt unadmitted pending slots immediately, without evicting admitted negotiations', async () => {
  const s = await setup();
  for (let i = 0; i < 4; i++) await s.join(false);
  for (let i = 0; i < 4; i++) assert.equal((await s.join(true)).status, 101);
  assert.equal(s.closes.filter(x => x === 4009).length, 4);
  assert.equal((await s.join(true)).status, 429);
});

test('keepalives and repeated offers do not reset expiry; 45-second gathering leaves time for negotiation', async () => {
  const s = await setup(); await s.join(false);
  const ws = s.sockets[0], start = s.now();
  s.advance(45000);
  await s.room.webSocketMessage(ws, JSON.stringify({ t: 'offer', sdp: 'test-sdp' }));
  assert.equal(ws.attachment.expiresAt, start + 90000);
  s.advance(16000); await s.room.alarm();
  assert.equal(ws.readyState, 1); assert.equal(s.alarm(), start + 90000);
  await s.room.webSocketMessage(ws, 'ping');
  await s.room.webSocketMessage(ws, JSON.stringify({ t: 'offer', sdp: 'replacement-sdp' }));
  assert.equal(ws.attachment.expiresAt, start + 90000); assert.equal(s.offers.length, 1);
  s.advance(30000); await s.room.alarm();
  assert.equal(ws.readyState, 3);
  assert.equal((await s.join(false)).status, 101);
});

test('anonymous join-rate exhaustion cannot consume the admitted owner join quota', async () => {
  const s = await setup();
  for (let i = 0; i < 20; i++) {
    assert.equal((await s.join(false)).status, 101);
    s.sockets.at(-1).close(1000);
  }
  assert.equal((await s.join(false)).status, 429);
  assert.equal((await s.join(true)).status, 101);
});
