"""Hop's own words, in English and Russian (the host window, notifications, update and error messages).

English is the default. The language is a host setting ("language" in ~/.hop.json, chosen in the host
window); the host calls set_language() when it loads or changes. The web pages have their own strings in
static/i18n.js.

Messages that viewers receive over the wire (PROTOCOL.md) stay English: the viewer translates them itself,
because its language can differ from the host's.

    t("err.pinDigits")                 -> "PIN must be exactly 6 digits"
    t("notify.received", name=…, …)    -> fills {name}
    t("update.minutes", n=5)           -> picks the plural form for n

Text(key, **kw) is a str holding the English text (for logs and for code that compares it) that also
remembers its key, so local(text) can show it in the current language later.
"""

import time

LANGUAGES = ("en", "ru")
LANGUAGE_NAMES = {"en": "English", "ru": "Русский"}
DEFAULT = "en"

_lang = DEFAULT

EN = {
    # host window API errors
    "err.pinDigits": "PIN must be exactly 6 digits",
    "err.noViewer": "No such viewer",
    "err.requestExpired": "That request has expired",
    "err.codeThrice": "Wrong code three times — the request was declined",
    "err.codeMismatch": "That code doesn't match the one on the device",
    "err.noDevice": "No such device",
    "err.badTheme": "Bad theme",
    "err.badOpenMode": "Bad open mode",
    "err.badLanguage": "Bad language",
    "err.shortName": "Use 1–30 letters, digits or hyphens (not at the start or end)",
    "err.startupChange": "Couldn't change the startup setting: {detail}",
    "err.startupMove": "Move Hop to the Applications folder first, then try again.",
    "err.loginItem": "Couldn't add the login item: {detail}",
    "err.startupUnsupported": "Start at login isn't supported on this system",
    "err.notServer": "That isn't a server address, like hop.yourname.workers.dev",
    "err.noInternetBuildWhy": "Internet access isn't available in this build ({detail})",
    "err.noInternetBuild": "Internet access isn't available in this build",
    "err.aiortcMissing": "aiortc is missing",
    "err.addServerFirst": "Add your connection server's address first",
    "err.unknownLink": "Unknown link",
    "err.sendLinksMac": "Sending links needs the Hop window on a Mac",
    "err.airdrop": "Couldn't open AirDrop: {detail}",
    "err.mirroringVersion": "iPhone Mirroring needs macOS 15 or later",
    "err.notAvailable": "Not available",
    "err.restartMacOnly": "Restarting is only needed on macOS",
    "err.restart": "Couldn't restart: {detail}",
    "err.peerGone": "That computer isn't on the network anymore",
    "err.enterAddress": "Enter an address like studio.local or 192.168.1.20",
    "err.noHopAt": "No Hop found at {address}. Check the address and that Hop is running there.",
    "err.thisComputer": "That's this computer",
    "err.setUpInternet": "Set up internet access first",
    "err.id9": "The computer ID has 9 digits",
    "err.nothingToConnect": "Nothing to connect to",
    "err.fileGone": "That file is no longer in the shared folder",
    "err.openFolder": "Couldn't open the folder",
    "err.openWindowToPick": "Open the Hop app window to pick files",
    "err.filePicker": "Couldn't open the file picker: {detail}",
    "err.copyFile": "Couldn't copy the file: {detail}",
    # internet password rules
    "pw.short": {"one": "Use at least {n} character", "other": "Use at least {n} characters"},
    "pw.long": {"one": "Use at most {n} character", "other": "Use at most {n} characters"},
    "pw.digits": "Use letters too, not only digits",
    "pw.variety": "Use more different characters",
    # "Your devices" / "Nearby" details
    "dev.onWifi": "On this Wi-Fi",
    "dev.installHop": "Install Hop on it to connect",
    "dev.lastInternet": "Connected over the internet · {date}",
    "dev.lastWifi": "Connected on Wi-Fi · {date}",
    "dev.generic": "Device",
    # device kinds guessed from the browser (device_from_ua) as shown to people
    "kind.Windows PC": "Windows PC",
    "kind.Android tablet": "Android tablet",
    "kind.Browser": "Browser",
    "kind.Internet": "Internet",
    # notifications
    "notify.guessing": {"one": "Someone is guessing your internet password. Hop paused internet sign-ins for {n} minute. If this continues, click New password.",
                        "other": "Someone is guessing your internet password. Hop paused internet sign-ins for {n} minutes. If this continues, click New password."},
    "notify.received": "Received {name} from {device}",
    "notify.viewing": "{device} ({ip}) is now viewing this computer",
    "notify.pairing": "New device {device} ({ip}) wants access: type the code it shows into Hop",
    "notify.asking": "{device} ({ip}) wants to connect",
    "notify.extendOn": "{device} is now a second screen",
    "notify.extendOff": "{device} stopped being a second screen",
    # updates
    "update.reachGithub": "Couldn't reach GitHub: {detail}",
    "update.noNewer": "There's no newer version to install.",
    "update.fromSource": "You're running Hop from source: update with git pull instead.",
    "update.noBundle": "This copy of Hop isn't running from an app bundle.",
    "update.translocated": "Move Hop to the Applications folder, open it from there, then update.",
    "update.cantReplaceMac": "Hop can't replace itself where it is. Move it to Applications, then update.",
    "update.notPackaged": "This copy of Hop isn't running from its packaged folder.",
    "update.cantWriteWin": "Hop can't write to its folder. Move the Hop folder somewhere you own (like Documents), then update.",
    "update.platforms": "Updates are available on Windows and macOS.",
    "update.noAsset": "This release has no download for your computer ({target}).",
    "update.noSums": "The release has no SHA256SUMS.txt, so the download can't be verified.",
    "update.notListed": "SHA256SUMS.txt doesn't list {name}.",
    "update.checksum": "The download didn't match its checksum. Nothing was changed; try again.",
    "update.noHop": "The download doesn't contain Hop.",
    "update.incompleteWin": "The download doesn't contain a complete Windows app.",
    "update.notStarted": "The update couldn't be started: {detail}",
    # internet access (connection server)
    "cloud.otherAddress": "This server is already set up with another private address. Paste the full address shown on your other computer (it ends with /k/…)",
    "cloud.refused": "The connection server refused this computer (HTTP {status})",
    "cloud.unreachable": "Can't reach the connection server",
    # windows, dialogs, terminal
    "title.computer": "Computer {id}",
    "title.secondScreen": "{title} · Second screen",
    "fatal.port": "Could not start Hop on port {port}: {detail}",
    "fatal.portHint": "Is another program using this port?",
    "banner.running": " Hop host '{name}' ({os}) is running",
    "banner.open": "  Open in a browser on your LAN:  {url}",
    "banner.or": "or  {url}",
    "banner.pin": "  PIN: {pin}",
    "banner.mac": "  macOS: grant Screen Recording + Accessibility to {app} in System Settings > Privacy & Security, then restart it.",
    "banner.thisTerminal": "this terminal app",
    "banner.stopWindow": "  Close the Hop window (or press Ctrl+C here) to stop.",
    "banner.stop": "  Press Ctrl+C to stop.",
}

