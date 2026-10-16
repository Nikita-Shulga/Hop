import { readFileSync } from 'node:fs';
import { Script } from 'node:vm';
import assert from 'node:assert/strict';

for (const name of ['static/index.html', 'static/host.html', 'cloud/public/static/index.html']) {
  const html = readFileSync(name, 'utf8');
  let count = 0;
  for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
    new Script(match[1], { filename: `${name}:script${++count}` });
  }
  assert.ok(count, `No scripts checked in ${name}`);
  console.log(`${name}: ${count} script(s) parsed`);
}
assert.equal(readFileSync('static/index.html', 'utf8'), readFileSync('cloud/public/static/index.html', 'utf8'),
             'LAN and cloud viewers must be identical; run node cloud/build.mjs');
console.log('LAN/cloud viewer parity: passed');
