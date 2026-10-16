"""Internet access for Hop.

The host keeps one WebSocket open to the Hop connection server (cloud/, a Cloudflare Worker)
under a 9-digit ID. A viewer anywhere opens the server's web page, enters the ID and password, and
sends a WebRTC offer through the server; the host answers. From then on video (VP8/H.264) and a
data channel carrying the same JSON messages as the LAN WebSocket go directly between the devices
(or through the optional TURN relay), encrypted end to end (DTLS-SRTP). The password is checked by
the host over that data channel, so it never passes through the server.

host.py wires this in: CloudLink hands each incoming viewer to HopServer.serve_viewer() with a
ChannelSocket (an aiohttp-WebSocket look-alike over the data channel) and a ScreenTrack that the
session feeds. See PROTOCOL.md, "Internet access".
"""

import asyncio
import fractions
import json
import logging
import secrets
import time
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout, WSMsgType, WSServerHandshakeError

from aiortc import (MediaStreamTrack, RTCConfiguration, RTCIceServer, RTCPeerConnection,
                    RTCSessionDescription)
from aiortc.codecs import h264 as _h264, vpx as _vpx
from aiortc.rtcrtpsender import RTCRtpSender
from av import VideoFrame
from PIL import Image

log = logging.getLogger("hop.remote")

# aiortc's defaults are tuned for webcams (VP8 at most 1.5 Mbit/s). Screen text needs more; the
# congestion controller still lowers the rate on slow connections.
_vpx.DEFAULT_BITRATE = 2500000
_vpx.MAX_BITRATE = 8000000
_h264.DEFAULT_BITRATE = 3000000
_h264.MAX_BITRATE = 10000000

VIDEO_CLOCK = 90000
VIDEO_TIME_BASE = fractions.Fraction(1, VIDEO_CLOCK)
# Data-channel messages are capped at 64 KiB. Outgoing JSON is ASCII (json.dumps escapes the rest) and
# wrapping a piece can at most double it (\" and \\), so 30000-character pieces always fit.
CHUNK = 30000
MAX_REMOTE = 4         # simultaneous internet viewers
NEGOTIATION_TIMEOUT = 25.0
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i


def new_cloud_id():
    return "%09d" % (100000000 + secrets.randbelow(900000000))


def new_cloud_key():
    return secrets.token_urlsafe(32)


def new_password(n=8):
    while True:  # random, but never all digits or too few different characters
        pw = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(n))
        if not pw.isdigit() and len(set(pw)) >= 4:
            return pw


def format_id(i):
    i = str(i or "")
    return " ".join(i[k:k + 3] for k in range(0, len(i), 3))


class _Msg(object):
    __slots__ = ("type", "data")

    def __init__(self, type_, data=None):
        self.type = type_
        self.data = data


class ChannelSocket(object):
    """The subset of aiohttp's WebSocketResponse that host.py's sessions use, over a data channel."""

    def __init__(self, pc, channel):
        self.pc = pc
        self.channel = channel
        self.closed = False
        self._q = asyncio.Queue()
        self._parts = {}

        @channel.on("message")
        def _on_message(m):
            if isinstance(m, bytes):
                return
            try:
                d = json.loads(m)
            except ValueError:
                return
            if isinstance(d, dict) and d.get("t") == "chunk":  # {t, id, i, n, s}
                self._add_part(d)
                return
            self._q.put_nowait(_Msg(WSMsgType.TEXT, m))

        @channel.on("close")
        def _on_close():
            self._mark_closed()

        @pc.on("connectionstatechange")
        async def _on_state():
            if pc.connectionState in ("failed", "closed"):
                self._mark_closed()

    def _add_part(self, d):
        try:
            key, i, n, s = str(d["id"]), int(d["i"]), int(d["n"]), str(d["s"])
        except (KeyError, TypeError, ValueError):
            return
        if n < 1 or n > 300 or not 0 <= i < n or len(s) > 70000:  # 1 MB clipboard ≈ 70 pieces
            return
        if key not in self._parts and len(self._parts) >= 4:  # don't buffer unbounded half-messages
            self._parts.pop(next(iter(self._parts)))
        parts = self._parts.setdefault(key, [None] * n)
        if len(parts) != n:
            return
        parts[i] = s
        if all(p is not None for p in parts):
            del self._parts[key]
            full = "".join(parts)
            try:  # rejoin UTF-16 surrogate pairs a browser split across pieces
                full = full.encode("utf-16", "surrogatepass").decode("utf-16")
            except UnicodeError:
                pass
            self._q.put_nowait(_Msg(WSMsgType.TEXT, full))

    def _mark_closed(self):
        if not self.closed:
            self.closed = True
            self._q.put_nowait(_Msg(WSMsgType.CLOSED))

    async def receive(self):
        if self.closed and self._q.empty():
            return _Msg(WSMsgType.CLOSED)
        return await self._q.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        m = await self.receive()
        if m.type in (WSMsgType.CLOSED, WSMsgType.CLOSE, WSMsgType.CLOSING):
            raise StopAsyncIteration
        return m

    def exception(self):
        return None

    async def send_str(self, s):
        if self.closed or self.channel.readyState != "open":
            raise ConnectionResetError("data channel closed")
        if len(s) <= CHUNK:
            self.channel.send(s)
            return
        key = secrets.token_hex(4)
        parts = [s[k:k + CHUNK] for k in range(0, len(s), CHUNK)]
        for i, p in enumerate(parts):
            self.channel.send(json.dumps({"t": "chunk", "id": key, "i": i, "n": len(parts), "s": p}))

    async def send_raw(self, s):
        """Send one message (< 64 KiB, no chunking), waiting while the channel's buffer is full."""
        while not self.closed and self.channel.readyState == "open" and self.channel.bufferedAmount > (1 << 20):
            await asyncio.sleep(0.02)
        if self.closed or self.channel.readyState != "open":
            raise ConnectionResetError("data channel closed")
        self.channel.send(s)

    async def send_bytes(self, b):
        pass  # video goes over the media track, not the data channel

    async def close(self, *a, **kw):
        if not self.closed:
            await asyncio.sleep(0.3)  # let a just-sent message (e.g. why we're closing) reach the viewer
        self._mark_closed()
        try:
            await self.pc.close()
        except Exception:
            pass


