"""
SubscriptionMgr client for CresNext devices (Media Player 2.0 registration API).

Most CresNext objects emit change events on the ordinary ``/websockify`` socket with
no ceremony — subscribe a callback and updates arrive. ``MediaPlayerNeXt`` does not.
Its player state and now-playing metadata are served by a SEPARATE WebSocket
endpoint, ``/subscriptionmgr``, and stay completely silent until the client has
registered there and named the object paths it wants.

That endpoint asymmetry is the trap this module exists to hide. Over ``/websockify``
(or plain HTTPS) the ``/Device/SubscriptionMgr`` object *appears* to exist but is a
stub: it reports no ``Version``, and a ``RegisterClient`` request against it is
accepted and then fails internally with an undocumented ``StatusId: -5``
("device response timeout error"). Connect to ``/subscriptionmgr`` instead and the
very same device announces ``"Version": "2.1.0"`` and answers properly. Read the
object over the wrong socket and you will conclude the firmware lacks the feature.

**Authentication is the ordinary CresNext session** — the username/password cookie +
XSRF handshake ``CresNextWSClient`` already performs. Crestron's docs describe a
"Simple Client Authentication" scheme using console-created credentials
(``createclient`` → UUID + secret → ``CrestronAuth-SHA256`` header); that is an
alternative for clients that would rather not hold a session, NOT a prerequisite.
Verified against a DM-NAX-4ZSP: standard auth connects and registers fine.

**This is optional.** Touch panels, control processors and most other CresNext gear
have no SubscriptionMgr at all. Nothing here runs unless a caller asks for it, and
:meth:`SubscriptionMgrClient.connect` reports unsupported devices rather than
raising, so it is safe to enable across a mixed fleet.

Lifecycle: a registration lives under ``WsConnectionsList/<WsNN>`` — it is scoped to
the WebSocket connection that created it and must be redone after a reconnect.

But it does NOT die with that socket, and this is the trap that matters most. The
socket going away removes the session from ``WsConnectionsList`` while leaving it in
the top-level ``RegisteredClientList``, where it stays — past ``ExpirationDurInSecs``,
and across a device reboot. It cannot be removed afterwards either: the device
refuses ``UnregisterClient`` for a session with no live socket
(``StatusId: -4 INVALID_RC_SESSION_ID``), singly or in a batch, though the same call
against a live session succeeds. So every ungraceful shutdown strands one session on
the device permanently, and the only defence is to unregister while the socket is
still up — which is what :meth:`SubscriptionMgrClient._release_previous_session`
exists to do. None of this is in Crestron's API reference, which says nothing about
socket-close cleanup or any cap. Measured on a DM-NAX-4ZSP (3.1.0103).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from .client import ClientConfig, ConnectionStatus, CresNextWSClient

logger = logging.getLogger(__name__)

#: The dedicated WebSocket endpoint serving the registration API.
SUBSCRIPTION_MGR_WS_PATH = "/subscriptionmgr"

# RegistrationAction verbs, per Crestron's Media Player 2.0 API reference.
ACTION_REGISTER = "RegisterClient"
ACTION_UNREGISTER = "UnregisterClient"
ACTION_SUBSCRIBE = "SubscribeToObject"
ACTION_UNSUBSCRIBE = "UnsubscribeFromObject"
ACTION_GET_OBJECT = "GetCresNextObject"

DEFAULT_TIMEOUT = 15.0

# How long to keep the socket open after an acked UnregisterClient, waiting for
# the device to actually drop the record.
#
# The ack is NOT the removal. Measured on a DM-NAX-4ZSP (3.1.0103): the ack comes
# back in ~6ms, the record disappears from RegisteredClientList ~390ms later, and
# closing the socket in between abandons the removal — leaving a session that can
# never be cleaned up (the device then refuses its id as INVALID_RC_SESSION_ID).
# Home Assistant closed the socket 3ms after the POST and stranded one session on
# every single reload, restart and reconnect.
#
# Generous against the measured figure because being slow here costs a moment of
# teardown, while being early costs a permanent slot on the device. Normally
# returns in well under a second — this is a ceiling, not a sleep.
REMOVAL_TIMEOUT = 5.0
REMOVAL_POLL = 0.1


class SubscriptionMgrError(Exception):
    """A SubscriptionMgr request failed, or the device does not support it."""


class SubscriptionMgrClient:
    """Registers with ``/subscriptionmgr`` and subscribes to object paths.

    Owns its own :class:`CresNextWSClient` on the dedicated endpoint, separate from
    whatever connection the caller uses for ordinary telemetry.

    Args:
        config: Connection settings for the device. ``websocket_path`` is overridden
            to ``/subscriptionmgr``; everything else (host, credentials, SSL,
            reconnect policy) is used as given.
        client_id: Stable identifier for this client, echoed back by the device as
            ``RegisteredClientId``. Crestron's examples use a MAC-derived string.
            Must be stable so our own registration is recognisable among others'.
        timeout: Seconds to wait for each request's acknowledgement.
        on_message: Optional callback invoked with every inbound message that is not
            a request acknowledgement — i.e. the subscribed telemetry. Wire this to
            your dispatcher.
    """

    def __init__(
        self,
        config: ClientConfig,
        client_id: str,
        timeout: float = DEFAULT_TIMEOUT,
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_reestablished: Optional[Callable[[], None]] = None,
    ) -> None:
        # dataclasses.replace would be neater but ClientConfig may be subclassed.
        sub_config = ClientConfig(
            **{
                **{
                    field: getattr(config, field)
                    for field in config.__dataclass_fields__  # type: ignore[attr-defined]
                },
                "websocket_path": SUBSCRIPTION_MGR_WS_PATH,
            }
        )
        self._client = CresNextWSClient(sub_config)
        self._client_id = client_id
        self._timeout = timeout
        self._on_message = on_message

        self._rc_session_id: Optional[str] = None
        # Confirmed by the device vs. what we intend to have subscribed. They
        # differ when a request fails or a socket drops mid-flight, and recovery
        # must replay INTENT — replaying only what was confirmed would restore
        # nothing after a failure and leave the feed permanently silent.
        self._subscribed_paths: List[str] = []
        self._desired_paths: List[str] = []
        self._supported = False
        # Each in-flight request parks a future keyed by MsgId; the device echoes
        # MsgId back in its Actions acknowledgement, so correlation is exact.
        self._pending: Dict[str, asyncio.Future] = {}
        self._on_reestablished = on_reestablished
        # A reconnect storm delivers several CONNECTED events in a row; without
        # this they each re-register concurrently. See reestablish().
        self._reestablish_lock = asyncio.Lock()
        self._reader_task: Optional[asyncio.Task] = None
        self._renew_task: Optional[asyncio.Task] = None
        self._latest_state: Dict[str, Any] = {}
        self._capabilities: Dict[str, Any] = {}
        self._expiration_secs: Optional[int] = None

    # -- state ---------------------------------------------------------------

    @property
    def rc_session_id(self) -> Optional[str]:
        """Device-generated session id, or None when not registered.

        Generated BY THE DEVICE at registration — a client-chosen UUID is rejected.
        """
        return self._rc_session_id

    @property
    def subscribed_paths(self) -> List[str]:
        return list(self._subscribed_paths)

    @property
    def is_registered(self) -> bool:
        return self._rc_session_id is not None

    @property
    def is_supported(self) -> bool:
        """Whether the device answered on ``/subscriptionmgr``. Valid after connect."""
        return self._supported

    @property
    def connected(self) -> bool:
        return self._client.connected

    @property
    def capabilities(self) -> Dict[str, Any]:
        """Limits and supported verbs, from the device's connect-time greeting.

        Includes ``MaxWsConnections``, ``MaxRcSessionsPerWsConnections``,
        ``MaxSubscriptionsPerRcSessions`` and ``ActionsSupported``. Empty until
        connected.
        """
        return dict(self._capabilities)

    @property
    def max_subscriptions(self) -> Optional[int]:
        """Subscription cap for one session, if the device stated one.

        A DM-NAX-4ZSP reports 50. Worth checking before subscribing to a large
        path list, since exceeding it is likely to fail the whole request.
        """
        value = self._capabilities.get("MaxSubscriptionsPerRcSessions")
        return value if isinstance(value, int) else None

    # -- connection ----------------------------------------------------------

    async def connect(self) -> bool:
        """Open the dedicated socket. Returns False if the device does not serve it.

        Never raises on an unsupported device — gear without SubscriptionMgr simply
        refuses the endpoint, which is a legitimate answer rather than an error.
        """
        try:
            ok = await self._client.connect()
        except Exception as err:  # noqa: BLE001 - unsupported devices refuse variously
            logger.info(
                "Device does not serve %s (%s); MP2 subscriptions unavailable",
                SUBSCRIPTION_MGR_WS_PATH,
                err,
            )
            self._supported = False
            return False

        if not ok:
            logger.info(
                "Connection to %s refused; MP2 subscriptions unavailable",
                SUBSCRIPTION_MGR_WS_PATH,
            )
            self._supported = False
            return False

        self._supported = True
        self._reader_task = asyncio.create_task(self._read_loop())
        # A session is bound to the socket that created it, so a reconnect
        # silently invalidates it. Nothing announces that: requests simply stop
        # being acknowledged and telemetry stops arriving, which is
        # indistinguishable from the feature not working. Re-establish eagerly.
        self._client.add_connection_status_handler(self._on_connection_status)
        logger.debug("Connected to %s", SUBSCRIPTION_MGR_WS_PATH)
        return True

    def _on_connection_status(self, status: ConnectionStatus) -> None:
        """Re-register after a reconnect, since the old session died with the socket."""
        if status is not ConnectionStatus.CONNECTED:
            return
        # Only meaningful once we HAVE a session; on the first connect there is
        # nothing to restore and register() is about to run anyway.
        if self._rc_session_id is None:
            return
        try:
            asyncio.get_running_loop().create_task(self._reestablish_safe())
        except RuntimeError:  # no running loop (tests / teardown)
            logger.debug("Reconnect seen with no event loop; skipping re-register")

    async def _reestablish_safe(self) -> None:
        """Best-effort re-register; a failure must not escape into the client."""
        try:
            session_id = await self.reestablish()
            logger.info(
                "Re-registered with SubscriptionMgr after reconnect (RcSessionId=%s)",
                session_id,
            )
        except Exception as err:  # noqa: BLE001
            logger.warning(
                "Could not re-register with SubscriptionMgr after reconnect: %s", err
            )

    async def disconnect(self) -> None:
        """Unregister and close. Safe to call when never connected."""
        self._cancel_renewal()
        try:
            await self.unregister()
        finally:
            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass
            self._reader_task = None
            if self._client.connected:
                await self._client.disconnect()

    # -- message plumbing ----------------------------------------------------

    async def _read_loop(self) -> None:
        """Drain the socket: resolve pending requests, forward telemetry."""
        try:
            while True:
                if not self._client.connected:
                    await asyncio.sleep(1.0)
                    continue
                message = await self._client.next_message(timeout=1.0)
                if message is None:
                    continue
                if self._handle_ack(message):
                    continue
                # SubscriptionMgr state pushes are recorded so a request can read
                # its result; everything else is subscribed telemetry.
                mgr = message.get("Device", {}).get("SubscriptionMgr")
                if mgr:
                    self._latest_state = mgr
                    # The connect-time greeting carries the device's limits and
                    # verb list; keep it so callers can respect the caps rather
                    # than discover them by hitting one.
                    if "ActionsSupported" in mgr:
                        self._capabilities = mgr
                if self._on_message is not None:
                    try:
                        self._on_message(message)
                    except Exception:  # noqa: BLE001 - a bad consumer must not kill the loop
                        logger.exception("SubscriptionMgr message consumer raised")
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("SubscriptionMgr read loop failed")

    def _handle_ack(self, message: Dict[str, Any]) -> bool:
        """Resolve the waiter for an Actions acknowledgement. True if consumed."""
        actions = message.get("Actions")
        if not isinstance(actions, list):
            return False
        consumed = False
        for action in actions:
            if not isinstance(action, dict):
                continue
            future = self._pending.get(action.get("MsgId", ""))
            if future is not None and not future.done():
                future.set_result(action)
                consumed = True
        return consumed

    async def _request(self, action: str, options: Dict[str, Any]) -> Dict[str, Any]:
        """Issue one RequestAction and await its acknowledgement.

        The device answers in two parts — an ``Actions`` ack echoing ``MsgId``, then
        a state push. Only the ack is awaited; the state push lands in
        ``_latest_state`` via the read loop.
        """
        if not self._supported:
            raise SubscriptionMgrError(
                f"Device does not serve {SUBSCRIPTION_MGR_WS_PATH}"
            )
        if not self._client.connected:
            raise SubscriptionMgrError("SubscriptionMgr socket is not connected")

        # UUIDv1 specifically — the API reference calls for it by name.
        msg_id = str(uuid.uuid1())
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future

        try:
            await self._client.ws_post(payload={"Device": {"SubscriptionMgr": {
                "RequestAction": {
                    "MsgId": msg_id,
                    "RegistrationAction": action,
                    "RegistrationActionOptions": options,
                }
            }}})
            ack = await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError as err:
            raise SubscriptionMgrError(
                f"No acknowledgement for {action} within {self._timeout}s"
            ) from err
        finally:
            self._pending.pop(msg_id, None)

        for result in ack.get("Results", []):
            status = result.get("StatusId")
            if isinstance(status, int) and status < 0:
                raise SubscriptionMgrError(
                    f"{action} failed: StatusId={status} "
                    f"{result.get('StatusInfo', '')}".strip()
                )
        return ack

    async def _await_state(
        self,
        predicate: Callable[[Dict[str, Any]], bool],
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """Wait for a SubscriptionMgr state push that satisfies ``predicate``.

        Waiting for merely "the next state message" is wrong: on connect the device
        volunteers a greeting carrying its schema, capabilities and EMPTY client
        lists. That arrives before any request's response, so a naive wait resolves
        against the greeting and concludes the registration produced no session.
        """
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self._latest_state and predicate(self._latest_state):
                return self._latest_state
            await asyncio.sleep(0.05)
        return self._latest_state

    # -- verbs ---------------------------------------------------------------

    async def register(self) -> str:
        """Register and return the device-generated ``RcSessionId``.

        Any leftover sessions bearing our client id are cleared FIRST, so exactly
        one match remains afterwards and identifying our own session needs no
        guesswork about ordering.
        """
        await self._reap_stale_sessions()

        self._latest_state = {}
        try:
            await self._request(
                ACTION_REGISTER, {"RegisteringClientIds": [self._client_id]}
            )
        except SubscriptionMgrError as err:
            raise SubscriptionMgrError(f"{err}{await self._registration_census()}") from err
        state = await self._await_state(
            lambda s: self._find_own_session(s) is not None
        )

        session_id = self._find_own_session(state)
        if session_id is None:
            raise SubscriptionMgrError(
                f"Registration acknowledged but no session id for client_id "
                f"{self._client_id!r} in: {state}"
            )
        self._rc_session_id = session_id
        expiry = state.get("ExpirationDurInSecs")
        if isinstance(expiry, int) and expiry > 0:
            self._expiration_secs = expiry
        logger.info(
            "Registered with SubscriptionMgr as %s (RcSessionId=%s, expires in %ss)",
            self._client_id,
            session_id,
            self._expiration_secs,
        )
        self._start_renewal()
        return session_id

    async def _registration_census(self) -> str:
        """A suffix naming what the device is holding, for a failed registration.

        A full or wedged SubscriptionMgr refuses by saying NOTHING — no negative
        StatusId, no notification, not even the connect-time greeting — so the bare
        timeout is indistinguishable from a device that lacks the feature. Counting
        what it is holding is the difference between "this firmware cannot do it"
        and "this device is out of session slots", which are opposite actions.

        Returns an empty string when the count cannot be read; a diagnostic must
        never turn one failure into two.
        """
        state = await self._read_state()
        if not state:
            return ""
        live = dict(self._iter_live_sessions(state))
        total = len(state.get("RegisteredClientList") or {})
        if not total and not live:
            return ""
        return (
            f" — the device is holding {total} registered session(s), "
            f"{len(live)} on a live connection; "
            f"orphaned sessions may have exhausted it"
        )

    # -- renewal -------------------------------------------------------------

    def _renewal_interval(self) -> Optional[float]:
        """How long to wait before renewing, or None to not renew at all."""
        if not self._expiration_secs:
            return None
        # Half the advertised window: early enough that one failed attempt still
        # leaves room for another before the session actually dies.
        return max(30.0, self._expiration_secs / 2)

    def _start_renewal(self) -> None:
        """(Re)start the proactive renewal timer."""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:  # no running loop (tests / teardown)
            logger.debug("No event loop; SubscriptionMgr renewal not scheduled")
            return

        # register() is called BY the renewal loop (via reestablish), so a naive
        # cancel-and-restart here would cancel the task currently executing this
        # line — killing renewal permanently after the first one.
        if self._renew_task is not None and self._renew_task is asyncio.current_task():
            return

        self._cancel_renewal()
        interval = self._renewal_interval()
        if interval is None:
            return
        self._renew_task = running_loop.create_task(self._renew_loop(interval))

    def _cancel_renewal(self) -> None:
        if self._renew_task and not self._renew_task.done():
            self._renew_task.cancel()
        self._renew_task = None

    async def _renew_loop(self, interval: float) -> None:
        """Re-register before the device expires the session.

        Sessions expire after ``ExpirationDurInSecs`` (1200s on a DM-NAX-4ZSP) —
        measured, not assumed: a session registered at T was gone by T+19min.

        Recovering only via the reconnect handler is not enough. That path depends
        on expiry happening to drop the socket, which nothing in the API promises.
        If a device ever expires a session while leaving the connection up, no
        reconnect fires, no error is logged, and the feed goes silent forever —
        indistinguishable from the bug this whole module exists to fix, except it
        appears twenty minutes in. So renew proactively and keep the reconnect
        handler purely as a backstop.

        There is no documented "renew" verb — the supported actions are register,
        unregister, subscribe, unsubscribe and get — so renewal is a fresh
        register plus a replay of the subscriptions.
        """
        try:
            while True:
                await asyncio.sleep(interval)
                if not self._client.connected:
                    # The reconnect handler will re-establish; nothing to do here.
                    continue
                try:
                    # force: renewal exists precisely to replace a session that is
                    # still live, so the "already live, nothing to do" skip must
                    # not apply here.
                    session_id = await self.reestablish(force=True)
                    logger.debug(
                        "Renewed SubscriptionMgr session (RcSessionId=%s)", session_id
                    )
                    if self._on_reestablished is not None:
                        try:
                            self._on_reestablished()
                        except Exception:  # noqa: BLE001
                            logger.exception("SubscriptionMgr renewal callback raised")
                except Exception as err:  # noqa: BLE001
                    # Half-window timing means a transient failure still leaves
                    # time for the next attempt before the session actually dies.
                    logger.warning(
                        "SubscriptionMgr renewal failed (will retry in %.0fs): %s",
                        interval,
                        err,
                    )
        except asyncio.CancelledError:
            pass

    async def _await_session_removed(self, session_id: str) -> bool:
        """Hold the socket open until the device has really dropped ``session_id``.

        Unregistering is TWO events, and only the first is observable from the
        request: the ack (~6ms) says the device accepted it, and the record
        actually leaves ``RegisteredClientList`` some ~390ms later. Close the
        socket in between and the removal never lands — and the session becomes
        permanently unremovable, since the device subsequently refuses its id as
        ``INVALID_RC_SESSION_ID``.

        That is not a hypothetical: Home Assistant closed the socket 3ms after
        posting the unregister, so every reload stranded exactly one session,
        while the log showed a clean successful teardown.

        Returns True once it is gone, False on timeout — the caller carries on
        either way, because a slow removal is still better than a held-open socket.
        """
        deadline = asyncio.get_running_loop().time() + REMOVAL_TIMEOUT
        while asyncio.get_running_loop().time() < deadline:
            state = await self._read_state()
            if not state:
                # Cannot see the registry (teardown, device blip); nothing to be
                # gained by spinning on a read that is not answering.
                return False
            if session_id not in (state.get("RegisteredClientList") or {}):
                return True
            await asyncio.sleep(REMOVAL_POLL)
        logger.debug(
            "Session %s still listed %.0fs after an acked unregister; "
            "it may be stranded on the device",
            session_id,
            REMOVAL_TIMEOUT,
        )
        return False

    async def _read_state(self) -> Dict[str, Any]:
        """The device's SubscriptionMgr object over HTTP, or ``{}``."""
        try:
            resp = await self._client.http_get("/Device/SubscriptionMgr")
        except Exception as err:  # noqa: BLE001 - every caller is best-effort
            logger.debug("Could not read SubscriptionMgr state: %s", err)
            return {}
        return (
            ((resp or {}).get("content") or resp or {})
            .get("Device", {})
            .get("SubscriptionMgr", {})
        )

    async def _reap_stale_sessions(self) -> None:
        """Release any live session of ours, and report ones nothing can reach.

        **An orphaned session cannot be cleaned up. There is no verb for it.**
        Measured on a DM-NAX-4ZSP (3.1.0103): ``UnregisterClient`` against a
        session with no live socket is refused with ``StatusId: -4
        INVALID_RC_SESSION_ID``, one at a time or batched, while the identical
        call against a live session of our own returns ``StatusId: 0`` and removes
        it. Those records also survive a device reboot. So a session abandoned
        without a clean unregister is on that device permanently, and cleaning up
        afterwards — which an earlier version of this method tried to do — is not
        a thing the API offers. Only :meth:`_release_previous_session` helps, by
        never creating one.

        **Two containers, and the difference is why this looked fixable.**
        ``WsConnectionsList`` holds only sessions on a LIVE socket and is the one
        place ``RegisteredClientId`` appears; the top-level
        ``RegisteredClientList`` is the SUBSCRIPTION registry — every session that
        has subscribed to anything, live or dead, with no owner attribution at all.
        A session appears there on ``subscribe``, not on ``register``.

        What remains worth doing here: unregister a LIVE session still carrying our
        own client id (valid, and it stops us stacking a second one), and count the
        unreachable ones so a device filling up says so in the log rather than
        failing later for a reason that looks nothing like its cause.

        Runs BEFORE registering, so it can never touch the session we are about to
        depend on.
        """
        state = await self._read_state()
        if not state:
            return

        live: Dict[str, Dict[str, Any]] = dict(self._iter_live_sessions(state))
        ours = [
            sid
            for sid, entry in live.items()
            if entry.get("RegisteredClientId") == self._client_id
        ]
        orphans = [
            sid for sid in (state.get("RegisteredClientList") or {}) if sid not in live
        ]
        if orphans:
            # INFO, not WARNING: these are inert. Measured on a DM-NAX-4ZSP with 14
            # of them present, a single connection still registered the full
            # documented 30 live sessions and failed the 31st with
            # EXCEEDED_RC_SESSIONS — so they occupy the subscription registry
            # without consuming the session budget, and nothing needs doing about
            # them. Worth stating anyway: the count is a running tally of
            # ungraceful shutdowns, and it is the first place to look if
            # registration ever starts failing.
            logger.info(
                "%d SubscriptionMgr session(s) on this device are registered with "
                "no live connection. They cannot be unregistered (the device "
                "refuses them as INVALID_RC_SESSION_ID) and survive a reboot, but "
                "they do not consume the live session cap",
                len(orphans),
            )
        if not ours:
            return

        logger.info(
            "Releasing %d live SubscriptionMgr session(s) still held by %s",
            len(ours),
            self._client_id,
        )
        try:
            # RcSessionId is an array here, so the whole batch goes in one call.
            await self._request(ACTION_UNREGISTER, {"RcSessionId": ours})
        except SubscriptionMgrError as err:
            # Cosmetic cleanup — never fail a working registration over it.
            logger.debug("Could not release our previous live session(s): %s", err)

    @staticmethod
    def _iter_live_sessions(state: Dict[str, Any]):
        """Yield ``(session_id, entry)`` for every session on a LIVE connection.

        Only these carry ``RegisteredClientId``; see :meth:`_reap_stale_sessions`.
        """
        for ws_entry in (state.get("WsConnectionsList") or {}).values():
            if not isinstance(ws_entry, dict):
                continue
            for sid, entry in (ws_entry.get("RegisteredClientList") or {}).items():
                if isinstance(entry, dict):
                    yield sid, entry

    def _find_own_session(self, state: Dict[str, Any]) -> Optional[str]:
        """Pick our RcSessionId out of a register response.

        Sessions are nested per WebSocket connection and other clients may be
        registered alongside us, so match on our own RegisteredClientId rather than
        taking whatever is first. The one we have just registered is by definition
        live, so the flat top-level list is not consulted here — it names no owner
        and could only guess.
        """
        for sid, entry in self._iter_live_sessions(state):
            if entry.get("RegisteredClientId") == self._client_id:
                return sid
        return None

    async def subscribe(self, paths: List[str]) -> None:
        """Subscribe to object paths so they begin emitting changes.

        One call carries the whole list. Note the device pushes PARTIAL updates —
        a single changed leaf, e.g. ``{"Player01": {"PlayerState": "paused"}}`` —
        so consumers must merge into retained state rather than replace it.
        """
        if not self._rc_session_id:
            raise SubscriptionMgrError("Not registered — call register() first")
        if not paths:
            return

        # Record intent BEFORE the request so a drop mid-flight is still recoverable.
        for path in paths:
            if path not in self._desired_paths:
                self._desired_paths.append(path)

        await self._request(
            ACTION_SUBSCRIBE,
            {"RcSessionId": self._rc_session_id, "CresNextPath": list(paths)},
        )
        for path in paths:
            if path not in self._subscribed_paths:
                self._subscribed_paths.append(path)
        logger.info("Subscribed to %d SubscriptionMgr path(s)", len(paths))

    async def get_object(self, cresnext_object: str) -> None:
        """Ask the device to send the CURRENT full contents of an object.

        Subscriptions carry only CHANGES, so a client that attaches part-way
        through — at startup, after a reconnect, after a session renewal — never
        receives the fields that are simply sitting still. A player mid-track
        reports its ticking ``ElapsedSec`` and nothing else, so the zone shows a
        position with no title and no player state.

        Crestron documents this verb for exactly that case: *"when the client
        reconnects to the media player, it must make this request to see the
        metadata of the currently-playing track"*.

        The object comes back as an ordinary telemetry message on this socket, so
        it flows through the same dispatch as subscribed updates and needs no
        special handling by the caller — which is also why this returns None
        rather than the object.
        """
        if not self._rc_session_id:
            raise SubscriptionMgrError("Not registered — call register() first")
        await self._request(
            ACTION_GET_OBJECT,
            {"RcSessionId": self._rc_session_id, "CresNextObject": cresnext_object},
        )

    async def unsubscribe(self, paths: List[str]) -> None:
        """Stop receiving changes for the given paths."""
        if not self._rc_session_id or not paths:
            return
        await self._request(
            ACTION_UNSUBSCRIBE,
            {"RcSessionId": self._rc_session_id, "CresNextPath": list(paths)},
        )
        for path in paths:
            if path in self._subscribed_paths:
                self._subscribed_paths.remove(path)

    async def unregister(self) -> None:
        """Release this client's session on the device.

        ``RcSessionId`` is sent as an ARRAY here, unlike subscribe/unsubscribe where
        the same field is a bare string. That asymmetry is Crestron's, not a typo.
        """
        if not self._rc_session_id:
            return
        session_id = self._rc_session_id
        try:
            await self._request(ACTION_UNREGISTER, {"RcSessionId": [session_id]})
            # The ack is not the removal — see _await_session_removed. Closing
            # here, as this method's caller is about to, would strand the session.
            await self._await_session_removed(session_id)
        except SubscriptionMgrError as err:
            # Teardown runs on the way down, often against a socket already going
            # away; failing here would mask the real reason we are closing.
            logger.debug("Unregister of %s did not confirm: %s", session_id, err)
        finally:
            self._rc_session_id = None
            self._subscribed_paths.clear()
            self._desired_paths.clear()

    async def reestablish(self, force: bool = False) -> Optional[str]:
        """Re-register and re-subscribe after a reconnect or a renewal.

        A registration is scoped to its WebSocket connection, so a reconnect leaves
        the old session on a socket that no longer exists. Paths are remembered
        locally to be replayed here.

        **Serialised, and a reconnect will not redo another's work.** A device
        coming back delivers a burst of CONNECTED events, and each one used to
        start its own re-registration: they interleaved, each releasing only the
        id it had captured, and the device was left holding TWO live sessions for
        one client. Seen on a DM-NAX-4ZSP straight after a power cycle. Two live
        sessions are not fatal — the reap in :meth:`register` collects our own on
        the next pass — but each is one more thing to strand if the process is
        killed, so it is worth not creating.

        ``force`` is the renewal's escape hatch: renewing is *deliberately*
        replacing a session that is still perfectly live, which is exactly what the
        skip below would otherwise suppress.
        """
        async with self._reestablish_lock:
            if not force and self._rc_session_id:
                if await self._session_is_live(self._rc_session_id):
                    logger.debug(
                        "Session %s is already live; skipping re-registration",
                        self._rc_session_id,
                    )
                    return self._rc_session_id
            paths = list(self._desired_paths)
            await self._release_previous_session()
            session_id = await self.register()
            if paths:
                await self.subscribe(paths)
            return session_id

    async def _session_is_live(self, session_id: str) -> bool:
        """Whether the device currently lists ``session_id`` on a live connection."""
        state = await self._read_state()
        if not state:
            # Unreadable is not evidence of absence, but re-registering is the
            # safe direction: a spare session is recoverable, a missing one is
            # silence on the feed.
            return False
        return any(sid == session_id for sid, _ in self._iter_live_sessions(state))

    async def _release_previous_session(self) -> None:
        """Hand the old session back before taking a new one.

        A session is scoped to its socket, but the device does NOT drop the record
        when that socket goes away. Measured on a DM-NAX-4ZSP (3.1.0103): sessions
        from dead connections sit in ``RegisteredClientList`` indefinitely, well
        past ``ExpirationDurInSecs``, with ``WsConnectionsList`` empty beside them.

        So abandoning the id leaks a session every time — and renewal alone
        re-registers every ten minutes. Once the device has accumulated enough it
        stops acknowledging ``RegisterClient`` at all: no error, no negative
        StatusId, no greeting on the socket, just silence. Oak Forest reached that
        state with 11 orphans, which took browsing and all externally-started
        playback telemetry down with it and read as a firmware fault.

        This is the ONLY thing that helps, so it is worth doing even though it is
        best-effort. On the reconnect path the old socket is already gone and the
        device refuses the id as ``INVALID_RC_SESSION_ID`` — nothing can be done
        about those. On the RENEWAL path, which is the frequent one at every
        ``ExpirationDurInSecs``/2, the socket is still up and this genuinely
        removes the record. See :meth:`_reap_stale_sessions` for why there is no
        cleaning up after the fact.
        """
        session_id = self._rc_session_id
        # Dropped locally either way: whatever the device does with the request,
        # this client is finished with that session.
        self._rc_session_id = None
        self._subscribed_paths.clear()
        if session_id is None:
            return
        try:
            await self._request(ACTION_UNREGISTER, {"RcSessionId": [session_id]})
            # Registering again immediately would not itself close the socket, but
            # the removal must land before anything counts sessions — and this is
            # the one path where waiting is nearly free.
            gone = await self._await_session_removed(session_id)
            logger.debug(
                "Released previous SubscriptionMgr session %s (removed=%s)",
                session_id,
                gone,
            )
        except SubscriptionMgrError as err:
            logger.debug("Could not release previous session %s: %s", session_id, err)
