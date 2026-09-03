"""Connection-failure reporting: right name for the fault, bounded volume.

A NAX firmware update at Oak Forest took the device off the network for 47
minutes and produced ~4,150 log lines from one site — 810 of them reading
"Authentication error: Cannot connect to host", which is not an authentication
problem at all. These tests pin both halves of that: what a failure is CALLED,
and how often it is repeated.
"""

import logging
import sys

import aiohttp
import pytest

from cresnextws import ClientConfig, CresNextWSClient

# Resolve the module the class actually came from. The repo root carries its own
# __init__.py re-exporting the inner package, so `cresnextws.client` and
# `cresnextws.cresnextws.client` can both be loaded — patching the wrong copy
# silently does nothing.
client_mod = sys.modules[CresNextWSClient.__module__]


class _Clock:
    """Stand-in for the module's `time`, so intervals are exact, not slept."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Response:
    def __init__(self, status=200, headers=None):
        self.status = status
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in for _authenticate()."""

    def __init__(self, logout_exc=None, get_exc=None, token="tok"):
        self.logout_exc = logout_exc
        self.get_exc = get_exc
        self.token = token
        self.logout_calls = 0

    def get(self, url, **kwargs):
        if url.endswith("/logout"):
            self.logout_calls += 1
            if self.logout_exc:
                raise self.logout_exc
            return _Response()
        if self.get_exc:
            raise self.get_exc
        return _Response()

    def post(self, url, **kwargs):
        return _Response(headers={"CREST-XSRF-TOKEN": self.token})


def _client(**overrides):
    config = ClientConfig(
        host="test.local", username="u", password="p", **overrides
    )
    return CresNextWSClient(config)


@pytest.mark.asyncio
async def test_unreachable_device_is_not_called_an_authentication_error(caplog):
    """A closed port is unreachability, and must not be logged as bad credentials."""
    client = _client()
    client._http_session = _FakeSession(
        get_exc=aiohttp.ClientOSError(111, "Connect call failed")
    )

    with caplog.at_level(logging.DEBUG):
        assert await client._authenticate() is None

    assert client._last_failure_transport is not None
    assert "Connect call failed" in client._last_failure_transport
    assert not any(
        "Authentication error" in r.getMessage() for r in caplog.records
    ), "transport failure was reported as an authentication failure"


@pytest.mark.asyncio
async def test_logout_failure_does_not_abort_authentication(caplog):
    """The pre-auth logout is a courtesy; its timeout used to fail the connect."""
    session = _FakeSession(
        logout_exc=aiohttp.ServerTimeoutError("Connection timeout to host /logout")
    )
    client = _client()
    client._http_session = session

    with caplog.at_level(logging.DEBUG):
        token = await client._authenticate()

    assert session.logout_calls == 1
    assert token == "tok", "a failed courtesy logout must not block authentication"
    assert client._last_failure_transport is None


def test_repeated_failures_quieten_but_do_not_go_silent(monkeypatch, caplog):
    """First few failures speak up, the rest summarise on an interval."""
    clock = _Clock()
    monkeypatch.setattr(client_mod, "time", clock)

    client = _client(failure_log_attempts=3, failure_log_interval=600.0)
    client._last_failure_transport = "Connect call failed"

    with caplog.at_level(logging.DEBUG):
        for _ in range(50):
            clock.advance(5.0)
            client._log_connect_failure()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 3, "only the first failures should be loud"

        # 50 attempts x 5s = 250s, still inside the first 600s window.
        summaries = [r for r in caplog.records if "still unreachable" in r.getMessage()]
        assert summaries == []

        clock.advance(600.0)
        client._log_connect_failure()
        summaries = [r for r in caplog.records if "still unreachable" in r.getMessage()]
        assert len(summaries) == 1, "a long outage must not vanish from the log"
        assert "51 attempts" in summaries[0].getMessage()


def test_recovery_reports_the_outage_it_ends(monkeypatch, caplog):
    """The log should say how long the device was gone, not just that it is back."""
    clock = _Clock()
    monkeypatch.setattr(client_mod, "time", clock)

    client = _client()
    client._last_failure_transport = "Connect call failed"
    client._log_connect_failure()
    clock.advance(2832.0)  # 47m12s, the Oak Forest outage
    client._log_connect_failure()

    with caplog.at_level(logging.INFO):
        client._log_connect_recovery()

    messages = [r.getMessage() for r in caplog.records]
    assert any("Reconnected to test.local" in m and "47m12s" in m for m in messages)
    assert client._consecutive_failures == 0
    assert client._outage_started_at is None


def test_backoff_ceiling_is_high_enough_to_stop_hammering():
    """A 5s ceiling meant ~12 attempts a minute forever against a dead device."""
    assert ClientConfig(host="h", username="u", password="p").max_reconnect_delay >= 30.0