class ScreenTrack(MediaStreamTrack):
    """Video track fed by a session: black until the viewer has signed in, then the screen."""

    kind = "video"

    def __init__(self):
        super().__init__()
        self.source = None      # set by the session after sign-in: callable(), awaitable -> PIL image
        self.fps = 20
        self._t0 = None
        self._next = 0.0
        self.frames = 0
        self._black = Image.new("RGB", (64, 36))

    async def recv(self):
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now
        else:
            fps = self.fps if self.source else 2
            wait = self._next - now
            if wait > 0:
                await asyncio.sleep(wait)
        self._next = time.monotonic() + 1.0 / max(1, self.fps if self.source else 2)
        img = None
        if self.source is not None:
            try:
                img = await self.source()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep the stream alive; the next frame may work
                log.warning("Capture for internet viewer failed: %s", e)
        if img is None:
            img = self._black
        frame = VideoFrame.from_image(img)
        frame.pts = int((time.monotonic() - self._t0) * VIDEO_CLOCK)
        frame.time_base = VIDEO_TIME_BASE
        self.frames += 1
        return frame


def even_size(img):
    """Video encoders need even dimensions (4:2:0 chroma)."""
    w, h = img.size
    if w % 2 or h % 2:
        img = img.crop((0, 0, w - w % 2, h - h % 2))
    return img


