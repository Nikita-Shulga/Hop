import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, Script } from 'node:vm';

// Exercise the actual browser connection function with network/DOM adapters, not live credentials.
const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const connection = html.slice(html.indexOf('function connectCloud() {'), html.indexOf('// Video frames →'));
for (const message of ['Relay is temporarily unavailable', 'Relay connection limit reached. Try again later.']) {
  test('browser reports the actual relay failure: ' + message, async () => {
    const errors = [], panel = { hidden: true };
    class Peer {
      connectionState = 'new';
      localDescription = { sdp: 'test' };
      addTransceiver() {}
      createDataChannel() { return {}; }
      createOffer() { return Promise.resolve({}); }
      setLocalDescription() { return Promise.resolve(); }
    }
    class Socket { readyState = 1; send() {} }
    const c = { window: { RTCPeerConnection: true }, RTCPeerConnection: Peer, WebSocket: Socket,
      CLOUD_BASE: 'https://hop.example.test', CLOUD_KEY: '', PUBLIC_SERVICE: true, cloudId: '123456789',
      cloudRetry: 1, rtc: null, ws: null, retryTimer: null, connectTimer: null, everHello: false,
      cloudApi: path => path, relayIdentity: () => 'a'.repeat(64),
      fetch: async () => ({ json: async () => ({ iceServers: [{ urls: ['stun:test'] }],
        relayAvailable: true, relayAuthorized: true, relayError: message }) }),
      $: () => panel, M: key => 'translated:' + key, setTimeout: () => 1, clearTimeout() {},
      teardownRtc: () => { c.rtc = null; }, onServerError: msg => errors.push(msg),
      onClosed() {}, toast() {}, I18N: { message: x => x }, HopIce: { waitForGathering: async () => {} },
    };
    createContext(c); new Script(connection).runInContext(c); c.connectCloud();
    for (let i = 0; i < 8; i++) await Promise.resolve();
    c.rtc.sig.onmessage({ data: JSON.stringify({ t: 'ready' }) });
    c.rtc.pc.connectionState = 'failed'; c.rtc.pc.onconnectionstatechange();
    assert.deepEqual(errors, [message]);
    assert.ok(!errors[0].includes('translated:msg.notDirect'));
  });
}
