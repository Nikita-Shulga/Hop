"""Smoke test for a built Local View app (used by CI on macOS and Windows).

Starts nothing itself: run the app first, e.g.
    LocalView.exe --headless --no-easy-port --port 8799 --pin 123456
then:  python packaging/smoke_test.py 8799 123456
Checks the viewer page, the info API, PIN sign-in over the WebSocket and (when the machine can capture its
screen) one video frame. Exit code 0 = OK.
"""
import asyncio
import json
import sys

import aiohttp


async def main(port, pin):
    base = "http://127.0.0.1:%d" % port
    async with aiohttp.ClientSession() as s:
        for attempt in range(30):  # the app may still be starting
            try:
                async with s.get(base + "/api/info") as r:
                    info = await r.json()
                break
            except Exception:
                await asyncio.sleep(1)
        else:
            print("FAIL: the app never answered on port %d" % port)
            return 1
        print("info:", info)
        async with s.get(base + "/") as r:
            page = await r.text()
        assert r.status == 200 and "Local View" in page, "viewer page missing"
        print("viewer page: ok")
        ws = await s.ws_connect(base + "/ws")
        await ws.send_str(json.dumps({"t": "auth", "pin": "000000"}))
        bad = await ws.receive(timeout=10)
        assert "Wrong PIN" in bad.data, "a wrong PIN was not refused: %r" % bad.data
        print("wrong PIN refused: ok")
        await ws.close()
        ws = await s.ws_connect(base + "/ws")
        await ws.send_str(json.dumps({"t": "auth", "pin": pin}))
        hello, frames = None, 0
        try:
            while True:
                m = await ws.receive(timeout=10)
                if m.type == aiohttp.WSMsgType.BINARY:
                    frames += 1
                    await ws.send_str('{"t":"ack"}')
                    if hello:
                        break
                elif m.type == aiohttp.WSMsgType.TEXT:
                    d = json.loads(m.data)
                    if d.get("t") == "hello":
                        hello = d
                        print("hello:", {k: d.get(k) for k in ("name", "os", "features")}, "monitors:", d.get("monitors"))
                    elif d.get("t") == "error":
                        print("FAIL: server error:", d.get("msg"))
                        return 1
                else:
                    break
        except asyncio.TimeoutError:
            pass
        await ws.close()
        if not hello:
            print("FAIL: no hello after sign-in")
            return 1
        print("video frames:", frames if frames else "none (this machine can't capture its screen)")
        print("SMOKE TEST PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]), sys.argv[2])))
