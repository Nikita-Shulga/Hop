from aiortc import RTCIceServer
from aiortc.rtcicetransport import connection_kwargs
from remote import prefer_tls_turn


def test_aiortc_uses_verified_tls_443_even_when_provider_lists_udp_first():
    servers = [RTCIceServer(urls=['stun:stun.cloudflare.com:3478']), RTCIceServer(
        urls=['turn:turn.cloudflare.com:3478?transport=udp',
              'turns:turn.cloudflare.com:5349?transport=tcp',
              'turns:turn.cloudflare.com:443?transport=tcp'], username='short-user', credential='short-secret')]
    config = connection_kwargs(prefer_tls_turn(servers))
    assert config['turn_server'] == ('turn.cloudflare.com', 443)
    assert config['turn_ssl'] is True
    assert config['turn_transport'] == 'tcp'
    assert config['turn_username'] == 'short-user'
    assert config['stun_server'] == ('stun.cloudflare.com', 3478)


def test_private_custom_turn_and_stun_are_preserved_when_no_tls_443_is_available():
    servers = [RTCIceServer(urls=['stun:stun.example.test:3478']), RTCIceServer(
        urls='turn:relay.example.test:3478?transport=udp', username='u', credential='p')]
    config = connection_kwargs(prefer_tls_turn(servers))
    assert config['turn_server'] == ('relay.example.test', 3478)
    assert config['turn_ssl'] is False
    assert config['turn_transport'] == 'udp'
