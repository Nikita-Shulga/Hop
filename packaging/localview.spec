# PyInstaller spec for Local View (macOS .app and Windows .exe, onedir).
# Build with packaging/build-mac.sh or packaging/build-windows.bat, not directly.
# Builds for the architecture of the Python running PyInstaller.
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.dirname(SPECPATH)  # noqa: F821  (SPECPATH is set by PyInstaller)
PKG = SPECPATH                    # noqa: F821
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

with open(os.path.join(PKG, "VERSION"), encoding="utf-8") as f:
    VERSION = f.read().strip()

APP_NAME = "Local View" if IS_MAC else "LocalView"
BUNDLE_ID = "com.nikitashulga.localview"


def _webview_platform(name):
    """Keep only the pywebview GUI backends this OS can use."""
    if ".platforms." not in name:
        return True
    leaf = name.split(".platforms.", 1)[1].split(".")[0]
    if IS_MAC:
        return leaf == "cocoa"
    if IS_WIN:
        return leaf in ("winforms", "edgechromium", "mshtml", "win32")
    return leaf in ("gtk", "qt")


hiddenimports = []
hiddenimports += collect_submodules("webview", filter=_webview_platform)
hiddenimports += collect_submodules("zeroconf")
hiddenimports += collect_submodules("aiohttp")
# Internet access (remote.py): WebRTC stack. av (FFmpeg) ships its own hook in pyinstaller-hooks-contrib.
hiddenimports += ["remote"] + collect_submodules("aiortc") + collect_submodules("aioice")
hiddenimports += ["pylibsrtp", "google_crc32c", "pyee", "OpenSSL", "av.video.frame", "av.codec"]
hiddenimports += ["pyperclip", "ifaddr", "qrcode", "qrcode.image.svg", "PIL.Image", "PIL.JpegImagePlugin",
                  "mss"]
if IS_MAC:
    hiddenimports += ["pynput.keyboard._darwin", "pynput.mouse._darwin",
                      "AppKit", "Foundation", "Quartz", "WebKit", "PyObjCTools.AppHelper",
                      "ApplicationServices", "objc", "dispatch"]  # dispatch: second-screen virtual displays
elif IS_WIN:
    hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32", "winreg", "clr"]

# Backends and toolkits we never use; keeps the bundle small.
excludes = ["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi", "cefpython3",
            "pynput.keyboard._xorg", "pynput.mouse._xorg", "pynput.keyboard._uinput",
            "matplotlib", "numpy", "IPython", "pytest"]

icon = os.path.join(PKG, "icon.icns") if IS_MAC else os.path.join(ROOT, "static", "icon.ico")

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "host.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "static"), "static")],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe_kwargs = {}
if IS_WIN:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
        VSVersionInfo)
    nums = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    exe_kwargs["version"] = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "Nikita Shulga"),
                StringStruct("FileDescription", "Local View"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "LocalView"),
                StringStruct("LegalCopyright", "Copyright (c) 2026 Nikita Shulga. MIT License."),
                StringStruct("OriginalFilename", "LocalView.exe"),
                StringStruct("ProductName", "Local View"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ])

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed: no Terminal / console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,       # the architecture of this Python
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    **exe_kwargs,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if IS_MAC:
    app = BUNDLE(  # noqa: F821
        coll,
        name=APP_NAME + ".app",
        icon=icon,
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist={
            "CFBundleName": "Local View",
            "CFBundleDisplayName": "Local View",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "CFBundleDevelopmentRegion": "en",
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "NSHumanReadableCopyright": "Copyright (c) 2026 Nikita Shulga. MIT License.",
            "NSLocalNetworkUsageDescription":
                "Local View finds your other computers and lets your devices connect over your Wi-Fi.",
            "NSBonjourServices": ["_http._tcp"],
            "NSAppleEventsUsageDescription":
                "Local View shows a notification when a device connects or asks to connect.",
        },
    )
