"""
CresNext WebSocket API Client

This module provides the main client class for connecting to and interacting
with Crestron CresNext WebSocket API.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, Type, Callable, List
from enum import Enum

import aiohttp
import websockets
from websockets.extensions.permessage_deflate import ClientPerMessageDeflateFactory
from websockets.exceptions import ConnectionClosed, WebSocketException
from dataclasses import dataclass
import ssl
from yarl import URL


logger = logging.getLogger(__name__)


class ConnectionStatus(Enum):
    """Enum representing connection status states."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"


@dataclass
class ClientConfig:
    """
    Configuration class for CresNext WebSocket client.

    Attributes:
        host (str): The hostname or IP address of the CresNext system
        username (str): Username for authentication (required)
        password (str): Password for authentication (required)
        ignore_self_signed (bool): If True, don't verify TLS certificates
            (useful for self-signed certs; default: True)
        auto_reconnect (bool): Whether to automatically reconnect on
            connection loss (default: True)
        auth_path (str): Path for REST authentication endpoint
            (default: "/userlogin.html")
        websocket_path (str): Path for WebSocket endpoint
            (default: "/websockify")
        reconnect_delay (float): Initial delay in seconds before reconnection attempt
            (default: 0.1)
        max_reconnect_delay (float): Maximum delay in seconds for exponential backoff
            (default: 5.0)
        health_check_interval (float): Interval in seconds for connection health checks
            to detect stale connections (default: 5.0)
        health_check_timeout (float): Timeout in seconds for health check responses
            (default: 2.0)
        health_check_path (str): Optional WebSocket path to request during health checks
            for additional validation. If None, only WebSocket ping is used (default: None)
    """

    host: str
    username: str
    password: str
    ignore_self_signed: bool = True
    auto_reconnect: bool = True
    auth_path: str = "/userlogin.html"  # REST auth path
    logout_path: str = "/logout"  # REST logout path
    websocket_path: str = "/websockify"  # WebSocket path
    reconnect_delay: float = 0.1  # Initial reconnect delay
    max_reconnect_delay: float = 5.0  # Maximum reconnect delay for exponential backoff
    health_check_interval: float = 5.0  # Health check every 5 seconds
    health_check_timeout: float = 2.0  # Health check timeout
    health_check_path: Optional[str] = None  # Optional WebSocket path for health check validation