RU = {
    "err.pinDigits": "PIN-код должен состоять ровно из 6 цифр",
    "err.noViewer": "Это устройство уже отключено",
    "err.requestExpired": "Срок действия запроса истёк",
    "err.codeThrice": "Код трижды введён неверно — запрос отклонён",
    "err.codeMismatch": "Код не совпадает с показанным на устройстве",
    "err.noDevice": "Такого устройства нет",
    "err.badTheme": "Недопустимое оформление",
    "err.badOpenMode": "Недопустимый способ открытия",
    "err.badLanguage": "Недопустимый язык",
    "err.shortName": "Используйте от 1 до 30 латинских букв, цифр или дефисов (дефис — не в начале и не в конце)",
    "err.startupChange": "Не удалось изменить параметр автозапуска: {detail}",
    "err.startupMove": "Сначала переместите Hop в папку «Программы», затем попробуйте ещё раз.",
    "err.loginItem": "Не удалось добавить Hop в объекты входа: {detail}",
    "err.startupUnsupported": "В этой системе автозапуск не поддерживается",
    "err.notServer": "Это не адрес сервера. Пример: hop.yourname.workers.dev",
    "err.noInternetBuildWhy": "В этой сборке нет доступа через интернет ({detail})",
    "err.noInternetBuild": "В этой сборке нет доступа через интернет",
    "err.aiortcMissing": "не установлен aiortc",
    "err.addServerFirst": "Сначала добавьте адрес сервера подключения",
    "err.unknownLink": "Неизвестная ссылка",
    "err.sendLinksMac": "Чтобы отправлять ссылки, нужно окно Hop на Mac",
    "err.airdrop": "Не удалось открыть AirDrop: {detail}",
    "err.mirroringVersion": "Для «Видеоповтора iPhone» нужна macOS 15 или новее",
    "err.notAvailable": "Недоступно",
    "err.restartMacOnly": "Перезапуск нужен только в macOS",
    "err.restart": "Не удалось перезапустить: {detail}",
    "err.peerGone": "Этого компьютера больше нет в сети",
    "err.enterAddress": "Введите адрес, например studio.local или 192.168.1.20",
    "err.noHopAt": "По адресу {address} Hop не найден. Проверьте адрес и убедитесь, что Hop там запущен.",
    "err.thisComputer": "Это этот же компьютер",
    "err.setUpInternet": "Сначала настройте доступ через интернет",
    "err.id9": "ID компьютера состоит из 9 цифр",
    "err.nothingToConnect": "Не указано, к чему подключаться",
    "err.fileGone": "Этого файла больше нет в общей папке",
    "err.openFolder": "Не удалось открыть папку",
    "err.openWindowToPick": "Чтобы выбрать файлы, откройте окно приложения Hop",
    "err.filePicker": "Не удалось открыть окно выбора файлов: {detail}",
    "err.copyFile": "Не удалось скопировать файл: {detail}",
    "pw.short": {"one": "Используйте не меньше {n} символа", "few": "Используйте не меньше {n} символов",
                 "many": "Используйте не меньше {n} символов", "other": "Используйте не меньше {n} символа"},
    "pw.long": {"one": "Используйте не больше {n} символа", "few": "Используйте не больше {n} символов",
                "many": "Используйте не больше {n} символов", "other": "Используйте не больше {n} символа"},
    "pw.digits": "Добавьте буквы — одних цифр недостаточно",
    "pw.variety": "Используйте больше разных символов",
    "dev.onWifi": "В этой сети Wi-Fi",
    "dev.installHop": "Установите на него Hop, чтобы подключаться",
    "dev.lastInternet": "Подключалось через интернет · {date}",
    "dev.lastWifi": "Подключалось по Wi-Fi · {date}",
    "dev.generic": "Устройство",
    "kind.Windows PC": "ПК с Windows",
    "kind.Android tablet": "Планшет Android",
    "kind.Browser": "Браузер",
    "kind.Internet": "Интернет",
    "notify.guessing": {"one": "Кто-то подбирает ваш пароль для доступа через интернет. Hop приостановил вход через интернет на {n} минуту. Если это продолжится, нажмите «Новый пароль».",
                        "few": "Кто-то подбирает ваш пароль для доступа через интернет. Hop приостановил вход через интернет на {n} минуты. Если это продолжится, нажмите «Новый пароль».",
                        "many": "Кто-то подбирает ваш пароль для доступа через интернет. Hop приостановил вход через интернет на {n} минут. Если это продолжится, нажмите «Новый пароль».",
                        "other": "Кто-то подбирает ваш пароль для доступа через интернет. Hop приостановил вход через интернет на {n} минуты. Если это продолжится, нажмите «Новый пароль»."},
    "notify.received": "{device}: получен файл «{name}»",
    "notify.viewing": "Новое подключение: {device} ({ip})",
    "notify.pairing": "Новое устройство {device} ({ip}) запрашивает доступ: введите в Hop код, который оно показывает",
    "notify.asking": "{device} ({ip}) хочет подключиться",
    "notify.extendOn": "{device} теперь работает как второй экран",
    "notify.extendOff": "{device} больше не работает как второй экран",
    "update.reachGithub": "Не удалось связаться с GitHub: {detail}",
    "update.noNewer": "Более новой версии для установки нет.",
    "update.fromSource": "Hop запущен из исходного кода — обновляйте его командой git pull.",
    "update.noBundle": "Эта копия Hop запущена не из пакета приложения.",
    "update.translocated": "Переместите Hop в папку «Программы», откройте его оттуда и обновите.",
    "update.cantReplaceMac": "Hop не может обновить себя в этой папке. Переместите его в «Программы» и обновите.",
    "update.notPackaged": "Эта копия Hop запущена не из своей папки установки.",
    "update.cantWriteWin": "Hop не может записывать в свою папку. Переместите папку Hop туда, где у вас есть права на запись (например, в «Документы»), и обновите.",
    "update.platforms": "Обновления доступны в Windows и macOS.",
    "update.noAsset": "В этом выпуске нет файла для вашего компьютера ({target}).",
    "update.noSums": "В выпуске нет файла SHA256SUMS.txt, поэтому загрузку нельзя проверить.",
    "update.notListed": "В SHA256SUMS.txt нет файла {name}.",
    "update.checksum": "Контрольная сумма загрузки не совпала. Ничего не изменено — попробуйте ещё раз.",
    "update.noHop": "В загруженном архиве нет Hop.",
    "update.incompleteWin": "В загруженном архиве нет полной версии приложения для Windows.",
    "update.notStarted": "Не удалось запустить обновление: {detail}",
    "cloud.otherAddress": "Этот сервер уже настроен на другой личный адрес. Вставьте полный адрес, показанный на другом вашем компьютере (он заканчивается на /k/…)",
    "cloud.refused": "Сервер подключения отказал этому компьютеру (HTTP {status})",
    "cloud.unreachable": "Не удаётся связаться с сервером подключения",
    "title.computer": "Компьютер {id}",
    "title.secondScreen": "{title} · второй экран",
    "fatal.port": "Не удалось запустить Hop на порту {port}: {detail}",
    "fatal.portHint": "Возможно, этот порт занят другой программой?",
    "banner.running": " Hop на компьютере «{name}» ({os}) запущен",
    "banner.open": "  Откройте в браузере в локальной сети:  {url}",
    "banner.or": "или  {url}",
    "banner.pin": "  PIN-код: {pin}",
    "banner.mac": "  macOS: разрешите {app} запись экрана и универсальный доступ в «Системные настройки» → «Конфиденциальность и безопасность», затем перезапустите его.",
    "banner.thisTerminal": "этому приложению терминала",
    "banner.stopWindow": "  Чтобы остановить, закройте окно Hop (или нажмите здесь Ctrl+C).",
    "banner.stop": "  Чтобы остановить, нажмите Ctrl+C.",
}

