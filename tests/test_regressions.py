import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

import host


class Socket:
    closed = False

    def __init__(self):
        self.messages = []

    async def send_str(self, value):
        self.messages.append(json.loads(value))

    async def send_raw(self, value):
        await self.send_str(value)


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(host, "SHARED_DIR", str(tmp_path / "shared"))
    srv = host.HopServer("Test", 0, "731926", "test-id", {"notify": False, "keepAwake": False})
    srv.status = lambda: {"settings": srv.settings()}
    srv.notify = Mock()
    yield srv
    for pool in (srv.io_ex, srv.clip.ex, srv._mdns_ex):
        pool.shutdown(wait=True)


@pytest_asyncio.fixture
async def remote_session(server):
    session = host.RemoteSession(server, Socket(), "test", track=Mock())
    yield session
    await session._up_cleanup()
    session._shutdown_executors()


@pytest.mark.asyncio
async def test_control_toggle_notifies_existing_viewers(server):
    session = Mock(closed=False)
    session.ws = Socket()
    server.sessions["test"] = session
    req = Mock()
    req.json = AsyncMock(return_value={"allowControl": False})
    await server.api_settings(req)
    assert {"t": "control", "allowed": False} in session.ws.messages
    session.release_input.assert_called_once()
    req.json = AsyncMock(return_value={"allowControl": True})
    await server.api_settings(req)
    assert {"t": "control", "allowed": True} in session.ws.messages


@pytest.mark.asyncio
async def test_remote_upload_rejects_truncated_file(remote_session, tmp_path):
    s = remote_session
    await s.handle({"t": "up.start", "id": "1", "name": "data.txt", "size": 8})
    await s.handle({"t": "up.data", "id": "1", "d": base64.b64encode(b"abc").decode()})
    await s.handle({"t": "up.end", "id": "1"})
    assert s.ws.messages[-1]["t"] == "up.err"
    assert not list((tmp_path / "shared").iterdir())


@pytest.mark.asyncio
async def test_remote_upload_cannot_finish_after_control_revoked(remote_session, tmp_path):
    s = remote_session
    await s.handle({"t": "up.start", "id": "1", "name": "data.txt", "size": 3})
    await s.handle({"t": "up.data", "id": "1", "d": base64.b64encode(b"abc").decode()})
    s.server.cfg["allowControl"] = False
    await s.handle({"t": "up.end", "id": "1"})
    assert s.ws.messages[-1]["t"] == "up.err"
    assert not list((tmp_path / "shared").iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [-1, "nonsense", 4 << 30 | 1])
async def test_remote_upload_rejects_invalid_size(remote_session, size):
    await remote_session.handle({"t": "up.start", "id": "1", "name": "data", "size": size})
    assert remote_session.ws.messages[-1]["t"] == "up.err"
    assert remote_session._up is None


@pytest.mark.asyncio
async def test_remote_upload_download_and_duplicate_names(remote_session, tmp_path):
    s = remote_session
    payload = bytes(range(256)) * 500
    for expected_name in ("Тест 文件.bin", "Тест 文件 (1).bin"):
        await s.handle({"t": "up.start", "id": "u", "name": "Тест 文件.bin", "size": len(payload)})
        for i in range(0, len(payload), 36000):
            await s.handle({"t": "up.data", "id": "u", "d": base64.b64encode(payload[i:i+36000]).decode()})
        await s.handle({"t": "up.end", "id": "u"})
        assert (tmp_path / "shared" / expected_name).read_bytes() == payload
    s.ws.messages.clear()
    await s._download({"id": "d", "name": "Тест 文件.bin"})
    assert s.ws.messages[0]["t"] == "down.start"
    assert s.ws.messages[-1]["t"] == "down.end"
    assert b"".join(base64.b64decode(m["d"]) for m in s.ws.messages if m["t"] == "down.data") == payload


