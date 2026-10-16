"""One-click updates from GitHub Releases (macOS and Windows; same approach as Quiet AI's updater).

check()   asks GitHub for the latest release of REPO and finds this platform's ZIP.
prepare() downloads it next to the installed app, verifies it against the release's SHA256SUMS.txt
          and unpacks it.
apply()   hands over to a small script that waits for Hop to quit, swaps the app for the new one
          and reopens it. Settings live outside the app (~/.hop.json), so they carry over.
Nothing but GitHub is contacted.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

REPO = "Nikita-Shulga/Hop"
FROZEN = bool(getattr(sys, "frozen", False))
OS = "mac" if sys.platform == "darwin" else "win" if sys.platform.startswith("win") else "other"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def target():
    m = platform.machine().lower()
    return "%s-%s" % (OS, "arm64" if m in ("arm64", "aarch64") else "x64")


def parse_version(v):
    return tuple(int(x) for x in (re.findall(r"\d+", str(v)) + ["0", "0", "0"])[:3])


def newer(a, b):
    return parse_version(a) > parse_version(b)


def _get(url, accept="application/octet-stream", timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Hop-updater", "Accept": accept})
    return urllib.request.urlopen(req, timeout=timeout)


def installation():
    """Where the running app lives: {'kind','path'} or {'problem': why it can't update itself}."""
    if not FROZEN:
        return {"problem": "You're running Hop from source: update with git pull instead."}
    exe = os.path.realpath(sys.executable)
    if OS == "mac":
        bundle = os.path.dirname(os.path.dirname(os.path.dirname(exe)))  # Hop.app/Contents/MacOS/Hop
        if not bundle.endswith(".app"):
            return {"problem": "This copy of Hop isn't running from an app bundle."}
        if "/AppTranslocation/" in bundle:
            return {"problem": "Move Hop to the Applications folder, open it from there, then update."}
        if not (_writable(os.path.dirname(bundle)) and _writable(bundle)):
            return {"problem": "Hop can't replace itself where it is. Move it to Applications, then update."}
        return {"kind": "mac", "path": bundle}
    if OS == "win":
        folder = os.path.dirname(exe)
        if not os.path.isdir(os.path.join(folder, "_internal")):
            return {"problem": "This copy of Hop isn't running from its packaged folder."}
        if not _writable(folder):
            return {"problem": "Hop can't write to its folder. Move the Hop folder somewhere you own "
                               "(like Documents), then update."}
        return {"kind": "win", "path": folder}
    return {"problem": "Updates are available on Windows and macOS."}


def _writable(folder):
    probe = os.path.join(folder, ".hop-write-test-%d" % os.getpid())
    try:
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def check(current):
    rel = json.load(_get("https://api.github.com/repos/%s/releases/latest" % REPO, "application/vnd.github+json"))
    latest = str(rel.get("tag_name") or "").lstrip("vV")
    name = "Hop-%s-%s.zip" % (latest, target())
    assets = {a.get("name"): a for a in rel.get("assets") or []}
    asset = assets.get(name)
    sums = assets.get("SHA256SUMS.txt")
    return {"current": current, "latest": latest, "available": bool(latest) and newer(latest, current),
            "page": rel.get("html_url") or "https://github.com/%s/releases/latest" % REPO,
            "notes": str(rel.get("body") or "")[:3000],
            "asset": {"name": name, "url": asset["browser_download_url"], "size": asset.get("size", 0)} if asset else None,
            "sums": sums["browser_download_url"] if sums else None}


def _work_dir(place):
    # Next to the app, so the macOS swap is a rename on the same volume and the system drive needn't have room.
    base = os.path.dirname(place["path"]) if place["kind"] == "mac" else os.path.dirname(place["path"].rstrip("\\/"))
    try:
        return tempfile.mkdtemp(prefix=".hop-update-", dir=base)
    except OSError:
        return tempfile.mkdtemp(prefix="hop-update-")


def prepare(info, place, progress=None):
    """Download + verify + unpack. Returns {'work', 'new'}: 'new' is the unpacked Hop.app / Hop folder."""
    if not info.get("asset"):
        raise RuntimeError("This release has no download for your computer (%s)." % target())
    if not info.get("sums"):
        raise RuntimeError("The release has no SHA256SUMS.txt, so the download can't be verified.")
    expected = None
    for line in _get(info["sums"]).read().decode("utf-8", "replace").splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == info["asset"]["name"]:
            expected = parts[0].lower()
    if not expected:
        raise RuntimeError("SHA256SUMS.txt doesn't list %s." % info["asset"]["name"])
    work = _work_dir(place)
    zpath = os.path.join(work, info["asset"]["name"])
    h = hashlib.sha256()
    total = info["asset"].get("size") or 0
    got = 0
    with _get(info["asset"]["url"], timeout=60) as r, open(zpath, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and total:
                progress(min(0.99, got / float(total)))
    if h.hexdigest().lower() != expected:
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError("The download didn't match its checksum. Nothing was changed; try again.")
    return unpack(zpath, work, place)


def unpack(zpath, work, place):
    out = os.path.join(work, "new")
    os.makedirs(out, exist_ok=True)
    if place["kind"] == "mac":
        # ditto keeps the bundle's symlinks and code signature intact
        subprocess.run(["/usr/bin/ditto", "-x", "-k", zpath, out], check=True)
        new = os.path.join(out, "Hop.app")
    else:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(out)
        new = os.path.join(out, "Hop")
    if not os.path.isdir(new):
        raise RuntimeError("The download doesn't contain Hop.")
    if place["kind"] == "win" and not (os.path.isfile(os.path.join(new, "Hop.exe")) and
                                        os.path.isdir(os.path.join(new, "_internal"))):
        raise RuntimeError("The download doesn't contain a complete Windows app.")
    return {"work": work, "new": new}


MAC_SCRIPT = r'''#!/bin/sh
# Hop update hand-over (macOS): waits for Hop to quit, swaps the app bundle, reopens it.
pid="$1"; new="$2"; target="$3"; log="$4"; work="$5"
note(){ printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%S)" "$1" >> "$log" 2>/dev/null; }
note "Update: waiting for Hop ($pid) to quit."
i=0; while kill -0 "$pid" 2>/dev/null && [ $i -lt 120 ]; do sleep 0.5; i=$((i+1)); done
sleep 1
old="$target.previous"
rm -rf "$old"
if mv "$target" "$old" && mv "$new" "$target"; then
  xattr -dr com.apple.quarantine "$target" 2>/dev/null
  rm -rf "$old"
  note "Update: app replaced."
else
  note "Update failed: could not replace $target."
  [ -d "$target" ] || mv "$old" "$target"
fi
open "$target"
sleep 5
rm -rf "$work"
'''

WIN_START = r'''# Hop: starts the update hand-over (apply-update.ps1) so it outlives the app, even inside a job object.
param([string]$Script,[int]$ProcessId,[string]$Source,[string]$Target,[string]$Log,[string]$Work)
$ErrorActionPreference='Stop'
try {
  Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public static class HopBreakaway {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  struct STARTUPINFO { public int cb; public string lpReserved, lpDesktop, lpTitle; public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags; public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError; }
  [StructLayout(LayoutKind.Sequential)]
  struct PROCESS_INFORMATION { public IntPtr hProcess, hThread; public int dwProcessId, dwThreadId; }
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  static extern bool CreateProcess(string app, string cmd, IntPtr pa, IntPtr ta, bool inherit, int flags, IntPtr env, string dir, ref STARTUPINFO si, out PROCESS_INFORMATION pi);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  public static int Start(string app, string cmd, string dir, int flags) {
    var si = new STARTUPINFO(); si.cb = Marshal.SizeOf(si); PROCESS_INFORMATION pi;
    if (!CreateProcess(app, cmd, IntPtr.Zero, IntPtr.Zero, false, flags, IntPtr.Zero, dir, ref si, out pi)) return Marshal.GetLastWin32Error();
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess); return 0;
  }
}
'@
  $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $cmd = "`"$shell`" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Script`" -ProcessId $ProcessId -Source `"$Source`" -Target `"$Target`" -Log `"$Log`" -Work `"$Work`""
  # CREATE_BREAKAWAY_FROM_JOB | CREATE_NO_WINDOW; without breakaway if the job doesn't allow it
  $err = [HopBreakaway]::Start($shell, $cmd, $Target, 0x01000000 -bor 0x08000000)
  if ($err -ne 0) { $err = [HopBreakaway]::Start($shell, $cmd, $Target, 0x08000000) }
  if ($err -ne 0) { [Console]::Out.WriteLine("CreateProcess failed with Windows error $err"); exit 2 }
  exit 0
} catch { [Console]::Out.WriteLine($_.Exception.Message); exit 1 }
'''

WIN_APPLY = r'''# Hop update hand-over (Windows): replace the executable and runtime together, or restore both.
param([int]$ProcessId,[string]$Source,[string]$Target,[string]$Log,[string]$Work)
$ErrorActionPreference='Stop'
function Note($text){try{Add-Content -LiteralPath $Log -Value ((Get-Date).ToString('s')+' '+$text) -Encoding UTF8}catch{}}
$movedInternal=$false; $movedExe=$false; $installedInternal=$false; $installedExe=$false
$replaced=$false; $restored=$true
try{
  $Target=(Resolve-Path -LiteralPath $Target).ProviderPath.TrimEnd('\')
  $Source=(Resolve-Path -LiteralPath $Source).ProviderPath.TrimEnd('\')
  $Work=(Resolve-Path -LiteralPath $Work).ProviderPath.TrimEnd('\')
  # Validate containment before moving or recursively removing anything.
  $prefix=$Target+'\'; $workPrefix=$Work+'\'
  if($Target -eq [IO.Path]::GetPathRoot($Target).TrimEnd('\') -or
     $Work -eq $Target -or $Work.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
     $Target.StartsWith($workPrefix,[StringComparison]::OrdinalIgnoreCase) -or
     -not $Source.StartsWith($workPrefix,[StringComparison]::OrdinalIgnoreCase)){
    throw 'Invalid update directories'
  }
  $exe=Join-Path $Target 'Hop.exe'; $internal=Join-Path $Target '_internal'
  $newExe=Join-Path $Source 'Hop.exe'; $newInternal=Join-Path $Source '_internal'
  $backup=Join-Path $Work 'previous-internal'; $backupExe=Join-Path $Work 'previous-Hop.exe'
  if(-not (Test-Path -LiteralPath $exe -PathType Leaf) -or
     -not (Test-Path -LiteralPath $newExe -PathType Leaf) -or
     -not (Test-Path -LiteralPath $newInternal -PathType Container)){
    throw 'The update does not contain a complete Windows app'
  }
  Note "Update: waiting for Hop ($ProcessId) to quit."
  if(Get-Process -Id $ProcessId -ErrorAction SilentlyContinue){
    Wait-Process -Id $ProcessId -Timeout 60 -ErrorAction Stop
  }
  $deadline=(Get-Date).AddSeconds(30)
  do{
    $busy=Get-Process -ErrorAction SilentlyContinue | Where-Object {
      try{$_.Path -and $_.Path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)}catch{$false}
    }
    if(-not $busy){break}
    Start-Sleep -Milliseconds 500
  }while((Get-Date) -lt $deadline)
  if($busy){throw 'Hop is still running; its files were left unchanged'}
  if(Test-Path -LiteralPath $internal){
    Move-Item -LiteralPath $internal -Destination $backup; $movedInternal=$true
  }
  Move-Item -LiteralPath $exe -Destination $backupExe; $movedExe=$true
  Move-Item -LiteralPath $newInternal -Destination $internal; $installedInternal=$true
  Move-Item -LiteralPath $newExe -Destination $exe; $installedExe=$true
  $replaced=$true
  Note 'Update: files replaced.'
}catch{
  Note ('Update failed: '+$_.Exception.Message)
  try{
    if($installedExe){Remove-Item -LiteralPath $exe -Force}
    if($installedInternal){Remove-Item -LiteralPath $internal -Recurse -Force}
    if($movedExe){Move-Item -LiteralPath $backupExe -Destination $exe}
    if($movedInternal){Move-Item -LiteralPath $backup -Destination $internal}
    if($movedExe -or $movedInternal){Note 'Update: previous version restored.'}
  }catch{
    $restored=$false
    try{New-Item -ItemType File -Path (Join-Path $Work '.keep-for-recovery') -Force | Out-Null}catch{}
    Note ('Update rollback failed; recovery files kept in '+$Work+': '+$_.Exception.Message)
  }
}
if($restored -and $exe -and (Test-Path -LiteralPath $exe)){
  try{Start-Process -FilePath $exe -WorkingDirectory $Target}catch{Note ('Could not reopen Hop: '+$_.Exception.Message); exit 1}
}
if($replaced){
  Start-Sleep -Seconds 5
  try{Remove-Item -LiteralPath $Work -Recurse -Force}catch{}
  exit 0
}
exit 1
'''


def apply(prepared, place, log_path):
    """Start the hand-over; the caller must then quit Hop promptly."""
    work, new = prepared["work"], prepared["new"]
    pid = str(os.getpid())
    if place["kind"] == "mac":
        script = os.path.join(work, "apply-update.sh")
        with open(script, "w") as f:
            f.write(MAC_SCRIPT)
        os.chmod(script, 0o755)
        subprocess.Popen(["/bin/sh", script, pid, new, place["path"], log_path, work],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return
    start = os.path.join(work, "start-update.ps1")
    applyp = os.path.join(work, "apply-update.ps1")
    with open(start, "w", encoding="utf-8") as f:
        f.write(WIN_START)
    with open(applyp, "w", encoding="utf-8") as f:
        f.write(WIN_APPLY)
    shell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\WindowsPowerShell\v1.0\powershell.exe")
    r = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", start,
                        "-Script", applyp, "-ProcessId", pid, "-Source", new, "-Target", place["path"],
                        "-Log", log_path, "-Work", work],
                       capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("The update couldn't be started: %s" % ((r.stdout or r.stderr or "").strip() or r.returncode))


def cleanup(place):
    """Remove leftovers of an interrupted update next to the app."""
    try:
        base = os.path.dirname(place["path"]) if place["kind"] == "mac" else os.path.dirname(place["path"].rstrip("\\/"))
        for name in os.listdir(base):
            if name.startswith(".hop-update-"):
                p = os.path.join(base, name)
                if os.path.isfile(os.path.join(p, ".keep-for-recovery")):
                    continue
                if time.time() - os.path.getmtime(p) > 3600:
                    shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass
