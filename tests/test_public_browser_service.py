"""Opt-in integration against an isolated Worker preview, using generated video and test profiles.

HOP_SERVICE_TEST_URL=http://127.0.0.1:8788 python -m pytest tests/test_public_browser_service.py -q
"""
import asyncio
import json
import os
import secrets
from unittest.mock import AsyncMock, Mock

import aiohttp
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from PIL import Image
import pytest
import pytest_asyncio

import host
import remote

URL = os.environ.get('HOP_SERVICE_TEST_URL', '').rstrip('/')
pytestmark = pytest.mark.skipif(not URL, reason='Set HOP_SERVICE_TEST_URL to an isolated Worker preview')


async def message(socket, kind):
    for _ in range(50):
        item = await asyncio.wait_for(socket.receive(), 15)
        if item.type != aiohttp.WSMsgType.TEXT:
            raise AssertionError('Connection closed before ' + kind)
        data = json.loads(item.data)
        if data.get('t') == kind:
            return data
    raise AssertionError('Missing ' + kind)


@pytest_asyncio.fixture
async def computer(tmp_path, monkeypatch):
    monkeypatch.setattr(host, 'CONFIG_PATH', str(tmp_path / 'profile.json'))
    monkeypatch.setattr(host, 'SHARED_DIR', str(tmp_path / 'shared'))
    monkeypatch.setattr(host, 'list_monitors', lambda: [
        {'index': 1, 'left': 0, 'top': 0, 'width': 640, 'height': 360}])
    monkeypatch.setattr(host, 'capture_image', lambda *args: Image.new('RGB', (640, 360), (210, 70, 30)))
    monkeypatch.setattr(host, 'mouse', Mock(position=(0, 0)))
    monkeypatch.setattr(host, 'keyboard', Mock())
    # No user's screen, input, clipboard, directory, configuration or persistent identity is used.
    srv = host.HopServer('Generated test screen', 0, '731926', 'test', {
        'notify': False, 'keepAwake': False, 'cloudUrl': URL, 'cloudEnabled': True})
    srv.notify = Mock()
    srv.attention = Mock()
    srv._ensure_cloud_identity()
    link = remote.CloudLink(srv, URL, srv.cfg['cloudId'], srv.cfg['cloudKey'], site_key=srv.site_key)
    link._ice_servers = AsyncMock(return_value=[])  # loopback does not need external STUN
    link.start()
    try:
        for _ in range(100):
            if link.state == 'online':
                break
            await asyncio.sleep(.05)
        assert link.state == 'online', link.error
        yield srv, link
    finally:
        await link.stop()
        for pool in (srv.io_ex, srv.clip.ex, srv._mdns_ex):
            pool.shutdown(wait=True)


async def viewer(computer, password, device):
    srv, _ = computer
    http = aiohttp.ClientSession()
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    data = pc.createDataChannel('lv', ordered=True)
    socket = remote.ChannelSocket(pc, data)
    opened = asyncio.get_running_loop().create_future()
    track = asyncio.get_running_loop().create_future()
    data.on('open', lambda: opened.done() or opened.set_result(True))

    @pc.on('track')
    def on_track(value):
        if value.kind == 'video' and not track.done():
            track.set_result(value)

    try:
        signaling = await http.ws_connect(URL + '/ws/view?id=' + srv.cfg['cloudId'])
        await message(signaling, 'ready')
        pc.addTransceiver('video', direction='recvonly')
        await pc.setLocalDescription(await pc.createOffer())
        await signaling.send_json({'t': 'offer', 'sdp': pc.localDescription.sdp})
        answer = await message(signaling, 'answer')
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'], type='answer'))
        await asyncio.wait_for(opened, 15)
        await socket.send_str(json.dumps({'t': 'auth', 'pin': password, 'device': device}))
        return http, pc, socket, track
    except BaseException:
        await pc.close()
        await http.close()
        raise


@pytest.mark.asyncio
async def test_public_service_requires_password_pairing_then_delivers_encrypted_video(computer):
    srv, link = computer
    device = {'id': secrets.token_hex(8), 'token': secrets.token_hex(24)}
    connection = await viewer(computer, 'incorrect-test-password', device)
    http, pc, socket, _ = connection
    try:
        assert (await message(socket, 'error'))['msg'] == 'Wrong password'
        assert not srv.sessions and not srv.pending
    finally:
        await pc.close()
        await http.close()

    http, pc, socket, track = await viewer(computer, srv.cfg['cloudPassword'], device)
    try:
        pending = await message(socket, 'pending')
        assert len(pending['code']) == 6
        assert not srv.sessions, 'No screen/control session exists before the owner approves pairing'
        approval = next(iter(srv.pending.values()))
        assert approval['code'] == pending['code']
        approval['future'].set_result(True)  # generated test computer only
        hello = await message(socket, 'hello')
        assert hello['name'] == 'Generated test screen'
        assert srv.find_trusted(device)
        video = await asyncio.wait_for(track, 10)
        # A few pre-auth black frames may already be in flight; require the generated authenticated image.
        for _ in range(40):
            frame = await asyncio.wait_for(video.recv(), 10)
            pixel = frame.to_image().getpixel((frame.width // 2, frame.height // 2))
            if abs(pixel[0] - 210) < 25 and abs(pixel[1] - 70) < 25:
                break
        else:
            raise AssertionError('No authenticated test video received')
        assert frame.width == 640 and frame.height == 360
        assert link.state == 'online'
    finally:
        await pc.close()
        await http.close()


@pytest.mark.asyncio
async def test_public_service_cannot_replace_host_with_wrong_secret(computer):
    srv, link = computer
    async with aiohttp.ClientSession() as http:
        with pytest.raises(aiohttp.WSServerHandshakeError) as error:
            await http.ws_connect(URL + '/ws/host?id=' + srv.cfg['cloudId'] + '&key=' + 'x' * 40)
        assert error.value.status == 409
        assert link.state == 'online'