class CloudLink(object):
    """Keeps this computer registered with the connection server and answers viewers' offers."""

    def __init__(self, server, base_url, host_id, key, on_change=None, site_key=""):
        self.server = server            # HopServer (serve_viewer, host name, etc.)
        self.base = base_url.rstrip("/")
        self.host_id = host_id
        self.key = key
        self.site_key = site_key   # the server's private key (claims a fresh server)
        self.on_change = on_change      # called when status changes (to refresh the host window)
        self.state = "connecting"       # connecting | online | offline | error
        self.error = ""
        self.peers = {}                 # sid -> RTCPeerConnection (negotiating or live)
        self._task = None
        self._ws = None
        self._stopped = False

    # ---- lifecycle
    def start(self):
        self._stopped = False
        self._task = asyncio.ensure_future(self._run())

    async def stop(self):
        self._stopped = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        for pc in list(self.peers.values()):
            try:
                await pc.close()
            except Exception:
                pass
        self.peers.clear()
        self._set("offline", "")

    def _set(self, state, error=""):
        if (state, error) != (self.state, self.error):
            self.state, self.error = state, error
            if self.on_change:
                try:
                    self.on_change()
                except Exception:
                    pass

    def ws_url(self):
        base = self.base
        if base.startswith("https://"):
            base = "wss://" + base[8:]
        elif base.startswith("http://"):
            base = "ws://" + base[7:]
        return "%s/ws/host?id=%s&key=%s&k=%s" % (base, self.host_id, quote(self.key, safe=""),
                                                quote(self.site_key, safe=""))

    async def _run(self):
        delay = 1.0
        timeout = ClientTimeout(total=None, connect=15, sock_connect=15)
        while not self._stopped:
            try:
                self._set("connecting", self.error)
                async with ClientSession(timeout=timeout) as http:
                    self._http = http
                    async with http.ws_connect(self.ws_url(), heartbeat=None, autoping=True,
                                               max_msg_size=1 << 20) as ws:
                        self._ws = ws
                        self._set("online")
                        log.info("Internet access on: ID %s via %s", format_id(self.host_id), self.base)
                        delay = 1.0
                        pinger = asyncio.ensure_future(self._ping(ws))
                        try:
                            async for msg in ws:
                                if msg.type == WSMsgType.TEXT:
                                    self._on_message(msg.data)
                                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSED):
                                    break
                        finally:
                            pinger.cancel()
                            self._ws = None
                        if ws.close_code == 4000:
                            log.warning("Another copy of Hop took over ID %s",
                                        format_id(self.host_id))
            except asyncio.CancelledError:
                raise
            except WSServerHandshakeError as e:
                if e.status == 403:
                    self._set("error", "This server is already set up with another private address. Paste the "
                                       "full address shown on your other computer (it ends with /k/…)")
                    await asyncio.sleep(30)
                    continue
                if e.status == 409:
                    # Someone else owns this ID (e.g. config copied from another computer).
                    old = self.host_id
                    self.host_id = new_cloud_id()
                    self.server.cloud_id_changed(self.host_id)
                    log.warning("ID %s belongs to another computer; switched to %s",
                                format_id(old), format_id(self.host_id))
                    continue
                self._set("error", "The connection server refused this computer (HTTP %s)" % e.status)
            except Exception as e:
                log.info("Connection server unreachable: %s", e)
                self._set("error", "Can't reach the connection server")
            if self._stopped:
                break
            await asyncio.sleep(delay)
            delay = min(30.0, delay * 2)

    async def _ping(self, ws):
        try:
            while True:
                await asyncio.sleep(25)
                await ws.send_str("ping")  # answered by the server without waking it up
        except (asyncio.CancelledError, Exception):
            pass

    async def _send(self, obj):
        ws = self._ws
        if ws is not None and not ws.closed:
            try:
                await ws.send_str(json.dumps(obj))
            except Exception:
                pass

    def _on_message(self, raw):
        if raw == "pong":
            return
        try:
            d = json.loads(raw)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        t = d.get("t")
        if t == "offer" and isinstance(d.get("sid"), str) and isinstance(d.get("sdp"), str):
            asyncio.ensure_future(self._answer(d["sid"], d["sdp"], str(d.get("ip") or "Internet"),
                                               str(d.get("ua") or "")))
        elif t == "bye":
            # The viewer left before we answered: drop that negotiation. Once answered, the viewer may
            # close its signaling socket at any time; NEGOTIATION_TIMEOUT cleans up if it never connects.
            pc = self.peers.get(d.get("sid"))
            if pc is not None and not getattr(pc, "_lv_answered", False):
                asyncio.ensure_future(pc.close())

    async def _ice_servers(self):
        try:
            async with self._http.get(self.base + "/api/ice", params={"k": self.site_key},
                                      timeout=ClientTimeout(total=8)) as r:
                j = await r.json(content_type=None)
            out = []
            for s in j.get("iceServers") or []:
                urls = s.get("urls")
                if isinstance(urls, str):
                    urls = [urls]
                if not urls:
                    continue
                out.append(RTCIceServer(urls=urls, username=s.get("username"),
                                        credential=s.get("credential")))
            return out
        except Exception as e:
            log.info("ICE server list unavailable (%s); using public STUN", e)
            return [RTCIceServer(urls=["stun:stun.cloudflare.com:3478"])]

    async def _answer(self, sid, sdp, ip, ua):
        if len([p for p in self.peers.values() if p.connectionState != "closed"]) >= MAX_REMOTE:
            await self._send({"t": "error", "sid": sid, "msg": "Too many people are connected to this computer"})
            return
        pc = RTCPeerConnection(RTCConfiguration(iceServers=await self._ice_servers()))
        pc._lv_answered = False
        self.peers[sid] = pc
        track = ScreenTrack()
        channel_fut = asyncio.get_event_loop().create_future()

        @pc.on("datachannel")
        def _on_dc(ch):
            # Listen right away: the viewer sends its password the moment the channel opens.
            if not channel_fut.done():
                channel_fut.set_result(ChannelSocket(pc, ch))

        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
            sender = pc.addTrack(track)
            # Prefer VP8 (any resolution, every browser), then H.264.
            try:
                tr = next(t for t in pc.getTransceivers() if t.sender is sender)
                caps = RTCRtpSender.getCapabilities("video").codecs
                order = {"video/VP8": 0, "video/H264": 1}
                tr.setCodecPreferences(sorted(caps, key=lambda c: order.get(c.mimeType, 2)))
            except Exception as e:
                log.debug("Codec preference not applied: %s", e)
            await pc.setLocalDescription(await pc.createAnswer())
            await self._send({"t": "answer", "sid": sid, "sdp": pc.localDescription.sdp})
            pc._lv_answered = True
            sock = await asyncio.wait_for(channel_fut, NEGOTIATION_TIMEOUT)
            channel = sock.channel
            if channel.readyState != "open":
                opened = asyncio.get_event_loop().create_future()
                channel.on("open", lambda: opened.done() or opened.set_result(True))
                await asyncio.wait_for(opened, NEGOTIATION_TIMEOUT)
            log.info("Internet viewer connected from %s", ip)
            await self.server.serve_viewer(sock, ip, ua, remote=True, track=track)
        except asyncio.TimeoutError:
            log.info("Internet viewer from %s didn't finish connecting", ip)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Internet session with %s failed: %s", ip, e)
        finally:
            self.peers.pop(sid, None)
            try:
                await pc.close()
            except Exception:
                pass
