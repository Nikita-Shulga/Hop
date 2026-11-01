import asyncio
from unittest.mock import AsyncMock
import pytest
import remote


def link():
    item = remote.CloudLink(object(), 'https://hop.example.test', '123456789', 'test-host-key-' * 3)
    item._send = AsyncMock()
    return item


@pytest.mark.asyncio
async def test_twelve_duplicate_offers_reserve_one_slot_and_fetch_ice_once():
    item = link()
    blocked = asyncio.Event()
    async def ice(sid):
        await blocked.wait()
        return []
    item._ice_servers = AsyncMock(side_effect=ice)
    tasks = [asyncio.create_task(item._answer('one-sid', 'test-sdp', 'test', '', True)) for _ in range(12)]
    await asyncio.sleep(0)
    assert item._ice_servers.await_count == 1
    assert item._negotiating == {'one-sid'}
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert not item._negotiating
    assert not item.peers


@pytest.mark.asyncio
async def test_distinct_concurrent_offers_reserve_capacity_before_any_ice_await():
    item = link()
    blocked = asyncio.Event()
    async def ice(sid):
        await blocked.wait()
        return []
    item._ice_servers = AsyncMock(side_effect=ice)
    tasks = [asyncio.create_task(item._answer(str(i), 'test-sdp', 'test', '', True)) for i in range(12)]
    await asyncio.sleep(0)
    assert item._ice_servers.await_count == remote.MAX_REMOTE == 4
    assert len(item._negotiating) == 4
    assert item._send.await_count == 8
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert not item._negotiating


@pytest.mark.asyncio
async def test_unapproved_public_offer_never_requests_host_relay_credentials(monkeypatch):
    item = link()
    item._ice_servers = AsyncMock(side_effect=AssertionError('unapproved relay fetch'))
    class Peer:
        connectionState = 'new'
        def on(self, name):
            return lambda callback: callback
        async def setRemoteDescription(self, description):
            raise ValueError('test negotiation ends without networking')
        async def close(self):
            self.connectionState = 'closed'
    monkeypatch.setattr(remote, 'RTCPeerConnection', lambda config: Peer())
    await item._answer('one-sid', 'test-sdp', 'test', '', False)
    item._ice_servers.assert_not_awaited()
    assert not item.peers
    assert not item._negotiating
