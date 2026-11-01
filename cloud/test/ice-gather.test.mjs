import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const { waitForGathering } = createRequire(import.meta.url)('../../static/ice-gather.js');

class Peer extends EventTarget {
  iceGatheringState = 'gathering';
  connectionState = 'new';
  localDescription = { sdp: 'host-candidate' };
  complete() { this.iceGatheringState = 'complete'; this.dispatchEvent(new Event('icegatheringstatechange')); }
}

test('single-offer signaling includes a TURN candidate arriving after the old three-second deadline', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const pc = new Peer(); let sent = null;
  const signaling = waitForGathering(pc, 45000).then(() => { sent = pc.localDescription.sdp; });
  t.mock.timers.tick(3000); await Promise.resolve();
  assert.equal(sent, null, 'must not send a partial host-only SDP at three seconds');
  t.mock.timers.tick(7000);
  pc.localDescription.sdp += '\nTLS-443-relay-candidate';
  pc.complete(); await signaling;
  assert.match(sent, /TLS-443-relay-candidate/);
});

test('a gathering timeout rejects instead of sending an incomplete offer', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const pc = new Peer(); let sent = false;
  const signaling = waitForGathering(pc, 45000).then(() => { sent = true; });
  const assertion = assert.rejects(signaling, { code: 'ICE_GATHERING_TIMEOUT' });
  t.mock.timers.tick(45000); await assertion;
  assert.equal(sent, false);
});

test('completed gathering resolves immediately and cancellation rejects without waiting for the deadline', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const complete = new Peer(); complete.complete(); await waitForGathering(complete);
  const pc = new Peer(), pending = waitForGathering(pc);
  const assertion = assert.rejects(pending, { code: 'ICE_CLOSED' });
  pc.connectionState = 'closed'; pc.dispatchEvent(new Event('connectionstatechange'));
  await assertion;
});