class CresNextWSClient:
    """
    CresNext WebSocket API Client

    A client for connecting to and communicating with Crestron CresNext
    WebSocket API endpoints.
    """

    def __init__(self, config: ClientConfig):
        """
        Initialize the CresNext WebSocket client.

        Args:
            config (ClientConfig): Configuration object containing all settings
        """
        self.config = config

        # Connection state
        self._websocket = None
        self._connected = False
        self._auth_token = None
        self._reconnect_task = None
        self._http_session = None

        # Background tasks and message queue
        self._recv_task = None
        self._health_check_task = None
        self._inbound_queue = asyncio.Queue()

        # Health check state
        self._last_health_check = 0.0
        self._health_check_pending = False

        # Connection status event handlers
        self._connection_status_handlers: List[Callable[[ConnectionStatus], None]] = []
        self._current_status = ConnectionStatus.DISCONNECTED

        logger.debug(
            f"CresNextWSClient initialized for {self.config.host} "
            f"(Auto-reconnect: {self.config.auto_reconnect})"
        )

    def add_connection_status_handler(
        self, handler: Callable[[ConnectionStatus], None]
    ) -> None:
        """
        Add a callback handler for connection status changes.

        Args:
            handler: A callable that takes a ConnectionStatus enum value.
                    This will be called whenever the connection status changes.

        Example:
            def on_status_change(status):
                if status == ConnectionStatus.CONNECTED:
                    print("Client connected!")
                elif status == ConnectionStatus.DISCONNECTED:
                    print("Client disconnected!")

            client.add_connection_status_handler(on_status_change)
        """
        if handler not in self._connection_status_handlers:
            self._connection_status_handlers.append(handler)

    def remove_connection_status_handler(
        self, handler: Callable[[ConnectionStatus], None]
    ) -> None:
        """
        Remove a connection status change handler.

        Args:
            handler: The handler function to remove
        """
        if handler in self._connection_status_handlers:
            self._connection_status_handlers.remove(handler)

    def get_connection_status(self) -> ConnectionStatus:
        """
        Get the current connection status.

        Returns:
            ConnectionStatus: The current status of the connection
        """
        return self._current_status

    def _notify_status_change(self, new_status: ConnectionStatus) -> None:
        """
        Internal method to notify all handlers of a status change.

        Args:
            new_status: The new connection status
        """
        if new_status != self._current_status:
            self._current_status = new_status
            logger.debug(f"Connection status changed to: {new_status.value}")

            # Notify all registered handlers
            for handler in self._connection_status_handlers:
                try:
                    handler(new_status)
                except Exception as e:
                    logger.error(f"Error in connection status handler: {e}")

    def get_base_endpoint(self) -> str:
        """
        Return the base URL for the configured host.

        This method provides access to the base HTTPS endpoint URL that is used
        for all HTTP requests and as the origin for WebSocket connections.

        Returns:
            str: Base URL in format 'https://{host}'

        Example:
            >>> client = CresNextWSClient(ClientConfig(host="device.local", ...))
            >>> client.get_base_endpoint()
            'https://device.local'
        """
        return f"https://{self.config.host}"  # :{self.config.port}

    def _get_auth_endpoint(self) -> str:
        """Return the full REST authentication endpoint for the configured host.

        Returns:
            str: Authentication URL in format 'https://{host}{auth_path}'
        """
        return f"{self.get_base_endpoint()}{self.config.auth_path}"

    def _get_logout_endpoint(self) -> str:
        """Return the full REST logout endpoint for the configured host.

        Returns:
            str: Logout URL in format 'https://{host}{logout_path}'
        """
        return f"{self.get_base_endpoint()}{self.config.logout_path}"

    def _get_ws_url(self) -> str:
        """Return the full WebSocket URL for the configured host.

        Returns:
            str: WebSocket URL in format 'wss://{host}{websocket_path}'
        """
        return f"wss://{self.config.host}{self.config.websocket_path}"  #:{self.config.port}

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context synchronously for use in executor."""
        ssl_context = ssl.create_default_context()
        if self.config.ignore_self_signed:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    async def _authenticate(self) -> Optional[str]:
        """
        Authenticate with the CresNext system via REST API to get auth token.

        Performs a two-step authentication process:
        1. GET request to auth endpoint to obtain TRACKID cookie
        2. POST request with username/password to get CREST-XSRF-TOKEN

        Returns:
            Optional[str]: Authentication token (CREST-XSRF-TOKEN) if successful, None otherwise
        """
        try:
            if self._http_session:
                await self._http_session.get(self._get_logout_endpoint())
            if not self._http_session:
                # Create SSL context in executor to avoid blocking
                loop = asyncio.get_event_loop()
                ssl_context = await loop.run_in_executor(None, self._create_ssl_context)
                connector = aiohttp.TCPConnector(ssl=ssl_context)
                cookie_jar = aiohttp.CookieJar(unsafe=True)
                self._http_session = aiohttp.ClientSession(
                    connector=connector, cookie_jar=cookie_jar
                )
            logger.debug(f"Getting TRACKID cookie from {self._get_auth_endpoint()}")
            async with self._http_session.get(self._get_auth_endpoint()) as response:
                if response.status != 200:
                    logger.error(
                        f"Initial auth request failed with status {response.status}"
                    )
                    return None

            logger.debug(f"Authenticating with {self._get_auth_endpoint()}")
            async with self._http_session.post(
                self._get_auth_endpoint(),
                headers={
                    "Origin": self.get_base_endpoint(),
                    "Referer": f"{self._get_auth_endpoint()}",
                },
                data={
                    "login": self.config.username,
                    "passwd": self.config.password,
                },
            ) as response:
                if response.status == 200:
                    # print all response headers for debugging
                    token = response.headers.get("CREST-XSRF-TOKEN")
                    if token:
                        logger.debug("Authentication successful")
                        return token
                    logger.warning(
                        "Authentication response missing CREST-XSRF-TOKEN header"
                    )
                    return None
                logger.warning(f"Authentication failed with status {response.status}")
                return None

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None

    async def connect(self) -> bool:
        """
        Connect to the CresNext WebSocket API.

        Establishes a complete connection by:
        1. Authenticating via REST API to get auth token
        2. Opening WebSocket connection with proper headers and SSL context
        3. Starting background receive loop task

        Returns:
            bool: True if connection successful, False otherwise
        """
        if self._connected:
            logger.debug("Already connected")
            return True

        # Notify that we're starting the connection process
        self._notify_status_change(ConnectionStatus.CONNECTING)

        logger.info(f"Connecting to CresNext WS API at {self.config.host}")

        try:
            # Authenticate and get token if credentials provided in config
            auth_token = await self._authenticate()

            # If authentication failed, don't proceed to open the WebSocket
            if auth_token is None or self._http_session is None:
                logger.error("Authentication failed; aborting connection")
                self._connected = False
                self._notify_status_change(ConnectionStatus.DISCONNECTED)
                return False

            # Create SSL context in executor to avoid blocking
            loop = asyncio.get_event_loop()
            ssl_context = await loop.run_in_executor(None, self._create_ssl_context)

            logger.debug(f"Connecting to WebSocket: {self._get_ws_url()}")

            # Add XSRF token to cookie jar if present (server expects it as a cookie on WS)
            if auth_token:
                self._http_session.cookie_jar.update_cookies(
                    {"CREST-XSRF-TOKEN": auth_token}, URL(self.get_base_endpoint())
                )

            # Build Cookie header with all cookies for this host
            cookies = self._http_session.cookie_jar.filter_cookies(
                URL(self.get_base_endpoint())
            )
            cookie_parts = (
                [f"{name}={m.value}" for name, m in cookies.items()] if cookies else []
            )
            headers = {
                "Origin": self.get_base_endpoint(),
                # "Referer": f"{self._get_auth_endpoint()}",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
                "X-CREST-XSRF-TOKEN": cookies["CREST-XSRF-TOKEN"].value,
            }
            if cookie_parts:
                headers["Cookie"] = "; ".join(cookie_parts)

            self._websocket = await websockets.connect(
                self._get_ws_url(),
                ssl=ssl_context,
                additional_headers=headers,
                extensions=[
                    ClientPerMessageDeflateFactory(
                        client_max_window_bits=11,
                        server_max_window_bits=11,
                        compress_settings={"memLevel": 4},
                    )
                ],
                ping_interval=None,  # We'll handle pings manually
                close_timeout=2,
            )

            self._connected = True
            # Start receive task
            self._recv_task = asyncio.create_task(self._recv_loop())

            # Start health check task to detect stale connections (e.g., after system sleep)
            self._health_check_task = asyncio.create_task(self._health_check_loop())

            logger.info("WebSocket connection established")
            self._notify_status_change(ConnectionStatus.CONNECTED)
            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            self._notify_status_change(ConnectionStatus.DISCONNECTED)
            return False

    async def _handle_disconnection(self) -> None:
        """
        Handle unexpected disconnection and attempt reconnection if enabled.

        Cleans up the current connection and starts the reconnection loop
        if auto_reconnect is enabled in the configuration.
        """

        logger.info("Connection lost")
        self._connected = False
        self._notify_status_change(ConnectionStatus.DISCONNECTED)

        # Clean up current connection
        await self._cleanup_connection()

        if self.config.auto_reconnect:
            logger.info("Attempting to reconnect...")
            self._notify_status_change(ConnectionStatus.RECONNECTING)
            # Start reconnection task
            if not self._reconnect_task or self._reconnect_task.done():
                self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """
        Background task to handle automatic reconnection.

        Continuously attempts to reconnect at intervals specified by
        config.reconnect_delay until successful or auto_reconnect is disabled.
        Uses exponential backoff to avoid overwhelming the server.
        """
        current_delay = self.config.reconnect_delay
        
        while self.config.auto_reconnect and not self._connected:
            try:
                logger.info(
                    f"Attempting reconnection in {current_delay:.1f} seconds..."
                )
                await asyncio.sleep(current_delay)

                if not self.config.auto_reconnect:
                    break

                # Attempt to reconnect
                success = await self.connect()
                if success:
                    logger.info("Reconnection successful")
                    break
                else:
                    logger.warning("Reconnection failed, will retry...")
                    # Exponential backoff: double the delay, up to max
                    current_delay = min(current_delay * 2, self.config.max_reconnect_delay)

            except asyncio.CancelledError:
                logger.debug("Reconnect loop cancelled")
                break
            except Exception as e:
                logger.error(f"Reconnect loop error: {e}, will retry...")
                # Apply exponential backoff even for exceptions
                current_delay = min(current_delay * 2, self.config.max_reconnect_delay)
                # Continue the loop to retry even after unexpected exceptions

    async def _cleanup_connection(self) -> None:
        """
        Clean up WebSocket connection and background tasks.

        Cancels the receive task and closes the WebSocket connection safely.
        """
        # Cancel receive task
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None

        # Cancel health check task
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

        # Close WebSocket
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as e:
                logger.debug(f"Error closing WebSocket: {e}")
            self._websocket = None

    async def _recv_loop(self) -> None:
        """Background task that receives messages from the WebSocket.

        Continuously listens for messages and processes them:
        - Parses JSON text frames into Python objects and enqueues them
        - Binary frames are logged and ignored
        - Handles incomplete JSON messages by buffering
        - On error/close, triggers disconnect handling if auto_reconnect is enabled
        """
        buffer = ""
        try:
            if not self._websocket:
                return
            async for raw in self._websocket:
                try:
                    if isinstance(raw, bytes):
                        logger.debug("Received binary message (%d bytes)", len(raw))
                        continue
                    # Ensure we have a string to work with
                    if isinstance(raw, str):
                        buffer += raw
                    else:
                        # Handle other types (bytearray, memoryview) by converting to string
                        buffer += str(raw)

                    # Try to parse complete JSON objects from buffer
                    while buffer:
                        try:
                            # Find end of first complete JSON object
                            decoder = json.JSONDecoder()
                            payload, idx = decoder.raw_decode(buffer)
                            await self._inbound_queue.put(payload)
                            buffer = buffer[
                                idx:
                            ].lstrip()  # Remove parsed JSON, skip whitespace
                        except json.JSONDecodeError:
                            # Incomplete JSON, wait for more data
                            break
                except Exception as e:
                    logger.error(f"Error handling received message: {e}")
        except asyncio.CancelledError:
            logger.debug("Receive loop cancelled")
        except (ConnectionClosed, WebSocketException) as e:
            # Log specific details for ConnectionClosed errors (like 1005)
            if isinstance(e, ConnectionClosed):
                if hasattr(e, 'rcvd') and e.rcvd:
                    logger.error(f"WebSocket connection error in receive loop: received {e.rcvd.code} ({e.rcvd.reason})")
                elif hasattr(e, 'sent') and e.sent:
                    logger.error(f"WebSocket connection error in receive loop: sent {e.sent.code} ({e.sent.reason})")
                else:
                    logger.error(f"WebSocket connection error in receive loop: {e}")
            else:
                logger.error(f"WebSocket connection error in receive loop: {e}")
            
            if self.config.auto_reconnect:
                await self._handle_disconnection()
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
            if self.config.auto_reconnect:
                await self._handle_disconnection()

    async def _health_check_loop(self) -> None:
        """
        Background task that performs periodic health checks to detect stale connections.

        This is particularly useful for detecting connections that become stale after
        system sleep/wake cycles, where the WebSocket may appear connected but the
        underlying network connection is dead.
        
        The health check performs two levels of validation:
        1. WebSocket ping/pong to verify basic connectivity
        2. Optional WebSocket GET request (if health_check_path is configured) 
           to ensure real API communication with the device
        """
        logger.debug("Starting connection health check loop")

        try:
            while self._connected:
                try:
                    # Wait for the health check interval
                    await asyncio.sleep(self.config.health_check_interval)

                    if not self._connected:
                        break

                    # Skip health check if one is already pending
                    if self._health_check_pending:
                        logger.debug("Health check already pending, skipping")
                        continue

                    logger.debug("Performing connection health check")
                    self._health_check_pending = True

                    # Send a WebSocket ping for basic connectivity check
                    try:
                        if self._websocket:
                            # Use the WebSocket's built-in ping method with our configured timeout
                            pong_waiter = await self._websocket.ping()
                            await asyncio.wait_for(
                                pong_waiter, timeout=self.config.health_check_timeout
                            )
                            logger.debug("Health check ping passed")
                            
                            # If health_check_path is configured, also send a WebSocket GET request
                            # This provides additional validation by making a real API call
                            if self.config.health_check_path:
                                logger.debug(f"Sending health check WebSocket GET to: {self.config.health_check_path}")
                                await self.ws_get(self.config.health_check_path)
                                logger.debug("Health check WebSocket GET sent successfully")
                    except (
                        asyncio.TimeoutError,
                        ConnectionClosed,
                        WebSocketException,
                    ) as e:
                        # Log specific details for ConnectionClosed errors (like 1005)
                        if isinstance(e, ConnectionClosed):
                            if hasattr(e, 'rcvd') and e.rcvd:
                                logger.warning(f"Health check failed: received {e.rcvd.code} ({e.rcvd.reason})")
                            elif hasattr(e, 'sent') and e.sent:
                                logger.warning(f"Health check failed: sent {e.sent.code} ({e.sent.reason})")
                            else:
                                logger.warning(f"Health check failed: {e}")
                        else:
                            logger.warning(f"Health check failed: {e}")
                        
                        # Health check failed - connection is likely stale
                        if self.config.auto_reconnect:
                            logger.info(
                                "Health check detected stale connection, triggering reconnection"
                            )
                            await self._handle_disconnection()
                            break
                    except Exception as e:
                        logger.error(f"Unexpected error during health check: {e}")
                    finally:
                        self._health_check_pending = False

                except asyncio.CancelledError:
                    logger.debug("Health check loop cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in health check loop: {e}")
                    # Continue health checks even if one fails
                    self._health_check_pending = False
                    await asyncio.sleep(self.config.health_check_interval)

        except asyncio.CancelledError:
            logger.debug("Health check loop cancelled")
        except Exception as e:
            logger.error(f"Health check loop error: {e}")
        finally:
            logger.debug("Health check loop ended")
            self._health_check_pending = False

    async def next_message(
        self, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Await the next inbound message from the receive loop.

        Args:
            timeout (Optional[float]): Optional timeout in seconds to wait before returning None

        Returns:
            Optional[Dict[str, Any]]: The next message dictionary, or None on timeout
        """
        try:
            if timeout is not None:
                return await asyncio.wait_for(
                    self._inbound_queue.get(), timeout=timeout
                )
            return await self._inbound_queue.get()
        except asyncio.TimeoutError:
            return None

    async def disconnect(self) -> None:
        """
        Disconnect from the CresNext WebSocket API.

        Performs a clean shutdown by:
        1. Cancelling any active reconnection tasks
        2. Cleaning up WebSocket connection and background tasks
        3. Closing the HTTP session
        4. Resetting connection state
        """
        if not self._connected:
            logger.debug("Already disconnected")
            return

        logger.info("Disconnecting from CresNext")

        # Stop reconnection attempts (by cancelling tasks below)

        # Cancel reconnect task
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        # Clean up connection
        await self._cleanup_connection()

        # Logout and close HTTP session
        if self._http_session:
            try:
                await self._http_session.get(self._get_logout_endpoint())
                logger.debug("Logout request sent")
            except Exception as e:
                logger.debug(f"Error during logout: {e}")
            await self._http_session.close()
            self._http_session = None

        self._connected = False
        self._auth_token = None
        self._notify_status_change(ConnectionStatus.DISCONNECTED)
        logger.info("Disconnected from CresNext")

    @property
    def connected(self) -> bool:
        """
        Check if the client is currently connected.

        Returns:
            bool: True if connected, False otherwise
        """
        return self._connected

    async def http_get(self, path: str) -> Optional[Dict[str, Any]]:
        """
        Make an HTTP GET request to the connected/authenticated server.

        Args:
            path (str): The path to request (e.g., '/api/status', '/device/info')

        Returns:
            Optional[Dict[str, Any]]: Response dictionary containing:
                - 'content': Response data (parsed JSON or text)
                - 'content_type': Response content type
                - 'status': HTTP status code
                - 'error': Error message (if request failed)
                Returns None if request completely failed

        Raises:
            RuntimeError: If not connected or no active HTTP session
        """
        if not self._connected or not self._http_session:
            raise RuntimeError("Client is not connected. Call connect() first.")

        try:
            # Construct full URL
            url = f"{self.get_base_endpoint()}{path}"
            logger.debug(f"Making HTTP GET request to: {url}")

            async with self._http_session.get(url) as response:
                if response.status == 200:
                    # Try to parse as JSON first
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "application/json" in content_type:
                        data = await response.json()
                        logger.debug(f"HTTP GET successful: {response.status}")
                        return {
                            "content": data,
                            "content_type": content_type,
                            "status": response.status,
                        }
                    else:
                        # For non-JSON responses, try to parse as JSON, fallback to text
                        text = await response.text()
                        text = text.rstrip("\r\n")

                        # Try to parse as JSON even if content-type doesn't indicate it
                        try:
                            json_data = json.loads(text)
                            logger.debug(
                                f"HTTP GET successful (parsed JSON): {response.status}"
                            )
                            return {
                                "content": json_data,
                                "content_type": content_type,
                                "status": response.status,
                            }
                        except json.JSONDecodeError:
                            # Not valid JSON, return as text
                            logger.debug(
                                f"HTTP GET successful (text): {response.status}"
                            )
                            return {
                                "content": text,
                                "content_type": content_type,
                                "status": response.status,
                            }
                else:
                    logger.warning(f"HTTP GET failed with status {response.status}")
                    return {
                        "content": await response.text(),
                        "content_type": response.headers.get(
                            "Content-Type", ""
                        ).lower(),
                        "error": f"HTTP {response.status}",
                        "status": response.status,
                    }

        except Exception as e:
            logger.error(f"HTTP GET request failed: {e}")
            return None

    async def http_post(
        self, path: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Make an HTTP POST request to the connected/authenticated server.

        Args:
            path (str): The path to request (e.g., '/Device/Ethernet/HostName')
            data (Dict[str, Any]): The data to send in the POST request as JSON

        Returns:
            Optional[Dict[str, Any]]: Response dictionary containing:
                - 'content': Response data (for non-JSON responses)
                - 'content_type': Response content type
                - 'status': HTTP status code
                - 'error': Error message (if request failed)
                For JSON responses, returns the parsed JSON directly
                Returns None if request completely failed

        Raises:
            RuntimeError: If not connected or no active HTTP session
            TypeError: If data is not a dictionary
        """
        # Validate data type
        if not isinstance(data, (dict)):
            raise TypeError("Unsupported data type. Data must be a dict.")

        if not self._connected or not self._http_session:
            raise RuntimeError("Client is not connected. Call connect() first.")

        try:
            # Construct full URL
            url = f"{self.get_base_endpoint()}{path}"
            logger.debug(f"Making HTTP post request to: {url}")

            # Prepare headers - start with Content-Type
            cookies = self._http_session.cookie_jar.filter_cookies(
                URL(self.get_base_endpoint())
            )
            headers = {"X-CREST-XSRF-TOKEN": cookies["CREST-XSRF-TOKEN"].value}

            # Make the post request
            async with self._http_session.post(
                url, json=data, headers=headers
            ) as response:
                # Try to parse response
                response_content_type = response.headers.get("Content-Type", "").lower()

                if response.status in [200, 201, 204]:
                    # Success status codes
                    if "application/json" in response_content_type:
                        response_data = await response.json()
                        logger.debug(f"HTTP post successful: {response.status}")
                        return response_data
                    else:
                        # For non-JSON responses, return text content in a dict
                        text = await response.text()
                        logger.debug(
                            f"HTTP post successful (non-JSON): {response.status}"
                        )
                        return {
                            "content": text,
                            "content_type": response_content_type,
                            "status": response.status,
                        }
                else:
                    logger.warning(f"HTTP post failed with status {response.status}")
                    return {
                        "error": f"HTTP {response.status}",
                        "status": response.status,
                        "content": await response.text(),
                    }

        except Exception as e:
            logger.error(f"HTTP post request failed: {e}")
            return None

    async def ws_get(self, path: str) -> None:
        """
        Send a WebSocket GET request for the specified path.

        This function sends a request for data at the given path via the WebSocket connection.
        No direct response is returned - the requested data will arrive later through the
        WebSocket receive loop and can be retrieved using next_message().

        Args:
            path (str): The path to request data from (e.g., "/Device/DiscoveryConfig/DiscoveryAgent")

        Raises:
            RuntimeError: If not connected to WebSocket
        """
        if not self._connected or not self._websocket:
            raise RuntimeError("WebSocket is not connected. Call connect() first.")

        try:
            logger.debug(f"Sending WebSocket GET request for path: {path}")
            await self._websocket.send(path)
            logger.debug(f"WebSocket GET request sent successfully for: {path}")

        except (ConnectionClosed, WebSocketException) as e:
            logger.error(f"Failed to send WebSocket GET request for {path}: {e}")
            # Handle connection loss and trigger reconnection if enabled
            if self.config.auto_reconnect:
                # Don't await here to avoid blocking the caller
                asyncio.create_task(self._handle_disconnection())
            raise
        except Exception as e:
            logger.error(f"Failed to send WebSocket GET request for {path}: {e}")
            raise

    async def ws_post(self, payload: Dict[str, Any]) -> None:
        """
        Send a WebSocket POST request with the specified payload.

        This function sends a dictionary payload as JSON over the WebSocket connection.
        No direct response is returned - any response data will arrive later through the
        WebSocket receive loop and can be retrieved using next_message().

        Args:
            payload (Dict[str, Any]): The data to send as JSON (e.g., {"path": "/Device/Config", "value": "data"})

        Raises:
            RuntimeError: If not connected to WebSocket
            TypeError: If payload is not a dictionary
        """
        if not self._connected or not self._websocket:
            raise RuntimeError("WebSocket is not connected. Call connect() first.")

        if not isinstance(payload, dict):
            raise TypeError("Payload must be a dictionary")

        try:
            json_payload = json.dumps(payload)
            logger.debug(f"Sending WebSocket POST request with payload: {json_payload}")
            await self._websocket.send(json_payload)
            logger.debug("WebSocket POST request sent successfully")

        except (ConnectionClosed, WebSocketException) as e:
            logger.error(f"Failed to send WebSocket POST request: {e}")
            # Handle connection loss and trigger reconnection if enabled
            if self.config.auto_reconnect:
                # Don't await here to avoid blocking the caller
                asyncio.create_task(self._handle_disconnection())
            raise
        except Exception as e:
            logger.error(f"Failed to send WebSocket POST request: {e}")
            raise

    async def __aenter__(self) -> "CresNextWSClient":
        """
        Async context manager entry.

        Automatically connects to the WebSocket when entering the context.

        Returns:
            CresNextWSClient: The connected client instance
        """
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        """
        Async context manager exit.

        Automatically disconnects from the WebSocket when exiting the context.

        Args:
            exc_type (Optional[Type[BaseException]]): Exception type if an exception occurred
            exc_val (Optional[BaseException]]): Exception value if an exception occurred
            exc_tb (Optional[object]): Exception traceback if an exception occurred
        """
        await self.disconnect()
