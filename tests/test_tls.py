import ssl
import asyncio
import datetime
from pathlib import Path

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

import hop_tls


def test_bundled_ca_roots_keep_certificate_and_hostname_verification():
    context = hop_tls.client_context()
    assert Path(certifi.where()).is_file()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.cert_store_stats()['x509_ca'] > 50


def test_default_asyncio_turn_tls_uses_the_bundled_ca_file(monkeypatch):
    import os
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    hop_tls.client_context.cache_clear()
    hop_tls.client_context()
    assert os.environ['SSL_CERT_FILE'] == certifi.where()
    context = ssl.create_default_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()['x509_ca'] > 50


def test_explicit_ca_override_is_preserved(monkeypatch):
    import os
    monkeypatch.setenv('SSL_CERT_FILE', certifi.where())
    hop_tls.client_context.cache_clear()
    hop_tls.client_context()
    assert os.environ['SSL_CERT_FILE'] == certifi.where()


@pytest.mark.asyncio
async def test_context_rejects_an_untrusted_self_signed_peer(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(minutes=5))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'test.pem', tmp_path / 'test.key'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)

    async def connected(reader, writer):
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(connected, '127.0.0.1', 0, ssl=server_context)
    try:
        port = server.sockets[0].getsockname()[1]
        with pytest.raises(ssl.SSLCertVerificationError):
            await asyncio.open_connection('127.0.0.1', port, ssl=hop_tls.client_context(), server_hostname='localhost')
    finally:
        server.close()
        await server.wait_closed()
