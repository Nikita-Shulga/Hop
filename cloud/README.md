# Hop connection server

## Managed browser service

Open **https://hop.nikitashulga.com/** in a browser and enter the computer ID and password from Hop.
On each computer you want to reach, open Hop, turn on **Internet access**, and use
`https://hop.nikitashulga.com` as the connection server. No private `/k/.../` URL is needed for this
managed service. Pair each browser once while you can approve it on the computer, before travelling.
The computer must stay powered on, online and awake; macOS also needs Screen Recording and
Accessibility permissions. Keep the computer password private.

This hostname uses separate device rooms. Existing private deployments below keep their private
links and are not enrolled automatically. Passwords, the initial pairing code and screen/control data
are still handled by the host over an encrypted peer connection. The public portal exposes no device
list, desktop image, file or control endpoint without that host authentication.

The initial managed service uses direct connections with STUN. A managed TURN relay is not yet
provisioned; restrictive networks that prevent direct connections need that relay before remote
access can be promised from those networks. Do not enable billable relay services without the owner's
approval.

### Managed service checks

```sh
node --experimental-vm-modules --test cloud/test/public-service.test.mjs
node cloud/build.mjs
node packaging/check-js.mjs
```

Use the same existing Worker and Durable Object namespace when deploying an update. This does not
require replacing any private server data or device credentials.

## Your own private server

A tiny Cloudflare Worker that lets your devices find each other over the internet. You set it up once;
it runs on Cloudflare's free plan.

**What it does:** your computers check in with it under a 9-digit ID, and it serves the viewer page at
an `https://` address. When you connect, it passes one "hello" message each way. After that, video,
control, clipboard and files go **directly between your devices, encrypted end to end**. The password
is checked by your computer itself, so it never passes through the server.

## Set it up (about 3 minutes, no tools needed)

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/Nikita-Shulga/Hop/tree/main/cloud)

1. Click the button above, or **Create** in Hop's Internet access card.
2. Sign in to Cloudflare, or create a free account.
3. Press **Deploy**. When it finishes, Cloudflare shows your server's address, such as
   `https://hop.yourname.workers.dev`.
4. Paste it into Hop. Your other computers on the same Wi-Fi offer to use it with one click.

### Or with the command line

You need [Node.js](https://nodejs.org) and a free [Cloudflare account](https://dash.cloudflare.com/sign-up).

```bash
cd cloud
npm install
npx wrangler login      # opens your browser: sign in to Cloudflare and allow access
npm run deploy
```

The last command prints your server's address, for example
`https://hop.yourname.workers.dev`. Then:

1. On each computer, open Hop, turn on **Internet access**, and paste that address when asked
   (it's saved; change it later in **Settings > Internet access**). If you build the apps yourself, you can
   preset it by creating `static/cloud.json` containing `{"url": "https://…"}`; that file is git-ignored,
   so your server never ends up in a public repository.
2. On any device, anywhere, open that address, enter the computer's **ID** and **password** (shown in
   Hop), and connect.

## Cost

Everything here fits Cloudflare's free plan: Workers (100,000 requests a day), Durable Objects with
SQLite storage, and the static viewer files. An idle computer costs nothing (its connection "hibernates"),
and connecting uses only a handful of requests.

## Optional: relay for hard networks

Most connections go directly between your devices. Some networks don't allow that (strict office or
hotel Wi-Fi, some mobile carriers), and then the connection fails with *"Couldn't reach that computer
directly."* For those, you can add Cloudflare's relay (TURN):

1. Cloudflare dashboard → **Realtime** → **TURN Server** → create a TURN key.
2. Add its ID and API token to the Worker:
   ```bash
   npx wrangler secret put TURN_KEY_ID
   npx wrangler secret put TURN_KEY_API_TOKEN
   ```

Relay traffic is **free for the first 1,000 GB a month, then $0.05 per GB** (Cloudflare's pricing). It is
only used when a direct connection is impossible. Without these secrets nothing is ever relayed, so there
is nothing to pay.

## Try it locally

```bash
npm run dev             # http://127.0.0.1:8787
```

Point a host at it with Settings → Internet access → `http://127.0.0.1:8787` (allowed for testing).