STRINGS = {"en": EN, "ru": RU}

# pywebview's own words (macOS menu, dialogs); passed to webview.start(localization=…)
WEBVIEW_RU = {
    "global.quitConfirmation": "Вы действительно хотите выйти?",
    "global.ok": "ОК",
    "global.quit": "Выйти",
    "global.cancel": "Отменить",
    "global.saveFile": "Сохранить файл",
    "cocoa.menu.about": "О программе",
    "cocoa.menu.services": "Службы",
    "cocoa.menu.view": "Вид",
    "cocoa.menu.edit": "Правка",
    "cocoa.menu.hide": "Скрыть",
    "cocoa.menu.hideOthers": "Скрыть остальные",
    "cocoa.menu.showAll": "Показать все",
    "cocoa.menu.quit": "Завершить",
    "cocoa.menu.fullscreen": "Перейти в полноэкранный режим",
    "cocoa.menu.cut": "Вырезать",
    "cocoa.menu.copy": "Скопировать",
    "cocoa.menu.paste": "Вставить",
    "cocoa.menu.selectAll": "Выбрать все",
    "windows.fileFilter.allFiles": "Все файлы",
    "windows.fileFilter.otherFiles": "Другие типы файлов",
    "linux.openFile": "Открыть файл",
    "linux.openFiles": "Открыть файлы",
    "linux.openFolder": "Открыть папку",
}

