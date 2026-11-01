// Run only by the Cloudflare account owner after approving relay provisioning and this browser.
// Stores hashes, never browser capabilities or desktop passwords. Uses existing Wrangler login.
import { readFile, writeFile, rename } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

const args = process.argv.slice(2), options = {};
for (let i = 0; i < args.length; i += 2) options[args[i]] = args[i + 1];
const code = options['--code'], id = options['--host-id'];
const days = Number(options['--days'] || 30);
if (!/^\d{6}$/.test(code || '') || !/^\d{9}$/.test(id || '') || !Number.isInteger(days) || days < 1 || days > 90) {
  throw new Error('Usage: node cloud/approve-relay.mjs --code 123456 --host-id 123456789 [--days 30] [--host-config /path/.hop.json]');
}
const base = 'https://hop.nikitashulga.com';
const r = await fetch(base + '/api/relay/enroll?code=' + code);
if (!r.ok) throw new Error('Browser approval code is invalid or expired');
const entry = await r.json();
if (entry.hostId !== id || !/^[a-f0-9]{64}$/.test(entry.tokenHash || '') || entry.expiresAt <= Date.now()) {
  throw new Error('Approval code does not match the intended computer');
}
const file = resolve(options['--registry'] || '.relay-admissions.json');
let admissions = [];
try { admissions = JSON.parse(await readFile(file, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
if (!Array.isArray(admissions)) throw new Error('Invalid local admissions registry');
admissions = admissions.filter(a => a.expiresAt > Date.now()).map(a =>
  a.role === 'browser' && a.tokenHash === entry.tokenHash ? { ...a, hostIds: a.hostIds.filter(h => h !== id) } : a
).filter(a => a.hostIds.length);
const expiresAt = Date.now() + days * 86400000;
admissions.push({ role: 'browser', tokenHash: entry.tokenHash, hostIds: [id], expiresAt });
if (options['--host-config']) {
  const host = JSON.parse(await readFile(options['--host-config'], 'utf8'));
  if (host.cloudId !== id || typeof host.cloudKey !== 'string' || host.cloudKey.length < 24) throw new Error('Wrong host configuration');
  const tokenHash = createHash('sha256').update(host.cloudKey).digest('hex');
  admissions = admissions.filter(a => !(a.role === 'host' && a.tokenHash === tokenHash));
  admissions.push({ role: 'host', tokenHash, hostIds: [id], expiresAt });
}
// A protected local hash registry is needed to merge later approvals: Worker secret values cannot
// be read back. Use a separate registry for each Worker and retain its backup.
const temporary = file + '.pending';
await writeFile(temporary, JSON.stringify(admissions, null, 2) + '\n', { mode: 0o600 });
const result = spawnSync(process.env.WRANGLER_BIN || 'wrangler', ['secret', 'bulk', '--name', 'localview'], {
  cwd: resolve(import.meta.dirname), input: JSON.stringify({ RELAY_ADMISSIONS: JSON.stringify(admissions) }),
  encoding: 'utf8', env: { ...process.env, WRANGLER_SEND_METRICS: 'false' },
});
if (result.status !== 0) throw new Error('Worker secret update failed; local pending registry retained. Check Wrangler authentication.');
await rename(temporary, file);
console.log('Relay browser approval saved. Computer password and first-device pairing are still required.');
