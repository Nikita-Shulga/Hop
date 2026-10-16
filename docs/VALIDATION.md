# Validation

Run the shared regression suite with the same environment used to build Hop:

```sh
python -m pip install -r requirements.txt -r requirements-test.txt
python -m pytest tests -q
node packaging/check-js.mjs
```

The suite covers live local HTTP/WebSocket authorization and session lifecycle, input dispatch,
control changes, shared-file boundaries, duplicate and Unicode filenames, interrupted and malformed
internet transfers, and actual loopback WebRTC video and data-channel delivery. Capture and input
devices are mocked in the HTTP tests; WebRTC uses a generated frame. These tests do not replace
physical input or screen-capture checks.

Windows additionally runs the real PowerShell updater with temporary executable stubs, exercising
successful replacement and recovery from a locked executable. Personal files in the application
folder must survive both cases, and incomplete downloads must be rejected.

For a packaged app, start it with an isolated profile and test PIN, then run:

```sh
python packaging/smoke_test.py 8799 123456 --require-video
```

The default smoke check can run without capture permissions, but prints VIDEO NOT VERIFIED when it
receives no frame. Windows release CI requires video. macOS CI still needs a real-user Screen
Recording permission check before its capture behavior can be called hardware-validated.

Release CI builds Windows x64, Apple silicon and Intel Mac from the same commit, runs the shared
tests, checks LAN/cloud viewer equality, starts each package and rehearses its update before release.

## Physical-device checklist

- Discover and connect in both directions; wrong PIN, approval, disconnect, pause and reconnect.
- Confirm visible changing video; test resolution, FPS, display selection, fit/zoom and fullscreen.
- In a disposable text document, test click, drag, scroll, Unicode text, shortcuts and held-key release.
- Send and retrieve generated clipboard text and files in both directions; compare file hashes.
- Check native window controls, notifications, login startup and sleep prevention.
- Rehearse an update with the actual package and check that settings and identity survive.
- Test internet pairing, revocation and reconnect across different networks, including TURN fallback.
- On macOS, test virtual display creation/removal. Windows needs an installed virtual display driver
  or HDMI dummy plug; Hop does not install a driver. Both platforms can view and control existing displays.

Passing automated tests does not certify the final two items, every Windows version, every keyboard
layout, unusual display hardware, mobile gestures, or administrative/UAC screens.
