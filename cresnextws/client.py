"""
CresNext WebSocket API Client

This module provides the main client class for connecting to and interacting
with Crestron CresNext WebSocket API.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, Type

import aiohttp
import websockets
from websockets.extensions.permessage_deflate import ClientPerMessageDeflateFactory
from dataclasses import dataclass
import ssl
from yarl import URL


logger = logging.getLogger(__name__)


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
        ws_ping_interval (float): Interval in seconds for WebSocket ping
            (default: 30.0)
        reconnect_delay (float): Delay in seconds before reconnection attempt
            (default: 5.0)
    """

    host: str
    username: str
    password: str
    ignore_self_signed: bool = True
    auto_reconnect: bool = True
    auth_path: str = "/userlogin.html"  # REST auth path
    logout_path: str = "/logout"  # REST logout path
    websocket_path: str = "/websockify"  # WebSocket path
    ws_ping_interval: float = 10.0  # Ping every 30 seconds
    reconnect_delay: float = 5.0  # Wait 5 seconds before reconnect


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
        self._inbound_queue = asyncio.Queue()

        logger.debug(
            f"CresNextWSClient initialized for {self.config.host} "
            f"(Auto-reconnect: {self.config.auto_reconnect})"
        )

    def get_base_endpoint(self) -> str:
        """Return the base URL for the configured host.

        Example: https://{host}
        """
        return f"https://{self.config.host}" # :{self.config.port}
    
    def get_auth_endpoint(self) -> str:
        """Return the full REST auth endpoint for the configured host.

        Example: https://{host}{auth_path}
        """
        return f"{self.get_base_endpoint()}{self.config.auth_path}"

    def get_logout_endpoint(self) -> str:
        """Return the full REST logout endpoint for the configured host.

        Example: https://{host}{logout_path}
        """
        return f"{self.get_base_endpoint()}{self.config.logout_path}"

    def get_ws_url(self) -> str:
        """Return the full WebSocket URL for the configured host.

        Example: wss://{host}{websocket_path} (or ws for non-SSL)
        """
        return f"wss://{self.config.host}{self.config.websocket_path}" #:{self.config.port}

    async def _authenticate(self) -> Optional[str]:
        """
        Authenticate with the CresNext system via REST API to get auth token.

        Returns:
            str: Authentication token if successful, None otherwise
        """
        try:
            if self._http_session:
                await self._http_session.get(self.get_logout_endpoint())
            if not self._http_session:
                ssl_context = ssl.create_default_context()
                if self.config.ignore_self_signed:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                connector = aiohttp.TCPConnector(ssl=ssl_context)
                cookie_jar = aiohttp.CookieJar(unsafe=True)
                self._http_session = aiohttp.ClientSession(
                    connector=connector, cookie_jar=cookie_jar
                )
            logger.debug(f"Getting TRACKID cookie from {self.get_auth_endpoint()}")
            async with self._http_session.get(self.get_auth_endpoint()) as response:
                if response.status != 200:
                    logger.error(
                        f"Initial auth request failed with status {response.status}"
                    )
                    return None

            logger.debug(f"Authenticating with {self.get_auth_endpoint()}")
            async with self._http_session.post(
                self.get_auth_endpoint(),
                headers={
                    "Origin": self.get_base_endpoint(),
                    "Referer": f"{self.get_auth_endpoint()}",
                },
                data={
                    "login": self.config.username,
                    "passwd": self.config.password,
                }
            ) as response:
                if response.status == 200:
                    # print all response headers for debugging
                    token = response.headers.get("CREST-XSRF-TOKEN")
                    if token:
                        logger.debug("Authentication successful")
                        return token
                    logger.warning("Authentication response missing CREST-XSRF-TOKEN header")
                    return None
                logger.warning(
                    f"Authentication failed with status {response.status}"
                )
                return None

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None

    async def connect(self) -> bool:
        """
        Connect to the CresNext WebSocket API.

        Returns:
            bool: True if connection successful, False otherwise
        """
        if self._connected:
            logger.debug("Already connected")
            return True

        logger.info(f"Connecting to CresNext WS API at {self.config.host}")

        try:
            # Authenticate and get token if credentials provided in config
            auth_token = await self._authenticate()

            # If authentication failed, don't proceed to open the WebSocket
            if auth_token is None or self._http_session is None:
                logger.error("Authentication failed; aborting connection")
                self._connected = False
                return False

            ssl_context = ssl.create_default_context()
            if self.config.ignore_self_signed:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            logger.debug(f"Connecting to WebSocket: {self.get_ws_url()}")

            # Add XSRF token to cookie jar if present (server expects it as a cookie on WS)
            if auth_token:
                self._http_session.cookie_jar.update_cookies(
                    {'CREST-XSRF-TOKEN': auth_token}, 
                    URL(self.get_base_endpoint())
                )
            
            # Build Cookie header with all cookies for this host
            cookies = self._http_session.cookie_jar.filter_cookies(URL(self.get_base_endpoint()))
            cookie_parts = [f"{name}={m.value}" for name, m in cookies.items()] if cookies else []
            headers = {
                "Origin": self.get_base_endpoint(),
                "Referer": f"{self.get_auth_endpoint()}",
            }
            if cookie_parts:
                headers["Cookie"] = "; ".join(cookie_parts)

            self._websocket = await websockets.connect(
                self.get_ws_url(),
                additional_headers=headers,
                extensions=[
                    ClientPerMessageDeflateFactory(
                        client_max_window_bits=11,
                        server_max_window_bits=11,
                        compress_settings={"memLevel": 4},
                    )
                ],
                ping_interval=self.config.ws_ping_interval,
                ping_timeout=5,
                close_timeout=5,
                ssl=ssl_context,
            )

            self._connected = True
            # Start receive task
            self._recv_task = asyncio.create_task(self._recv_loop())

            logger.info("WebSocket connection established")
            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            return False

    async def _handle_disconnection(self) -> None:
        """
        Handle unexpected disconnection and attempt reconnection if enabled.
        """
        
        logger.info("Connection lost")
        self._connected = False

        # Clean up current connection
        await self._cleanup_connection()

        if self.config.auto_reconnect:
            logger.info("Attempting to reconnect...")
            # Start reconnection task
            if not self._reconnect_task or self._reconnect_task.done():
                self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """
        Background task to handle automatic reconnection.
        """
        try:
            while self.config.auto_reconnect and not self._connected:
                logger.info(
                    f"Attempting reconnection in {self.config.reconnect_delay} seconds..."
                )
                await asyncio.sleep(self.config.reconnect_delay)

                if not self.config.auto_reconnect:
                    break

                # Attempt to reconnect
                success = await self.connect()
                if success:
                    logger.info("Reconnection successful")
                    break
                else:
                    logger.warning("Reconnection failed, will retry...")

        except asyncio.CancelledError:
            logger.debug("Reconnect loop cancelled")
        except Exception as e:
            logger.error(f"Reconnect loop error: {e}")

    async def _cleanup_connection(self) -> None:
        """
        Clean up WebSocket connection and background tasks.
        """
        # Cancel receive task
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None

        # Close WebSocket
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as e:
                logger.debug(f"Error closing WebSocket: {e}")
            self._websocket = None

    async def _recv_loop(self) -> None:
        """Background task that receives messages from the WebSocket.

        - Parses JSON text frames into Python objects and enqueues them.
        - Binary frames are logged and ignored
        - On error/close, triggers disconnect handling if auto_reconnect is enabled.
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
                            buffer = buffer[idx:].lstrip()  # Remove parsed JSON, skip whitespace
                        except json.JSONDecodeError:
                            # Incomplete JSON, wait for more data
                            break
                except Exception as e:
                    logger.error(f"Error handling received message: {e}")
        except asyncio.CancelledError:
            logger.debug("Receive loop cancelled")
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
            if self.config.auto_reconnect:
                await self._handle_disconnection()

    async def next_message(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Await the next inbound message from the receive loop.

        Args:
            timeout: Optional seconds to wait before returning None.

        Returns:
            The next message dict, or None on timeout.
        """
        try:
            if timeout is not None:
                return await asyncio.wait_for(self._inbound_queue.get(), timeout=timeout)
            return await self._inbound_queue.get()
        except asyncio.TimeoutError:
            return None

    async def disconnect(self) -> None:
        """
        Disconnect from the CresNext WebSocket API.
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

        # Close HTTP session
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

        self._connected = False
        self._auth_token = None
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
            Dict[str, Any]: The response data as a dictionary if successful, None otherwise

        Raises:
            RuntimeError: If not connected or no active HTTP session
        """
        if not self._connected or not self._http_session:
            raise RuntimeError("Client is not connected. Call connect() first.")

        try:
            # Construct full URL
            url = f"{self.get_base_endpoint()}{path}"
            logger.error(f"Making HTTP GET request to: {url}")

            async with self._http_session.get(url) as response:
                if response.status == 200:
                    # Try to parse as JSON first
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'application/json' in content_type:
                        data = await response.json()
                        logger.debug(f"HTTP GET successful: {response.status}")
                        return {
                            'content': data,
                            'content_type': content_type,
                            'status': response.status
                        }
                    else:
                        # For non-JSON responses, try to parse as JSON, fallback to text
                        text = await response.text()
                        text = text.rstrip('\r\n')
                        
                        # Try to parse as JSON even if content-type doesn't indicate it
                        try:
                            json_data = json.loads(text)
                            logger.debug(f"HTTP GET successful (parsed JSON): {response.status}")
                            return {
                                'content': json_data,
                                'content_type': content_type,
                                'status': response.status
                            }
                        except json.JSONDecodeError:
                            # Not valid JSON, return as text
                            logger.debug(f"HTTP GET successful (text): {response.status}")
                            return {
                                'content': text,
                                'content_type': content_type,
                                'status': response.status
                            }
                else:
                    logger.warning(f"HTTP GET failed with status {response.status}")
                    return {
                        'content': await response.text(),
                        'content_type': response.headers.get('Content-Type', '').lower(),
                        'error': f"HTTP {response.status}",
                        'status': response.status
                    }

        except Exception as e:
            logger.error(f"HTTP GET request failed: {e}")
            return None

    async def http_post(self, path: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Make an HTTP POST request to the connected/authenticated server.

        Args:
            path (str): The path to request (e.g., '/api/config', '/device/settings')
            data: The data to send in the post request. Can be a dict, list, string, float, or integer.

        Returns:
            Dict[str, Any]: The response data as a dictionary if successful, None otherwise

        Raises:
            RuntimeError: If not connected or no active HTTP session
            TypeError: If data type is not supported
        """
        if not self._connected or not self._http_session:
            raise RuntimeError("Client is not connected. Call connect() first.")

        try:
            # Construct full URL
            url = f"{self.get_base_endpoint()}{path}"
            logger.debug(f"Making HTTP post request to: {url}")

            # Prepare headers - start with Content-Type
            cookies = self._http_session.cookie_jar.filter_cookies(URL(self.get_base_endpoint()))
            headers = {'X-CREST-XSRF-TOKEN': cookies['CREST-XSRF-TOKEN'].value}
            
            # Make the post request
            async with self._http_session.post(url, json=data, headers=headers) as response:
                # Try to parse response
                response_content_type = response.headers.get('Content-Type', '').lower()
                
                if response.status in [200, 201, 204]:
                    # Success status codes
                    if 'application/json' in response_content_type:
                        response_data = await response.json()
                        logger.debug(f"HTTP post successful: {response.status}")
                        return response_data
                    else:
                        # For non-JSON responses, return text content in a dict
                        text = await response.text()
                        logger.debug(f"HTTP post successful (non-JSON): {response.status}")
                        return {
                            'content': text,
                            'content_type': response_content_type,
                            'status': response.status
                        }
                else:
                    logger.warning(f"HTTP post failed with status {response.status}")
                    return {
                        'error': f"HTTP {response.status}",
                        'status': response.status,
                        'content': await response.text()
                    }

        except Exception as e:
            logger.error(f"HTTP post request failed: {e}")
            return None

    async def __aenter__(self) -> "CresNextWSClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        """Async context manager exit."""
        await self.disconnect()
