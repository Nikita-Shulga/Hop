# Contributing to Hop

Thanks for wanting to help! Bug reports, ideas, docs fixes and code are all welcome.

## Ways to help

- **Report a bug.** Use the [bug report form](https://github.com/Nikita-Shulga/Hop/issues/new?template=bug_report.yml). Say which computer you were sharing, which device you used to connect, and whether it was on Wi-Fi or over the internet.
- **Test on your setup.** Intel Macs, multi-monitor PCs, tablets, older phones, unusual networks — tell us what worked and what didn't.
- **Improve the guide.** If something in [docs/GUIDE.md](docs/GUIDE.md) confused you, a small fix helps the next person.
- **Write code.** For anything bigger than a small fix, open an issue first so we can agree on the approach.

## Getting set up

You need Python 3.10 or newer (and Node.js only if you work on the internet server in `cloud/`).

```sh
git clone https://github.com/Nikita-Shulga/Hop.git
cd Hop
./start-mac.command                     # run from source on a Mac (start-windows.bat on Windows)
pip install -r requirements-test.txt
python -m pytest tests                  # tests
```

## Where things live

| Path | What it is |
| --- | --- |
| `host.py` | The app on the computer being shared: screen capture, input, discovery, the local web server |
| `remote.py` | Internet access: pairing, sign-in and the WebRTC session |
| `updater.py` | One-click updates |
| `static/` | The viewer (`index.html`) and the host window (`host.html`) |
| `cloud/` | The optional internet server (Cloudflare Workers) |
| `packaging/` | Builds for macOS and Windows, icons, screenshots, smoke test |
| `tests/` | `pytest` suites |
| `PROTOCOL.md` | The contract between the host, the viewer and the server — update it with any protocol change |

## Ground rules

**Nothing without consent.** Hop only shares a screen the person sitting at that computer turned on, behind a PIN or password (and an approval prompt, if they switched it on). Never add a way around any of them.

**Encrypted over the internet.** Internet sessions are end-to-end encrypted between the two devices; the server only introduces them. Keep it that way.

**Privacy.** No telemetry. Screenshots in the repository must use sample data (`packaging/make_screenshots.py`). Don't attach real computer IDs, passwords or addresses to issues.

**Testing.** Add a test for every behaviour you change, and say what you actually ran: tests, a real Mac, a real PC, a real phone.

## Pull requests

- Keep each PR focused on one change, and describe how you checked it. The PR template has a short checklist.
- Update `CHANGELOG.md` for anything users will notice.
- Be patient: this project is maintained in spare time.

By contributing you agree that your work is released under the [MIT License](LICENSE), and that you'll follow the [Code of Conduct](CODE_OF_CONDUCT.md).
