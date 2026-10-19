#!/usr/bin/env python3
"""Hop host: LAN-only remote desktop server.

Serves the web viewer (static/index.html) and a WebSocket at /ws that streams
JPEG frames of the selected monitor and injects mouse/keyboard input.
By default it also opens a small app window (static/host.html in pywebview) that
shows the address, QR code, PIN and connected viewers; --headless keeps the
terminal-only mode. See PROTOCOL.md for the wire contract. Python 3.9+, macOS / Windows.
"""

import os
import sys

# --------------------------------------------------------------------------- early process setup
# Windowed builds (PyInstaller --windowed, pythonw.exe) start with sys.stdout / sys.stderr = None:
# any print(), flush() or logging StreamHandler would then crash. Send both to ~/.hop.log.
LOG_PATH = os.path.join(os.path.expanduser("~"), ".hop.log")
FROZEN = bool(getattr(sys, "frozen", False))


def _open_log_file():
    try:
        if os.path.getsize(LOG_PATH) > 2 * 1024 * 1024:  # keep it small: one rotation
            os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass
    try:
        return open(LOG_PATH, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return open(os.devnull, "w")


NO_CONSOLE = sys.stdout is None or sys.stderr is None
if NO_CONSOLE:
    _log_file = _open_log_file()
    if sys.stdout is None:
        sys.stdout = _log_file
    if sys.stderr is None:
        sys.stderr = _log_file

if sys.platform.startswith("win"):
    # DPI awareness must be set before any window exists so that mss (capture), pynput (input)
    # and pywebview all agree on physical pixels. Per-monitor v2 first (Windows 10 1703+),
    # then per-monitor v1 (8.1), then system-aware (Vista). mss and pywebview try again later;
    # those calls fail harmlessly once the awareness is set.
    try:
        import ctypes
        _u32 = ctypes.windll.user32
        _ok = False
        try:
            _u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            _u32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
            _ok = bool(_u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
        except Exception:
            _ok = False
        if not _ok:
            try:
                _ok = ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0
            except Exception:
                _ok = False
        if not _ok:
            _u32.SetProcessDPIAware()
    except Exception:
        pass

import argparse  # noqa: E402
import asyncio  # noqa: E402
import base64  # noqa: E402
import hashlib  # noqa: E402
import collections  # noqa: E402
import concurrent.futures  # noqa: E402
import contextlib  # noqa: E402
import functools  # noqa: E402
import hmac  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import unicodedata  # noqa: E402
import uuid  # noqa: E402
from urllib.parse import quote, urlsplit  # noqa: E402

from aiohttp import (ClientSession, ClientTimeout, TCPConnector, ThreadedResolver,  # noqa: E402
                     WSMsgType, web)

import mss  # noqa: E402
from PIL import Image  # noqa: E402
from pynput.keyboard import Controller as KeyboardController, Key, KeyCode  # noqa: E402
from pynput.mouse import Button, Controller as MouseController  # noqa: E402

import i18n  # noqa: E402  (English / Russian; see i18n.py)
from i18n import Text  # noqa: E402
import updater  # noqa: E402  (one-click updates from GitHub Releases)

try:  # Internet access (WebRTC via aiortc). Optional: without it the LAN features all still work.
    import remote  # noqa: E402
    REMOTE_ERROR = ""
except Exception as _remote_exc:  # pragma: no cover
    remote = None
    REMOTE_ERROR = str(_remote_exc)

APP = "hop"
VERSION = os.environ.get("HOP_TEST_VERSION") or "2.0.2"  # HOP_TEST_VERSION: pretend to be older, to test updates
DEFAULT_PORT = 8765
EASY_PORT = 80
DISCOVERY_PORT = 8766
DISCOVERY_INTERVAL = 2.0
PEER_TTL = 10.0
AUTH_TIMEOUT = 10.0
ACK_TIMEOUT = 2.0
MAX_FAILS = 5
LOCKOUT_SECS = 60
APPROVAL_TIMEOUT = 30.0  # "Ask before someone connects": deny after this long
KICK_BLOCK_SECS = 60     # after "Disconnect", refuse that IP's next (auto-)reconnect once
CLIP_MAX = 1 << 20       # clipboard text limit (bytes, UTF-8)
UPLOAD_MAX = 4 << 30     # per uploaded file
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".hop.json")
RES_DIR = getattr(sys, "_MEIPASS", None) if FROZEN else None
RES_DIR = RES_DIR or os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(RES_DIR, "static")
LAUNCH_AGENT_LABEL = "com.hop.host"
WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WIN_RUN_VALUE = "Hop"

# Host-window endpoints (/host, /api/host/*) expose the PIN: loopback only.
LOOPBACK_IPS = frozenset(["127.0.0.1", "::1", "::ffff:127.0.0.1"])
LOOPBACK_HOSTS = frozenset(["127.0.0.1", "localhost", "::1"])
INPUT_TYPES = frozenset(["move", "down", "up", "click", "scroll", "key", "text"])
DEFAULT_SETTINGS = {"allowControl": True, "askBeforeConnect": False, "theme": "system",
                    "notify": True, "keepAwake": True, "openIn": "window", "language": "en"}
OPEN_IN = ("window", "fullscreen", "browser")  # how this app opens other computers' screens
# Messages to viewers are part of the protocol and stay English; viewers translate them (static/i18n.js).
MSG_PAUSED = "Sharing is paused on this computer"
MSG_DECLINED = "Connection declined on the host"
MSG_KICKED = "Disconnected by the host"
MSG_INTERNET_OFF = "Internet access is turned off on that computer"
# Where the project lives; "Create my free server" opens Cloudflare's one-click deploy for its cloud/ folder.
PROJECT_REPO = "https://github.com/Nikita-Shulga/Hop"
DEPLOY_URL = "https://deploy.workers.cloudflare.com/?url=" + PROJECT_REPO + "/tree/main/cloud"
GUIDE_URL = PROJECT_REPO + "/blob/main/cloud/README.md"
CLOUD_PASSWORD_MIN = 8
PAIR_TIMEOUT = 120.0      # a new internet device waits this long for its code to be typed on the host
PAIR_TRIES = 3            # wrong codes typed on the host before the request is declined
NET_FAIL_WINDOW = 600.0   # wrong internet passwords from *any* address within 10 minutes…
NET_FAIL_LIMIT = 20       # …more than this many pauses internet sign-ins…
NET_PAUSE_SECS = 300      # …for 5 minutes
MAX_TRUSTED = 50
MSG_PAIR_DECLINED = "This device wasn't confirmed on the computer"


def password_problem(pw):
    """Why an internet password is too weak, or None."""
    if len(pw) < CLOUD_PASSWORD_MIN:
        return Text("pw.short", n=CLOUD_PASSWORD_MIN)
    if len(pw) > 64:
        return Text("pw.long", n=64)
    if pw.isdigit():
        return Text("pw.digits")
    if len(set(pw.lower())) < 4:
        return Text("pw.variety")
    return None
SHORT_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?$")
PEER_SHORT_RE = re.compile(r"^[a-z0-9-]{1,40}$")  # effective names may carry a -N suffix

if sys.platform == "darwin":
    OS_NAME = "mac"
elif sys.platform.startswith("win"):
    OS_NAME = "windows"
else:
    OS_NAME = "linux"

DEFAULT_SHORT = {"mac": "mac", "windows": "pc"}.get(OS_NAME, "linux")
# Child processes must not flash a console window from a windowed build on Windows.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if OS_NAME == "windows" else 0

# Scroll scaling. pynput's macOS backend (pynput/mouse/_darwin.py, Controller._scroll)
# posts CGEventCreateScrollWheelEvent with kCGScrollEventUnitPixel and multiplies the
# value by _SCROLL_SPEED = 10, i.e. one pynput "unit" = 10 pixels, which is far less
# than a physical mouse-wheel notch (apps typically move ~3 lines / ~40 px per notch).
# On Windows pynput uses WHEEL_DELTA (120) per unit, i.e. one real notch already.
# So on macOS we multiply notches by 4 (=> 40 px per notch).
SCROLL_FACTOR = 4 if OS_NAME == "mac" else 1

try:
    RESAMPLE = Image.Resampling.BILINEAR  # Pillow >= 9.1
except AttributeError:  # pragma: no cover
    RESAMPLE = Image.BILINEAR

log = logging.getLogger(APP)


# --------------------------------------------------------------------------- config

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if isinstance(cfg, dict):
                return cfg
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("Could not read %s: %s", CONFIG_PATH, e)
    return {}


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        if OS_NAME != "windows":
            os.chmod(tmp, 0o600)  # holds the PIN, internet password and host key
        os.replace(tmp, CONFIG_PATH)
    except Exception as e:
        log.warning("Could not write %s: %s", CONFIG_PATH, e)


def default_cloud_url():
    """The connection server this build was set up for (static/cloud.json), or ""."""
    try:
        with open(os.path.join(STATIC_DIR, "cloud.json"), "r", encoding="utf-8") as f:
            return parse_server_address(json.load(f).get("url"))[0] or ""
    except Exception:
        return ""


SITE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def parse_server_address(v):
    """'hop.you.workers.dev/k/KEY…' → ('https://hop.you.workers.dev', 'KEY' or None).

    Returns (None, None) for something that isn't a server address.
    """
    v = str(v or "").strip()
    if not v:
        return None, None
    if not re.match(r"^[a-z]+://", v, re.I):  # typed without http(s)://
        v = ("http://" if re.match(r"^(localhost|127\.0\.0\.1)(:|/|$)", v, re.I) else "https://") + v
    m = re.match(r"^(https?://[^/?#]+)(?:/k/([A-Za-z0-9_-]{16,64}))?", v, re.I)
    if not m:
        return None, None
    origin = valid_cloud_url(m.group(1))
    return (origin, m.group(2)) if origin else (None, None)


def valid_cloud_url(v):
    v = str(v or "").strip().rstrip("/")
    if re.match(r"^https://[A-Za-z0-9.-]+(:\d+)?$", v):
        return v
    if re.match(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$", v):  # local testing (wrangler dev)
        return v
    return None


def valid_short(v):
    return isinstance(v, str) and bool(SHORT_RE.match(v))


def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packets are sent for UDP connect
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127.") and ip != "0.0.0.0":
            return ip
    except Exception:
        pass
    finally:
        s.close()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def get_all_ips():
    ips = [get_lan_ip()]
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def local_ipv4_set():
    """Every IPv4 address of this machine (used to recognise our own mDNS answers)."""
    ips = set(get_all_ips()) | {"127.0.0.1"}
    try:
        import ifaddr  # dependency of zeroconf
        for ad in ifaddr.get_adapters():
            for a in ad.ips:
                if isinstance(a.ip, str):
                    ips.add(a.ip)
    except Exception:
        pass
    return ips


def default_name():
    """Friendly computer name: macOS 'Computer Name' (e.g. "Alex's MacBook Air"), else hostname."""
    if OS_NAME == "mac":
        try:
            out = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True,
                                 text=True, timeout=2)
            name = out.stdout.strip()
            if out.returncode == 0 and name:
                return name[:64]
        except Exception:
            pass
    name = socket.gethostname()
    if name.endswith(".local"):
        name = name[:-6]
    return name


def device_from_ua(ua):
    """Rough device kind from a User-Agent (iPadOS Safari reports itself as a Mac)."""
    ua = ua or ""
    if "iPhone" in ua or "iPod" in ua:
        return "iPhone"
    if "iPad" in ua:
        return "iPad"
    if "Android" in ua:
        return "Android" if "Mobile" in ua else "Android tablet"
    if "CrOS" in ua:
        return "Chromebook"
    if "Windows" in ua:
        return "Windows PC"
    if "Macintosh" in ua or "Mac OS X" in ua:
        return "Mac"
    if "Linux" in ua:
        return "Linux"
    return "Browser"


@functools.lru_cache(maxsize=8)
def qr_svg(text):
    """QR code for `text` as a compact SVG path (fill=currentColor, no quiet zone)."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(text)
        qr.make(fit=True)
        m = qr.get_matrix()
    except Exception as e:
        log.debug("QR generation failed: %s", e)
        return ""
    n = len(m)
    parts = []
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                parts.append("M%d %dh%dv1h-%dz" % (start, y, x - start, x - start))
            else:
                x += 1
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges">'
            '<path fill="currentColor" stroke="none" d="%s"/></svg>' % (n, n, "".join(parts)))


_perm_libs = {}
_perm_cache = {"t": 0.0, "v": None}


def _perm_call(path, fn):
    import ctypes
    lib = _perm_libs.get(path)
    if lib is None:
        lib = ctypes.cdll.LoadLibrary(path)
        _perm_libs[path] = lib
    f = getattr(lib, fn)
    f.restype = ctypes.c_bool
    f.argtypes = []
    return bool(f())


def responsible_app():
    """The app macOS checks permissions for: the bundled app itself, or the launching terminal."""
    if FROZEN:
        return "Hop"
    tp = os.environ.get("TERM_PROGRAM", "")
    names = {"Apple_Terminal": "Terminal", "iTerm.app": "iTerm", "vscode": "Visual Studio Code",
             "WarpTerminal": "Warp", "ghostty": "Ghostty", "WezTerm": "WezTerm"}
    return names.get(tp, tp or "")


def mac_permissions():
    """Screen Recording / Accessibility status on macOS (None = unknown). Cached 2 s."""
    if OS_NAME != "mac":
        return None
    now = time.monotonic()
    if _perm_cache["v"] is not None and now - _perm_cache["t"] < 2.0:
        return _perm_cache["v"]
    v = {"screen": None, "accessibility": None, "app": responsible_app()}
    try:
        v["screen"] = _perm_call(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
            "CGPreflightScreenCaptureAccess")
    except Exception as e:
        log.debug("CGPreflightScreenCaptureAccess unavailable: %s", e)
    try:
        v["accessibility"] = _perm_call(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices",
            "AXIsProcessTrusted")
    except Exception as e:
        log.debug("AXIsProcessTrusted unavailable: %s", e)
    _perm_cache.update(t=now, v=v)
    return v


MAC_PANES = {
    "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
}


def request_mac_permission(which):
    """Show macOS's own permission prompt (first time), then the right Privacy pane."""
    if OS_NAME != "mac":
        return False
    service = {"screen": "ScreenCapture", "accessibility": "Accessibility"}.get(which)
    if service is None:
        return False
    granted = (mac_permissions() or {}).get(which)
    if FROZEN and not granted:
        # An unsigned app is identified by its exact build, so a switch turned on for an earlier
        # Hop stays "on" in System Settings but doesn't apply to this one. Clearing Hop's
        # own entries (and nothing else) makes macOS ask again for the copy that's running.
        bundle_id = "com.nikitashulga.hop"
        try:
            subprocess.run(["/usr/bin/tccutil", "reset", service, bundle_id], timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log.debug("tccutil reset %s failed: %s", service, e)
    try:
        if which == "screen":
            import Quartz
            if not Quartz.CGPreflightScreenCaptureAccess():
                Quartz.CGRequestScreenCaptureAccess()  # system prompt the first time; no-op after
        elif which == "accessibility":
            from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    except Exception as e:
        log.debug("Permission prompt for %s failed: %s", which, e)
    _perm_cache["v"] = None
    # macOS only prompts once per app; afterwards the switch lives in System Settings.
    threading.Timer(0.8, open_mac_pane, args=(which,)).start()
    return True


def relaunch_command():
    """argv that starts this app again (the .app bundle, the .exe, or python host.py …)."""
    if FROZEN and OS_NAME == "mac":
        app = mac_app_bundle()
        if app:
            return ["/usr/bin/open", "-n", app]
    if FROZEN:
        return [sys.executable] + [a for a in sys.argv[1:] if a != "--background"]
    return [sys.executable, os.path.abspath(__file__)] + [a for a in sys.argv[1:] if a != "--background"]


def open_mac_pane(which):
    url = MAC_PANES.get(which)
    if OS_NAME != "mac" or not url:
        return False
    try:
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        log.warning("Could not open System Settings: %s", e)
        return False


def system_notify(text):
    """Best-effort native desktop notification; never blocks the server loop."""
    if OS_NAME == "windows":
        # Windows PowerShell and Windows Forms ship with Windows 10/11. No extra
        # Python/WinRT package or persistent notification registration is needed.
        # Base64 transports the script as UTF-16; quote text as data, never code.
        message = str(text)[:200].replace("'", "''")
        script = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
try {
  $icon.Icon = [System.Drawing.SystemIcons]::Information
  $icon.Text = 'Hop'
  $icon.Visible = $true
  $icon.ShowBalloonTip(5000, 'Hop', '%s', [System.Windows.Forms.ToolTipIcon]::Info)
  $until = [DateTime]::UtcNow.AddSeconds(8)
  while ([DateTime]::UtcNow -lt $until) {
    [System.Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 100
  }
} finally { $icon.Dispose() }
""" % message
        shell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                             r"System32\WindowsPowerShell\v1.0\powershell.exe")
        try:
            subprocess.Popen([shell, "-NoProfile", "-NonInteractive", "-EncodedCommand",
                              base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=NO_WINDOW)
        except Exception as e:
            log.debug("Notification failed: %s", e)
        return
    if OS_NAME != "mac":
        return
    def q(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        subprocess.Popen(["osascript", "-e", "display notification %s with title %s"
                          % (q(text[:200]), q("Hop"))],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log.debug("Notification failed: %s", e)


def fatal_dialog(text):
    """Tell the user about a startup failure when there is no console to read it in."""
    try:
        if OS_NAME == "windows":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "Hop", 0x10)
        elif OS_NAME == "mac":
            esc = text.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", 'display alert "Hop" message "%s" as critical'
                            % esc], timeout=120, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    except Exception:
        pass


# --------------------------------------------------------------------------- shared folder

def downloads_dir():
    if OS_NAME == "windows":
        try:  # the Downloads folder can be relocated (OneDrive, other drive): ask the shell
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
            fid = GUID(0x374DE290, 0x123F, 0x4565,
                       (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            out = ctypes.c_wchar_p()
            fn = ctypes.windll.shell32.SHGetKnownFolderPath
            fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                           ctypes.POINTER(ctypes.c_wchar_p)]
            if fn(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0 and out.value:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                return path
        except Exception as e:
            log.debug("SHGetKnownFolderPath failed: %s", e)
    return os.path.join(os.path.expanduser("~"), "Downloads")


SHARED_DIR = os.path.join(downloads_dir(), "Hop")
WIN_RESERVED = frozenset(["CON", "PRN", "AUX", "NUL"] + ["COM%d" % i for i in range(1, 10)] +
                         ["LPT%d" % i for i in range(1, 10)] +
                         [p + n for p in ("COM", "LPT") for n in "¹²³"])


def display_path(p):
    home = os.path.expanduser("~")
    if OS_NAME != "windows" and (p == home or p.startswith(home + os.sep)):
        return "~" + p[len(home):]
    return p


def ensure_shared_dir():
    os.makedirs(SHARED_DIR, exist_ok=True)
    return SHARED_DIR


def safe_filename(raw):
    """A file name that is safe on macOS and Windows (no path parts, no reserved names)."""
    # Browsers escape '"' in multipart file names as %22 (and CR/LF as %0D/%0A).
    name = unicodedata.normalize("NFC", str(raw or "").replace("%22", '"'))
    name = re.split(r"[\\/]", name)[-1]
    name = "".join("_" if (c < " " or c in '<>:"|?*\x7f') else c for c in name)
    name = name.strip().strip(".").strip()
    if not name:
        name = "file"
    stem, ext = os.path.splitext(name)
    if stem.split(".")[0].rstrip(" .").upper() in WIN_RESERVED:
        stem = "_" + stem
    while len((stem + ext).encode("utf-8")) > 200 and stem:
        stem = stem[:-1]
    if len(ext.encode("utf-8")) > 40:
        ext = ""
    return (stem or "file") + ext


def reserve_name(folder, name):
    """Create an empty `name` (or `name (1).ext`, …) in folder atomically; return the path."""
    stem, ext = os.path.splitext(name)
    for i in range(0, 10000):
        cand = name if i == 0 else "%s (%d)%s" % (stem, i, ext)
        path = os.path.join(folder, cand)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        os.close(fd)
        return path
    raise OSError("Too many files named %s" % name)


def _is_hidden(entry):
    if entry.name.startswith(".") or entry.name.lower() in ("desktop.ini", "thumbs.db"):
        return True
    if OS_NAME == "windows":
        try:
            return bool(entry.stat().st_file_attributes & 0x2)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            return False
    return False


def list_shared_files():
    """Top-level regular files in the shared folder, newest first (hidden files skipped)."""
    out = []
    try:
        real_root = os.path.realpath(SHARED_DIR)
        with os.scandir(SHARED_DIR) as it:
            for e in it:
                try:
                    if _is_hidden(e) or not e.is_file():
                        continue
                    if os.path.dirname(os.path.realpath(e.path)) != real_root:
                        continue  # symlink pointing elsewhere
                    st = e.stat()
                except OSError:
                    continue
                out.append({"name": e.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    except FileNotFoundError:
        return []
    except OSError as e:
        log.debug("Listing %s failed: %s", SHARED_DIR, e)
        return []
    out.sort(key=lambda f: (-f["mtime"], f["name"].lower()))
    return out


def resolve_shared_file(name):
    """Path of `name` inside the shared folder, or None if the name is unsafe / missing."""
    if not isinstance(name, str) or not name or name in (".", ".."):
        return None
    if "/" in name or "\\" in name or "\x00" in name or name.startswith(".."):
        return None
    root = os.path.realpath(SHARED_DIR)
    path = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(path) != root or not os.path.isfile(path):
        return None
    return path


def content_disposition(name):
    ascii_name = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in name)
    return "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (ascii_name, quote(name, safe=""))


def reveal_path(path, select=False):
    """Show a folder (or select a file) in Finder / Explorer."""
    try:
        if OS_NAME == "mac":
            subprocess.Popen(["open", "-R", path] if select else ["open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif OS_NAME == "windows":
            if select:
                subprocess.Popen('explorer /select,"%s"' % path, creationflags=NO_WINDOW)
            else:
                os.startfile(path)  # noqa: no-member (Windows only)
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) if select else path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        log.warning("Could not open %s: %s", path, e)
        return False


# --------------------------------------------------------------------------- start at login

def mac_app_bundle():
    """The enclosing .app of a frozen macOS build (None when not inside a bundle)."""
    p = os.path.abspath(sys.executable)
    while p and p != os.path.dirname(p):
        if p.endswith(".app"):
            return p
        p = os.path.dirname(p)
    return None


def login_argv():
    """Command line that starts Hop in the background at login."""
    if FROZEN:
        if OS_NAME == "mac":
            app = mac_app_bundle()
            if app:
                return ["/usr/bin/open", "-g", "-a", app, "--args", "--background"]
        return [os.path.abspath(sys.executable), "--background"]
    py = sys.executable
    if OS_NAME == "windows":  # pythonw.exe: no console window at login
        w = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.isfile(w):
            py = w
    return [py, os.path.abspath(__file__), "--background"]


def _launch_agent_path():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                        LAUNCH_AGENT_LABEL + ".plist")


def startup_supported():
    return OS_NAME in ("mac", "windows")


def startup_command():
    """The installed start-at-login command (list on macOS, string on Windows) or None."""
    if OS_NAME == "mac":
        path = _launch_agent_path()
        if not os.path.isfile(path):
            return None
        try:
            import plistlib
            with open(path, "rb") as f:
                return list(plistlib.load(f).get("ProgramArguments") or [])
        except Exception:
            return []
    if OS_NAME == "windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY) as k:
                return winreg.QueryValueEx(k, WIN_RUN_VALUE)[0]
        except OSError:
            return None
    return None


def migrate_from_local_view():
    """Hop was called Local View: carry over its settings, pairings, shared folder and login item."""
    home = os.path.expanduser("~")
    moved = []
    try:
        old = os.path.join(home, ".localview.json")
        if not os.path.exists(CONFIG_PATH) and os.path.isfile(old):
            shutil.copy2(old, CONFIG_PATH)
            moved.append("settings")
        old_web, new_web = os.path.join(home, ".localview-web"), os.path.join(home, ".hop-web")
        if not os.path.exists(new_web) and os.path.isdir(old_web):
            os.rename(old_web, new_web)  # remembered computers and this device's pairing key
            moved.append("window storage")
        old_dir = os.path.join(downloads_dir(), "Local View")
        if not os.path.exists(SHARED_DIR) and os.path.isdir(old_dir):
            os.rename(old_dir, SHARED_DIR)
            moved.append("shared folder")
    except OSError as e:
        log.warning("Couldn't carry over Local View's files: %s", e)
    # The old login item would start the old app (or nothing): replace it with Hop's.
    try:
        if OS_NAME == "mac":
            old_agent = os.path.join(home, "Library", "LaunchAgents", "com.localview.host.plist")
            if os.path.isfile(old_agent):
                subprocess.run(["launchctl", "unload", old_agent], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.remove(old_agent)
                set_startup(True)
                moved.append("start at login")
        elif OS_NAME == "windows":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY, 0, winreg.KEY_ALL_ACCESS) as k:
                try:
                    winreg.QueryValueEx(k, "LocalView")
                except OSError:
                    pass
                else:
                    winreg.DeleteValue(k, "LocalView")
                    set_startup(True)
                    moved.append("start at login")
    except Exception as e:
        log.debug("Login item migration skipped: %s", e)
    if moved:
        log.info("Carried over from Local View: %s", ", ".join(moved))


def startup_enabled():
    return startup_command() is not None


def set_startup(on):
    """Install / remove the login item. Raises RuntimeError with a user-facing message."""
    if OS_NAME == "mac":
        path = _launch_agent_path()
        if not on:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            return
        argv = login_argv()
        if FROZEN and "/AppTranslocation/" in " ".join(argv):
            raise RuntimeError(Text("err.startupMove"))
        import plistlib
        plist = {"Label": LAUNCH_AGENT_LABEL, "ProgramArguments": argv, "RunAtLoad": True,
                 "ProcessType": "Interactive", "LimitLoadToSessionType": "Aqua"}
        if not FROZEN:
            plist["WorkingDirectory"] = os.path.dirname(os.path.abspath(__file__))
            plist["StandardOutPath"] = LOG_PATH
            plist["StandardErrorPath"] = LOG_PATH
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "wb") as f:
                plistlib.dump(plist, f)
            os.replace(path + ".tmp", path)
        except OSError as e:
            raise RuntimeError(Text("err.loginItem", detail=e))
    elif OS_NAME == "windows":
        import winreg
        try:
            if on:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY) as k:
                    winreg.SetValueEx(k, WIN_RUN_VALUE, 0, winreg.REG_SZ,
                                      subprocess.list2cmdline(login_argv()))
            else:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, WIN_RUN_VALUE)
        except FileNotFoundError:
            pass
        except OSError as e:
            raise RuntimeError(Text("err.startupChange", detail=e))
    else:
        raise RuntimeError(Text("err.startupUnsupported"))


def refresh_startup_entry():
    """A frozen app that was moved (e.g. Downloads -> Applications) re-points its login item."""
    if not FROZEN or not startup_supported():
        return
    cur = startup_command()
    if cur is None:
        return
    want = login_argv()
    if OS_NAME == "windows":
        want = subprocess.list2cmdline(want)
    if cur != want:
        try:
            set_startup(True)
            log.info("Updated the start-at-login entry")
        except Exception as e:
            log.debug("Could not update the login item: %s", e)


# --------------------------------------------------------------------------- keep awake

class VirtualDisplays(object):
    """Extra displays that macOS treats as real monitors ("second screen" mode).

    Uses CoreGraphics' CGVirtualDisplay (the API behind DeskPad and BetterDisplay; present since
    macOS 11). Each display belongs to one viewer session and disappears when it's released.
    Windows has no in-process equivalent: there a virtual display needs a display driver (e.g. the
    free Virtual Display Driver) or an HDMI dummy plug, which then shows up as an ordinary monitor.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}   # owner (session id) -> {"display": CGVirtualDisplay, "id": CGDirectDisplayID}
        self.error = ""
        self._classes = None
        self._queue = None
        if OS_NAME == "mac":
            try:
                import objc
                from dispatch import dispatch_queue_create, DISPATCH_QUEUE_SERIAL
                self._classes = tuple(objc.lookUpClass(n) for n in (
                    "CGVirtualDisplayDescriptor", "CGVirtualDisplay",
                    "CGVirtualDisplaySettings", "CGVirtualDisplayMode"))
                self._queue = dispatch_queue_create(b"hop.virtual-display", DISPATCH_QUEUE_SERIAL)
            except Exception as e:
                self.error = str(e)
                self._classes = None

    @property
    def supported(self):
        return self._classes is not None

    def create(self, owner, width, height, hidpi=True, side="right"):
        """Add a display of width×height points next to the main one; returns its CGDirectDisplayID."""
        import Quartz
        D, V, S, M = self._classes
        width = max(640, min(3840, int(width) // 2 * 2))
        height = max(480, min(2400, int(height) // 2 * 2))
        scale = 2 if hidpi else 1
        self.destroy(owner)
        with self.lock:
            serial = 1 + len(self.items) + (int(time.time()) % 1000) * 8
        d = D.alloc().init()
        d.setQueue_(self._queue)
        d.setName_("Hop")
        d.setMaxPixelsWide_(width * scale)
        d.setMaxPixelsHigh_(height * scale)
        d.setSizeInMillimeters_((width * 25.4 / 110.0, height * 25.4 / 110.0))  # ~110 points per inch
        d.setProductID_(0x4C56)
        d.setVendorID_(0x4C56)
        d.setSerialNum_(serial)
        v = V.alloc().initWithDescriptor_(d)
        if v is None:
            raise RuntimeError("macOS refused to create a virtual display")
        st = S.alloc().init()
        st.setHiDPI_(1 if hidpi else 0)
        st.setModes_([M.alloc().initWithWidth_height_refreshRate_(width, height, 60.0)])
        if not v.applySettings_(st):
            raise RuntimeError("macOS refused the virtual display's size")
        did = int(v.displayID())
        with self.lock:
            self.items[owner] = {"display": v, "id": did}
        # Place it beside the main display (macOS puts new displays on the left by default).
        try:
            time.sleep(0.6)
            main = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            others = [Quartz.CGDisplayBounds(i["id"]) for o, i in self.items.items() if o != owner]
            if side == "left":
                x, y = int(main.origin.x - width - sum(b.size.width for b in others if b.origin.x < main.origin.x)), 0
            elif side == "above":
                x, y = 0, int(main.origin.y - height)
            else:
                x, y = int(main.origin.x + main.size.width + sum(b.size.width for b in others
                                                                  if b.origin.x >= main.origin.x + main.size.width)), 0
            err, cfg = Quartz.CGBeginDisplayConfiguration(None)
            if not err:
                Quartz.CGConfigureDisplayOrigin(cfg, did, x, y)
                Quartz.CGCompleteDisplayConfiguration(cfg, Quartz.kCGConfigureForSession)
            time.sleep(0.4)
        except Exception as e:
            log.debug("Couldn't place the virtual display: %s", e)
        log.info("Second screen: added a %dx%d%s display", width, height, " HiDPI" if hidpi else "")
        return did

    def bounds(self, owner):
        import Quartz
        with self.lock:
            it = self.items.get(owner)
        if not it:
            return None
        b = Quartz.CGDisplayBounds(it["id"])
        return (int(b.origin.x), int(b.origin.y), int(b.size.width), int(b.size.height))

    def destroy(self, owner):
        with self.lock:
            it = self.items.pop(owner, None)
        if it is not None:
            it["display"] = None  # releasing the object removes the display
            log.info("Second screen: removed the virtual display")
            return True
        return False

    def destroy_all(self):
        with self.lock:
            owners = list(self.items)
        for o in owners:
            self.destroy(o)


class KeepAwake(object):
    """Prevent idle/display sleep while viewers are connected.

    macOS: a `caffeinate -di -w <pid>` child (dies with us). Windows: SetThreadExecutionState
    is per-thread and lasts only while that thread lives, so a dedicated thread owns it.
    """

    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    def __init__(self):
        self.active = False
        self._proc = None
        self._cv = threading.Condition()
        self._want = False
        self._thread = None

    def set(self, on):
        on = bool(on)
        if on == self.active:
            return
        self.active = on
        log.info("Keep awake %s", "on" if on else "off")
        if OS_NAME == "mac":
            if on:
                try:
                    self._proc = subprocess.Popen(
                        ["/usr/bin/caffeinate", "-di", "-w", str(os.getpid())],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e:
                    log.warning("caffeinate failed: %s", e)
                    self._proc = None
            else:
                p, self._proc = self._proc, None
                if p is not None:
                    try:
                        p.terminate()
                        p.wait(2)
                    except Exception:
                        try:
                            p.kill()
                        except Exception:
                            pass
        elif OS_NAME == "windows":
            with self._cv:
                self._want = on
                if self._thread is None:
                    self._thread = threading.Thread(target=self._win_loop, name="lv-awake",
                                                    daemon=True)
                    self._thread.start()
                self._cv.notify_all()

    def _win_loop(self):
        try:
            import ctypes
            fn = ctypes.windll.kernel32.SetThreadExecutionState
            fn.argtypes = [ctypes.c_uint32]
            fn.restype = ctypes.c_uint32
        except Exception as e:
            log.warning("SetThreadExecutionState unavailable: %s", e)
            return
        applied = None
        while True:
            with self._cv:
                while self._want == applied:
                    self._cv.wait()
                want = self._want
            flags = self.ES_CONTINUOUS
            if want:
                flags |= self.ES_SYSTEM_REQUIRED | self.ES_DISPLAY_REQUIRED
            if not fn(flags):
                log.debug("SetThreadExecutionState(%#x) failed", flags)
            applied = want


# --------------------------------------------------------------------------- clipboard

class Clipboard(object):
    """Host clipboard (text) via pyperclip, all calls on one worker thread."""

    def __init__(self):
        self.ex = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="lv-clip")
        self._pc = None
        try:
            import pyperclip
            self._pc = pyperclip
        except Exception as e:
            log.info("Clipboard sharing unavailable (%s)", e)
        self._seq_fn = None
        self._seq_init = False
        self._pool = None

    @property
    def available(self):
        return self._pc is not None

    def _pool_ctx(self):
        if OS_NAME == "mac":
            try:
                import objc
                return objc.autorelease_pool()
            except Exception:
                pass
        return contextlib.nullcontext()

    def get(self):
        with self._pool_ctx():
            v = self._pc.paste()
        return v if isinstance(v, str) else ""

    def set(self, text):
        with self._pool_ctx():
            self._pc.copy(text)

    def seq(self):
        """A counter that changes whenever the clipboard changes (None if unknown)."""
        if not self._seq_init:
            self._seq_init = True
            try:
                if OS_NAME == "mac":
                    import AppKit
                    pb = AppKit.NSPasteboard.generalPasteboard()
                    self._seq_fn = lambda: int(pb.changeCount())
                elif OS_NAME == "windows":
                    import ctypes
                    f = ctypes.windll.user32.GetClipboardSequenceNumber
                    f.restype = ctypes.c_uint32
                    self._seq_fn = lambda: int(f())
            except Exception as e:
                log.debug("No clipboard change counter: %s", e)
        if self._seq_fn is None:
            return None
        with self._pool_ctx():
            return self._seq_fn()


# --------------------------------------------------------------------------- mDNS

class NsecResponder(object):
    """Answers AAAA queries for our A-only host name with a proper negative (NSEC) response.

    python-zeroconf names the NSEC it sends for missing address types after the service
    instance instead of the host name, so resolvers ignore it and getaddrinfo() (curl, Chrome,
    Windows) waits ~5 s for an AAAA answer before using the A record. This tiny listener shares
    UDP 5353 (like zeroconf and the OS responder do) and replies correctly, in ~10 ms.
    """

    def __init__(self):
        self.host = None
        self.ip = None
        self._sock_ip = None
        self._thread = None
        self._stop = False
        self._last_mcast = 0.0

    def update(self, short, ip):
        self.host = (short + ".local.") if short else None
        self.ip = ip
        if self.host and (self._thread is None or not self._thread.is_alive()):
            self._stop = False
            self._thread = threading.Thread(target=self._run, name="lv-nsec", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop = True
        self.host = None

    @staticmethod
    def _open(ip):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            s.bind(("", 5353))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         socket.inet_aton("224.0.0.251") + socket.inet_aton(ip))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            s.settimeout(1.0)
            return s
        except Exception:
            s.close()
            raise

    def _run(self):
        try:
            from zeroconf import DNSAddress, DNSIncoming, DNSNsec, DNSOutgoing, const
        except Exception as e:
            log.debug("NSEC helper unavailable: %s", e)
            return
        sock = None
        while not self._stop:
            host, ip = self.host, self.ip
            if not host or not ip:
                time.sleep(0.5)
                continue
            if sock is None or self._sock_ip != ip:
                if sock is not None:
                    sock.close()
                    sock = None
                try:
                    sock = self._open(ip)
                    self._sock_ip = ip
                except OSError as e:
                    log.debug("NSEC helper can't listen on 5353: %s", e)
                    time.sleep(30)
                    continue
            try:
                data, addr = sock.recvfrom(9000)
            except socket.timeout:
                continue
            except OSError:
                sock.close()
                sock = None
                time.sleep(1)
                continue
            try:
                msg = DNSIncoming(data)
                if not msg.is_query():
                    continue
                for q in msg.questions:
                    if q.type != const._TYPE_AAAA or q.name.lower() != host:
                        continue
                    legacy = addr[1] != 5353  # one-shot resolver: unicast reply with its id
                    out = DNSOutgoing(const._FLAGS_QR_RESPONSE | const._FLAGS_AA,
                                      multicast=not legacy, id_=msg.id if legacy else 0)
                    if legacy:
                        out.add_question(q)
                    out.add_answer_at_time(DNSNsec(host, const._TYPE_NSEC, const._CLASS_IN_UNIQUE,
                                                   120, host, [const._TYPE_A]), 0)
                    out.add_additional_answer(DNSAddress(host, const._TYPE_A,
                                                         const._CLASS_IN_UNIQUE, 120,
                                                         socket.inet_aton(ip)))
                    for pkt in out.packets():
                        if legacy or q.unicast:
                            sock.sendto(pkt, addr)
                        if not legacy and time.monotonic() - self._last_mcast > 1.0:
                            self._last_mcast = time.monotonic()
                            sock.sendto(pkt, ("224.0.0.251", 5353))
            except Exception as e:
                log.debug("NSEC helper: %s", e)
        if sock is not None:
            sock.close()


class NearbyDevices(object):
    """iPhones, iPads and Macs on this Wi-Fi, from the Bonjour announcements AirDrop/Handoff use.

    Apple devices announce "_companion-link._tcp" while awake. Only the name and address are used.
    """
    TYPES = ("_companion-link._tcp.local.",)
    TTL = 180.0

    def __init__(self):
        self.zc = None
        self.browsers = []
        self.found = {}   # bonjour name -> {"name", "kind", "ip", "seen"}
        self.lock = threading.Lock()

    @staticmethod
    def kind_of(name):
        n = name.lower()
        if "iphone" in n:
            return "phone"
        if "ipad" in n:
            return "tablet"
        if "macbook" in n or "imac" in n or "mac mini" in n or "mac studio" in n or "mac pro" in n or n.endswith("mac"):
            return "computer"
        return None   # Apple TV, HomePod, … can't be viewed or controlled

    def start(self):
        try:
            from zeroconf import Zeroconf, ServiceBrowser
            self.zc = Zeroconf()
            self.browsers = [ServiceBrowser(self.zc, t, handlers=[self._on_change]) for t in self.TYPES]
        except Exception as e:
            log.debug("Device discovery unavailable: %s", e)

    def _on_change(self, zeroconf, service_type, name, state_change):
        label = name.split("." + service_type)[0].split("._")[0].replace("\\032", " ").strip()
        kind = self.kind_of(label)
        if not kind:
            return
        if "Removed" in str(state_change):
            return  # keep it until it goes stale: phones drop off briefly when they sleep
        ip = None
        try:
            info = zeroconf.get_service_info(service_type, name, timeout=1500)
            if info:
                v4 = [a for a in info.parsed_addresses() if ":" not in a]
                ip = v4[0] if v4 else None
        except Exception:
            pass
        with self.lock:
            self.found[label] = {"name": label, "kind": kind, "ip": ip, "seen": time.time()}

    def current(self):
        now = time.time()
        with self.lock:
            for k in [k for k, v in self.found.items() if now - v["seen"] > self.TTL]:
                del self.found[k]
            return list(self.found.values())

    def stop(self):
        try:
            if self.zc is not None:
                self.zc.close()
        except Exception:
            pass
        self.zc = None


class Mdns(object):
    """python-zeroconf wrapper. Every method blocks: call them on the mdns worker thread."""

    def __init__(self):
        self.zc = None
        self.info = None
        self.nsec = NsecResponder()

    def ensure(self):
        if self.zc is None:
            from zeroconf import IPVersion, Zeroconf
            self.zc = Zeroconf(ip_version=IPVersion.V4Only)
        return self.zc

    def probe(self, short, ours):
        """True if `<short>.local` already answers with an address that isn't ours."""
        from zeroconf import AddressResolverIPv4
        r = AddressResolverIPv4(short + ".local.")
        if r.request(self.ensure(), 1500):
            addrs = r.parsed_addresses()
            return any(a not in ours for a in addrs)
        return False

    def register(self, short, ip, port, name, host_id):
        from zeroconf import ServiceInfo
        self.unregister()
        inst = ("Hop on %s" % name).replace(".", " ")
        while len(inst.encode("utf-8")) > 63:
            inst = inst[:-1]
        info = ServiceInfo("_http._tcp.local.", "%s._http._tcp.local." % inst,
                           addresses=[socket.inet_aton(ip)], port=port,
                           properties={"path": "/", "id": host_id}, server=short + ".local.")
        self.ensure().register_service(info, allow_name_change=True)
        self.info = info
        self.nsec.update(short, ip)

    def unregister(self):
        self.nsec.update(None, None)
        if self.info is not None and self.zc is not None:
            info, self.info = self.info, None
            try:
                self.zc.unregister_service(info)
            except Exception as e:
                log.debug("mDNS unregister failed: %s", e)

    def close(self):
        self.unregister()
        self.nsec.stop()
        if self.zc is not None:
            try:
                self.zc.close()
            except Exception:
                pass
            self.zc = None


# --------------------------------------------------------------------------- capture

_tls = threading.local()

# mss >= 10.2 exposes mss.MSS and deprecates the mss.mss() factory; older versions only have mss.mss.
_MSS_FACTORY = getattr(mss, "MSS", None) or mss.mss


def _new_mss():
    return _MSS_FACTORY()


def _get_sct():
    """Thread-local mss instance (mss is not thread-safe)."""
    sct = getattr(_tls, "sct", None)
    if sct is None:
        sct = _new_mss()
        _tls.sct = sct
    return sct


def _close_sct():
    sct = getattr(_tls, "sct", None)
    if sct is not None:
        try:
            sct.close()
        except Exception:
            pass
        _tls.sct = None


def list_monitors():
    """Return mss monitors 1..N as plain dicts (index, left, top, width, height)."""
    mons = _get_sct().monitors
    out = []
    for i, m in enumerate(mons):
        if i == 0:
            continue
        out.append({"index": i, "left": m["left"], "top": m["top"],
                    "width": m["width"], "height": m["height"]})
    if not out and mons:
        m = mons[0]
        out.append({"index": 1, "left": m["left"], "top": m["top"],
                    "width": m["width"], "height": m["height"]})
    return out


def capture_frame(monitor, maxw, quality, last_raw):
    """Grab, downscale and JPEG-encode a monitor.

    Returns (jpeg_bytes_or_None, raw_bytes). jpeg is None when the downscaled raw
    image is byte-identical to last_raw.
    """
    sct = _get_sct()
    region = {"left": monitor["left"], "top": monitor["top"],
              "width": monitor["width"], "height": monitor["height"]}
    shot = sct.grab(region)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if img.width > maxw:
        h = max(1, int(round(img.height * maxw / float(img.width))))
        img = img.resize((maxw, h), RESAMPLE)
    raw = img.tobytes()
    if last_raw is not None and raw == last_raw:
        return None, raw
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), raw


def capture_image(monitor, maxw):
    """Grab and downscale a monitor for the internet video stream (even width/height, RGB)."""
    sct = _get_sct()
    region = {"left": monitor["left"], "top": monitor["top"],
              "width": monitor["width"], "height": monitor["height"]}
    shot = sct.grab(region)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if img.width > maxw:
        h = max(2, int(round(img.height * maxw / float(img.width))))
        img = img.resize((maxw, h), RESAMPLE)
    return remote.even_size(img)


# --------------------------------------------------------------------------- input

mouse = MouseController()
keyboard = KeyboardController()

BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}


def _build_keymap():
    # "Meta" -> Key.cmd: Command on macOS, the Windows key on Windows (VK_LWIN).
    names = {
        "Enter": "enter", "Backspace": "backspace", "Tab": "tab", "Escape": "esc",
        "Delete": "delete", "ArrowUp": "up", "ArrowDown": "down", "ArrowLeft": "left",
        "ArrowRight": "right", "Home": "home", "End": "end", "PageUp": "page_up",
        "PageDown": "page_down", "Shift": "shift", "Control": "ctrl", "Alt": "alt",
        "Meta": "cmd", "CapsLock": "caps_lock", " ": "space", "Insert": "insert",
    }
    for i in range(1, 13):
        names["F%d" % i] = "f%d" % i
    km = {}
    for browser_name, attr in names.items():
        k = getattr(Key, attr, None)  # e.g. Key.insert does not exist on macOS
        if k is not None:
            km[browser_name] = k
    return km


KEYMAP = _build_keymap()

# Browser shortcut keys are normalized to their physical US-keyboard positions.
# pynput's character path uses the current layout; on e.g. a Russian layout an
# ASCII letter becomes a Unicode packet, so Ctrl+A inserts "a" instead of selecting.
WIN_SHORTCUT_VK = {c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"}
WIN_SHORTCUT_VK.update(dict(zip(";=,-./`[\\]'", (0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF,
                                               0xC0, 0xDB, 0xDC, 0xDD, 0xDE))))


def map_key(k):
    if not isinstance(k, str) or not k:
        return None
    if k in KEYMAP:
        return KEYMAP[k]
    if len(k) == 1:
        return k
    return None


def _clamp01(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return min(1.0, max(0.0, v))


class InputState(object):
    """Per-connection input injector. All methods run on the connection's input thread."""

    def __init__(self):
        self.held_keys = set()
        self.held_buttons = set()
        self.key_codes = {}

    @staticmethod
    def to_screen(mon, x, y):
        x, y = _clamp01(x), _clamp01(y)
        px = mon["left"] + min(x * mon["width"], mon["width"] - 1)
        py = mon["top"] + min(y * mon["height"], mon["height"] - 1)
        return (int(round(px)), int(round(py)))

    def move(self, mon, x, y):
        mouse.position = self.to_screen(mon, x, y)

    def button(self, mon, b, x, y, down):
        btn = BUTTONS.get(b)
        if btn is None:
            return
        if x is not None and y is not None:
            self.move(mon, x, y)
        if down:
            mouse.press(btn)
            self.held_buttons.add(btn)
        else:
            mouse.release(btn)
            self.held_buttons.discard(btn)

    def click(self, mon, b, x, y, n):
        btn = BUTTONS.get(b)
        if btn is None:
            return
        if x is not None and y is not None:
            self.move(mon, x, y)
        if n == 2:
            mouse.click(btn, 2)  # sets click count on macOS (real double-click)
        else:
            mouse.press(btn)
            mouse.release(btn)
        self.held_buttons.discard(btn)

    def scroll(self, dx, dy):
        dx, dy = int(dx), int(dy)
        dx = max(-50, min(50, dx))
        dy = max(-50, min(50, dy))
        if dx or dy:
            # protocol: dy>0 = content down; pynput: dy>0 = up
            mouse.scroll(dx * SCROLL_FACTOR, -dy * SCROLL_FACTOR)

    def key(self, k, down):
        key = map_key(k)
        if key is None:
            log.debug("Unknown key %r", k)
            return
        if down:
            if k in self.key_codes:
                key = self.key_codes[k]
            elif OS_NAME == "windows" and self.held_keys.intersection((Key.ctrl, Key.alt, Key.cmd)):
                vk = WIN_SHORTCUT_VK.get(k.lower())
                if vk is not None:
                    key = KeyCode.from_vk(vk)
            keyboard.press(key)
            self.held_keys.add(key)
            self.key_codes[k] = key
        else:
            # Release the same native key even if the modifier was released first.
            key = self.key_codes.pop(k, key)
            keyboard.release(key)
            self.held_keys.discard(key)

    def text(self, s):
        if isinstance(s, str) and s:
            keyboard.type(s[:10000])

    def release_all(self):
        for key in list(self.held_keys):
            try:
                keyboard.release(key)
            except Exception as e:
                log.debug("release key %r failed: %s", key, e)
        self.held_keys.clear()
        self.key_codes.clear()
        for btn in list(self.held_buttons):
            try:
                mouse.release(btn)
            except Exception as e:
                log.debug("release button %r failed: %s", btn, e)
        self.held_buttons.clear()


# --------------------------------------------------------------------------- discovery

class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, server):
        self.server = server

    def datagram_received(self, data, addr):
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            return
        if not isinstance(msg, dict) or msg.get("app") != APP:
            return
        pid = msg.get("id")
        if not isinstance(pid, str) or pid == self.server.id:
            return
        try:
            port = int(msg.get("port", DEFAULT_PORT))
        except (TypeError, ValueError):
            return
        short = msg.get("short")
        origin, key = parse_server_address(msg.get("cloud"))
        self.server.peers[pid] = {
            "cloud": ("%s/k/%s" % (origin, key)) if origin and key and origin.startswith("https://") else None,
            "name": str(msg.get("name", "?"))[:64],
            "os": str(msg.get("os", "?"))[:16],
            "ip": addr[0],
            "port": port,
            "id": pid[:64],
            "short": short if isinstance(short, str) and PEER_SHORT_RE.match(short) else None,
            "easy": bool(msg.get("easy")),
            "seen": time.time(),
        }

    def error_received(self, exc):
        pass


# --------------------------------------------------------------------------- server

class HopServer(object):
    def __init__(self, name, port, pin, host_id, cfg=None, easy_port=True):
        self.name = name
        self.port = port
        self.pin = pin
        self.id = host_id
        self.cfg = cfg if cfg is not None else {}
        self.want_easy = easy_port and port != EASY_PORT
        self.easy_bound = port == EASY_PORT
        self.peers = {}
        self.failures = {}  # ip -> {"count": n, "until": ts}
        self.websockets = set()
        self.sessions = {}  # session id -> Session (authenticated viewers)
        self.by_token = {}  # session token -> Session (HTTP feature auth)
        self.pending = {}   # request id -> {"ip","device","ua","at","future"}
        self.kicked = {}    # ip -> until ts (one-shot refusal after "Disconnect")
        self.received = collections.deque(maxlen=5)
        self.paused = False
        self.token = secrets.token_urlsafe(24)  # embedded in /host, required by /api/host/*
        self.on_attention = None  # set by the window: bring it to front (called on the loop thread)
        self.gui = None           # WindowBridge when the app window runs (None = headless)
        self.loop = None
        self._transport = None
        self._tasks = []
        self._disc_error_logged = False
        # easy address / mDNS
        self.short = self.short_want
        self.mdns_ok = None      # None = not tried yet, True = advertising, False = failed
        self._mdns = Mdns()
        self._mdns_ex = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="lv-mdns")
        self._mdns_state = None
        self._mdns_retry_at = 0.0
        self._mdns_logged = False
        self._probed = None
        self._foreign = {}       # short -> until ts (answered by a device that isn't us)
        self._addr_event = None
        # clipboard / files / awake
        self.clip = Clipboard()
        self._clip_last = None
        self._clip_seq = None
        self._clip_origin = None  # (text, session id) of the last viewer clip.set
        self._files_sig = None
        self._files_tick = 0
        self.io_ex = concurrent.futures.ThreadPoolExecutor(2, thread_name_prefix="lv-io")
        self.awake = KeepAwake()
        self.vdisplays = VirtualDisplays()
        self._startup_cache = (0.0, False)
        # internet access (remote.CloudLink while turned on)
        self.cloud = None
        self.perms_at_start = mac_permissions()
        self.nearby = NearbyDevices()
        self.update = {"state": "idle", "latest": "", "available": False, "progress": 0.0, "error": "",
                       "page": "https://github.com/%s/releases/latest" % updater.REPO, "checked": 0,
                       "problem": updater.installation().get("problem", "")}
        self._update_info = None
        self.net_fails = collections.deque()  # times of wrong internet passwords (any address)
        self.net_paused_until = 0.0
        i18n.set_language(self.setting("language"))

    # ---- internet access
    @property
    def cloud_url(self):
        return valid_cloud_url(self.cfg.get("cloudUrl")) or default_cloud_url()

    @property
    def site_key(self):
        k = str(self.cfg.get("siteKey") or "")
        return k if SITE_KEY_RE.match(k) else ""

    def private_address(self):
        """The server's address with its key — what phones open and other computers copy."""
        return "%s/k/%s" % (self.cloud_url, self.site_key) if self.cloud_url and self.site_key else ""

    def cloud_enabled(self):
        return bool(self.cfg.get("cloudEnabled")) and remote is not None and bool(self.cloud_url)

    def _ensure_cloud_identity(self):
        changed = False
        if not re.match(r"^\d{9}$", str(self.cfg.get("cloudId") or "")):
            self.cfg["cloudId"] = remote.new_cloud_id()
            changed = True
        if not self.site_key:  # a fresh server: this computer creates its private key and claims it
            self.cfg["siteKey"] = secrets.token_urlsafe(18)
            changed = True
        if len(str(self.cfg.get("cloudKey") or "")) < 24:
            self.cfg["cloudKey"] = remote.new_cloud_key()
            changed = True
        if password_problem(str(self.cfg.get("cloudPassword") or "")):  # missing or too weak
            self.cfg["cloudPassword"] = remote.new_password()
            changed = True
        if changed:
            self.save()

    # ---- devices paired for internet access (first connection confirmed with a code on this computer)
    def trusted_devices(self):
        t = self.cfg.get("trustedDevices")
        return t if isinstance(t, list) else []

    def find_trusted(self, device):
        if not isinstance(device, dict):
            return None
        did, tok = str(device.get("id") or ""), str(device.get("token") or "")
        if not did or len(tok) < 20:
            return None
        h = hashlib.sha256(tok.encode("utf-8")).hexdigest()
        for d in self.trusted_devices():
            if d.get("id") == did and hmac.compare_digest(str(d.get("hash", "")), h):
                return d
        return None

    def add_trusted(self, device, name):
        did, tok = str(device.get("id") or "")[:64], str(device.get("token") or "")
        if not did or len(tok) < 20:
            return
        lst = [d for d in self.trusted_devices() if d.get("id") != did]
        lst.insert(0, {"id": did, "hash": hashlib.sha256(tok.encode("utf-8")).hexdigest(),
                       "name": name[:80], "added": int(time.time()), "seen": int(time.time())})
        self.cfg["trustedDevices"] = lst[:MAX_TRUSTED]
        self.save()
        log.info("Trusted a new device for internet access: %s", name)

    def touch_trusted(self, d):
        d["seen"] = int(time.time())
        self.save()

    # ---- updates (GitHub Releases)
    async def _update_loop(self):
        await asyncio.sleep(8)
        while True:
            await self.check_update(quiet=True)
            await asyncio.sleep(6 * 3600)

    async def check_update(self, quiet=False):
        u = self.update
        if u["state"] in ("downloading", "installing"):
            return
        u.update(state="checking", error="")
        try:
            info = await asyncio.get_event_loop().run_in_executor(self.io_ex, updater.check, VERSION)
            self._update_info = info
            u.update(state="idle", latest=info["latest"], available=info["available"], page=info["page"],
                     checked=time.time())
            if info["available"]:
                log.info("Hop %s is available (this is %s)", info["latest"], VERSION)
        except Exception as e:
            u.update(state="idle" if quiet else "error", error="" if quiet else Text("update.reachGithub", detail=e),
                     checked=time.time())
            log.info("Update check failed: %s", e)

    async def install_update(self):
        u = self.update
        place = updater.installation()
        if place.get("problem"):
            u.update(state="error", error=place["problem"])
            return
        info = self._update_info
        if not info or not info.get("available"):
            u.update(state="error", error=Text("update.noNewer"))
            return
        loop = asyncio.get_event_loop()
        u.update(state="downloading", progress=0.0, error="")

        def progress(f):
            u["progress"] = round(f, 3)
        try:
            prepared = await loop.run_in_executor(self.io_ex, updater.prepare, info, place, progress)
            u.update(state="installing", progress=1.0)
            await loop.run_in_executor(self.io_ex, updater.apply, prepared, place, LOG_PATH)
        except Exception as e:
            u.update(state="error", error=e.args[0] if e.args and isinstance(e.args[0], Text) else str(e))
            log.warning("Update failed: %s", e)
            return
        log.info("Installing Hop %s: quitting so it can be replaced", info["latest"])
        loop.call_later(0.8, os.kill, os.getpid(), signal.SIGTERM)

    async def api_update_check(self, request):
        await self.check_update()
        return web.json_response(self.status())

    async def api_update_install(self, request):
        if self.update["state"] not in ("downloading", "installing"):
            asyncio.ensure_future(self.install_update())
        await asyncio.sleep(0.2)
        return web.json_response(self.status())

    def remember_device(self, device, remote, ip):
        """Devices that viewed this computer, so 'Your devices' can show them even while they sleep."""
        name = device.replace(" · Internet", "")
        lst = [d for d in (self.cfg.get("knownDevices") or []) if isinstance(d, dict) and d.get("name") != name]
        lst.insert(0, {"name": name, "via": "internet" if remote else "wifi", "ip": None if remote else ip,
                       "last": int(time.time())})
        self.cfg["knownDevices"] = lst[:8]
        self.save()

    def devices(self):
        """Everything worth showing under 'Your devices', most useful first."""
        out, names = [], set()
        for p in self.live_peers():
            out.append({"key": "peer:" + p["id"], "section": "mine", "kind": "computer", "os": p["os"], "name": p["name"],
                        "detail": (p["short"] + ".local") if p.get("short") else p["ip"],
                        "online": True, "hasHop": True, "peer": p["id"]})
            names.add(p["name"].lower())
        me = self.name.lower()
        my_ips = local_ipv4_set() | {"127.0.0.1", get_lan_ip()}
        try:
            real_name = default_name().lower()  # this computer's own name, even if Hop shows another
        except Exception:
            real_name = me
        can_mirror = OS_NAME == "mac" and os.path.isdir("/System/Applications/iPhone Mirroring.app")
        nearby = self.nearby.current()
        hidden = set(n.lower() for n in (self.cfg.get("hiddenNearby") or []) if isinstance(n, str))
        self.hidden_nearby_count = 0
        for d in sorted(nearby, key=lambda d: ("phone", "tablet", "computer").index(d["kind"])):
            if d["name"].lower() in names or d["name"].lower() in (me, real_name) or d.get("ip") in my_ips:
                continue
            names.add(d["name"].lower())
            if d["name"].lower() in hidden:
                self.hidden_nearby_count += 1
                continue
            # Any Apple device on this Wi-Fi announces itself (AirDrop/Handoff), not only yours: "Nearby".
            item = {"key": "near:" + d["name"], "section": "nearby", "kind": d["kind"], "name": d["name"],
                    "online": True, "hasHop": False, "detail": i18n.t("dev.onWifi"), "hideable": True}
            if d["kind"] in ("phone", "tablet"):
                item["send"] = True                          # AirDrop the connect link
                item["mirror"] = can_mirror and d["kind"] == "phone"
            else:
                item["detail"] = i18n.t("dev.installHop")
            out.append(item)
        near_kinds = {d["kind"] for d in nearby}
        for k in (self.cfg.get("knownDevices") or [])[:6]:
            kind = "phone" if "iPhone" in k.get("name", "") or "Android" in k.get("name", "") else \
                   "tablet" if "iPad" in k.get("name", "") else "computer"
            if kind in near_kinds or k.get("name", "").lower() in names:
                continue  # the same device is already listed as nearby
            names.add(k.get("name", "").lower())
            out.append({"key": "known:" + k.get("name", ""), "section": "mine", "kind": kind,
                        "name": k.get("name") or i18n.t("dev.generic"),
                        "online": False, "hasHop": False, "send": kind in ("phone", "tablet"),
                        "mirror": can_mirror and kind == "phone" and "iPhone" in k.get("name", ""),
                        "detail": i18n.t("dev.lastInternet" if k.get("via") == "internet" else "dev.lastWifi",
                                         date=i18n.day_month(k.get("last", 0)))})
        return out

    def net_paused_for(self):
        return max(0, int(self.net_paused_until - time.time()) + 1) if self.net_paused_until > time.time() else 0

    def net_failure(self, ip):
        now = time.time()
        self.net_fails.append(now)
        while self.net_fails and now - self.net_fails[0] > NET_FAIL_WINDOW:
            self.net_fails.popleft()
        if len(self.net_fails) > NET_FAIL_LIMIT and self.net_paused_until <= now:
            self.net_paused_until = now + NET_PAUSE_SECS
            self.net_fails.clear()
            log.warning("Many wrong internet passwords from different addresses: internet sign-ins paused "
                        "for %d minutes", NET_PAUSE_SECS // 60)
            system_notify(i18n.t("notify.guessing", n=NET_PAUSE_SECS // 60))
            self.attention()

    def cloud_id_changed(self, new_id):
        self.cfg["cloudId"] = new_id
        self.save()

    def _cloud_changed(self):
        pass  # the host window polls /api/host/status every second

    async def start_cloud(self):
        await self.stop_cloud()
        if not self.cloud_enabled():
            return
        self._ensure_cloud_identity()
        self.cloud = remote.CloudLink(self, self.cloud_url, self.cfg["cloudId"], self.cfg["cloudKey"],
                                      on_change=self._cloud_changed, site_key=self.site_key)
        self.cloud.start()

    async def stop_cloud(self):
        link, self.cloud = self.cloud, None
        if link is not None:
            # Tell internet viewers why first; stopping the link closes their connections.
            kicks = [s.kick(MSG_INTERNET_OFF) for s in list(self.sessions.values())
                     if getattr(s, "remote", False)]
            if kicks:
                await asyncio.gather(*kicks, return_exceptions=True)
            await link.stop()

    def cloud_status(self):
        url = self.cloud_url
        cid = str(self.cfg.get("cloudId") or "")
        if self.cloud is not None:
            cid = self.cloud.host_id
        enabled = self.cloud_enabled()
        st = {"available": remote is not None, "unavailableReason": REMOTE_ERROR,
              "enabled": enabled, "url": url or "", "defaultUrl": default_cloud_url(),
              "address": self.private_address(),
              "id": cid if enabled else "", "idFormatted": remote.format_id(cid) if (enabled and remote) else "",
              "password": str(self.cfg.get("cloudPassword") or "") if enabled else "",
              "state": "off", "error": ""}
        if enabled and self.cloud is not None:
            st["state"] = self.cloud.state
            st["error"] = i18n.local(self.cloud.error)
        if enabled and cid and self.site_key:
            st["link"] = "%s/#id=%s" % (self.private_address(), cid)
            st["qr"] = qr_svg(st["link"])
        st["deployUrl"] = DEPLOY_URL
        # servers your other computers on this network already use
        seen, sug = set(), []
        now = time.time()
        mine = self.private_address()
        for p in self.peers.values():
            u = p.get("cloud")
            if u and u != mine and u not in seen and now - p["seen"] <= PEER_TTL:
                seen.add(u)
                sug.append({"name": p["name"], "url": u})
        st["suggest"] = sug[:3]
        return st

    # ---- settings (persisted in ~/.hop.json next to pin/id)
    def setting(self, key):
        v = self.cfg.get(key, DEFAULT_SETTINGS[key])
        if key == "theme":
            return v if v in ("system", "light", "dark") else "system"
        if key == "openIn":
            return v if v in OPEN_IN else "window"
        if key == "language":
            return i18n.normalize(v)
        return bool(v)

    @property
    def short_want(self):
        v = self.cfg.get("shortName")
        return v if valid_short(v) else DEFAULT_SHORT

    def startup_state(self):
        t, v = self._startup_cache
        if time.monotonic() - t > 2.0:
            v = startup_enabled()
            self._startup_cache = (time.monotonic(), v)
        return v

    def settings(self):
        d = {k: self.setting(k) for k in DEFAULT_SETTINGS}
        d["shortName"] = self.short_want
        d["startAtLogin"] = self.startup_state()
        return d

    @property
    def allow_control(self):
        return self.setting("allowControl")

    def save(self):
        self.cfg["pin"] = self.pin
        self.cfg["id"] = self.id
        save_config(self.cfg)

    def attention(self):
        cb = self.on_attention
        if cb is not None:
            try:
                cb()
            except Exception as e:
                log.debug("attention callback failed: %s", e)

    def notify(self, text):
        if self.setting("notify"):
            system_notify(text)

    # ---- addresses
    def easy_host(self):
        """Host part of the primary URL: <short>.local, or the LAN IP if mDNS isn't working."""
        if self.mdns_ok is False:
            return get_lan_ip()
        return self.short + ".local"

    def primary_url(self):
        host = self.easy_host()
        return "http://%s" % host if self.easy_bound else "http://%s:%d" % (host, self.port)

    def ip_url(self):
        return "http://%s:%d" % (get_lan_ip(), self.port)

    def urls(self):
        out = [self.primary_url()]
        ip = self.ip_url()
        if ip not in out:
            out.append(ip)
        return out

    # ---- HTTP
    async def handle_index(self, request):
        path = os.path.join(STATIC_DIR, "index.html")
        if not os.path.isfile(path):
            return web.Response(status=404, text="static/index.html not found")
        resp = web.FileResponse(path)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    def info(self):
        return {"name": self.name, "os": OS_NAME, "port": self.port, "id": self.id,
                "short": self.short, "url": self.primary_url()}

    async def handle_remote_page(self, request):
        """The internet viewer, served by this computer for connecting to your other computers."""
        resp = web.FileResponse(os.path.join(STATIC_DIR, "index.html"))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def api_remote_config(self, request):
        if not self.cloud_url or not self.site_key:
            return web.json_response({"error": "Set up internet access first"}, status=404)
        return web.json_response({"base": self.cloud_url, "key": self.site_key, "name": self.name},
                                 headers={"Cache-Control": "no-store"})

    async def handle_info(self, request):
        return web.json_response(self.info())

    def live_peers(self):
        now = time.time()
        out = []
        for pid, p in list(self.peers.items()):
            if now - p["seen"] > PEER_TTL:
                self.peers.pop(pid, None)
                continue
            out.append({"name": p["name"], "os": p["os"], "ip": p["ip"], "port": p["port"],
                        "id": p["id"], "short": p.get("short"), "easy": p.get("easy", False),
                        "self": False})
        out.sort(key=lambda p: p["name"].lower())
        return out

    async def handle_peers(self, request):
        me = dict(self.info(), ip=get_lan_ip(), easy=self.easy_bound, self=True)
        return web.json_response({"peers": [me] + self.live_peers()})

    # ---- host window (loopback only; see guard middleware)
    @staticmethod
    def _host_name(request):
        h = (request.host or "").strip().lower()
        if h.startswith("["):
            return h[1:h.find("]")] if "]" in h else h
        return h.rsplit(":", 1)[0] if h.count(":") == 1 else h

    @staticmethod
    def _local_port(request):
        try:
            return request.transport.get_extra_info("sockname")[1]
        except Exception:
            return None

    def is_local_request(self, request):
        """Loopback peer AND loopback Host header (defeats DNS rebinding)."""
        return request.remote in LOOPBACK_IPS and self._host_name(request) in LOOPBACK_HOSTS

    def origin_ok(self, origin):
        if not origin:
            return True  # same-origin GET/POST from some engines omit it; the token still applies
        try:
            u = urlsplit(origin)
            return u.scheme == "http" and (u.hostname or "") in LOOPBACK_HOSTS and \
                (u.port or 80) == self.port
        except Exception:
            return False

    def make_guard(self):
        @web.middleware
        async def guard(request, handler):
            p = request.path
            if p == "/host" or p.startswith("/api/host/") or p == "/static/host.html" or \
                    p == "/remote" or p == "/api/remote-config":
                # The host window API only exists on the main port (never on the easy port 80).
                if self._local_port(request) != self.port or not self.is_local_request(request):
                    log.info("Refused host-window request from %s (%s)", request.remote, p)
                    return web.json_response({"error": "forbidden"}, status=403)
                if p == "/api/host/activate" and request.method == "POST" and \
                        not request.headers.get("Origin"):
                    return await handler(request)  # second instance asking us to show the window
                if p.startswith("/api/host/"):
                    tok = request.headers.get("X-Hop-Token", "")
                    if not hmac.compare_digest(tok.encode("utf-8"), self.token.encode("utf-8")):
                        return web.json_response({"error": "forbidden"}, status=403)
                    if request.method != "GET" and not self.origin_ok(request.headers.get("Origin")):
                        return web.json_response({"error": "forbidden"}, status=403)
            return await handler(request)
        return guard

    async def handle_host_page(self, request):
        path = os.path.join(STATIC_DIR, "host.html")
        try:
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError:
            return web.Response(status=404, text="static/host.html not found")
        html = (html.replace("__LV_TOKEN__", self.token)
                    .replace("__LV_THEME__", self.setting("theme"))
                    .replace("__LV_LANG__", self.setting("language")))
        resp = web.Response(text=html, content_type="text/html")
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        return resp

    def status(self):
        urls = self.urls()
        now = time.time()
        viewers = [s.describe(now) for s in sorted(self.sessions.values(),
                                                   key=lambda s: s.connected_at)]
        pending = [{"id": pid, "ip": p["ip"], "device": p["device"], "pair": bool(p.get("code")),
                    "expiresIn": max(0, int(round(p["at"] + p.get("timeout", APPROVAL_TIMEOUT) - now)))}
                   for pid, p in sorted(self.pending.items(), key=lambda kv: kv[1]["at"])]
        return {
            "name": self.name, "os": OS_NAME, "version": VERSION, "port": self.port,
            "id": self.id, "paused": self.paused, "pin": self.pin,
            "url": urls[0], "urls": urls, "qr": qr_svg(urls[0]),
            "short": self.short, "easyPort": self.easy_bound, "mdns": self.mdns_ok is not False,
            "folder": display_path(SHARED_DIR), "received": list(self.received),
            "frozen": FROZEN, "windowed": self.gui is not None,
            "viewers": viewers, "pending": pending, "peers": self.live_peers(),
            "settings": self.settings(), "permissions": mac_permissions(),
            "permissionsAtStart": self.perms_at_start,
            "cloud": self.cloud_status(),
            "trusted": [{"id": d.get("id"), "name": d.get("name"), "added": d.get("added"), "seen": d.get("seen")}
                        for d in self.trusted_devices()],
            "netPausedFor": self.net_paused_for(),
            "devices": self.devices(),
            "update": {k: i18n.local(v) if isinstance(v, str) else v for k, v in self.update.items()},
            "hiddenNearby": getattr(self, "hidden_nearby_count", 0),
            "canAirDrop": OS_NAME == "mac" and self.gui is not None,
            "totals": {"fps": round(sum(v["fps"] for v in viewers), 1),
                       "kbps": int(sum(v["kbps"] for v in viewers))},
        }

    async def api_status(self, request):
        return web.json_response(self.status())

    @staticmethod
    async def _json_body(request):
        try:
            d = await request.json()
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _err(msg, status=400):
        return web.json_response({"error": msg}, status=status)

    async def api_pause(self, request):
        await self.set_paused(True)
        return web.json_response(self.status())

    async def api_resume(self, request):
        await self.set_paused(False)
        return web.json_response(self.status())

    async def set_paused(self, paused):
        if paused == self.paused:
            return
        self.paused = paused
        log.info("Sharing %s", "paused" if paused else "resumed")
        if paused:
            for p in list(self.pending.values()):
                if not p["future"].done():
                    p["future"].set_result(MSG_PAUSED)
            for s in list(self.sessions.values()):
                await s.kick(MSG_PAUSED)
        self.update_awake()

    async def api_new_pin(self, request):
        self.pin = "%06d" % random.SystemRandom().randint(0, 999999)
        self.save()
        log.info("New PIN generated: %s", self.pin)
        return web.json_response(self.status())

    async def api_set_pin(self, request):
        d = await self._json_body(request)
        pin = str(d.get("pin", "")).strip()
        if not (len(pin) == 6 and pin.isdigit()):
            return self._err(i18n.t("err.pinDigits"))
        self.pin = pin
        self.save()
        log.info("PIN changed: %s", self.pin)
        return web.json_response(self.status())

    async def api_disconnect(self, request):
        s = self.sessions.get(request.match_info["sid"])
        if s is None:
            return self._err(i18n.t("err.noViewer"), 404)
        self.kicked[s.ip] = time.time() + KICK_BLOCK_SECS
        log.info("Disconnecting %s (host request)", s.ip)
        await s.kick(MSG_KICKED)
        return web.json_response(self.status())

    async def _decide(self, request, verdict):
        p = self.pending.get(request.match_info["rid"])
        if p is None:
            return self._err(i18n.t("err.requestExpired"), 404)
        if not p["future"].done():
            p["future"].set_result(verdict)
        return web.json_response(self.status())

    async def api_approve(self, request):
        p = self.pending.get(request.match_info["rid"])
        if p is not None and p.get("code"):
            d = await self._json_body(request)
            typed = re.sub(r"\D", "", str(d.get("code", "")))
            if not hmac.compare_digest(typed.encode(), p["code"].encode()):
                p["tries"] += 1
                if p["tries"] >= PAIR_TRIES:
                    if not p["future"].done():
                        p["future"].set_result(MSG_PAIR_DECLINED)
                    return self._err(i18n.t("err.codeThrice"), 403)
                return self._err(i18n.t("err.codeMismatch"), 400)
        return await self._decide(request, True)

    async def api_deny(self, request):
        p = self.pending.get(request.match_info["rid"])
        return await self._decide(request, MSG_PAIR_DECLINED if (p and p.get("code")) else MSG_DECLINED)

    async def api_forget_device(self, request):
        tid = request.match_info["tid"]
        lst = self.trusted_devices()
        keep = [d for d in lst if d.get("id") != tid]
        if len(keep) == len(lst):
            return self._err(i18n.t("err.noDevice"), 404)
        self.cfg["trustedDevices"] = keep
        self.save()
        log.info("Forgot a trusted device")
        return web.json_response(self.status())

    async def api_settings(self, request):
        d = await self._json_body(request)
        loop = asyncio.get_event_loop()
        # validate everything first, then apply
        if "theme" in d and d["theme"] not in ("system", "light", "dark"):
            return self._err(i18n.t("err.badTheme"))
        if "openIn" in d and d["openIn"] not in OPEN_IN:
            return self._err(i18n.t("err.badOpenMode"))
        if "language" in d and d["language"] not in i18n.LANGUAGES:
            return self._err(i18n.t("err.badLanguage"))
        if "shortName" in d:
            v = str(d["shortName"] or "").strip().lower()
            if v.endswith(".local"):
                v = v[:-6]
            if not valid_short(v):
                return self._err(i18n.t("err.shortName"))
            d["shortName"] = v
        if "startAtLogin" in d:
            on = bool(d["startAtLogin"])
            if on != startup_enabled():
                try:
                    await loop.run_in_executor(self.io_ex, set_startup, on)
                except RuntimeError as e:
                    return self._err(i18n.local(e))
                except Exception as e:
                    return self._err(i18n.t("err.startupChange", detail=e))
                log.info("Start at login %s", "on" if on else "off")
            self._startup_cache = (0.0, False)
        cloud_touch = False
        if "cloudUrl" in d:
            raw = str(d.get("cloudUrl") or "").strip()
            v, key = parse_server_address(raw) if raw else ("", None)
            if v is None:
                return self._err(i18n.t("err.notServer"))
            if v != str(self.cfg.get("cloudUrl") or ""):
                self.cfg["cloudUrl"] = v
                if not key:  # a different server without a key: create a new one for it
                    self.cfg.pop("siteKey", None)
                cloud_touch = True
            if key and key != self.site_key:  # the private address from another of your computers
                self.cfg["siteKey"] = key
                cloud_touch = True
        if "cloudEnabled" in d:
            on = bool(d["cloudEnabled"])
            if on and remote is None:
                return self._err(i18n.t("err.noInternetBuildWhy", detail=REMOTE_ERROR or i18n.t("err.aiortcMissing")))
            if on and not self.cloud_url:
                return self._err(i18n.t("err.addServerFirst"))
            if on != bool(self.cfg.get("cloudEnabled")):
                self.cfg["cloudEnabled"] = on
                cloud_touch = True
                log.info("Internet access %s", "on" if on else "off")
        changed = False
        control_changed = False
        for k in list(DEFAULT_SETTINGS) + ["shortName"]:
            if k not in d:
                continue
            v = d[k]
            if k not in ("theme", "shortName", "openIn", "language"):
                v = bool(v)
            cur = self.cfg.get(k, DEFAULT_SETTINGS.get(k, None) if k != "shortName"
                               else self.short_want)
            if cur != v:
                self.cfg[k] = v
                changed = True
                log.info("Setting %s = %s", k, v)
                if k == "allowControl":
                    control_changed = True
                    if not v:
                        for s in list(self.sessions.values()):
                            s.release_input()
                if k == "language":
                    i18n.set_language(v)
                if k == "shortName":
                    self._probed = None
                    if self._addr_event is not None:
                        self._addr_event.set()
        if changed or cloud_touch:
            self.save()
        if control_changed:
            await self.broadcast({"t": "control", "allowed": self.allow_control})
        if cloud_touch:
            await self.start_cloud()
        self.update_awake()
        return web.json_response(self.status())

    async def api_cloud_new_password(self, request):
        if remote is None:
            return self._err(i18n.t("err.noInternetBuild"))
        self.cfg["cloudPassword"] = remote.new_password()
        self.save()
        log.info("New internet password generated")
        return web.json_response(self.status())

    async def api_cloud_set_password(self, request):
        d = await self._json_body(request)
        pw = str(d.get("password", "")).strip()
        problem = password_problem(pw)
        if problem:
            return self._err(i18n.local(problem))
        self.cfg["cloudPassword"] = pw
        self.save()
        log.info("Internet password changed")
        return web.json_response(self.status())

    async def api_open_link(self, request):
        """Open one of the app's own help pages in the system browser (fixed list, no arbitrary URLs)."""
        d = await self._json_body(request)
        url = {"deploy": DEPLOY_URL, "guide": GUIDE_URL}.get(str(d.get("which", "")))
        if not url:
            return self._err(i18n.t("err.unknownLink"))
        import webbrowser
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        return web.json_response({"ok": True})

    async def api_device_send(self, request):
        """AirDrop this computer's connect link (with the PIN) — the phone opens it already signed in."""
        if OS_NAME != "mac" or self.gui is None:
            return self._err(i18n.t("err.sendLinksMac"))
        url = "http://%s:%d/#pin=%s" % (get_lan_ip(), self.port, self.pin)
        try:
            self.gui.airdrop(url)
        except Exception as e:
            return self._err(i18n.t("err.airdrop", detail=e))
        return web.json_response({"ok": True})

    async def api_device_hide(self, request):
        d = await self._json_body(request)
        name = str(d.get("name") or "").strip()[:120]
        lst = [n for n in (self.cfg.get("hiddenNearby") or []) if isinstance(n, str)]
        if d.get("all") is True and d.get("show"):
            lst = []
        elif name and name not in lst:
            lst.append(name)
        self.cfg["hiddenNearby"] = lst[-100:]
        self.save()
        return web.json_response(self.status())

    async def api_device_mirror(self, request):
        if OS_NAME != "mac" or not os.path.isdir("/System/Applications/iPhone Mirroring.app"):
            return self._err(i18n.t("err.mirroringVersion"))
        subprocess.Popen(["/usr/bin/open", "-a", "iPhone Mirroring"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return web.json_response({"ok": True})

    async def api_permission(self, request):
        d = await self._json_body(request)
        ok = request_mac_permission(str(d.get("which", "")))
        return web.json_response(self.status() if ok else {"error": i18n.t("err.notAvailable")}, status=200 if ok else 400)

    async def api_restart(self, request):
        """Start a fresh copy, then quit this one (macOS applies Screen Recording after a restart)."""
        if OS_NAME != "mac":
            return self._err(i18n.t("err.restartMacOnly"))
        cmd = relaunch_command()
        log.info("Restarting Hop")
        try:
            # the new copy waits until this one has let go of the port
            subprocess.Popen(["/bin/sh", "-c", 'sleep 1.5; exec "$@"', "sh"] + cmd,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception as e:
            return self._err(i18n.t("err.restart", detail=e))
        asyncio.get_event_loop().call_later(0.4, os.kill, os.getpid(), signal.SIGTERM)
        return web.json_response({"ok": True})

    async def api_open(self, request):
        d = await self._json_body(request)
        ok = open_mac_pane(str(d.get("pane", "")))
        return web.json_response({"ok": ok}, status=200 if ok else 400)

    async def api_activate(self, request):
        self.attention()
        return web.json_response({"ok": True})

    # ---- connect to another computer
    async def _probe_info(self, host, port):
        url = "http://%s/api/info" % (host if port == 80 else "%s:%d" % (host, port))
        try:
            # ThreadedResolver = the OS resolver, which also resolves *.local via mDNS.
            conn = TCPConnector(resolver=ThreadedResolver())
            async with ClientSession(timeout=ClientTimeout(total=2.5), connector=conn) as cs:
                async with cs.get(url) as r:
                    if r.status != 200:
                        return None
                    d = await r.json(content_type=None)
                    if isinstance(d, dict) and isinstance(d.get("id"), str):
                        return d
        except Exception:
            return None
        return None

    async def api_connect(self, request):
        d = await self._json_body(request)
        if d.get("peer"):
            p = self.peers.get(str(d["peer"]))
            if p is None or time.time() - p["seen"] > PEER_TTL:
                return self._err(i18n.t("err.peerGone"), 404)
            url = "http://%s:%d/#pin=%s" % (p["ip"], p["port"], self.pin)
            title = p["name"]
        elif d.get("url"):
            raw = str(d["url"]).strip()
            raw = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", raw)
            raw = re.split(r"[/?#]", raw, 1)[0]
            m = re.match(r"^(\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]+)(?::(\d{1,5}))?$", raw)
            if not m:
                return self._err(i18n.t("err.enterAddress"))
            host, port = m.group(1), m.group(2)
            ports = [int(port)] if port else [EASY_PORT, DEFAULT_PORT]
            infos = await asyncio.gather(*[self._probe_info(host, pt) for pt in ports])
            found = [(pt, i) for pt, i in zip(ports, infos) if i]
            if not found:
                return self._err(i18n.t("err.noHopAt", address=raw), 404)
            pt, info = found[0]
            if info.get("id") == self.id:
                return self._err(i18n.t("err.thisComputer"))
            hostport = host if pt == 80 else "%s:%d" % (host, pt)
            url = "http://%s/#pin=%s" % (hostport, self.pin)
            title = str(info.get("name") or host)[:64]
        elif "cloud" in d:  # over the internet, through the connection server
            if not self.cloud_url or not self.site_key:
                return self._err(i18n.t("err.setUpInternet"))
            cid = re.sub(r"\D", "", str(d.get("cloud") or ""))
            if cid and len(cid) != 9:
                return self._err(i18n.t("err.id9"))
            if cid and cid == str(self.cfg.get("cloudId") or ""):
                return self._err(i18n.t("err.thisComputer"))
            # The interface comes from this computer's own Hop; the server only introduces.
            url = "http://127.0.0.1:%d/remote%s" % (self.port, ("#id=" + cid) if cid else "")
            title = i18n.t("title.computer", id=remote.format_id(cid)) if (cid and remote) else "Hop"
        else:
            return self._err(i18n.t("err.nothingToConnect"))
        extend = d.get("mode") == "extend"
        if extend:  # this computer becomes the other one's second screen
            url += ("&" if "#" in url else "#") + "mode=extend"
            title = i18n.t("title.secondScreen", title=title)
        if self.setting("language") != "en":  # the viewer window speaks this app's language
            url += ("&" if "#" in url else "#") + "lang=" + self.setting("language")
        how = d.get("openIn") if d.get("openIn") in OPEN_IN else self.setting("openIn")
        if extend and how == "window":
            how = "fullscreen"
        log.info("Opening a viewer for %s (%s%s)", title, how, ", second screen" if extend else "")
        self.open_viewer(url, title, how)
        return web.json_response(self.status())

    def open_viewer(self, url, title, how="window"):
        if os.environ.get("HOP_DRY_OPEN"):
            log.info("(dry run) would open %s in %s", url.split("#")[0], how)
            self.last_open = (url, how)
            return
        gui = self.gui
        if gui is not None and how != "browser":
            try:
                gui.open_viewer(url, title, fullscreen=(how == "fullscreen"))
                return
            except Exception as e:
                log.warning("Could not open a window (%s); using the browser", e)
        import webbrowser
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    # ---- shared folder (host window)
    async def api_files_open(self, request):
        d = await self._json_body(request)
        loop = asyncio.get_event_loop()
        name = d.get("name")
        if name:
            path = resolve_shared_file(name)
            if path is None:
                return self._err(i18n.t("err.fileGone"), 404)
            ok = await loop.run_in_executor(self.io_ex, reveal_path, path, True)
        else:
            folder = await loop.run_in_executor(self.io_ex, ensure_shared_dir)
            ok = await loop.run_in_executor(self.io_ex, reveal_path, folder, False)
        if not ok:
            return self._err(i18n.t("err.openFolder"))
        return web.json_response(self.status())

    async def api_files_send(self, request):
        gui = self.gui
        if gui is None:
            return self._err(i18n.t("err.openWindowToPick"), 400)
        loop = asyncio.get_event_loop()
        try:
            picked = await loop.run_in_executor(None, gui.pick_files)
        except Exception as e:
            return self._err(i18n.t("err.filePicker", detail=e))
        names = []
        if picked:
            try:
                names = await loop.run_in_executor(self.io_ex, self._copy_in, list(picked))
            except Exception as e:
                return self._err(i18n.t("err.copyFile", detail=e))
            log.info("Offered %s to viewers", ", ".join(names))
            await self.push_files()
        st = self.status()
        st["sent"] = names
        return web.json_response(st)

    @staticmethod
    def _copy_in(paths):
        folder = ensure_shared_dir()
        names = []
        for src in paths:
            if not os.path.isfile(src):
                continue
            if os.path.dirname(os.path.realpath(src)) == os.path.realpath(folder):
                names.append(os.path.basename(src))  # already shared
                continue
            dst = reserve_name(folder, safe_filename(os.path.basename(src)))
            try:
                shutil.copyfile(src, dst)
                try:
                    shutil.copystat(src, dst)
                    os.utime(dst, None)  # newest first in viewers' lists
                except OSError:
                    pass
            except Exception:
                try:
                    os.remove(dst)
                except OSError:
                    pass
                raise
            names.append(os.path.basename(dst))
        return names

    # ---- files (viewer, session token)
    def session_for(self, request):
        tok = request.headers.get("X-LV-Session") or request.query.get("s") or ""
        s = self.by_token.get(tok) if tok else None
        if s is None or s.closed:
            return None
        return s

    async def api_files_list(self, request):
        if self.session_for(request) is None:
            return self._err("Not connected", 401)
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(self.io_ex, list_shared_files)
        resp = web.json_response({"files": files, "folder": display_path(SHARED_DIR)})
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def api_files_download(self, request):
        s = self.session_for(request)
        if s is None:
            return self._err("Not connected", 401)
        name = request.query.get("name", "")
        path = resolve_shared_file(name)
        if path is None:
            bad = (not name or "/" in name or "\\" in name or name in (".", "..") or
                   name.startswith(".."))
            return self._err("Bad file name" if bad else "File not found", 400 if bad else 404)
        log.info("%s (%s) downloads %s", s.device, s.ip, name)
        resp = web.FileResponse(path)
        resp.headers["Content-Disposition"] = content_disposition(os.path.basename(path))
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    async def api_files_upload(self, request):
        s = self.session_for(request)
        if s is None:
            return self._err("Not connected", 401)
        if not self.allow_control:
            return self._err("This computer only allows viewing", 403)
        loop = asyncio.get_event_loop()
        try:
            reader = await request.multipart()
        except Exception:
            return self._err("Expected a multipart upload")
        folder = await loop.run_in_executor(self.io_ex, ensure_shared_dir)
        saved = []
        try:
            while True:
                part = await reader.next()
                if part is None:
                    break
                if getattr(part, "name", None) != "file" or not getattr(part, "filename", None):
                    await part.release()
                    continue
                name = safe_filename(part.filename)
                tmp = os.path.join(folder, ".lv-upload-%s.part" % uuid.uuid4().hex)
                f = await loop.run_in_executor(self.io_ex, open, tmp, "wb")
                done = False
                try:
                    size = 0
                    while True:
                        chunk = await part.read_chunk(1 << 20)
                        if not self.allow_control or self.paused or s.closed:
                            raise PermissionError("Sharing or control was turned off during the upload")
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > UPLOAD_MAX:
                            raise _TooLarge(name)
                        await loop.run_in_executor(self.io_ex, f.write, chunk)
                    await loop.run_in_executor(self.io_ex, f.close)
                    final = await loop.run_in_executor(self.io_ex, self._finish_upload,
                                                       tmp, folder, name)
                    done = True
                finally:
                    if not done:
                        try:
                            f.close()
                        except Exception:
                            pass
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                fname = os.path.basename(final)
                saved.append(fname)
                self.received.appendleft({"name": fname, "from": s.device, "at": time.time()})
                log.info("Received %s (%d bytes) from %s (%s)", fname, size, s.device, s.ip)
                self.notify(i18n.t("notify.received", name=fname, device=i18n.device_label(s.device)))
        except _TooLarge as e:
            return self._err("%s is larger than 4 GB" % e.args[0], 413)
        except PermissionError as e:
            return self._err(str(e), 403)
        except OSError as e:
            log.warning("Upload failed: %s", e)
            return self._err("Couldn't save the file: %s" % (e.strerror or e), 507)
        except Exception as e:
            log.info("Upload from %s interrupted: %s", s.ip, e)
            return self._err("Upload interrupted")
        finally:
            if saved:
                await self.push_files()
        return web.json_response({"saved": saved})

    @staticmethod
    def _finish_upload(tmp, folder, name):
        final = reserve_name(folder, name)
        os.replace(tmp, final)
        return final

    async def push_files(self):
        loop = asyncio.get_event_loop()
        try:
            files = await loop.run_in_executor(self.io_ex, list_shared_files)
            self._files_sig = tuple((f["name"], f["size"], f["mtime"]) for f in files)
        except Exception:
            pass
        await self.broadcast({"t": "files"})

    async def broadcast(self, obj, exclude=None):
        text = json.dumps(obj)
        for s in list(self.sessions.values()):
            if s is exclude or s.closed:
                continue
            try:
                await s.ws.send_str(text)
            except Exception:
                pass

    # ---- clipboard
    async def clip_get(self):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.clip.ex, self.clip.get)

    async def clip_set(self, text, session):
        loop = asyncio.get_event_loop()
        self._clip_origin = (text, session.id)
        await loop.run_in_executor(self.clip.ex, self.clip.set, text)

    async def _poll_clipboard(self):
        loop = asyncio.get_event_loop()
        seq = await loop.run_in_executor(self.clip.ex, self.clip.seq)
        if seq is not None and seq == self._clip_seq and self._clip_last is not None:
            return
        self._clip_seq = seq
        text = await self.clip_get()
        if self._clip_last is None:
            self._clip_last = text  # baseline: don't push what was there before anyone connected
            return
        if text == self._clip_last:
            return
        self._clip_last = text
        origin = None
        if self._clip_origin is not None and self._clip_origin[0] == text:
            origin = self.sessions.get(self._clip_origin[1])
        self._clip_origin = None
        if not text or len(text.encode("utf-8")) > CLIP_MAX:
            return
        await self.broadcast({"t": "clip", "s": text, "auto": True}, exclude=origin)

    # ---- background watcher: clipboard (1 s), shared folder (2 s), keep-awake
    async def _watch_loop(self):
        loop = asyncio.get_event_loop()
        while True:
            try:
                if self.sessions:
                    if self.clip.available:
                        try:
                            await self._poll_clipboard()
                        except Exception as e:
                            log.debug("Clipboard poll failed: %s", e)
                    self._files_tick += 1
                    if self._files_tick % 2 == 0:
                        files = await loop.run_in_executor(self.io_ex, list_shared_files)
                        sig = tuple((f["name"], f["size"], f["mtime"]) for f in files)
                        if self._files_sig is None:
                            self._files_sig = sig
                        elif sig != self._files_sig:
                            self._files_sig = sig
                            await self.broadcast({"t": "files"})
                else:
                    self._clip_last = None
                    self._clip_seq = None
                    self._files_sig = None
                self.update_awake()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("watch loop: %s", e)
            await asyncio.sleep(1.0)

    def update_awake(self):
        want = bool(self.sessions) and not self.paused and self.setting("keepAwake")
        try:
            self.awake.set(want)
        except Exception as e:
            log.debug("keep awake: %s", e)

    # ---- easy address (mDNS + conflict suffixing)
    def _pick_short(self):
        base = self.short_want
        cur = self.short
        now = time.time()
        held = [(p["short"], p["id"]) for p in self.peers.values()
                if p.get("short") and now - p["seen"] <= PEER_TTL]

        def blocked(c):
            if self._foreign.get(c, 0) > now:
                return True
            for s, pid in held:
                # Incumbent keeps a name; on a tie the smaller id wins.
                if s == c and (c != cur or pid < self.id):
                    return True
            return False
        for i in range(1, 100):
            c = base if i == 1 else "%s-%d" % (base, i)
            if not blocked(c):
                return c
        return base

    async def _address_loop(self):
        self._addr_event = asyncio.Event()
        while True:
            try:
                await self._refresh_address()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("address refresh: %s", e)
            try:
                await asyncio.wait_for(self._addr_event.wait(), 3.0)
            except asyncio.TimeoutError:
                pass
            self._addr_event.clear()

    def _mdns_fail(self, e):
        self.mdns_ok = False
        self._mdns_state = None
        self._mdns_retry_at = time.monotonic() + 60
        if not self._mdns_logged:
            self._mdns_logged = True
            log.warning("mDNS (%s.local) unavailable (%s); showing the IP address instead.",
                        self.short, e)

    async def _refresh_address(self):
        loop = asyncio.get_event_loop()
        run = functools.partial(loop.run_in_executor, self._mdns_ex)
        ip = get_lan_ip()
        if self.mdns_ok is False and time.monotonic() < self._mdns_retry_at:
            self.short = self._pick_short()
            return
        target = self._pick_short()
        if target != self._probed:
            ours = local_ipv4_set()
            for _ in range(6):
                try:
                    taken = await run(self._mdns.probe, target, ours)
                except Exception as e:
                    self._mdns_fail(e)
                    self.short = target
                    return
                if not taken:
                    break
                log.info("%s.local is used by another device on this network", target)
                self._foreign[target] = time.time() + 60
                target = self._pick_short()
            self._probed = target
        if target != self.short:
            log.info("Easy address is now %s.local", target)
        self.short = target
        if ip.startswith("127."):
            return  # no network right now
        port = EASY_PORT if self.easy_bound else self.port
        want = (self.short, ip, port, self.name)
        if want != self._mdns_state:
            try:
                await run(self._mdns.register, self.short, ip, port, self.name, self.id)
            except Exception as e:
                self._mdns_fail(e)
                return
            if self._mdns_state is None or self.mdns_ok is not True:
                log.info("Advertising http://%s.local (%s) via mDNS", self.short, ip)
            self._mdns_state = want
            self.mdns_ok = True
            if self._mdns_logged:
                self._mdns_logged = False

    async def _stop_mdns(self):
        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(loop.run_in_executor(self._mdns_ex, self._mdns.close), 4)
        except Exception as e:
            log.debug("mDNS close: %s", e)
        self._mdns_ex.shutdown(wait=False)

    # ---- discovery
    def _disc_fail(self, what, e):
        if not self._disc_error_logged:
            self._disc_error_logged = True
            log.warning("Discovery %s failed (%s); peer discovery disabled/limited.", what, e)

    async def on_startup(self, app):
        self.loop = asyncio.get_event_loop()
        await self.start_discovery()
        self._tasks.append(asyncio.ensure_future(self._watch_loop()))
        self._tasks.append(asyncio.ensure_future(self._update_loop()))
        self._tasks.append(asyncio.ensure_future(self._address_loop()))
        asyncio.get_event_loop().run_in_executor(self.io_ex, self.nearby.start)
        if self.cloud_enabled():
            await self.start_cloud()

    async def start_discovery(self):
        loop = asyncio.get_event_loop()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.setblocking(False)
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: DiscoveryProtocol(self), sock=sock)
        except Exception as e:
            self._disc_fail("listen", e)
            self._transport = None
        self._tasks.append(asyncio.ensure_future(self._broadcast_loop()))

    def _discovery_payload(self):
        return json.dumps({"app": APP, "name": self.name, "os": OS_NAME, "port": self.port,
                           "id": self.id, "short": self.short,
                           "easy": self.easy_bound,
                           # lets your other computers offer "use the same server" (an address, not a secret)
                           "cloud": self.private_address() or None}).encode("utf-8")

    async def _broadcast_loop(self):
        send_sock = None
        while True:
            try:
                payload = self._discovery_payload()
                if self._transport is not None:
                    self._transport.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
                else:
                    if send_sock is None:
                        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        send_sock.setblocking(False)
                    send_sock.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._disc_fail("broadcast", e)
            try:
                await asyncio.sleep(DISCOVERY_INTERVAL)
            except asyncio.CancelledError:
                if send_sock is not None:
                    send_sock.close()
                raise

    async def on_cleanup(self, app):
        try:
            self.vdisplays.destroy_all()
        except Exception:
            pass
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        if self._transport is not None:
            self._transport.close()
        self.awake.set(False)
        await self._stop_mdns()
        self.nearby.stop()
        self.io_ex.shutdown(wait=False)
        self.clip.ex.shutdown(wait=False)

    async def on_shutdown(self, app):
        try:
            await self.stop_cloud()
        except Exception as e:
            log.debug("Stopping internet access: %s", e)
        for p in list(self.pending.values()):
            if not p["future"].done():
                p["future"].set_result("Server shutdown")
        for ws in list(self.websockets):
            try:
                await ws.close(code=1001, message=b"Server shutdown")
            except Exception:
                pass

    # ---- auth
    def _locked_for(self, ip):
        f = self.failures.get(ip)
        if f and f.get("until", 0) > time.time():
            return int(f["until"] - time.time()) + 1
        return 0

    async def _register_failure(self, ip):
        f = self.failures.setdefault(ip, {"count": 0, "until": 0})
        if f["until"] and f["until"] <= time.time():
            f["until"] = 0
        f["count"] += 1
        if f["count"] >= MAX_FAILS:
            f["count"] = 0
            f["until"] = time.time() + LOCKOUT_SECS
            log.warning("Locking out %s for %d s after %d failed PIN attempts",
                        ip, LOCKOUT_SECS, MAX_FAILS)
        await asyncio.sleep(1.0)

    # ---- websocket
    async def handle_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * CLIP_MAX)  # JSON escaping
        await ws.prepare(request)
        await self.serve_viewer(ws, request.remote or "?", request.headers.get("User-Agent", ""))
        return ws

    async def serve_viewer(self, ws, ip, ua, remote=False, track=None):
        """Sign in, approve and run one viewer.

        `ws` is an aiohttp WebSocket (Wi-Fi, PIN) or a remote.ChannelSocket (internet, password;
        the video then goes over `track`). Both speak the same JSON protocol (PROTOCOL.md).
        """
        secret = str(self.cfg.get("cloudPassword") or "") if remote else self.pin
        wrong = "Wrong password" if remote else "Wrong PIN"
        lock_key = ("net:" + ip) if remote else ip  # internet attempts are throttled separately

        # --- auth phase
        try:
            msg = await asyncio.wait_for(ws.receive(), AUTH_TIMEOUT)
        except asyncio.TimeoutError:
            await self._send_error_close(ws, "Auth timeout")
            return
        if msg.type != WSMsgType.TEXT:
            await ws.close()
            return
        try:
            data = json.loads(msg.data)
        except Exception:
            data = {}
        locked = self._locked_for(lock_key)
        if locked:
            await self._send_error_close(ws, "Locked out, try again in %d s" % locked)
            log.info("Rejected %s (locked out, %d s left)", ip, locked)
            return
        if remote and self.net_paused_for():
            mins = (self.net_paused_for() + 59) // 60
            await self._send_error_close(ws, "Too many wrong passwords. Internet sign-ins are paused for "
                                             "%d more minute%s" % (mins, "" if mins == 1 else "s"))
            log.info("Rejected %s (internet sign-ins paused)", ip)
            return
        if self.paused:
            await self._send_error_close(ws, MSG_PAUSED)
            log.info("Rejected %s (sharing paused)", ip)
            return
        pin = data.get("pin") if isinstance(data, dict) and data.get("t") == "auth" else None
        if not secret or not isinstance(pin, str) or not hmac.compare_digest(
                pin.strip().encode("utf-8"), secret.encode("utf-8")):
            log.info("%s from %s", wrong, ip)
            if remote:
                self.net_failure(ip)
            await self._register_failure(lock_key)
            locked = self._locked_for(lock_key)
            if locked:
                await self._send_error_close(ws, "Locked out, try again in %d s" % locked)
            else:
                await self._send_error_close(ws, wrong)
            return
        self.failures.pop(lock_key, None)

        until = self.kicked.pop(ip, 0)
        if until > time.time():
            await self._send_error_close(ws, MSG_KICKED)
            log.info("Rejected %s (disconnected by the host moments ago)", ip)
            return

        early = []  # text messages that arrive while waiting for approval
        self.websockets.add(ws)
        try:
            # Internet: a device seen for the first time must be confirmed on this computer by typing
            # the code it shows (proves someone has both); afterwards it's remembered.
            device = data.get("device") if remote and isinstance(data, dict) else None
            trusted = self.find_trusted(device) if remote else None
            if remote and trusted is None:
                code = "%06d" % random.SystemRandom().randint(0, 999999)
                verdict = await self._await_approval(ws, ip, ua, early, code=code)
                if verdict is None:
                    return
                if verdict is not True:
                    await self._send_error_close(ws, verdict)
                    log.info("New device from %s not confirmed: %s", ip, verdict)
                    return
                if isinstance(device, dict):
                    self.add_trusted(device, "%s · %s" % (device_from_ua(ua), time.strftime("%d %b %Y")))
                if self.paused:
                    await self._send_error_close(ws, MSG_PAUSED)
                    return
            elif trusted is not None:
                self.touch_trusted(trusted)
            if self.setting("askBeforeConnect") and not (remote and trusted is None):
                verdict = await self._await_approval(ws, ip, ua, early)
                if verdict is None:  # viewer gave up / closed
                    return
                if verdict is not True:
                    await self._send_error_close(ws, verdict)
                    log.info("Connection from %s not approved: %s", ip, verdict)
                    return
                if self.paused:
                    await self._send_error_close(ws, MSG_PAUSED)
                    return

            # --- session
            if remote:
                session = RemoteSession(self, ws, ip, ua, early, track=track)
            else:
                session = Session(self, ws, ip, ua, early)
            self.sessions[session.id] = session
            self.by_token[session.token] = session
            log.info("Client connected: %s (%s)", ip, session.device)
            self.remember_device(session.device, remote, ip)
            self.notify(i18n.t("notify.viewing", device=i18n.device_label(session.device), ip=ip))
            self.update_awake()
            try:
                await session.run()
            finally:
                self.sessions.pop(session.id, None)
                self.by_token.pop(session.token, None)
                session.closed = True
                self.update_awake()
                log.info("Client disconnected: %s", ip)
        finally:
            self.websockets.discard(ws)

    async def _await_approval(self, ws, ip, ua, early, code=None):
        """Hold the auth reply until the host approves.

        Returns True (approved), an error string (declined / timed out / paused), or None
        if the viewer closed the socket while waiting.
        """
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        rid = uuid.uuid4().hex[:12]
        device = device_from_ua(ua)
        timeout = PAIR_TIMEOUT if code else APPROVAL_TIMEOUT
        self.pending[rid] = {"ip": ip, "device": device, "ua": ua, "at": time.time(),
                             "future": fut, "code": code, "tries": 0, "timeout": timeout}
        log.info("Waiting for %s: %s (%s)", "pairing" if code else "approval", ip, device)
        self.notify(i18n.t("notify.pairing" if code else "notify.asking", device=i18n.device_label(device), ip=ip))
        self.attention()
        recv = None
        try:
            try:  # additive message; older viewers ignore unknown types
                msg = {"t": "pending", "msg": "Waiting for approval on the host…"}
                if code:
                    msg = {"t": "pending", "code": code, "timeout": int(timeout),
                           "msg": "Type this code into Hop on %s to trust this device" % self.name}
                await ws.send_str(json.dumps(msg))
            except Exception:
                return None
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log.info("Approval timed out for %s", ip)
                    return MSG_PAIR_DECLINED if code else MSG_DECLINED
                if recv is None:
                    recv = asyncio.ensure_future(ws.receive())
                done, _ = await asyncio.wait({fut, recv}, timeout=remaining,
                                             return_when=asyncio.FIRST_COMPLETED)
                if recv in done:
                    msg = recv.result()
                    recv = None
                    if msg.type == WSMsgType.TEXT:
                        if len(early) < 32:
                            early.append(msg.data)
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED,
                                      WSMsgType.ERROR):
                        log.info("%s left before being approved", ip)
                        return None
                if fut.done():
                    return fut.result()
        finally:
            self.pending.pop(rid, None)
            if recv is not None:
                recv.cancel()
                try:
                    await recv
                except (asyncio.CancelledError, Exception):
                    pass

    @staticmethod
    async def _send_error_close(ws, text):
        try:
            await ws.send_str(json.dumps({"t": "error", "msg": text}))
            await ws.close()
        except Exception:
            pass


class _TooLarge(Exception):
    pass


class Session(object):
    remote = False

    def __init__(self, server, ws, ip, ua="", early=None):
        self.server = server
        self.ws = ws
        self.ip = ip
        self.id = uuid.uuid4().hex[:12]
        self.token = secrets.token_hex(16)
        self.ua = ua
        self.device = device_from_ua(ua)
        self.connected_at = time.time()
        self.early = list(early or [])
        self.sent = collections.deque()  # (monotonic ts, bytes) of recent frames
        self.loop = asyncio.get_event_loop()
        self.cap_ex = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="lv-cap")
        self.inp_ex = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="lv-inp")
        self.input = InputState()
        self.monitors = []
        self.monitor_index = 1
        self.quality = 60
        self.maxw = 1600
        self.fps = 20
        self.ack = asyncio.Event()
        self.reset_frame = False
        self.closed = False

    @property
    def monitor(self):
        for m in self.monitors:
            if m["index"] == self.monitor_index:
                return m
        return self.monitors[0]

    def describe(self, now=None):
        now = now or time.time()
        self._prune()
        n = len(self.sent)
        span = 3.0
        age = time.monotonic() - (self.sent[0][0] if n else time.monotonic())
        if n > 1:
            span = min(3.0, max(age, 0.5))
        nbytes = sum(b for _, b in self.sent)
        return {"id": self.id, "ip": self.ip, "device": self.device, "ua": self.ua[:300],
                "remote": self.remote,
                "connectedAt": self.connected_at, "seconds": int(now - self.connected_at),
                "fps": round(n / span, 1) if n else 0.0,
                "kbps": int(nbytes * 8 / 1000.0 / span) if n else 0}

    def _prune(self):
        cutoff = time.monotonic() - 3.0
        while self.sent and self.sent[0][0] < cutoff:
            self.sent.popleft()

    async def kick(self, text):
        """Tell the viewer why and close (used for pause / host-side disconnect)."""
        await HopServer._send_error_close(self.ws, text)

    def release_input(self):
        if not self.closed:
            self._run_input(self.input.release_all)

    async def send_json(self, obj):
        try:
            await self.ws.send_str(json.dumps(obj))
        except Exception as e:
            log.debug("send to %s failed: %s", self.ip, e)

    def features(self):
        return ((["clipboard"] if self.server.clip.available else []) + ["files"] +
                (["extend"] if self.server.vdisplays.supported else []))

    def public_monitors(self):
        vd = self.server.vdisplays.bounds(self.id) if self.server.vdisplays.supported else None
        return [{"index": m["index"], "width": m["width"], "height": m["height"],
                 "virtual": bool(vd and (m["left"], m["top"], m["width"], m["height"]) == vd)}
                for m in self.monitors]

    async def _refresh_monitors(self):
        def fresh():
            _close_sct()  # mss caches the display list per instance
            return list_monitors()
        self.monitors = await self.loop.run_in_executor(self.cap_ex, fresh)

    async def extend(self, d):
        """Second-screen mode: add a virtual display sized for the viewer and stream it."""
        srv = self.server
        if not srv.allow_control:
            await self.send_json({"t": "extend.err", "msg": "This computer only allows viewing"})
            return
        if not srv.vdisplays.supported:
            await self.send_json({"t": "extend.err", "msg": "This computer can't add a display by itself. "
                                  "Add a virtual display (or an HDMI dummy plug), then pick it in Settings → Display."})
            return
        try:
            w, h = int(d.get("w")), int(d.get("h"))
        except (TypeError, ValueError):
            await self.send_json({"t": "extend.err", "msg": "Bad screen size"})
            return
        side = d.get("side") if d.get("side") in ("left", "right", "above") else "right"
        try:
            await self.loop.run_in_executor(srv.io_ex, srv.vdisplays.create, self.id, w, h,
                                            bool(d.get("hidpi", True)), side)
            b = await self.loop.run_in_executor(srv.io_ex, srv.vdisplays.bounds, self.id)
            await self._refresh_monitors()
        except Exception as e:
            log.warning("Second screen failed for %s: %s", self.ip, e)
            await self.send_json({"t": "extend.err", "msg": "Couldn't add a display: %s" % e})
            return
        idx = next((m["index"] for m in self.monitors
                    if (m["left"], m["top"], m["width"], m["height"]) == b), self.monitors[-1]["index"])
        self.monitor_index = idx
        self.reset_frame = True
        self.ack.set()
        log.info("%s (%s) is now a second screen (%dx%d)", self.device, self.ip, b[2], b[3])
        srv.notify(i18n.t("notify.extendOn", device=i18n.device_label(self.device)))
        await self.send_json({"t": "extend.ok", "monitor": idx, "monitors": self.public_monitors(),
                              "width": b[2], "height": b[3]})

    async def extend_stop(self):
        srv = self.server
        removed = await self.loop.run_in_executor(srv.io_ex, srv.vdisplays.destroy, self.id)
        if removed:
            await asyncio.sleep(0.5)
            await self._refresh_monitors()
            self.monitor_index = self.monitors[0]["index"]
            self.reset_frame = True
            self.ack.set()
        await self.send_json({"t": "extend.off", "monitor": self.monitor_index,
                              "monitors": self.public_monitors()})

    async def run(self):
        srv = self.server
        features = self.features()
        try:
            self.monitors = await self.loop.run_in_executor(self.cap_ex, list_monitors)
            await self.ws.send_str(json.dumps({
                "t": "hello", "name": srv.name, "os": OS_NAME,
                "monitors": self.public_monitors(),
                "control": srv.allow_control,
                "token": self.token, "short": srv.short, "url": srv.primary_url(),
                "features": features,
            }))
        except Exception as e:
            log.error("Session setup failed for %s: %s", self.ip, e)
            await HopServer._send_error_close(self.ws, "Screen capture failed: %s" % e)
            self._shutdown_executors()
            return

        for raw in self.early:  # messages sent while the host was approving
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    await self.handle(data)
            except Exception as e:
                log.debug("Bad early message from %s: %s", self.ip, e)
        self.early = []

        stream = asyncio.ensure_future(self.stream_loop())
        try:
            await self.read_loop()
        finally:
            self.closed = True
            self.ack.set()
            stream.cancel()
            try:
                await stream
            except (asyncio.CancelledError, Exception):
                pass
            try:
                await self.loop.run_in_executor(self.inp_ex, self.input.release_all)
            except Exception as e:
                log.warning("release_all failed for %s: %s", self.ip, e)
            if self.server.vdisplays.destroy(self.id):  # a second screen goes away with its viewer
                self.server.notify(i18n.t("notify.extendOff", device=i18n.device_label(self.device)))
            self._shutdown_executors()

    def _shutdown_executors(self):
        try:
            self.cap_ex.submit(_close_sct)
        except Exception:
            pass
        self.cap_ex.shutdown(wait=False)
        self.inp_ex.shutdown(wait=False)

    # ---- server -> client
    async def stream_loop(self):
        last_raw = None
        last_cursor = None
        while not self.closed and not self.ws.closed:
            t0 = time.monotonic()
            if self.reset_frame:
                self.reset_frame = False
                last_raw = None
            mon = self.monitor
            try:
                jpeg, raw = await self.loop.run_in_executor(
                    self.cap_ex, capture_frame, mon, self.maxw, self.quality, last_raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Capture failed: %s", e)
                await asyncio.sleep(1.0)
                continue

            # cursor
            try:
                cx, cy = mouse.position
                cur = self._norm_cursor(mon, cx, cy)
                if cur != last_cursor:
                    last_cursor = cur
                    await self.ws.send_str(json.dumps(
                        {"t": "cursor", "x": cur[0], "y": cur[1], "visible": cur[2]}))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("Cursor position failed: %s", e)

            if jpeg is not None and not self.reset_frame:
                last_raw = raw
                self.ack.clear()
                try:
                    await self.ws.send_bytes(jpeg)
                except (ConnectionResetError, RuntimeError):
                    break
                self.sent.append((time.monotonic(), len(jpeg)))
                if len(self.sent) > 200:
                    self._prune()
                try:
                    await asyncio.wait_for(self.ack.wait(), ACK_TIMEOUT)
                except asyncio.TimeoutError:
                    pass

            delay = 1.0 / max(1, self.fps) - (time.monotonic() - t0)
            if delay > 0:
                await asyncio.sleep(delay)

    @staticmethod
    def _norm_cursor(mon, cx, cy):
        w, h = float(mon["width"]), float(mon["height"])
        x = (cx - mon["left"]) / w
        y = (cy - mon["top"]) / h
        visible = 0.0 <= x < 1.0 and 0.0 <= y < 1.0
        return (round(min(1.0, max(0.0, x)), 4), round(min(1.0, max(0.0, y)), 4), visible)

    # ---- client -> server
    async def read_loop(self):
        async for msg in self.ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if isinstance(data, dict):
                        await self.handle(data)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("Bad message from %s: %s", self.ip, e)
            elif msg.type == WSMsgType.ERROR:
                log.debug("WS error from %s: %s", self.ip, self.ws.exception())
                break

    def _run_input(self, fn, *args):
        def wrapped():
            try:
                fn(*args)
            except Exception as e:
                log.warning("Input error (%s): %s", getattr(fn, "__name__", fn), e)
        # fire and forget, ordered by the single-worker executor
        self.loop.run_in_executor(self.inp_ex, wrapped)

    async def handle(self, d):
        t = d.get("t")
        if t in INPUT_TYPES and not self.server.allow_control:
            log.debug("View-only: ignored %r from %s", t, self.ip)
            return  # view-only: "Allow control" is off on the host
        if t == "ack":
            self.ack.set()
        elif t == "settings":
            self.apply_settings(d)
        elif t == "move":
            self._run_input(self.input.move, self.monitor, d.get("x"), d.get("y"))
        elif t in ("down", "up"):
            self._run_input(self.input.button, self.monitor, d.get("b", "left"),
                            d.get("x"), d.get("y"), t == "down")
        elif t == "click":
            try:
                n = int(d.get("n", 1))
            except (TypeError, ValueError):
                n = 1
            self._run_input(self.input.click, self.monitor, d.get("b", "left"),
                            d.get("x"), d.get("y"), n)
        elif t == "scroll":
            self._run_input(self.input.scroll, int(d.get("dx", 0) or 0), int(d.get("dy", 0) or 0))
        elif t == "key":
            self._run_input(self.input.key, d.get("k"), bool(d.get("down")))
        elif t == "text":
            self._run_input(self.input.text, d.get("s"))
        elif t == "releaseall":
            self._run_input(self.input.release_all)
        elif t == "clip.get":
            await self.clip_get()
        elif t == "clip.set":
            await self.clip_set(d.get("s"))
        elif t == "extend":
            await self.extend(d)
        elif t == "extend.stop":
            await self.extend_stop()

    async def clip_get(self):
        srv = self.server
        if not srv.clip.available:
            await self.send_json({"t": "clip", "s": "",
                                  "error": "The clipboard isn't available on this computer"})
            return
        try:
            text = await srv.clip_get()
        except Exception as e:
            log.info("Reading the clipboard failed: %s", e)
            await self.send_json({"t": "clip", "s": "", "error": "Couldn't read the clipboard"})
            return
        if len(text.encode("utf-8")) > CLIP_MAX:
            await self.send_json({"t": "clip", "s": "",
                                  "error": "The clipboard text is larger than 1 MB"})
            return
        await self.send_json({"t": "clip", "s": text})

    async def clip_set(self, s):
        srv = self.server
        if not srv.allow_control or not srv.clip.available or not isinstance(s, str):
            return  # view-only: ignored (see PROTOCOL.md)
        if len(s.encode("utf-8")) > CLIP_MAX:
            return
        try:
            await srv.clip_set(s, self)
        except Exception as e:
            log.info("Setting the clipboard failed: %s", e)
            return
        log.info("%s (%s) set the clipboard (%d chars)", self.device, self.ip, len(s))
        await self.send_json({"t": "clip.ok"})

    def apply_settings(self, d):
        def clamp_int(v, lo, hi, cur):
            try:
                return max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                return cur
        changed = False
        if "monitor" in d:
            idx = clamp_int(d["monitor"], 1, 64, self.monitor_index)
            if any(m["index"] == idx for m in self.monitors) and idx != self.monitor_index:
                self.monitor_index = idx
                changed = True
        if "quality" in d:
            q = clamp_int(d["quality"], 20, 95, self.quality)
            changed = changed or q != self.quality
            self.quality = q
        if "maxw" in d:
            w = clamp_int(d["maxw"], 640, 3840, self.maxw)
            changed = changed or w != self.maxw
            self.maxw = w
        if "fps" in d:
            self.fps = clamp_int(d["fps"], 1, 30, self.fps)
        if changed:
            self.reset_frame = True  # force a fresh frame even if pixels are unchanged
            self.ack.set()


class RemoteSession(Session):
    """An internet viewer (remote.CloudLink): video over a WebRTC track, JSON over a data channel."""

    remote = True

    FILE_PIECE = 40000  # raw bytes per file message: base64 ≈ 53 KB, under the 64 KiB channel limit

    def __init__(self, server, ws, ip, ua="", early=None, track=None):
        Session.__init__(self, server, ws, ip, ua, early)
        self.track = track
        self.maxw = 1600
        self.device = "%s · Internet" % self.device
        self._up = None              # upload in progress: {"id","name","tmp","f","got","folder"}
        self._down_abort = set()
        self._tasks = set()

    def features(self):
        # Files go over the data channel instead of HTTP (see PROTOCOL.md, "Internet access").
        return ((["clipboard"] if self.server.clip.available else []) + ["files"] +
                (["extend"] if self.server.vdisplays.supported else []))

    async def run(self):
        try:
            await Session.run(self)
        finally:
            for t in list(self._tasks):
                t.cancel()
            await self._up_cleanup()

    def _spawn(self, coro):
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def handle(self, d):
        t = d.get("t")
        if t == "files.list":
            await self._files_list()
        elif t == "down":
            self._spawn(self._download(d))
        elif t == "down.abort":
            self._down_abort.add(str(d.get("id") or ""))
        elif t in ("up.start", "up.data", "up.end", "up.abort"):
            await self._upload(t, d)
        else:
            await Session.handle(self, d)

    # ---- files over the data channel
    async def _files_list(self):
        files = await self.loop.run_in_executor(self.server.io_ex, list_shared_files)
        await self.send_json({"t": "files.list", "files": files, "folder": display_path(SHARED_DIR)})

    async def _download(self, d):
        did = str(d.get("id") or "")[:40]
        name = d.get("name")
        path = resolve_shared_file(name)
        if path is None:
            await self.send_json({"t": "down.err", "id": did, "msg": "That file isn't there anymore"})
            return
        io_ex = self.server.io_ex
        try:
            f = await self.loop.run_in_executor(io_ex, open, path, "rb")
        except OSError as e:
            await self.send_json({"t": "down.err", "id": did, "msg": "Couldn't open the file: %s" % (e.strerror or e)})
            return
        log.info("%s (%s) downloads %s over the internet", self.device, self.ip, os.path.basename(path))
        try:
            size = os.fstat(f.fileno()).st_size
            await self.send_json({"t": "down.start", "id": did, "name": os.path.basename(path), "size": size})
            while not self.closed:
                if did in self._down_abort:
                    self._down_abort.discard(did)
                    return
                chunk = await self.loop.run_in_executor(io_ex, f.read, self.FILE_PIECE)
                if not chunk:
                    await self.send_json({"t": "down.end", "id": did})
                    return
                await self.ws.send_raw(json.dumps(
                    {"t": "down.data", "id": did, "d": base64.b64encode(chunk).decode("ascii")}))
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        except Exception as e:
            log.info("Download to %s failed: %s", self.ip, e)
            await self.send_json({"t": "down.err", "id": did, "msg": "Download failed"})
        finally:
            await self.loop.run_in_executor(io_ex, f.close)

    async def _up_cleanup(self):
        u, self._up = self._up, None
        if u is None:
            return
        try:
            await self.loop.run_in_executor(self.server.io_ex, u["f"].close)
        except Exception:
            pass
        try:
            os.remove(u["tmp"])
        except OSError:
            pass

    async def _up_fail(self, uid, msg):
        await self._up_cleanup()
        await self.send_json({"t": "up.err", "id": uid, "msg": msg})

    async def _upload(self, t, d):
        srv, io_ex = self.server, self.server.io_ex
        uid = str(d.get("id") or "")[:40]
        u = self._up
        if t == "up.start":
            await self._up_cleanup()
            if not srv.allow_control:
                await self.send_json({"t": "up.err", "id": uid, "msg": "This computer only allows viewing"})
                return
            try:
                expect = int(d.get("size"))
            except (TypeError, ValueError):
                await self.send_json({"t": "up.err", "id": uid, "msg": "Invalid file size"})
                return
            if expect < 0:
                await self.send_json({"t": "up.err", "id": uid, "msg": "Invalid file size"})
                return
            name = safe_filename(d.get("name"))
            if expect > UPLOAD_MAX:
                await self.send_json({"t": "up.err", "id": uid, "msg": "%s is larger than 4 GB" % name})
                return
            try:
                folder = await self.loop.run_in_executor(io_ex, ensure_shared_dir)
                tmp = os.path.join(folder, ".lv-upload-%s.part" % uuid.uuid4().hex)
                f = await self.loop.run_in_executor(io_ex, open, tmp, "wb")
            except OSError as e:
                await self.send_json({"t": "up.err", "id": uid, "msg": "Couldn't save the file: %s" % (e.strerror or e)})
                return
            self._up = {"id": uid, "name": name, "tmp": tmp, "f": f, "got": 0,
                        "expected": expect, "folder": folder}
            await self.send_json({"t": "up.ready", "id": uid})
            return
        if u is None or u["id"] != uid:
            return
        if t == "up.abort":
            await self._up_cleanup()
            log.info("Upload of %s from %s cancelled", u["name"], self.ip)
        elif t == "up.data":
            if not srv.allow_control:
                await self._up_fail(uid, "This computer only allows viewing")
                return
            try:
                raw = base64.b64decode(str(d.get("d") or ""), validate=True)
            except Exception:
                await self._up_fail(uid, "The upload was damaged in transit")
                return
            u["got"] += len(raw)
            if u["got"] > u["expected"]:
                await self._up_fail(uid, "The upload doesn't match its expected size")
                return
            if u["got"] > UPLOAD_MAX:
                await self._up_fail(uid, "%s is larger than 4 GB" % u["name"])
                return
            try:
                await self.loop.run_in_executor(io_ex, u["f"].write, raw)
            except OSError as e:
                await self._up_fail(uid, "Couldn't save the file: %s" % (e.strerror or e))
        elif t == "up.end":
            if not srv.allow_control:
                await self._up_fail(uid, "This computer only allows viewing")
                return
            if u["got"] != u["expected"]:
                await self._up_fail(uid, "The upload is incomplete; send the file again")
                return
            self._up = None
            try:
                await self.loop.run_in_executor(io_ex, u["f"].close)
                final = await self.loop.run_in_executor(io_ex, HopServer._finish_upload,
                                                        u["tmp"], u["folder"], u["name"])
            except OSError as e:
                try:
                    os.remove(u["tmp"])
                except OSError:
                    pass
                await self.send_json({"t": "up.err", "id": uid, "msg": "Couldn't save the file: %s" % (e.strerror or e)})
                return
            fname = os.path.basename(final)
            srv.received.appendleft({"name": fname, "from": self.device, "at": time.time()})
            log.info("Received %s (%d bytes) from %s (%s)", fname, u["got"], self.device, self.ip)
            srv.notify(i18n.t("notify.received", name=fname, device=i18n.device_label(self.device)))
            await self.send_json({"t": "up.done", "id": uid, "name": fname})
            await srv.push_files()

    async def _grab(self):
        return await self.loop.run_in_executor(self.cap_ex, capture_image, self.monitor, self.maxw)

    async def stream_loop(self):
        # The video track pulls frames itself; this loop starts it and keeps the cursor and stats fresh.
        track = self.track
        track.fps = self.fps
        track.source = self._grab
        last_cursor = None
        last_frames = track.frames
        try:
            while not self.closed and not self.ws.closed:
                n = track.frames
                now = time.monotonic()
                for _ in range(max(0, n - last_frames)):
                    self.sent.append((now, 0))
                last_frames = n
                if len(self.sent) > 200:
                    self._prune()
                try:
                    cx, cy = mouse.position
                    cur = self._norm_cursor(self.monitor, cx, cy)
                    if cur != last_cursor:
                        last_cursor = cur
                        await self.ws.send_str(json.dumps(
                            {"t": "cursor", "x": cur[0], "y": cur[1], "visible": cur[2]}))
                except asyncio.CancelledError:
                    raise
                except ConnectionResetError:
                    break
                except Exception as e:
                    log.debug("Cursor position failed: %s", e)
                await asyncio.sleep(1.0 / 30)
        finally:
            track.source = None

    def apply_settings(self, d):
        Session.apply_settings(self, d)
        if self.track is not None:
            self.track.fps = self.fps


# --------------------------------------------------------------------------- main

def _banner(server, urls, windowed, lang=None):
    """The terminal banner as (lines before the QR code, lines after it)."""
    def tr(key, **kw):
        return i18n.t(key, lang, **kw)
    open_line = tr("banner.open", url=urls[0])
    pad = " " * max(0, len(open_line) - len(urls[0]) - len(tr("banner.or", url="")))  # line up the addresses
    head = ["", "=" * 60, tr("banner.running", name=server.name, os=OS_NAME), "=" * 60, open_line]
    head += [pad + tr("banner.or", url=u) for u in urls[1:]]
    head += [tr("banner.pin", pin=server.pin), ""]
    tail = []
    if OS_NAME == "mac":
        tail.append(tr("banner.mac", app=responsible_app() or tr("banner.thisTerminal")))
    tail += [tr("banner.stopWindow" if windowed else "banner.stop"), ""]
    return head, tail


def _print_lines(lines, fallback):
    try:
        text = "\n".join(lines)
        if sys.stdout.encoding:
            text.encode(sys.stdout.encoding)  # a console that can't show the chosen language gets English
    except (UnicodeEncodeError, LookupError):
        text = "\n".join(fallback)
    print(text)


def print_banner(server, windowed=False):
    urls = server.urls()
    head, tail = _banner(server, urls, windowed)
    head_en, tail_en = _banner(server, urls, windowed, "en")
    _print_lines(head, head_en)
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(urls[0])
        qr.make(fit=True)
        qr.print_ascii(out=sys.stdout, invert=True)
    except Exception:
        pass
    _print_lines(tail, tail_en)
    try:
        sys.stdout.flush()
    except Exception:
        pass


def build_app(server):
    app = web.Application(middlewares=[server.make_guard()])
    app.router.add_get("/", server.handle_index)
    app.router.add_get("/api/info", server.handle_info)
    app.router.add_get("/api/peers", server.handle_peers)
    app.router.add_get("/ws", server.handle_ws)
    # Viewer features (session token from the WebSocket hello)
    app.router.add_get("/api/files", server.api_files_list)
    app.router.add_get("/api/files/download", server.api_files_download)
    app.router.add_post("/api/files/upload", server.api_files_upload)
    # Host window (loopback only, main port only, token-protected; see make_guard)
    app.router.add_get("/host", server.handle_host_page)
    app.router.add_get("/remote", server.handle_remote_page)
    app.router.add_get("/api/remote-config", server.api_remote_config)
    app.router.add_get("/api/host/status", server.api_status)
    app.router.add_post("/api/host/pause", server.api_pause)
    app.router.add_post("/api/host/resume", server.api_resume)
    app.router.add_post("/api/host/pin/new", server.api_new_pin)
    app.router.add_post("/api/host/pin", server.api_set_pin)
    app.router.add_post("/api/host/viewers/{sid}/disconnect", server.api_disconnect)
    app.router.add_post("/api/host/pending/{rid}/approve", server.api_approve)
    app.router.add_post("/api/host/pending/{rid}/deny", server.api_deny)
    app.router.add_post("/api/host/settings", server.api_settings)
    app.router.add_post("/api/host/open", server.api_open)
    app.router.add_post("/api/host/connect", server.api_connect)
    app.router.add_post("/api/host/files/open", server.api_files_open)
    app.router.add_post("/api/host/files/send", server.api_files_send)
    app.router.add_post("/api/host/activate", server.api_activate)
    app.router.add_post("/api/host/permission", server.api_permission)
    app.router.add_post("/api/host/link", server.api_open_link)
    app.router.add_post("/api/host/trusted/{tid}/forget", server.api_forget_device)
    app.router.add_post("/api/host/device/send", server.api_device_send)
    app.router.add_post("/api/host/device/mirror", server.api_device_mirror)
    app.router.add_post("/api/host/device/hide", server.api_device_hide)
    app.router.add_post("/api/host/update/check", server.api_update_check)
    app.router.add_post("/api/host/update/install", server.api_update_install)
    app.router.add_post("/api/host/restart", server.api_restart)
    app.router.add_post("/api/host/cloud/password/new", server.api_cloud_new_password)
    app.router.add_post("/api/host/cloud/password", server.api_cloud_set_password)
    if os.path.isdir(STATIC_DIR):
        app.router.add_static("/static/", STATIC_DIR)
    app.on_startup.append(server.on_startup)
    app.on_shutdown.append(server.on_shutdown)
    app.on_cleanup.append(server.on_cleanup)
    return app


class ServerThread(threading.Thread):
    """Runs the aiohttp app (main port + optional easy port 80) on its own event loop."""

    def __init__(self, server, app):
        threading.Thread.__init__(self, name="lv-server", daemon=True)
        self.server = server
        self.app = app
        self.loop = None
        self.error = None
        self.ready = threading.Event()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        srv = self.server
        runner = web.AppRunner(self.app, access_log=None, handle_signals=False)
        try:
            loop.run_until_complete(runner.setup())
            loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", srv.port).start())
        except Exception as e:
            self.error = e
            self.ready.set()
            try:
                loop.run_until_complete(runner.cleanup())
            except Exception:
                pass
            loop.close()
            return
        if srv.want_easy:
            try:
                loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", EASY_PORT).start())
                srv.easy_bound = True
                log.info("Also listening on port %d (easy address)", EASY_PORT)
            except Exception as e:
                log.info("Port %d unavailable (%s); the address keeps :%d.",
                         EASY_PORT, getattr(e, "strerror", None) or e, srv.port)
        self.ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(asyncio.wait_for(runner.cleanup(), 10))
            except Exception as e:
                log.debug("Server cleanup: %s", e)
            loop.close()

    def stop(self):
        loop = self.loop
        if loop is not None and self.is_alive():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
            self.join(12)


# --------------------------------------------------------------------------- app window

class WindowApi(object):
    """Exposed to host.html as window.pywebview.api (custom title-bar buttons on Windows)."""

    def __init__(self):
        self._window = None

    def minimize(self):
        if self._window is not None:
            self._window.minimize()

    def close(self):
        if self._window is not None:
            self._window.destroy()


class ViewerApi(object):
    """window.pywebview.api inside viewer windows: lets the page switch the window to full screen
    (the browser Fullscreen API isn't available in every embedded web view)."""

    def __init__(self):
        self._window = None
        self._full = False

    def toggle_fullscreen(self):
        if self._window is not None:
            self._window.toggle_fullscreen()
            self._full = not self._full
        return self._full

    def is_fullscreen(self):
        return self._full

    def close(self):
        if self._window is not None:
            self._window.destroy()


class WindowBridge(object):
    """What the server may ask of the GUI (called from the server thread)."""

    def __init__(self, main_window):
        self.main = main_window

    def open_viewer(self, url, title, fullscreen=False):
        import webview
        w, h = viewer_window_size()
        api = ViewerApi()
        win = webview.create_window(title, url, width=w, height=h, min_size=(480, 360),
                                    resizable=True, background_color="#0A0A0B",
                                    fullscreen=fullscreen, js_api=api)
        api._window = win
        api._full = bool(fullscreen)

    def airdrop(self, url):
        from AppKit import NSSharingService, NSURL
        from PyObjCTools import AppHelper

        def go():
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)  # the panel needs a front app
            svc = NSSharingService.sharingServiceNamed_("com.apple.share.AirDrop.send")
            if svc is not None:
                self._airdrop = svc  # keep it alive while the panel is open
                svc.performWithItems_([NSURL.URLWithString_(url)])
        AppHelper.callAfter(go)

    def pick_files(self):
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
        if kind is None:
            kind = webview.OPEN_DIALOG
        return self.main.create_file_dialog(kind, directory=os.path.expanduser("~"),
                                            allow_multiple=True) or []


def screen_size():
    """Usable size of the primary screen in logical points (None if unknown)."""
    try:
        if OS_NAME == "windows":
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            u32 = ctypes.windll.user32
            if not u32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return None
            try:
                dpi = u32.GetDpiForSystem() or 96
            except Exception:
                dpi = 96
            s = dpi / 96.0  # the process is DPI aware: RECT is in physical pixels
            return (rect.right - rect.left) / s, (rect.bottom - rect.top) / s
        if OS_NAME == "mac":
            import AppKit
            f = AppKit.NSScreen.mainScreen().visibleFrame()
            return f.size.width, f.size.height
    except Exception as e:
        log.debug("screen size: %s", e)
    return None


def viewer_window_size():
    sz = screen_size()
    if not sz:
        return 1280, 800
    return int(min(1280, sz[0] * 0.8)), int(min(800, sz[1] * 0.8))


def system_is_light():
    try:
        if OS_NAME == "mac":
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True, timeout=2)
            return "dark" not in out.stdout.lower()
        if OS_NAME == "windows":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0])
    except Exception:
        pass
    return False


