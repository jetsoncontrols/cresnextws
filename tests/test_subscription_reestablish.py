"""Re-registration after a reconnect is decided by socket identity, not by a read.

The regression these pin, measured at Oak Forest during a DM-NAX-4ZSP firmware
update: on both reconnects the manager logged "Re-registered with SubscriptionMgr
after reconnect" while handing back the PREVIOUS session id. It had read
``WsConnectionsList`` over HTTP ~30ms after the new socket opened, seen the entry
belonging to the socket that had just died, and concluded the dead session was
live. The feed then stayed silent until the renewal keepalive proved otherwise —
4m25s the first time, 46s the second — and each cycle left another live session
on the device for the reap to collect.
"""

import pytest

# Imported through subscription_mgr, not the package root: the repo root carries
# its own __init__.py re-exporting the inner package, so the root's
# ConnectionStatus can be a DIFFERENT enum object than the one the manager
# compares against by identity.
from cresnextws.subscription_mgr import (
    ClientConfig,
    ConnectionStatus,
    SubscriptionMgrClient,
)


def _mgr():
    config = ClientConfig(host="test.local", username="u", password="p")
    return SubscriptionMgrClient(config, client_id="HA-TEST")


def _with_session(mgr, session_id="old-session", generation=0):
    mgr._rc_session_id = session_id
    mgr._session_generation = generation
    mgr._connection_generation = generation
    return mgr


def _stub_register(mgr, new_id="new-session"):
    """Replace register()/subscribe() and record that they ran."""
    calls = {"register": 0, "subscribe": []}

    async def register():
        calls["register"] += 1
        mgr._rc_session_id = new_id
        mgr._session_generation = mgr._connection_generation
        return new_id

    async def subscribe(paths):
        calls["subscribe"].append(list(paths))

    mgr.register = register  # type: ignore[method-assign]
    mgr.subscribe = subscribe  # type: ignore[method-assign]
    return calls


@pytest.mark.asyncio
async def test_same_socket_skips_reregistration():
    """A duplicate CONNECTED for the socket we already hold must not churn."""
    mgr = _with_session(_mgr())
    calls = _stub_register(mgr)

    assert await mgr.reestablish() == "old-session"
    assert calls["register"] == 0


@pytest.mark.asyncio
async def test_new_socket_forces_reregistration_even_if_device_still_lists_it():
    """The production race: the device's view lags, socket identity does not."""
    mgr = _with_session(_mgr())
    calls = _stub_register(mgr)
    mgr._desired_paths = ["/Device/MediaPlayerNeXt"]

    # The device has not yet pruned the dead socket's entry — the stale read that
    # used to make this skip. It must be irrelevant now.
    async def stale_state():
        return {
            "WsConnectionsList": {
                "Ws01": {
                    "RegisteredClientList": {
                        "old-session": {"RegisteredClientId": "HA-TEST"}
                    }
                }
            }
        }

    mgr._read_state = stale_state  # type: ignore[method-assign]

    mgr._connection_generation += 1  # a new socket arrived

    assert await mgr.reestablish() == "new-session"
    assert calls["register"] == 1, "a reconnect must re-register, not reuse"
    assert calls["subscribe"] == [["/Device/MediaPlayerNeXt"]]


@pytest.mark.asyncio
async def test_dead_session_is_not_unregistered_over_the_wire():
    """UnregisterClient for a session whose socket is gone is always refused."""
    mgr = _with_session(_mgr())
    _stub_register(mgr)

    requests = []

    async def record(action, options):
        requests.append((action, options))
        return {}

    mgr._request = record  # type: ignore[method-assign]

    mgr._connection_generation += 1
    await mgr.reestablish()

    assert requests == [], "no point spending a round-trip on a certain refusal"


@pytest.mark.asyncio
async def test_force_replaces_a_session_on_the_current_socket():
    """The renewal path deliberately replaces a session that IS still live."""
    mgr = _with_session(_mgr())
    calls = _stub_register(mgr)

    async def record(action, options):
        return {}

    mgr._request = record  # type: ignore[method-assign]

    async def removed(session_id):
        return True

    mgr._await_session_removed = removed  # type: ignore[method-assign]

    assert await mgr.reestablish(force=True) == "new-session"
    assert calls["register"] == 1


def test_connection_generation_tracks_every_socket():
    """Counted for all CONNECTED events, not just the ones acted on."""

    mgr = _mgr()
    assert mgr._connection_generation == 0

    # No session yet: the handler returns early, but the socket still counts.
    mgr._on_connection_status(ConnectionStatus.CONNECTED)
    assert mgr._connection_generation == 1

    mgr._on_connection_status(ConnectionStatus.RECONNECTING)
    assert mgr._connection_generation == 1, "only CONNECTED is a new socket"
