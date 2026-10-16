import asyncio
import io
import json
from unittest.mock import Mock

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import pytest
import pytest_asyncio

import host


@pytest_asyncio.fixture
async def app(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(host, "SHARED_DIR", str(tmp_path / "shared"))
    monkeypatch.setattr(host, "list_monitors", lambda: [{"index": 1, "left": 0, "top": 0, "width": 1280, "height": 720}])
    def frame(mon, maxw, quality, previous):
        image = Image.new("RGB", (min(maxw, 1280), 720), "orange")
        out = io.BytesIO()
        image.save(out, format="JPEG")
        return out.getvalue(), b"frame"
    monkeypatch.setattr(host, "capture_frame", frame)
    monkeypatch.setattr(host, "mouse", Mock(position=(0, 0)))
    monkeypatch.setattr(host, "keyboard", Mock())
    srv = host.HopServer("Test", 0, "731926", "id", {"notify": False, "keepAwake": False})
    # Exercise real routes and middleware, without discovery or production settings.
    server_app = host.build_app(srv)
    server_app.on_startup.clear()
    client = TestClient(TestServer(server_app))
    await client.start_server()
    srv.port = client.server.port
    yield srv, client
    await client.close()


async def read_type(ws, kind):
    for _ in range(100):
        msg = await ws.receive(timeout=5)
        if msg.type == aiohttp.WSMsgType.BINARY:
            await ws.send_json({"t": "ack"})
        elif msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data["t"] == kind:
                return data
        else:
            raise AssertionError("Socket closed before " + kind)
    raise AssertionError("No " + kind)


async def connect(client, pin="731926"):
    ws = await client.ws_connect("/ws")
    await ws.send_json({"t": "auth", "pin": pin})
    return ws


@pytest.mark.asyncio
async def test_host_api_requires_loopback_token_and_origin(app):
    srv, client = app
    assert (await client.get("/host")).status == 200
    assert (await client.get("/host", headers={"Host": "evil.example"})).status == 403
    assert (await client.get("/api/host/status")).status == 403
    headers = {"X-Hop-Token": srv.token}
    assert (await client.get("/api/host/status", headers=headers)).status == 200
    assert (await client.post("/api/host/pause", headers=dict(headers, Origin="https://evil.example"))).status == 403
    assert not srv.paused


@pytest.mark.asyncio
async def test_wrong_pin_pause_resume_and_session_expiry(app):
    srv, client = app
    ws = await connect(client, "000000")
    assert "Wrong PIN" in (await read_type(ws, "error"))["msg"]
    await ws.close()
    ws = await connect(client)
    hello = await read_type(ws, "hello")
    assert hello["os"] == host.OS_NAME
    assert hello["monitors"][0]["width"] == 1280
    headers = {"X-LV-Session": hello["token"]}
    assert (await client.get("/api/files", headers=headers)).status == 200
    await srv.set_paused(True)
    assert "paused" in (await read_type(ws, "error"))["msg"]
    await ws.close()
    await asyncio.sleep(0.05)
    assert (await client.get("/api/files", headers=headers)).status == 401
    ws = await connect(client)
    assert "paused" in (await read_type(ws, "error"))["msg"]
    await ws.close()
    await srv.set_paused(False)
    ws = await connect(client)
    assert (await read_type(ws, "hello"))["control"]
    await ws.close()


@pytest.mark.asyncio
async def test_approval_and_denial(app):
    srv, client = app
    srv.cfg["askBeforeConnect"] = True
    for allowed in (False, True):
        ws = await connect(client)
        await read_type(ws, "pending")
        rid = next(iter(srv.pending))
        response = await client.post("/api/host/pending/" + rid + ("/approve" if allowed else "/deny"),
                                     headers={"X-Hop-Token": srv.token}, json={})
        assert response.status == 200
        result = await read_type(ws, "hello" if allowed else "error")
        assert ("token" in result) if allowed else ("declined" in result["msg"])
        await ws.close()


@pytest.mark.asyncio
async def test_http_file_roundtrip_and_view_only(app):
    srv, client = app
    assert (await client.get("/api/files")).status == 401
    ws = await connect(client)
    hello = await read_type(ws, "hello")
    headers = {"X-LV-Session": hello["token"]}
    payload = bytes(range(256)) * 1024
    for expected in ("Тест 文件.bin", "Тест 文件 (1).bin"):
        form = aiohttp.FormData(quote_fields=False)
        form.add_field("file", payload, filename="Тест 文件.bin", content_type="application/octet-stream")
        response = await client.post("/api/files/upload", headers=headers, data=form)
        assert response.status == 200
        assert (await response.json())["saved"] == [expected]
        response = await client.get("/api/files/download", headers=headers, params={"name": expected})
        assert response.status == 200
        assert await response.read() == payload
    response = await client.get("/api/files/download", headers=headers, params={"name": "../config.json"})
    assert response.status == 400
    await client.post("/api/host/settings", headers={"X-Hop-Token": srv.token}, json={"allowControl": False})
    assert (await read_type(ws, "control"))["allowed"] is False
    form = aiohttp.FormData()
    form.add_field("file", b"denied", filename="denied.txt")
    assert (await client.post("/api/files/upload", headers=headers, data=form)).status == 403
    assert (await client.get("/api/files", headers=headers)).status == 200
    await client.post("/api/host/settings", headers={"X-Hop-Token": srv.token}, json={"allowControl": True})
    assert (await read_type(ws, "control"))["allowed"] is True
    await ws.close()


@pytest.mark.asyncio
async def test_settings_validation_persistence_and_pin(app):
    srv, client = app
    headers = {"X-Hop-Token": srv.token}
    for data in ({"theme": "invalid"}, {"openIn": "invalid"}, {"shortName": "bad/name"}):
        assert (await client.post("/api/host/settings", headers=headers, json=data)).status == 400
    assert (await client.post("/api/host/settings", headers=headers, json={"theme": "dark", "openIn": "fullscreen"})).status == 200
    assert host.load_config()["theme"] == "dark"
    assert (await client.post("/api/host/pin", headers=headers, json={"pin": "123"})).status == 400
    assert (await client.post("/api/host/pin", headers=headers, json={"pin": "829461"})).status == 200
    ws = await connect(client, "829461")
    await read_type(ws, "hello")
    await ws.close()


@pytest.mark.asyncio
async def test_input_routes_and_view_only(app):
    srv, client = app
    ws = await connect(client)
    await read_type(ws, "hello")
    session = next(iter(srv.sessions.values()))
    recorder = Mock()
    session.input = recorder
    messages = [{"t": "move", "x": .25, "y": .5}, {"t": "click", "b": "right", "n": 2},
                {"t": "scroll", "dx": 1, "dy": -2}, {"t": "key", "k": "Control", "down": True},
                {"t": "text", "s": "Hello Привет"}, {"t": "releaseall"}]
    for msg in messages:
        await ws.send_json(msg)
    await asyncio.sleep(0.1)
    for method in ("move", "click", "scroll", "key", "text", "release_all"):
        assert getattr(recorder, method).call_count == 1
    srv.cfg["allowControl"] = False
    await ws.send_json({"t": "text", "s": "must be ignored"})
    await asyncio.sleep(0.05)
    assert recorder.text.call_count == 1
    await ws.close()
