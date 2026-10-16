# Local View

**See and control your Mac or PC from any browser: at home on your Wi-Fi, or from anywhere over the internet.** Your iPhone, iPad, another laptop: open `mac.local` and enter the PIN, or open your Local View address and enter the computer's ID and password. No app to install on the phone.

<p>
  <b><a href="https://github.com/Nikita-Shulga/LocalView/releases/latest">Download</a></b> ·
  <a href="#install">Install</a> ·
  <a href="#connect">Connect</a> ·
  <a href="#internet-access">Internet access</a> ·
  <a href="#second-screen">Second screen</a> ·
  <a href="#controls">Controls</a> ·
  <a href="#troubleshooting">Troubleshooting</a> ·
  <a href="PROTOCOL.md">Protocol</a>
</p>

---

## Quick start

1. **Install** Local View on each computer you want to reach ([download](https://github.com/Nikita-Shulga/LocalView/releases/latest)), and open it. On a Mac, click the two **Allow** buttons it shows.
2. **At home:** on your phone or another computer, scan the QR code in the Local View window (or open the address it shows) and enter the PIN.
3. **From anywhere** (optional): switch on **Internet access** in the window and follow its two steps. Then tap **Phone** and scan that QR code once. Your other computers on the same Wi-Fi offer to use the same server automatically.

That's it. Everything below is detail.

## Features

|  |  |
| --- | --- |
| 🖥️ **View and control** | Live screen with mouse, keyboard and scrolling. Ctrl and Cmd are swapped for you between Mac and PC. |
| 📱 **Made for the iPhone too** | Trackpad or touch mode, zoom, a keyboard with Esc, Tab, arrows and modifiers, and a **Shortcuts** menu (copy, paste, switch apps, screenshot…). Add it to the Home Screen and it opens full screen like an app. |
| 🔗 **Easy addresses** | Every computer gets a short name: `mac.local`, `pc.local`. Type it in any browser on the same Wi-Fi. |
| 🧭 **Hop between computers** | Local View finds your other computers on the network. Use the same PIN on all of them and switch with one tap. |
| 🌍 **From anywhere** | Turn on **Internet access** and connect with an ID and password, like TeamViewer: real video (WebRTC) that is smooth on mobile data, with control, clipboard and files, all encrypted end to end. Runs on a free connection server you own. |
| 🖥️➕ **Second screen** | Turn another computer or an iPad into an extra display for your Mac: windows drag across to it like a real monitor. |
| 🪟 **Window, full screen or browser** | Open other computers in a Local View window, full screen, or a browser tab — your choice in Settings. |
| 🖼️ **Multiple monitors** | Pick which screen to watch; quality, resolution and frame rate adjust to your Wi-Fi. |
| 📋 **Clipboard** | Send text from your phone to the computer's clipboard, and get the computer's clipboard on your phone. |
| 📁 **Files** | Upload from your phone into `~/Downloads/Local View` on the computer, and download anything you put there. |
| 🙋 **You stay in charge** | PIN on every connection, optional **Ask before someone connects**, view-only mode, one-click **Pause sharing**, and a list of who's connected with **Disconnect**. |
| ☕ **Stays out of the way** | Optional **Start at login**, and **Keep awake** so the computer doesn't sleep while someone is viewing. |
| 🔒 **Private** | At home, everything stays on your network. Over the internet, devices connect directly to each other, encrypted; the connection server only introduces them and never sees your screen, input, files or password. No telemetry. |

## Install

Get the zip for your computer from the **[latest release](https://github.com/Nikita-Shulga/LocalView/releases/latest)**. Install Local View on every computer you want to reach. The phone or tablet you control it from needs nothing but a browser.

| System | Package |
| --- | --- |
| macOS 11+ (Apple silicon) | `LocalView-<version>-mac-arm64.zip` |
| macOS 11+ (Intel) | `LocalView-<version>-mac-x64.zip` |
| Windows 10 / 11 | `LocalView-<version>-win-x64.zip` |

### Mac

1. Open the zip and drag **Local View** to **Applications**.
2. The first time, **right-click Local View > Open**, then **Open** again. (The app isn't notarized by Apple yet. If there's no Open button, go to **System Settings > Privacy & Security** and click **Open Anyway**.)
3. Allow **Local Network** access when macOS asks. Local View uses it to find your other computers and to answer `mac.local`.
4. Local View shows **Finish setting up** with two steps: click **Allow** for screen access and for control, turn on **Local View** in the window macOS opens, then click **Restart** in Local View. Done.

### Windows

1. Extract the **whole** zip somewhere permanent, for example `C:\Apps\LocalView`. Keep `LocalView.exe` in its folder: it needs the files next to it.
2. Run **LocalView.exe**. If SmartScreen says *Windows protected your PC*, click **More info > Run anyway** (the app isn't code-signed yet).
3. When Windows Firewall asks, allow access on **Private networks**.

Nothing else needs installing. The window uses the Edge WebView2 runtime built into Windows 10 and 11.

## Connect

The Local View window shows this computer's address, a QR code and a 6-digit PIN. On your phone or another computer on the **same Wi-Fi**, do one of these:

- **Type the address** in any browser: `mac.local` for a Mac, `pc.local` for a PC (the window shows the exact one, e.g. `studio.local` if you renamed it).
  On iPhone, if Safari searches instead of opening it, type it with a slash at the end: `mac.local/`
- **Scan the QR code** with the iPhone camera.
- **From another computer running Local View:** click **Connect** next to it under **Other computers**. It opens in its own window and signs in with your PIN.

Then enter the PIN.

> [!TIP]
> **Use the same PIN on every computer** (**Set PIN…** in the window). Then the device list in the viewer lets you jump between them without typing a PIN again.

### Make it an iPhone app

In Safari, open the address, tap **Share > Add to Home Screen**. Local View then opens full screen from its own icon, like a native app.

## Internet access

Reach your computers from anywhere: mobile data, another city, a friend's Wi-Fi.

**One-time setup (free, about 3 minutes):** switch on **Internet access** in the Local View window. It shows two steps:

1. **Create your free server.** Opens Cloudflare: sign in or sign up (free) and press **Deploy**. ([details](cloud/README.md))
2. **Paste its address** (like `localview.yourname.workers.dev`) and click **Connect**.

Your other computers on the same Wi-Fi then show **"… already has a server — Use it"**: one click each. Local View doesn't come with a server built in; everyone has their own, so nobody else is involved in your connections. The window then shows:

- **ID**: 9 digits, e.g. `482 913 557`. It stays the same.
- **Password**: generated for you. Change it with **Set password…**, or **New password** to lock out anyone who had the old one.
- **Copy link**: a link that opens the viewer with the ID filled in.

**Your server is private.** It only answers at your private address (the server address plus a secret key, like `localview.yourname.workers.dev/k/x8f2…`); anyone else who opens it sees "Not found". Local View creates the key the first time you switch on Internet access, your other computers get it with **Use it**, and your phone gets it from the **Phone** QR code. Computer to computer, the interface comes from Local View itself: the website is only used, invisibly, to introduce the two computers.

**To connect from anywhere:** open your server address in any browser, enter the **ID** and **password**, and press **Connect**. **The first time**, the device shows a 6-digit code: type it into Local View on the computer (do this at home before you travel). After that, the device connects with just the ID and password. The viewer remembers your computers (and passwords, if you leave **Remember on this device** on), so next time it's one tap. Add the page to your iPhone's Home Screen for an app-like icon. From another computer running Local View: **Other computers > Over the internet…**, then type the ID.

Everything works over the internet: control, gestures, zoom, shortcuts, clipboard, multiple monitors and **files**. The video adapts to your connection.

> [!NOTE]
> Most connections go straight between your devices. On some strict networks (some offices, hotels, mobile carriers) that isn't possible, and you'll see *"Couldn't reach that computer directly."* You can add an optional relay; see [cloud/README.md](cloud/README.md#optional-relay-for-hard-networks).

## Your devices

The Local View window lists your devices on the same Wi-Fi:

- **Computers running Local View**: **Connect** or **Second screen** in one click.
- **Your iPhone or iPad** (when it's awake, or once it has connected before): **Send link** AirDrops a link that opens this computer on it, already signed in; **Control** opens Apple's iPhone Mirroring to control the iPhone from your Mac (macOS 15+).
- **A Mac without Local View** shows up with a reminder to install it.

## Second screen

Use a second computer (or an iPad) as an extra monitor:

- **From the device that should become the screen:** in Local View, under **Other computers**, click **Second screen** next to the computer you want to extend. Over the internet: **Over the internet…**, type the ID, then **Second screen**.
- **From any viewer** (browser or app window): click the two-screens button in the toolbar, or **Settings > Mode > Second screen**.

The other computer gains a new display the size of your screen, to the right of its main one. Its own mouse and keyboard move across to it like a real monitor, and you can drag windows onto it. Click the button again (or disconnect) and the display goes away.

| Computer being extended | What you need |
| --- | --- |
| **Mac** (macOS 11+) | Nothing: Local View creates the display itself. |
| **Windows PC** | Windows can only add displays through a display driver. Install a virtual display driver (for example the free [Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver)) or plug in an HDMI dummy plug, then pick that display in the viewer's **Settings > Display**. |

Second screens open full screen when started from the Local View window. In a browser, click ⛶ in the toolbar (browsers only allow full screen after a click).

## The Local View window

- **Sharing / In use / Paused** at the top, with this computer's name and address.
- **Connect a device**: QR code, address (click to copy), PIN (Show / Hide, New PIN, Set PIN…).
- **Connected**: who is viewing (device, IP, for how long), with **Disconnect**.
- **Other computers** on your network, with **Connect**.
- **Files**: open the shared folder, or **Send a file…** to offer a file to your devices.
- **Pause sharing** (or press <kbd>Enter</kbd>): turns away new connections and disconnects everyone until you resume.
- **Settings**: Appearance, **Allow control** (off = view-only), **Ask before someone connects**, short name, **Start at login**, **Keep awake**, notifications and permissions (Mac).

Closing the window stops sharing.

## Controls

| Where | Do this | Result |
| --- | --- | --- |
| Computer browser | Mouse, keyboard, wheel | Sent straight to the host |
| | Trackpad pinch, or Ctrl + scroll wheel | Zoom the view at the pointer (1× to 5×); hold the pointer near an edge to glide the zoomed view |
| iPhone, **trackpad** mode | Drag one finger | Move the cursor (the zoomed view follows it) |
| | Tap | Click |
| | Double-tap | Double-click |
| | Tap, then press and drag | Drag |
| | Long-press | Right-click |
| iPhone, **touch** mode | Tap | Click right there |
| | Long-press | Right-click |
| | Drag | Drag |
| iPhone, both modes | Pinch | Zoom the view around your fingers (1× to 5×); move your fingers while pinching to pan |
| | Two-finger drag | Scroll (keeps gliding after you let go, like on iPhone) |
| | Two-finger tap | Right-click |
| | Two-finger double-tap | Zoom in there / back to fit |
| | Three-finger tap | Show or hide the keyboard |
| | Rotate the phone | The picture re-fits; the zoomed spot stays in view |
| | One-finger drag (view only) | Pan the zoomed view |
| | Toolbar **− / 1× / +** | Zoom out, back to fit, zoom in |
| Anywhere | **Keyboard** button | On-screen keyboard plus a row with Esc, Tab, arrows and modifiers |
| | **Shortcuts** | Common key combos for the host's OS (copy, paste, undo, switch apps…) |
| | **Clipboard** | Send text to the host, or copy the host's clipboard |
| | **Files** | Upload to / download from `~/Downloads/Local View` on the host |
| | **Settings** | Monitor, quality, resolution, frame rate; lower them for smoother video on weak Wi-Fi |

## Controlling the iPhone

iOS doesn't allow any third-party app to be remote-controlled. The workaround: on a Mac with macOS 15 Sequoia or later, open the **iPhone Mirroring** app (iPhone on iOS 18, same Apple Account, Mac with Apple silicon or a T2 chip). Control that Mac through Local View, and you control the iPhone through the mirroring window.

For viewing only, AirPlay screen mirroring to the Mac (**Control Center > Screen Mirroring**) also shows up in Local View.

## Security

- Every connection needs the PIN. After 5 wrong tries a device is locked out for 60 seconds.
- Optional **Ask before someone connects**: after the right PIN, the device waits until you click **Allow** on the computer.
- **Allow control** off makes every viewer view-only.
- The Local View window and its settings (which show the PIN) only answer the computer itself, never the network.
- On Wi-Fi, traffic is plain HTTP on your local network, not encrypted. Use it on networks you trust, like your home Wi-Fi.
- **New devices must be confirmed on the computer.** The first time a device connects over the internet, it shows a 6-digit code that has to be typed into Local View on the computer (the computer never displays it). After that the device only needs the ID and password. See and remove them under **Settings > Trusted devices**. So pair your phone while you're at home.
- **Strong passwords:** at least 8 characters, not only digits. If someone tries many wrong passwords from different addresses, internet sign-ins pause for 5 minutes and you get a notification.
- **Internet access** is off until you turn it on. Over the internet, video, input, clipboard and files are encrypted end to end (WebRTC, DTLS-SRTP). The password is checked by your computer itself; the connection server never sees it. 5 wrong passwords lock that address out for 60 seconds.
- Never port-forward Local View on your router. Use **Internet access** instead. Quit it, or **Pause sharing**, when you don't need it.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `mac.local` / `pc.local` doesn't open | Use the IP address shown in the Local View window (e.g. `http://192.168.1.20:8765`). Some networks and older Android phones don't resolve `.local` names. On iPhone, add the slash: `mac.local/`. |
| The address has `:8765` in it | Another app is using port 80, so Local View uses its own port. Type the address exactly as shown, including `:8765`. |
| The phone can't reach the computer at all | Same Wi-Fi network (not a guest network)? Some routers have **AP / client isolation** or a guest mode that blocks devices from seeing each other; turn it off or use the main network. |
| Windows: nothing connects | Windows Firewall: allow **LocalView** on **Private networks** (Windows Security > Firewall & network protection > Allow an app through firewall), and make sure your Wi-Fi is set to **Private**, not Public. |
| Black screen or only the wallpaper (Mac) | **Screen Recording** permission is missing. Turn on Local View in Privacy & Security, then quit and reopen it. |
| Clicks and typing do nothing | Mac: **Accessibility** permission is missing. Everywhere: check **Allow control** is on in the window's Settings. |
| Permissions were on, but stopped working after an update (Mac) | Remove Local View from Screen Recording and Accessibility (the **−** button), add it again, then reopen the app. |
| Can't click admin / UAC prompts (Windows) | Windows protects those from other apps. Right-click LocalView.exe > **Run as administrator** to control them. |
| "Sharing is paused on this computer" | Click **Resume sharing** in the Local View window. |
| Choppy video | Lower the resolution, quality or frame rate in the viewer's Settings, or move closer to the router. |
| "That computer is offline" | On that computer, Local View must be running with **Internet access** on, and its status must show **Online**. Turn on **Start at login** so it's always reachable. |
| "Couldn't reach that computer directly" | One of the networks blocks direct connections. Try another network (e.g. mobile data), or add the relay ([cloud/README.md](cloud/README.md#optional-relay-for-hard-networks)). |
| "Can't add a display by itself" (Windows) | See [Second screen](#second-screen): install a virtual display driver or use an HDMI dummy plug, then choose that display under **Display**. |
| Internet access says "Can't connect" | Check the computer's internet connection and the server address in **Settings > Internet access**. |

## Command-line options

The app accepts these options (on a Mac: `"/Applications/Local View.app/Contents/MacOS/Local View" --pin 123456`; on Windows: `LocalView.exe --pin 123456`; from source: `python host.py …`):

| Option | What it does |
| --- | --- |
| `--port 8765` | Main port (default 8765) |
| `--pin 123456` | Set the 6-digit PIN (saved for next time) |
| `--name "Studio Mac"` | Display name (default: the computer's name) |
| `--short studio` | Short address name, giving `studio.local` (default `mac` / `pc`; saved) |
| `--headless` | No window: print the address, PIN and a QR code in the terminal |
| `--background` | Start with the window minimized (used by Start at login) |
| `--no-easy-port` | Don't try port 80; addresses always include `:8765` |
| `--debug` | Verbose log |

Settings live in `~/.localview.json`.

## Run from source

Needs Python 3.10 or newer (3.12 from python.org recommended). The internet video library has no builds for Python 3.9, the version macOS's command-line tools include.

- **Mac:** double-click `start-mac.command` (first time: right-click > Open), or run `./start-mac.command` in Terminal. Grant Screen Recording and Accessibility to **Terminal** instead of Local View, then restart Terminal.
- **Windows:** install Python from [python.org](https://www.python.org/downloads/) with "Add python.exe to PATH" ticked, then double-click `start-windows.bat`.

The launchers create a `.venv`, install `requirements.txt` on first run and pass any options through (for example `./start-mac.command --pin 123456`).

## Build the apps

- **Mac:** `packaging/build-mac.sh` builds `dist/Local View.app` and `dist/LocalView-<version>-mac-<arch>.zip` for the Mac's architecture (PyInstaller, ad hoc signed).
- **Windows:** `packaging\build-windows.bat` builds `dist\LocalView\LocalView.exe` and `dist\LocalView-<version>-win-x64.zip`.
- **GitHub Actions:** `.github/workflows/build.yml` builds all three zips on demand. Pushing a tag like `v1.2.0` (matching `packaging/VERSION`) publishes a GitHub Release with the zips and `SHA256SUMS.txt`.

The version lives in `packaging/VERSION`.

## License

[MIT](LICENSE) © 2026 Nikita Shulga
