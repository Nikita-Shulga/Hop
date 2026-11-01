# Changelog

## Managed relay preparation
- Owner-approved browser/computer relay admission, expiring credentials and bounded issuance;
  no anonymous funded TURN endpoint. Relay remains disabled until account provisioning is approved.
- Prefer verified TURN TLS/TCP 443 on desktop because aiortc consumes only one TURN URL.
- Keep bundled CA trust for HTTPS, updates and asyncio TURN TLS without weakening verification.

## Unreleased

- Bundle trusted HTTPS certificate roots and use them for the connection server and updater, so
  packaged apps connect without relying on the developer machine's Python certificate paths.
- Add a managed browser entry at hop.nikitashulga.com: connect with the computer ID and password,
  with setup instructions and the existing encrypted session and first-device pairing.
- Isolate managed-service signaling from existing private server rooms, reject cross-origin socket
  requests and rate-limit connection attempts. Private deployments keep their existing access gate.

## 2.1.2

- **Русский язык:** Hop can now be used in Russian. Pick **English** or **Русский** under **Settings → Appearance → Language** in the Hop window (it also covers notifications, update and error messages, and the viewer windows Hop opens) or in a viewer's Settings on any device. English stays the default; the choice applies instantly and is remembered.

## 2.0.2

- Windows keyboard shortcuts now use native virtual keys, so Ctrl+A/C/V and other shortcuts work when the host keyboard layout is not English. Ordinary Unicode typing is preserved.
- Windows updates now replace the executable and runtime together and restore the previous version if replacement fails. Unrelated files are preserved, incomplete downloads are rejected, and recovery files are retained if rollback fails.
- Changing **Allow control** updates already-connected viewers immediately, including when control is turned back on.
- Internet file transfers reject incomplete or oversized payloads, and transfers stop when control is revoked. Additional Windows reserved filenames are handled safely on both platforms.
- Desktop notifications are now implemented on Windows as well as macOS.
- Added cross-platform HTTP, WebSocket, WebRTC, file-transfer and updater regression tests. Release builds check viewer parity and Windows screen capture.
- Windows CI uses the configured Python interpreter consistently.

## 2.0.1

- Direct **Download** buttons for Windows and Mac on the GitHub page.
- A clearer "How it works" picture.
- More reliable automatic builds: every release is started, signed in to and updated once on Windows and Mac before it's published.

## 2.0.0 — Hop

- **New name and icon:** Local View is now **Hop**. Settings, pairings and the shared folder carry over automatically.
- **One-click updates:** Hop checks GitHub and updates itself (Settings → About, or the banner when a new version is out).
- **Nearby devices:** other Apple devices on your Wi-Fi are listed separately and can be hidden.
- **Stable Mac signature:** updates keep their Screen Recording and Accessibility permissions.
- New GitHub page, guide and screenshots.

## 1.5.0 — first public release (as Local View)

- See and control your Mac or PC from any browser, on Wi-Fi or over the internet (WebRTC, end to end encrypted).
- Private connection server on Cloudflare; device pairing with a code; strong passwords; lockouts.
- Second screen, clipboard, files, gestures, iPhone Home Screen app, Windows and Mac apps.
