// The managed browser service uses a separate room namespace. Private deployments and their
// /k/<key>/ gate continue to use the original rooms and are never enrolled automatically.
const ID_RE = /^\d{9}$/;
const METHODS = new Set(['GET', 'HEAD']);
const PUBLIC_HOST = 'hop.nikitashulga.com';
import { relayIce, relayEnrollment } from './public-relay.mjs';

export function isPublicService(url, env) {
  return url.hostname === (env.PUBLIC_SERVICE_HOST || PUBLIC_HOST);
}

function response(body, status = 200, headers = {}) {
  return new Response(body, { status, headers: {
    'cache-control': 'no-store', 'referrer-policy': 'no-referrer',
    'x-content-type-options': 'nosniff', 'x-frame-options': 'DENY', ...headers,
  } });
}

function json(value, status = 200, headers = {}) {
  return response(JSON.stringify(value), status, { 'content-type': 'application/json; charset=utf-8', ...headers });
}

async function allowJoin(request, env) {
  // Cloudflare supplies this header; clients cannot choose it at the edge. Do not retain raw IPs.
  const ip = request.headers.get('CF-Connecting-IP') || 'local-test';
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(ip));
  const hash = [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
  const gate = env.ROOMS.get(env.ROOMS.idFromName('public-rate:' + hash));
  const result = await gate.fetch('https://public-service/rate', { method: 'POST' });
  return result.status !== 429;
}

export async function publicServiceRequest(request, env, version) {
  const url = new URL(request.url), path = url.pathname;
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.protocol === 'http:' && !loopback) return response(null, 308, { location: 'https://' + url.host + url.pathname + url.search });
  if (path === '/api/relay/enroll' && ['POST', 'GET'].includes(request.method)) {
    if (request.headers.get('Origin') && request.headers.get('Origin') !== url.origin) return json({ error: 'Wrong origin' }, 403);
    if (!(await allowJoin(request, env))) return json({ error: 'Too many attempts' }, 429);
    return relayEnrollment(request, env);
  }
  if (!METHODS.has(request.method)) return json({ error: 'Method not allowed' }, 405, { allow: 'GET, HEAD' });

  if (path === '/' || path === '/index.html') {
    const page = await env.ASSETS.fetch(new Request(url.origin + '/index.html'));
    if (!page.ok) return response('Hop is temporarily unavailable. Please try again.', 503);
    return response(request.method === 'HEAD' ? null : page.body, 200, { 'content-type': 'text/html; charset=utf-8' });
  }
  // Older Hop apps generate /k/.../ links. The managed service uses ID/password + pairing instead;
  // discard the obsolete URL key and preserve the non-secret device-ID fragment in the browser.
  if (/^\/k\/[A-Za-z0-9_-]{16,64}\/?$/.test(path)) {
    return response(null, 302, { location: url.origin + '/' + url.search });
  }
  if (path === '/manifest.webmanifest') {
    return json({ name: 'Hop', short_name: 'Hop', id: '/', start_url: '/', scope: '/',
      display: 'standalone', theme_color: '#0A0A0B', background_color: '#0A0A0B',
      icons: [{ src: '/static/icon-192.png', sizes: '192x192', type: 'image/png' },
        { src: '/static/icon-512.png', sizes: '512x512', type: 'image/png' }],
    }, 200, { 'content-type': 'application/manifest+json' });
  }
  if (path === '/api/info') {
    return json({ cloud: true, app: 'hop', version, publicService: true, server: url.origin });
  }
  if (path === '/api/ice') {
    if (request.headers.get('Origin') && request.headers.get('Origin') !== url.origin) return json({ error: 'Wrong origin' }, 403);
    return relayIce(request, env);
  }
  if (path !== '/ws/host' && path !== '/ws/view') return response('Not found', 404);
  const origin = request.headers.get('Origin');
  if (origin && origin !== url.origin) return json({ error: 'Use this server’s Hop page to connect' }, 403);
  const id = url.searchParams.get('id') || '';
  if (!ID_RE.test(id)) return json({ error: 'The ID has 9 digits' }, 400);
  if (path === '/ws/host') {
    const key = url.searchParams.get('key') || '';
    if (key.length < 24 || key.length > 200) return json({ error: 'Bad host key' }, 400);
  }
  if ((request.headers.get('Upgrade') || '').toLowerCase() !== 'websocket') {
    return json({ error: 'Expected a WebSocket' }, 426);
  }
  if (!(await allowJoin(request, env))) {
    return json({ error: 'Too many connection attempts. Wait a minute and try again.' }, 429, { 'retry-after': '60' });
  }
  const room = env.ROOMS.get(env.ROOMS.idFromName('public:' + id));
  return room.fetch(request);
}
