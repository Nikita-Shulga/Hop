# Security policy

Hop lets other devices see and control a computer, so security reports matter more than anything else.

## Supported versions

Only the [latest release](https://github.com/Nikita-Shulga/Hop/releases/latest) gets fixes.

## Reporting a vulnerability

Please report it **privately**:

- through GitHub: **[Security → Report a vulnerability](https://github.com/Nikita-Shulga/Hop/security/advisories/new)**, or
- through the contact details at [nikitashulga.com](https://nikitashulga.com).

Don't open a public issue. Please include:

- what an attacker could do, and what they'd need first (same Wi-Fi, a known computer ID, a paired device…);
- steps to reproduce, and the Hop version and OS on both ends;
- whether it's already public anywhere.

You'll get an acknowledgement within a week. Once a fix is released, you'll be credited in the changelog if you'd like.

## Things that are in scope

- Anything that lets someone see or control a computer without the PIN, the password or the approval on that computer.
- Pairing, sign-in and session tokens, on Wi-Fi and over the internet.
- The internet server in `cloud/` and the WebRTC session it sets up.
- The local web server and the host window's loopback API.
- Clipboard and file transfer, and one-click updates.