@pytest.mark.asyncio
async def test_remote_upload_cancel_and_bad_base64(remote_session, tmp_path):
    s = remote_session
    for ending in ({"t": "up.abort"}, {"t": "up.data", "d": "!!!"}):
        await s.handle({"t": "up.start", "id": "u", "name": "data", "size": 100})
        await s.handle(dict(ending, id="u"))
        assert s._up is None
        assert not list((tmp_path / "shared").iterdir())


@pytest.mark.parametrize("name", ["CON.txt", "CON .txt", "COM¹.txt", "LPT².txt", "aux.log", "nul.tar.gz"])
def test_reserved_windows_filenames_can_be_created(tmp_path, name):
    result = host.safe_filename(name)
    assert result.startswith("_")
    Path(host.reserve_name(str(tmp_path), result)).write_bytes(b"ok")


@pytest.mark.parametrize("name", ["../escape", "..\\escape", "a:b?.txt", "文件.txt", "a" * 300 + ".txt"])
def test_filename_is_safe_and_portable(tmp_path, name):
    result = host.safe_filename(name)
    assert not any(c in result for c in '/\\<>:"|?*')
    assert len(result.encode("utf-8")) <= 200
    Path(host.reserve_name(str(tmp_path), result)).write_bytes(b"ok")


def test_input_coordinates_cover_negative_monitor_and_edges():
    mon = {"left": -1920, "top": -100, "width": 1920, "height": 1080}
    assert host.InputState.to_screen(mon, 0, 0) == (-1920, -100)
    assert host.InputState.to_screen(mon, 1, 1) == (-1, 979)
    assert host.InputState.to_screen(mon, float("nan"), -5) == (-1920, -100)


@pytest.mark.parametrize("letter,vk", [("a", 0x41), ("C", 0x43), ("1", 0x31), ("/", 0xBF)])
def test_windows_shortcuts_use_virtual_keys_and_release_original_key(monkeypatch, letter, vk):
    keyboard = Mock()
    monkeypatch.setattr(host, "keyboard", keyboard)
    monkeypatch.setattr(host, "OS_NAME", "windows")
    state = host.InputState()
    state.key("Control", True)
    state.key(letter, True)
    assert keyboard.press.call_args.args[0] == host.KeyCode.from_vk(vk)
    state.key("Control", False)
    state.key(letter, False)
    assert keyboard.release.call_args.args[0] == host.KeyCode.from_vk(vk)
    assert not state.held_keys and not state.key_codes


def test_ordinary_unicode_typing_stays_character_based(monkeypatch):
    keyboard = Mock()
    monkeypatch.setattr(host, "keyboard", keyboard)
    state = host.InputState()
    for char in "aЖ文🚀":
        state.key(char, True)
        keyboard.press.assert_called_with(char)
        state.key(char, False)
        keyboard.release.assert_called_with(char)


def test_input_releases_held_keys_and_buttons(monkeypatch):
    mouse, keyboard = Mock(), Mock()
    monkeypatch.setattr(host, "mouse", mouse)
    monkeypatch.setattr(host, "keyboard", keyboard)
    state = host.InputState()
    state.key("Control", True)
    state.key("a", True)
    state.button({}, "left", None, None, True)
    state.release_all()
    assert keyboard.release.call_count == 2
    mouse.release.assert_called_once_with(host.Button.left)
    assert not state.held_buttons and not state.held_keys


def test_shared_file_path_boundary(tmp_path, monkeypatch):
    folder = tmp_path / "shared"
    folder.mkdir()
    (folder / "ok.txt").write_text("ok")
    (tmp_path / "private.txt").write_text("private")
    monkeypatch.setattr(host, "SHARED_DIR", str(folder))
    assert host.resolve_shared_file("ok.txt") == str(folder / "ok.txt")
    for name in ("../private.txt", "..\\private.txt", "ok.txt:stream", "C:\\private.txt", "..", ""):
        assert host.resolve_shared_file(name) is None