# Short month names for "5 Oct" style dates (Russian: the genitive forms used with a day number)
MONTHS_RU = ("янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек.")


def normalize(lang):
    return lang if lang in LANGUAGES else DEFAULT


def set_language(lang):
    global _lang
    _lang = normalize(lang)
    return _lang


def get_language():
    return _lang


def plural_form(n, lang=None):
    """CLDR plural category of n: English one/other, Russian one/few/many."""
    lang = lang or _lang
    n = abs(int(n))
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    return "one" if n == 1 else "other"


def t(key, lang=None, **kw):
    """`key` in the current (or given) language, with {placeholders} filled in."""
    lang = normalize(lang or _lang)
    s = STRINGS[lang].get(key)
    if s is None:
        s = EN.get(key, key)
    if isinstance(s, dict):
        s = s.get(plural_form(kw.get("n", 0), lang)) or s["other"]
    return s.format(**kw) if kw else s


class Text(str):
    """English text that remembers its key: local(text) shows it in the current language."""

    def __new__(cls, key, **kw):
        obj = str.__new__(cls, t(key, "en", **kw))
        obj.key = key
        obj.kw = kw
        return obj


def local(v):
    """A Text (or an exception carrying one) in the current language; anything else as str."""
    if isinstance(v, BaseException):
        v = v.args[0] if v.args and isinstance(v.args[0], Text) else str(v)
    if isinstance(v, Text):
        return t(v.key, **v.kw)
    return v if isinstance(v, str) else str(v)


def device_label(name):
    """A device name from device_from_ua ("Windows PC", "iPhone · Internet") in the current language."""
    name = str(name or "")
    parts = name.split(" · ")
    out = []
    for p in parts:
        key = "kind." + p
        out.append(t(key) if key in EN else p)
    return " · ".join(out)


def day_month(ts, lang=None):
    """'05 Oct' (English, as Hop always wrote it) / '5 окт.'"""
    lang = normalize(lang or _lang)
    tm = time.localtime(ts)
    if lang == "ru":
        return "%d %s" % (tm.tm_mday, MONTHS_RU[tm.tm_mon - 1])
    return time.strftime("%d %b", tm)


def webview_localization(lang=None):
    return dict(WEBVIEW_RU) if normalize(lang or _lang) == "ru" else {}
