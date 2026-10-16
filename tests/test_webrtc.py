import asyncio
import json

from aiortc import RTCConfiguration, RTCPeerConnection
from PIL import Image
import pytest

import remote


@pytest.mark.asyncio
async def test_real_webrtc_video_and_large_unicode_data():
    """Real ICE/DTLS/SRTP/SCTP on loopback, without a cloud account or external STUN."""
    host = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    viewer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    channel_ready = asyncio.get_running_loop().create_future()
    track_ready = asyncio.get_running_loop().create_future()
    data = viewer.createDataChannel("hop")
    viewer_socket = remote.ChannelSocket(viewer, data)

    @host.on("datachannel")
    def channel(ch):
        channel_ready.set_result(remote.ChannelSocket(host, ch))

    @viewer.on("track")
    def track(t):
        if t.kind == "video":
            track_ready.set_result(t)

    screen = remote.ScreenTrack()
    async def image():
        return Image.new("RGB", (640, 360), (210, 70, 30))
    screen.source = image
    host.addTrack(screen)
    viewer.addTransceiver("video", direction="recvonly")
    try:
        await viewer.setLocalDescription(await viewer.createOffer())
        await host.setRemoteDescription(viewer.localDescription)
        await host.setLocalDescription(await host.createAnswer())
        await viewer.setRemoteDescription(host.localDescription)
        socket = await asyncio.wait_for(channel_ready, 15)
        track = await asyncio.wait_for(track_ready, 15)
        frame = await asyncio.wait_for(track.recv(), 15)
        assert (frame.width, frame.height) == (640, 360)
        pixel = frame.to_image().getpixel((320, 180))
        assert abs(pixel[0] - 210) < 20 and abs(pixel[1] - 70) < 20
        payload = json.dumps({"t": "clip", "s": "Привет 文件 🚀" * 10000})
        await socket.send_str(payload)
        result = await asyncio.wait_for(viewer_socket.receive(), 15)
        assert json.loads(result.data) == json.loads(payload)
        await viewer_socket.send_str(json.dumps({"t": "ack"}))
        result = await asyncio.wait_for(socket.receive(), 5)
        assert json.loads(result.data) == {"t": "ack"}
    finally:
        await viewer.close()
        await host.close()


def test_video_odd_dimensions():
    assert remote.even_size(Image.new("RGB", (641, 361))).size == (640, 360)
