"""English / Russian interface text: same keys everywhere, English by default, English text unchanged."""
import io
import json
import re
import string
import time
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import Mock

import aiohttp  # noqa: F401  (aiohttp test utilities below)
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import pytest
import pytest_asyncio

import host
import i18n
import updater

ROOT = Path(__file__).resolve().parents[1]
I18N_JS = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
TAG = re.compile(r"</?([a-z]+)")


def js_block(name):
    m = re.search(r"/\*%s\*/(.*?)/\*END %s\*/" % (name, name), I18N_JS, re.S)
    assert m, name
    return json.loads(m.group(1))


JS = js_block("STRINGS")
PATTERNS = js_block("PATTERNS")
PLURAL_FORMS = {"en": {"one", "other"}, "ru": {"one", "few", "many", "other"}}


@pytest.fixture(autouse=True)
def english_afterwards():
    yield
    i18n.set_language("en")


def forms(value):
    return list(value.values()) if isinstance(value, dict) else [value]


def placeholders(value):
    return set().union(*(set(PLACEHOLDER.findall(f)) for f in forms(value)))


def check_dictionaries(strings):
    assert set(strings) == {"en", "ru"}
    en, ru = strings["en"], strings["ru"]
    assert sorted(en) == sorted(ru), "keys differ: %s" % sorted(set(en) ^ set(ru))
    for key in en:
        for lang in ("en", "ru"):
            value = strings[lang][key]
            if isinstance(value, dict):
                assert set(value) == PLURAL_FORMS[lang], (lang, key)
                assert isinstance(en[key], dict) and isinstance(ru[key], dict), key
            for f in forms(value):
                assert isinstance(f, str) and f.strip(), (lang, key)
        assert placeholders(en[key]) == placeholders(ru[key]), key
        for f in forms(en[key]) + forms(ru[key]):  # every plural form shows the same values
            assert set(PLACEHOLDER.findall(f)) == placeholders(en[key]), key
        assert sorted(TAG.findall(" ".join(forms(en[key])))) == sorted(TAG.findall(" ".join(forms(ru[key])))), key


def test_web_dictionaries_have_the_same_keys_and_placeholders():
    check_dictionaries(JS)


def test_python_dictionaries_have_the_same_keys_and_placeholders():
    check_dictionaries(i18n.STRINGS)
    for key, value in i18n.WEBVIEW_RU.items():
        assert value.strip(), key


def test_russian_text_uses_russian_typography():
    for key, value in list(JS["ru"].items()) + list(i18n.RU.items()):
        for f in forms(value):
            assert '"' not in re.sub(r"<[^>]+>", "", f), (key, "use « » quotes")
            assert " - " not in f, (key, "use an em dash")
            assert not re.search(r"\(а\)|\(ы\)|\(ов\)|\(и\)", f), (key, "use plural forms")


def test_server_message_patterns_point_at_matching_keys():
    exact = {v for k, v in JS["en"].items() if k.startswith("msg.") and isinstance(v, str)}
    assert len(exact) == len([k for k, v in JS["en"].items() if k.startswith("msg.") and isinstance(v, str)]),         "msg.* texts must be unique"
    for pattern, key, names in PATTERNS:
        assert key in JS["en"], key
        assert re.compile(pattern).groups == len(names), pattern
        assert set(names) == placeholders(JS["en"][key]), key
        # the English text the key describes is matched by its own pattern
        sample = {n: "7" if n == "n" else "Sample" for n in names}
        for f in forms(JS["en"][key]):
            assert re.match(pattern, f.format(**sample)), (pattern, f)


def test_messages_hosts_send_are_known_to_the_viewer():
    english = {v for k, v in JS["en"].items() if k.startswith("msg.") and isinstance(v, str)}

    def known(msg):
        return msg in english or any(re.match(p, msg) for p, _k, _n in PATTERNS)
    for msg in (host.MSG_PAUSED, host.MSG_DECLINED, host.MSG_KICKED, host.MSG_INTERNET_OFF, host.MSG_PAIR_DECLINED,
                "Wrong PIN", "Wrong password", "Auth timeout", "Locked out, try again in 60 s",
                "Too many wrong passwords. Internet sign-ins are paused for 1 more minute",
                "Too many wrong passwords. Internet sign-ins are paused for 5 more minutes",
                "Waiting for approval on the host…", "Type this code into Hop on Studio to trust this device",
                "This computer only allows viewing", "Too many people are connected to this computer",
                "That computer is offline. Make sure Hop is running on it with Internet access turned on."):
        assert known(msg), msg


