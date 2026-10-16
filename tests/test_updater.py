import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

import pytest

import updater


def test_cleanup_preserves_failed_rollback_recovery(tmp_path):
    recovery = tmp_path / ".hop-update-recovery"
    stale = tmp_path / ".hop-update-stale"
    unrelated = tmp_path / "personal"
    for folder in (recovery, stale, unrelated):
        folder.mkdir()
        (folder / "data.txt").write_text("keep")
    (recovery / ".keep-for-recovery").touch()
    for folder in (recovery, stale, unrelated):
        os.utime(folder, (time.time() - 7200, time.time() - 7200))
    updater.cleanup({"kind": "win", "path": str(tmp_path / "Hop")})
    assert (recovery / "data.txt").read_text() == "keep"
    assert not stale.exists()
    assert (unrelated / "data.txt").read_text() == "keep"


def test_update_platform_version_and_missing_asset(monkeypatch):
    monkeypatch.setattr(updater, "OS", "win")
    monkeypatch.setattr(updater.platform, "machine", lambda: "AMD64")
    assert updater.target() == "win-x64"
    assert updater.newer("v2.0.2", "2.0.1")
    assert not updater.newer("2.0.1", "2.0.1")
    monkeypatch.setattr(updater, "_get", lambda *a, **k: io.StringIO(json.dumps({"tag_name": "v2.0.2"})))
    result = updater.check("2.0.1")
    assert result["available"] and result["asset"] is None
    with pytest.raises(RuntimeError, match="no download"):
        updater.prepare(result, {"kind": "win", "path": "unused"})


def test_incomplete_windows_archive_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("Hop/readme.txt", "not an application")
    with pytest.raises(RuntimeError, match="complete Windows app"):
        updater.unpack(str(archive), str(tmp_path / "work"), {"kind": "win"})


@pytest.mark.skipif(sys.platform != "win32", reason="Windows updater integration")
@pytest.mark.parametrize("locked", [False, True])
def test_windows_update_success_and_rollback(tmp_path, locked):
    # Run the real hand-over against a tiny harmless executable in temporary folders.
    root = tmp_path / "Unicode путь with spaces"
    target = root / "Hop"
    work = root / ".hop-update-test"
    source = work / "new" / "Hop"
    target.mkdir(parents=True)
    source.mkdir(parents=True)
    for folder, value in ((target, "old"), (source, "new")):
        (folder / "_internal").mkdir()
        (folder / "_internal" / "version.txt").write_text(value)
    (target / "personal.txt").write_text("preserve")
    code = root / "stub.cs"
    code.write_text('class Program { static void Main() {} }')
    csc = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run([str(csc), "/nologo", "/target:winexe", "/out:" + str(target / "Hop.exe"), str(code)],
                   check=True, capture_output=True, creationflags=updater.NO_WINDOW)
    old_exe = (target / "Hop.exe").read_bytes()
    (source / "Hop.exe").write_bytes(old_exe + b"new-version")
    script = work / "apply.ps1"
    script.write_text(updater.WIN_APPLY, encoding="utf-8-sig")
    log = root / "update.log"
    handle = None
    if locked:
        from ctypes import wintypes
        create = ctypes.windll.kernel32.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        handle = create(str(target / "Hop.exe"), 0x80000000, 1, None, 3, 0, None)
        assert handle != ctypes.c_void_p(-1).value
    try:
        # 0 would identify the idle process; use an already-exited child PID instead.
        child = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=updater.NO_WINDOW)
        child.wait()
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                 "-ProcessId", str(child.pid), "-Source", str(source), "-Target", str(target),
                                 "-Log", str(log), "-Work", str(work)],
                                capture_output=True, timeout=45, creationflags=updater.NO_WINDOW)
        assert log.exists(), result.stderr.decode(errors="replace")
        assert (target / "personal.txt").read_text() == "preserve"
        assert (target / "_internal" / "version.txt").read_text() == ("old" if locked else "new")
        assert (target / "Hop.exe").read_bytes() == (old_exe if locked else old_exe + b"new-version")
        assert result.returncode == (1 if locked else 0), result.stderr.decode(errors="replace")
        if locked:
            assert "previous version restored" in log.read_text(encoding="utf-8-sig")
            assert work.exists()
        else:
            assert not work.exists()
    finally:
        if handle is not None:
            close = ctypes.windll.kernel32.CloseHandle
            close.argtypes = [ctypes.c_void_p]
            close(handle)
