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
the WebSocket connection that created it, dies with that socket, and must be redone
after a reconnect. It is not a durable server-side record.
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
        await self._request(ACTION_REGISTER, {"RegisteringClientIds": [self._client_id]})
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
                    session_id = await self.reestablish()
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

    async def _reap_stale_sessions(self) -> None:
        """Unregister leftover sessions that carry OUR client id.

        A session whose socket died without a clean unregister is never removed by
        us — teardown had nothing to send on. Since we re-register on every
        reconnect and every HA restart, those corpses accumulate under the same
        ``RegisteredClientId``, and the device caps sessions per connection
        (``MaxRcSessionsPerWsConnections``, 30 on a DM-NAX-4ZSP). Left alone, a few
        dozen reloads exhaust the slots and registration starts failing for a
        reason that looks nothing like its cause.

        Only sessions matching our own client id are touched — other clients'
        registrations are none of our business. Runs BEFORE registering, so it can
        never reap the session we are about to depend on.
        """
        try:
            resp = await self._client.http_get("/Device/SubscriptionMgr")
        except Exception as err:  # noqa: BLE001 - cleanup is best-effort
            logger.debug("Could not read SubscriptionMgr state to reap sessions: %s", err)
            return
        state = (
            ((resp or {}).get("content") or resp or {})
            .get("Device", {})
            .get("SubscriptionMgr", {})
        )

        stale = [
            sid
            for sid, entry in self._iter_sessions(state)
            if entry.get("RegisteredClientId") == self._client_id
        ]
        if not stale:
            return

        logger.info(
            "Reaping %d stale SubscriptionMgr session(s) for %s: %s",
            len(stale),
            self._client_id,
            ", ".join(stale),
        )
        try:
            # RcSessionId is an array here, so the whole batch goes in one call.
            await self._request(ACTION_UNREGISTER, {"RcSessionId": stale})
        except SubscriptionMgrError as err:
            # Cosmetic cleanup — never fail a working registration over it.
            logger.debug("Could not reap stale sessions: %s", err)

    @staticmethod
    def _iter_sessions(state: Dict[str, Any]):
        """Yield ``(session_id, entry)`` for every registration in a state blob."""
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
        taking whatever is first.
        """
        for sid, entry in self._iter_sessions(state):
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
        except SubscriptionMgrError as err:
            # Teardown runs on the way down, often against a socket already going
            # away; failing here would mask the real reason we are closing.
            logger.debug("Unregister of %s did not confirm: %s", session_id, err)
        finally:
            self._rc_session_id = None
            self._subscribed_paths.clear()
            self._desired_paths.clear()

    async def reestablish(self) -> Optional[str]:
        """Re-register and re-subscribe after a reconnect.

        A registration is scoped to its WebSocket connection, so a reconnect leaves
        the old session on a socket that no longer exists. Paths are remembered
        locally to be replayed here.
        """
        paths = list(self._desired_paths)
        self._rc_session_id = None
        self._subscribed_paths.clear()
        session_id = await self.register()
        if paths:
            await self.subscribe(paths)
        return session_id
