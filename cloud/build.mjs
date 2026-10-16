// Copies the viewer (../static) into public/ for Workers static assets.
// The host window page and its icons for desktop apps are left out: they only make sense on a computer.
import { cpSync, rmSync, mkdirSync, copyFileSync, existsSync } from 'node:fs';
import { dirname, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'static');
const out = join(here, 'public');
const SKIP = new Set(['host.html', 'icon.ico', 'cloud.json']);

// One-click deploys (Cloudflare's "Deploy" button) copy only this folder: then ../static isn't there and the
// committed public/ copy is used as it is.
if (!existsSync(join(src, 'index.html'))) {
  console.log('No ../static here; deploying the viewer already in public/');
  process.exit(0);
}
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
cpSync(src, join(out, 'static'), { recursive: true, filter: (p) => !SKIP.has(basename(p)) });
copyFileSync(join(src, 'index.html'), join(out, 'index.html'));
console.log('Viewer copied to', out);
