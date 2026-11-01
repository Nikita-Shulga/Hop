Hop 2.1.4 — Internet relay compatibility:

- Updated hosts bind relay requests to the connecting browser's approved session and support verified TLS on port 443 for restrictive networks.
- Packaged clients include trusted CA roots for HTTPS, updates and relay TLS. Existing passwords, paired devices and settings remain in place.
- Duplicate offers and concurrent negotiations respect the host's connection limit. The browser waits for complete network-route gathering and reports relay failures.
- The managed service still requires owner-approved browser enrollment, the computer password and first-device pairing. The computer must stay powered on, online and awake.
- Same-network protocol tests do not establish overseas reachability. Live cross-network relay validation remains pending; these are candidate packages, not a claim of a completed phone-to-PC test.

Hop in Russian:

- Pick **English** or **Русский** under **Settings → Appearance → Language** in the Hop window, or in a viewer's Settings on any device. The switch applies instantly and is remembered.
- The Hop window, its notifications, update and error messages, and the viewer windows Hop opens all follow the language you choose.
- English stays the default for new and existing installs; Hop never picks the language from the system.
- Hosts and viewers on different versions or languages still work together.

Windows and macOS use the same host, viewer and protocol code. Windows still requires a virtual display driver or HDMI dummy plug to create an additional host display; Mac hosts can create a virtual display directly. See the [validation checklist](https://github.com/Nikita-Shulga/Hop/blob/main/docs/VALIDATION.md) for automated coverage and checks that require physical devices or separate networks.
