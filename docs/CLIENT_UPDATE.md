# Hop 2.1.4 candidate update

The managed Worker requires an active admitted viewer `sid` on host relay requests. Installed
2.1.3 does not send it and correctly receives STUN only. A new browser can relay its own leg, but
both-leg TLS/443 support requires the updated host. Do not treat a Mac update as a Windows PC update.

## Verified device context

- The connected Mac's installed bundle is **2.1.3**, bundle ID `com.nikitashulga.hop`.
- Existing Hop discovery identifies **NikitaPC** as **Windows**. Its public info endpoint was
  unreachable, so its installed version and whether it is the phone's intended host remain unverified.
- The existing pending phone browser-code question identifies the intended computer. Do not request
  passwords or repeat that question, and do not enroll devices before the independent security verdict.

## Candidate packages

Existing manual CI run: https://github.com/Nikita-Shulga/Hop/actions/runs/41311351997

Build source: `abab8aa88d92562dff004816cf03b783fefa9a5a` (2.1.4 version plus reviewed host changes).
The later viewer-capacity Worker changes do not alter any native build input: `host.py`, `remote.py`,
`updater.py`, `hop_tls.py`, `i18n.py`, `static/`, requirements and packaging scripts are unchanged.

The workflow builds Windows x64, Apple-silicon Mac and Intel Mac independently. Each must pass
regressions, package smoke tests and an in-place update rehearsal. A manual run does not publish
a release. Check the run's current result before using artifacts; physical-device/cross-network
testing is still required. Windows CI requires generated-screen video; Mac CI does not certify
the user's Screen Recording permissions or hardware capture.

The downloaded Apple-silicon candidate is 2.1.4 with the same bundle ID and certificate-leaf
requirement as the installed Mac: `359154d9af353d6c34d654283cdc9281409e8aab`. Both installed and
candidate apps use the existing self-signed identity; ordinary local codesign verification reports
an untrusted chain for both. No certificate trust or OS permission setting was changed. CI's
signature verification passed in its build keychain. Do not replace this with ad-hoc signing.

All packages must include `certifi/cacert.pem` and `static/ice-gather.js`. Package bytes are hashed
into `SHA256SUMS.txt` and compared with the final GitHub release assets before installing.

## Authorized update path

1. After the security verdict and successful packaging jobs, prepare/publish **v2.1.4** with
   `Hop-2.1.4-win-x64.zip`, `Hop-2.1.4-mac-arm64.zip`, `Hop-2.1.4-mac-x64.zip`, and `SHA256SUMS.txt`.
   Keep the release draft until its checks and source/asset provenance are complete. A draft is
   not returned by GitHub's `/releases/latest` endpoint and does not update other users.
2. On the actual intended host, use Hop **Settings → About → Updates → Check now → Update now**.
   The updater chooses its platform's versioned ZIP and verifies it against `SHA256SUMS.txt`.
   If an older host's updater cannot download, transfer its verified platform ZIP and use the
   existing executable's `--update-from <zip>` path; first verify that installed version supports it.
3. Update in place. Preserve the existing Mac app path, bundle ID and signing requirement. Keep
   `~/.hop.json` (Mac) or `%USERPROFILE%\.hop.json` (Windows) and shared files in place; do not reset
   computer ID/password, host secret, paired browsers, Internet activation or approved permissions.
4. Recheck the installed version, Internet Online state and existing permissions on that actual host.
   Then, after approved browser enrollment, refresh the phone page and test it on a separate network.
   Verify the selected relay route and video/control; same-host synthetic peers are insufficient.

No candidate was installed on the user's devices during preparation. Existing approved Mac
activation remains in place. No live relay credentials were issued as part of packaging.