def _mac_window_chrome(win):
    """Quiet AI-style chrome: hidden, transparent title bar; content runs under it."""
    try:
        import AppKit
        ns = win.native
        frame = ns.frame()
        ns.setTitlebarAppearsTransparent_(True)
        ns.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        ns.setStyleMask_(ns.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
        # An empty unified toolbar makes the title bar 52 px tall, so the traffic lights
        # sit centred on the page's title bar (host.html uses 52 px with ?shell=mac).
        tb = AppKit.NSToolbar.alloc().initWithIdentifier_("hop")
        tb.setShowsBaselineSeparator_(False)
        ns.setToolbar_(tb)
        if hasattr(ns, "setToolbarStyle_"):
            ns.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnified)
        # pywebview paints the title-bar container with windowBackgroundColor; clear it so
        # the page shows through behind the traffic lights.
        try:
            bar = ns.contentView().superview().subviews().lastObject()
            if bar is not None and bar.respondsToSelector_("setBackgroundColor:"):
                bar.setBackgroundColor_(AppKit.NSColor.clearColor())
        except Exception:
            pass
        ns.setFrame_display_(frame, True)  # the style change shrinks the frame; restore it
    except Exception as e:
        log.debug("macOS window styling failed: %s", e)


def _mac_app_name(name):
    try:
        from Foundation import NSBundle
        bundle = NSBundle.mainBundle()
        for info in (bundle.localizedInfoDictionary(), bundle.infoDictionary()):
            if info is not None:
                info["CFBundleName"] = name
    except Exception as e:
        log.debug("Could not set app name: %s", e)


