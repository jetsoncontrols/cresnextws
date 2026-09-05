"""A setup failure that the client already recovered from is not a failure.

The regression, measured at Oak Forest 2026-09-05. `enable_device_subscriptions`
sent SubscribeToObject; the socket errored 2s later and the ack died with it;
the client's own reconnect registered a NEW session and replayed all 10 paths at
16:52:51; and at 16:52:54 the original 15s wait expired and the except handler
disconnected the socket that had just fixed itself. Home Assistant logged
"Playback started outside Home Assistant will not be reflected" and the site ran
without MP2 telemetry until someone reloaded the integration by hand.

`_reestablish_safe` runs as an INDEPENDENT task, so the recovery and the stale
caller never learn about each other. The handler therefore has to ask the client
what is true now rather than trusting the exception to still describe it.
"""

import pytest

from cresnextws.client import ClientConfig
from cresnextws.data_event_manager import DataEventManager


class _FakeMgr:
    """Stands in for SubscriptionMgrClient across register()/subscribe()."""

    def __init__(self, *, reestablished: bool):
        self._reestablished = reestablished
        self.disconnected = False
        self.subscribed_paths = ["/p1", "/p2"] if reestablished else []

    async def connect(self):
        return True

    async def register(self):
        return "session-1"

    async def subscribe(self, paths):
        # The ack died with the socket. By now the client's own reconnect task
        # has (or has not) put a fresh session in place.
        raise TimeoutError("No acknowledgement for SubscribeToObject within 15.0s")

    async def disconnect(self):
        self.disconnected = True

    @property
    def is_registered(self):
        return self._reestablished

    @property
    def connected(self):
        return self._reestablished

    @property
    def rc_session_id(self):
        return "session-2" if self._reestablished else None


def _manager(monkeypatch, mgr):
    dem = DataEventManager(_Client())
    import cresnextws.subscription_mgr as sm

    monkeypatch.setattr(sm, "SubscriptionMgrClient", lambda *a, **k: mgr)
    return dem


class _Client:
    """Minimal stand-in. DataEventManager registers a status handler on
    construction and `enable_device_subscriptions` reads `.config`; nothing
    else on the real client is reached by these two paths."""

    config = ClientConfig(host="test.local", username="u", password="p")
    connected = True

    def add_connection_status_handler(self, handler):
        self._handler = handler

    def remove_connection_status_handler(self, handler):
        self._handler = None

    async def ws_post(self, payload):  # pragma: no cover - never reached here
        raise AssertionError("not used")


@pytest.mark.asyncio
async def test_a_reestablished_session_is_ADOPTED_not_torn_down(monkeypatch):
    """The bug: this used to disconnect a working subscription and raise."""
    mgr = _FakeMgr(reestablished=True)
    dem = _manager(monkeypatch, mgr)

    session = await dem.enable_device_subscriptions(client_id="HA-TEST", paths=["/p1"])

    assert session == "session-2", "should hand back the session that is LIVE"
    assert not mgr.disconnected, "tore down a subscription that was working"
    assert dem.device_subscriptions is mgr, "caller left thinking telemetry is off"


@pytest.mark.asyncio
async def test_a_genuine_failure_still_cleans_up_and_raises(monkeypatch):
    """The other half. Nothing recovered, so the old behaviour is correct:
    drop the reference, close the socket, and let the caller hear about it."""
    mgr = _FakeMgr(reestablished=False)
    dem = _manager(monkeypatch, mgr)

    with pytest.raises(TimeoutError):
        await dem.enable_device_subscriptions(client_id="HA-TEST", paths=["/p1"])

    assert mgr.disconnected, "leaked a socket nobody can reach"
    assert dem.device_subscriptions is None