def test_english_is_the_default_everywhere():
    assert re.search(r"var lang = 'en';", I18N_JS)
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "var l = 'en';" in index and '<html lang="en">' in index
    assert "navigator.language" not in index + I18N_JS  # never picked from the browser
    assert host.DEFAULT_SETTINGS["language"] == "en"
    assert i18n.DEFAULT == "en"
    srv = host.HopServer("Test", 0, "731926", "id", {})
    try:
        assert srv.setting("language") == "en" and srv.settings()["language"] == "en"
        assert i18n.get_language() == "en"
        assert host.HopServer("Test", 0, "731926", "id", {"language": "xx"}).setting("language") == "en"
    finally:
        srv.io_ex.shutdown(wait=True)


class Marked(HTMLParser):
    """Elements carrying data-i18n* attributes, with their English text as written in the page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for kind, attr in (("data-i18n-title", "title"), ("data-i18n-aria", "aria-label"), ("data-i18n-ph", "placeholder")):
            if kind in a and attr in a:
                self.found.append((a[kind], a[attr]))
        if "data-i18n" in a:
            self.stack.append([a["data-i18n"], tag, ""])
        elif self.stack:
            self.stack.append([None, tag, ""])

    def handle_endtag(self, tag):
        if self.stack:
            key, _tag, text = self.stack.pop()
            if key:
                self.found.append((key, text))
            elif self.stack:
                self.stack[-1][2] += text

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][2] += data


@pytest.mark.parametrize("page", ["index.html", "host.html"])
def test_english_page_text_is_unchanged(page):
    html = (ROOT / "static" / page).read_text(encoding="utf-8")
    parser = Marked()
    parser.feed(html)
    assert len(parser.found) > 40
    for key, text in parser.found:
        assert key in JS["en"], key
        assert JS["en"][key] == text, (key, text)
    for key, inner in re.findall(r'data-i18n-html="([^"]+)"[^>]*>(.*?)</(?:p|small|span)>', html):
        assert JS["en"][key] == inner, key


def test_python_text_and_plurals():
    assert i18n.t("err.pinDigits") == "PIN must be exactly 6 digits"
    assert host.password_problem("abc") == "Use at least 8 characters"
    assert updater.installation()["problem"] == "You're running Hop from source: update with git pull instead."
    i18n.set_language("ru")
    assert i18n.t("err.pinDigits") == "PIN-код должен состоять ровно из 6 цифр"
    assert i18n.local(host.password_problem("abc")) == "Используйте не меньше 8 символов"
    assert host.password_problem("abc") == "Use at least 8 characters"  # logs and comparisons stay English
    assert i18n.local(updater.installation()["problem"]).startswith("Hop запущен из исходного кода")
    assert [i18n.plural_form(n) for n in (1, 2, 5, 11, 21, 22, 25, 111)] == \
        ["one", "few", "many", "many", "one", "few", "many", "many"]
    assert i18n.t("notify.guessing", n=5).count("5 минут") == 1
    assert i18n.t("notify.guessing", n=2).count("2 минуты") == 1
    assert i18n.device_label("Windows PC · Internet") == "ПК с Windows · Интернет"
    assert i18n.device_label("iPhone") == "iPhone"
    assert i18n.day_month(time.mktime((2026, 10, 5, 12, 0, 0, 0, 0, -1))) == "5 окт."
    assert i18n.webview_localization()["cocoa.menu.quit"] == "Завершить"
    i18n.set_language("en")
    ts = time.mktime((2026, 10, 5, 12, 0, 0, 0, 0, -1))
    assert i18n.day_month(ts) == time.strftime("%d %b", time.localtime(ts))
    assert i18n.webview_localization() == {}
    assert i18n.local(RuntimeError(i18n.Text("update.noHop"))) == "The download doesn't contain Hop."


def test_terminal_banner_follows_the_language(monkeypatch, capsys):
    srv = Mock(name="srv", pin="123456", urls=lambda: ["http://pc.local", "http://192.168.1.20:8765"])
    srv.name = "Studio"
    host.print_banner(srv)
    english = capsys.readouterr().out
    assert " Hop host 'Studio' (%s) is running" % host.OS_NAME in english
    assert "  Open in a browser on your LAN:  http://pc.local\n" + " " * 30 + "or  http://192.168.1.20:8765" in english
    i18n.set_language("ru")
    host.print_banner(srv)
    russian = capsys.readouterr().out
    assert "PIN-код: 123456" in russian or "PIN: 123456" in russian  # English if the console can't show Russian


@pytest_asyncio.fixture
async def app(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(host, "SHARED_DIR", str(tmp_path / "shared"))
    monkeypatch.setattr(host, "list_monitors", lambda: [{"index": 1, "left": 0, "top": 0, "width": 1280, "height": 720}])

    def frame(mon, maxw, quality, previous):
        out = io.BytesIO()
        Image.new("RGB", (640, 360), "orange").save(out, format="JPEG")
        return out.getvalue(), b"frame"
    monkeypatch.setattr(host, "capture_frame", frame)
    monkeypatch.setattr(host, "mouse", Mock(position=(0, 0)))
    monkeypatch.setattr(host, "keyboard", Mock())
    monkeypatch.setenv("HOP_DRY_OPEN", "1")
    srv = host.HopServer("Test", 0, "731926", "id", {"notify": False, "keepAwake": False})
    server_app = host.build_app(srv)
    server_app.on_startup.clear()
    client = TestClient(TestServer(server_app))
    await client.start_server()
    srv.port = client.server.port
    yield srv, client
    await client.close()


@pytest.mark.asyncio
async def test_language_setting_is_saved_by_the_host(app):
    srv, client = app
    headers = {"X-Hop-Token": srv.token}
    page = await (await client.get("/host")).text()
    assert 'data-lang="en"' in page and "__LV_LANG__" not in page
    bad = await client.post("/api/host/pin", headers=headers, json={"pin": "12"})
    assert (await bad.json())["error"] == "PIN must be exactly 6 digits"
    assert (await client.post("/api/host/settings", headers=headers, json={"language": "de"})).status == 400

    r = await client.post("/api/host/settings", headers=headers, json={"language": "ru"})
    status = await r.json()
    assert status["settings"]["language"] == "ru" and srv.cfg["language"] == "ru"
    assert json.loads(Path(host.CONFIG_PATH).read_text(encoding="utf-8"))["language"] == "ru"
    assert 'data-lang="ru"' in await (await client.get("/host")).text()
    bad = await client.post("/api/host/pin", headers=headers, json={"pin": "12"})
    assert (await bad.json())["error"] == "PIN-код должен состоять ровно из 6 цифр"

    # Viewer windows this app opens speak its language; viewers' protocol messages stay English.
    def add_peer():  # re-added before each connect: the wrong-PIN delay can outlast PEER_TTL on slow runners
        srv.peers["p"] = {"id": "p", "name": "Studio", "os": "mac", "ip": "192.168.1.30", "port": 8765, "seen": time.time()}
    add_peer()
    assert (await client.post("/api/host/connect", headers=headers, json={"peer": "p"})).status == 200
    assert srv.last_open[0].endswith("#pin=731926&lang=ru")
    ws = await client.ws_connect("/ws")
    await ws.send_json({"t": "auth", "pin": "000000"})
    msg = await ws.receive_json(timeout=5)
    assert msg == {"t": "error", "msg": "Wrong PIN"}
    await ws.close()

    await client.post("/api/host/settings", headers=headers, json={"language": "en"})
    add_peer()
    assert (await client.post("/api/host/connect", headers=headers, json={"peer": "p"})).status == 200
    assert srv.last_open[0].endswith("#pin=731926")