_mac_keep = []


def _mac_quit_hooks(on_quit):
    """Cmd+Q, Ctrl+C and SIGTERM end the Cocoa app with exit() from inside the run loop, so
    webview.start() never returns: run our shutdown (mDNS goodbye, keep-awake off) first."""
    try:
        import AppKit
        import Foundation
        from PyObjCTools import AppHelper, MachSignals

        class LVQuitObserver(Foundation.NSObject):
            def appWillTerminate_(self, _note):
                on_quit()
        obs = LVQuitObserver.alloc().init()
        Foundation.NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            obs, "appWillTerminate:", AppKit.NSApplicationWillTerminateNotification, None)
        _mac_keep.append(obs)
        # A Python signal handler would never run while the main thread sits in the Cocoa run
        # loop; MachSignals delivers SIGTERM through the run loop instead.
        MachSignals.signal(signal.SIGTERM,
                           lambda _sig: AppHelper.callAfter(
                               AppKit.NSApplication.sharedApplication().terminate_, None))
    except Exception as e:
        log.debug("Quit hooks unavailable: %s", e)


def run_window(server, background=False, on_quit=None):
    """Open the host window and block until it is closed (main thread)."""
    import webview

    theme = server.setting("theme")
    light = theme == "light" or (theme == "system" and system_is_light())
    shell = {"mac": "mac", "windows": "win"}.get(OS_NAME, "")
    url = "http://127.0.0.1:%d/host%s" % (server.port, ("?shell=" + shell) if shell else "")
    api = WindowApi()
    width, height, min_h = 460, (800 if OS_NAME == "mac" else 780), 640
    sz = screen_size()
    if sz:  # small screens (e.g. 1366x768 at 125 %): keep the whole window visible
        height = int(min(height, sz[1] - 40))
        min_h = int(min(min_h, height))
    win = webview.create_window(
        "Hop", url, js_api=api, width=width, height=height,
        min_size=(420, min_h), minimized=background,
        background_color="#F3F3F5" if light else "#0A0A0B",
        frameless=(OS_NAME == "windows"), easy_drag=False, text_select=True)
    api._window = win

    def on_closed(*_a):
        # Closing the main window quits the app, including any viewer windows it opened.
        server.gui = None
        for w in list(webview.windows):
            if w is not win:
                try:
                    w.destroy()
                except Exception:
                    pass
    win.events.closed += on_closed

    if OS_NAME == "mac":
        _mac_app_name("Hop")
        if on_quit is not None:
            _mac_quit_hooks(on_quit)
        try:
            from PyObjCTools import AppHelper

            def before_show(*_a):
                AppHelper.callAfter(_mac_window_chrome, win)
            win.events.before_show += before_show
        except Exception as e:
            log.debug("No window chrome hook: %s", e)

    def attention():
        def bring():
            try:
                win.restore()
                win.show()
            except Exception:
                pass
            if OS_NAME == "mac":
                try:
                    import AppKit
                    from PyObjCTools import AppHelper
                    AppHelper.callAfter(
                        lambda: AppKit.NSApplication.sharedApplication()
                        .activateIgnoringOtherApps_(True))
                except Exception:
                    pass
        threading.Thread(target=bring, name="lv-attention", daemon=True).start()
    server.on_attention = attention
    server.gui = WindowBridge(win)

    icon_name = "icon.ico" if OS_NAME == "windows" else "icon.png"
    icon = os.path.join(STATIC_DIR, icon_name)
    # Not private: viewer windows must remember recent computers, this device's pairing key and the theme
    # between launches (the host page itself keeps nothing secret in web storage).
    storage = os.path.join(os.path.expanduser("~"), ".hop-web")
    kwargs = {"private_mode": False, "storage_path": storage}
    if os.path.isfile(icon):
        kwargs["icon"] = icon
    words = i18n.webview_localization()  # menu and dialog words; a language change applies at the next start
    if words:
        kwargs["localization"] = words
    log.info("Opening the Hop window%s", " (minimized)" if background else "")
    try:
        webview.start(**kwargs)
    except TypeError:  # older pywebview without icon= / storage_path= / localization=
        kwargs.pop("icon", None)
        kwargs.pop("storage_path", None)
        kwargs.pop("localization", None)
        webview.start(**kwargs)
    finally:
        server.on_attention = None
        server.gui = None


