# Hop guide

Everything in detail. For the overview, see the [README](../README.md).

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
| | **Files** | Upload to / download from `~/Downloads/Hop` on the host |
| | **Settings** | Monitor, quality, resolution, frame rate; lower them for smoother video on weak Wi-Fi. Also theme and language (English / Русский) |

## Your devices

The Hop window lists your devices on the same Wi-Fi:

- **Computers running Hop**: **Connect** or **Second screen** in one click.
- **Your iPhone or iPad** (when it's awake, or once it has connected before): **Send link** AirDrops a link that opens this computer on it, already signed in; **Control** opens Apple's iPhone Mirroring to control the iPhone from your Mac (macOS 15+).
- **A Mac without Hop** shows up with a reminder to install it.

## Second screen

Use a second computer (or an iPad) as an extra monitor:

- **From the device that should become the screen:** in Hop, under **Other computers**, click **Second screen** next to the computer you want to extend. Over the internet: **Over the internet…**, type the ID, then **Second screen**.
- **From any viewer** (browser or app window): click the two-screens button in the toolbar, or **Settings > Mode > Second screen**.

The other computer gains a new display the size of your screen, to the right of its main one. Its own mouse and keyboard move across to it like a real monitor, and you can drag windows onto it. Click the button again (or disconnect) and the display goes away.

| Computer being extended | What you need |
| --- | --- |
| **Mac** (macOS 11+) | Nothing: Hop creates the display itself. |
| **Windows PC** | Windows can only add displays through a display driver. Install a virtual display driver (for example the free [Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver)) or plug in an HDMI dummy plug, then pick that display in the viewer's **Settings > Display**. |

Second screens open full screen when started from the Hop window. In a browser, click ⛶ in the toolbar (browsers only allow full screen after a click).

## Controlling the iPhone

iOS doesn't allow any third-party app to be remote-controlled. The workaround: on a Mac with macOS 15 Sequoia or later, open the **iPhone Mirroring** app (iPhone on iOS 18, same Apple Account, Mac with Apple silicon or a T2 chip). Control that Mac through Hop, and you control the iPhone through the mirroring window.

For viewing only, AirPlay screen mirroring to the Mac (**Control Center > Screen Mirroring**) also shows up in Hop.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `mac.local` / `pc.local` doesn't open | Use the IP address shown in the Hop window (e.g. `http://192.168.1.20:8765`). Some networks and older Android phones don't resolve `.local` names. On iPhone, add the slash: `mac.local/`. |
| The address has `:8765` in it | Another app is using port 80, so Hop uses its own port. Type the address exactly as shown, including `:8765`. |
| The phone can't reach the computer at all | Same Wi-Fi network (not a guest network)? Some routers have **AP / client isolation** or a guest mode that blocks devices from seeing each other; turn it off or use the main network. |
| Windows: nothing connects | Windows Firewall: allow **Hop** on **Private networks** (Windows Security > Firewall & network protection > Allow an app through firewall), and make sure your Wi-Fi is set to **Private**, not Public. |
| Black screen or only the wallpaper (Mac) | **Screen Recording** permission is missing. Turn on Hop in Privacy & Security, then quit and reopen it. |
| Clicks and typing do nothing | Mac: **Accessibility** permission is missing. Everywhere: check **Allow control** is on in the window's Settings. |
| Permissions were on, but stopped working after an update (Mac) | Remove Hop from Screen Recording and Accessibility (the **−** button), add it again, then reopen the app. |
| Can't click admin / UAC prompts (Windows) | Windows protects those from other apps. Right-click Hop.exe > **Run as administrator** to control them. |
| "Sharing is paused on this computer" | Click **Resume sharing** in the Hop window. |
| Choppy video | Lower the resolution, quality or frame rate in the viewer's Settings, or move closer to the router. |
| "That computer is offline" | On that computer, Hop must be running with **Internet access** on, and its status must show **Online**. Turn on **Start at login** so it's always reachable. |
| "Couldn't reach that computer directly" | One of the networks blocks direct connections. Try another network (e.g. mobile data), or add the relay ([cloud/README.md](../cloud/README.md#optional-relay-for-hard-networks)). |
| "Can't add a display by itself" (Windows) | See [Second screen](#second-screen): install a virtual display driver or use an HDMI dummy plug, then choose that display under **Display**. |
| Internet access says "Can't connect" | Check the computer's internet connection and the server address in **Settings > Internet access**. |

## Command-line options

The app accepts these options (on a Mac: `"/Applications/Hop.app/Contents/MacOS/Hop" --pin 123456`; on Windows: `Hop.exe --pin 123456`; from source: `python host.py …`):

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

Settings live in `~/.hop.json`.
