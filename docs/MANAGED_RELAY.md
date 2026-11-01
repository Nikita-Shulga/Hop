# Managed-service relay

The public service defaults to STUN only. Registering a computer or knowing its ID does not
authorize use of owner-funded TURN. The device password, device pairing and optional connection
approval continue to be checked by the computer through its encrypted WebRTC channel.

## Provisioning proposal (not activated)

Target: Cloudflare account `9fb7170757d6dd4bb0a6b9aac196e2c7`,
**Nikos1279@gmail.com's Account**, Worker **localview**, hostname **hop.nikitashulga.com**.
The account dashboard currently redirects TURN Server to its Realtime subscription introduction;
there is no enabled TURN resource available to reuse. The introduction states 1,000 GB/month free.

After explicit owner approval:

1. Enable Cloudflare Realtime TURN in that account and create a dedicated **Hop** TURN key.
   Use its key-specific API token, not an account-wide token. This credential can issue and revoke
   TURN credentials for that key. Keep `TURN_KEY_ID` and `TURN_KEY_API_TOKEN` only as encrypted
   Worker secrets, never in source, browser storage, URLs, logs or desktop configuration.
2. Set `RELAY_ENABLED=true`. Set `RELAY_DAILY_ISSUANCE_LIMIT=24` initially.
3. Approve the specific owner's browser and computer as described below, with a 30-day admission
   expiry. No other public hosts or anonymous visitors are automatically admitted.
4. Verify a forced-relay connection, TLS/443 transport and actual phone-to-computer use on separate
   networks. A synthetic peer test on one Mac does not establish overseas reachability.

Cloudflare's published rate is **first 1,000 GB/month free, then $0.05/GB egress**. SFU and TURN share
that allowance across the account. Existing Workers/Durable Objects have separate charges. Source:
https://developers.cloudflare.com/realtime/sfu/platform/pricing/

No enforceable dollar or byte cap has been found in the available TURN configuration or primary
documentation. The local daily issuance limit is **not a spending cap**: one credential can carry
substantial traffic, and TURN usage occurs outside this Worker. Do not describe this as guaranteed
free. Approval must cover the metered overage, or provisioning must remain off.

## Admission and lifetime

The browser generates an independent random 256-bit relay capability. Only its SHA-256 hash is
sent during enrollment. The owner checks the six-digit code shown in the intended browser,
matching its computer ID, and updates `RELAY_ADMISSIONS` through the existing authenticated
Wrangler session. An enrollment code expires after ten minutes and cannot authorize itself.

For example, after the owner has approved provisioning and this browser:

```sh
WRANGLER_BIN=/path/to/wrangler node cloud/approve-relay.mjs \
  --code 123456 --host-id 123456789 --days 30 --host-config /path/to/.hop.json
```

The optional host config authorizes only that actual computer's existing host-secret hash. It never
uploads the host secret or password. Without it, an approved browser can still use TURN on its leg
while an older host uses STUN. The explicit registry is `.relay-admissions.json` (ignored by Git,
mode 0600). Preserve it when approving further browsers; Worker secrets cannot be read back.

`/api/ice` checks owner admission, expiry, exact target computer ID and online host before issuing
any relay credentials. Hosts additionally prove their existing host secret against the actual room.
Issued credentials expire after one hour and are cached per capability/target, with a global daily
issuance ceiling. Failed provider requests consume an issuance slot to bound repeated attempts.
New sessions refresh credentials when the cached credentials approach expiry. Long sessions may
need reconnection; seamless mid-session host credential renewal is not implemented.

Cloudflare TLS/443 is included. aiortc currently supports only the first TURN URL, so the desktop
client deliberately places verified `turns:turn.cloudflare.com:443?transport=tcp` first.
The bundled CA roots also apply to asyncio/aioice's default TLS context; certificate and hostname
checks remain enabled. Custom private TURN servers retain their existing fallback behavior.

## Shutoff

Set `RELAY_ENABLED=false` to stop new credential delivery immediately, or remove an admission to
stop that device obtaining more credentials. Credentials already issued are not revoked by changing
the Worker flag and can remain usable until provider expiry/allocation cleanup. For emergency
revocation use Cloudflare's credential-revocation API for issued usernames:
https://developers.cloudflare.com/realtime/turn/generate-credentials/#revoke-credentials
Do not claim the issuance counter or Worker flag instantly terminates provider allocations.

## Validation

```sh
node cloud/build.mjs
node packaging/check-js.mjs
node --experimental-vm-modules --test cloud/test/public-service.test.mjs cloud/test/public-relay.test.mjs
python -m pytest tests -q
```

The relay unit tests mock the provider: they cover fail-closed admission, expiry, host matching,
offline hosts, limits, credential caching, TLS/443 inclusion and enrollment lifetime. The aiortc test
uses its actual parser to verify selection of TLS/TCP 443 ahead of UDP. These do **not** validate a
live TURN allocation, firewall traversal, a real phone, Windows capture, or cross-network video.
