"""Verified HTTPS for source and frozen builds, independent of a build machine's CA paths."""
from functools import lru_cache
import os
import ssl

import certifi


@lru_cache(maxsize=1)
def client_context():
    # Keep normal certificate and hostname verification. Add the bundled Mozilla roots so a
    # packaged app does not depend on /opt/homebrew or a developer's Python installation.
    # aioice's TLS TURN socket asks asyncio for the default context. Supply the same bundled
    # trust store through OpenSSL's process-local setting, preserving explicit user overrides.
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context