def _ask_running_instance(port, host_id):
    """If our own Hop already runs on `port`, bring its window forward. True if so."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/info" % port, timeout=2) as r:
            info = json.loads(r.read().decode("utf-8"))
        if not isinstance(info, dict) or info.get("id") != host_id:
            return False
    except Exception:
        return False
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/api/host/activate" % port, data=b"{}",
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        urllib.request.urlopen(req, timeout=2).close()
    except Exception:
        pass
    return True


def setup_logging(debug):
    handlers = [logging.StreamHandler(sys.stderr)]
    if FROZEN and not NO_CONSOLE:
        # A bundled app started from Finder has nowhere useful to print: keep a log file too.
        handlers.append(logging.StreamHandler(_open_log_file()))
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S", handlers=handlers)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("zeroconf").setLevel(logging.WARNING if debug else logging.ERROR)


def main():
    parser = argparse.ArgumentParser(description="Hop host (LAN remote desktop)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--pin", help="6-digit PIN (saved to ~/.hop.json)")
    parser.add_argument("--name", help="display name (default: computer name)")
    parser.add_argument("--short", help="easy address name, e.g. 'studio' for http://studio.local "
                                        "(saved)")
    parser.add_argument("--no-easy-port", action="store_true",
                        help="don't also listen on port 80")
    parser.add_argument("--headless", action="store_true",
                        help="no app window: terminal output only")
    parser.add_argument("--background", action="store_true",
                        help="start with the window minimized (used by start at login)")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--update-from", metavar="ZIP", help=argparse.SUPPRESS)  # CI: rehearse an update
    # macOS passes -psn_0_12345 to apps opened from Finder on old systems: ignore unknowns.
    args, _unknown = parser.parse_known_args()

    setup_logging(args.debug)
    log.info("Hop %s starting (%s%s)", VERSION, OS_NAME, ", app bundle" if FROZEN else "")

    if args.update_from:  # replace this app with the Hop inside ZIP, then reopen (used by CI)
        place = updater.installation()
        if place.get("problem"):
            log.error("Can't update: %s", place["problem"])
            sys.exit(2)
        work = updater._work_dir(place)
        prepared = updater.unpack(os.path.abspath(args.update_from), work, place)
        updater.apply(prepared, place, LOG_PATH)
        log.info("Update handed over; quitting")
        sys.exit(0)

    migrate_from_local_view()
    cfg = load_config()
    i18n.set_language(cfg.get("language"))
    dirty = False
    if args.pin is not None:
        pin = args.pin.strip()
        if not (len(pin) == 6 and pin.isdigit()):
            parser.error("--pin must be exactly 6 digits")
        if cfg.get("pin") != pin:
            cfg["pin"] = pin
            dirty = True
    elif not (isinstance(cfg.get("pin"), str) and len(cfg["pin"]) == 6 and cfg["pin"].isdigit()):
        cfg["pin"] = "%06d" % random.SystemRandom().randint(0, 999999)
        dirty = True
    if not isinstance(cfg.get("id"), str) or not cfg.get("id"):
        cfg["id"] = str(uuid.uuid4())
        dirty = True
    if args.short is not None:
        short = args.short.strip().lower()
        if short.endswith(".local"):
            short = short[:-6]
        if not valid_short(short):
            parser.error("--short: use 1-30 letters, digits or hyphens (not at the start or end)")
        if cfg.get("shortName") != short:
            cfg["shortName"] = short
            dirty = True
    if dirty:
        save_config(cfg)

    name = args.name or default_name()

    # Instantiate mss once in the main thread before any window exists (Windows: mss also
    # requests per-monitor DPI awareness, already set at the top of this file).
    try:
        with _new_mss() as sct:
            _ = sct.monitors
    except Exception as e:
        log.warning("Screen capture init failed: %s", e)

    refresh_startup_entry()

    server = HopServer(name, args.port, cfg["pin"], cfg["id"], cfg,
                             easy_port=not args.no_easy_port)
    app = build_app(server)

    headless = args.headless
    if not headless:
        try:
            import webview  # noqa: F401
        except Exception as e:
            log.warning("App window unavailable (%s); running in the terminal only.", e)
            headless = True

    thread = ServerThread(server, app)
    thread.start()
    thread.ready.wait(30)
    if thread.error is not None:
        if _ask_running_instance(args.port, server.id):
            log.info("Hop is already running; showed its window.")
            return
        msg = "Could not start Hop on port %d: %s" % (args.port, thread.error)
        log.error(msg)
        if NO_CONSOLE or FROZEN:
            fatal_dialog(i18n.t("fatal.port", port=args.port, detail=thread.error) + "\n\n" + i18n.t("fatal.portHint"))
        sys.exit(1)

    stopped = threading.Event()

    def shutdown():
        if not stopped.is_set():
            stopped.set()
            thread.stop()
            log.info("Hop host stopped.")
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass

    def on_term(*_a):
        # `kill` / logout: shut down cleanly (mDNS goodbye, keep-awake off) from a helper thread.
        def stop():
            thread.stop()
            try:
                import webview
                for w in list(webview.windows):
                    w.destroy()
            except Exception:
                pass
        threading.Thread(target=stop, daemon=True).start()
    if headless or OS_NAME != "mac":  # macOS window mode: see _mac_quit_hooks
        try:
            signal.signal(signal.SIGTERM, on_term)
        except Exception:
            pass

    for _ in range(40):  # let the first mDNS probe finish so the banner shows the right address
        if server.mdns_ok is not None:
            break
        time.sleep(0.1)
    print_banner(server, windowed=not headless)

    try:
        if headless:
            while thread.is_alive():
                thread.join(0.5)
        else:
            try:
                run_window(server, background=args.background, on_quit=shutdown)
            except KeyboardInterrupt:
                pass
            except Exception as e:
                log.warning("App window failed (%s); still running in the terminal. "
                            "Press Ctrl+C to stop.", e)
                while thread.is_alive():
                    thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    main()
