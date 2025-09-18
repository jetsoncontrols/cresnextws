"""
Test cases for WebSocket connection error handling and automatic reconnection.

These tests verify that the client properly handles WebSocket connection errors
that occur during send operations (ws_post and ws_get) and triggers automatic
reconnection when configured to do so.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from cresnextws import CresNextWSClient, ClientConfig
from websockets.exceptions import ConnectionClosed, WebSocketException


class TestWebSocketReconnection:
    """Test WebSocket error handling and reconnection behavior."""

    @pytest.mark.asyncio
    async def test_ws_post_connection_error_triggers_reconnection(self):
        """Test that ConnectionClosed in ws_post triggers reconnection when auto_reconnect=True."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            auto_reconnect=True,
            reconnect_delay=0.1
        )
        
        client = CresNextWSClient(config)
        
        # Mock authentication and session
        client._authenticate = AsyncMock(return_value="token")
        client._http_session = Mock()
        client._http_session.cookie_jar.filter_cookies.return_value = {
            "CREST-XSRF-TOKEN": Mock(value="token")
        }
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
            client._connected = False
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Set up mock WebSocket that raises ConnectionClosed
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock(side_effect=ConnectionClosed(rcvd=None, sent=None))
        
        client._connected = True
        client._websocket = mock_websocket
        
        # ws_post should raise ConnectionClosed AND trigger reconnection
        with pytest.raises(ConnectionClosed):
            await client.ws_post({"test": "data"})
        
        # Give time for background task to execute
        await asyncio.sleep(0.1)
        
        assert len(reconnection_triggered) > 0, "Reconnection should have been triggered"

    @pytest.mark.asyncio
    async def test_ws_get_connection_error_triggers_reconnection(self):
        """Test that ConnectionClosed in ws_get triggers reconnection when auto_reconnect=True."""
        config = ClientConfig(
            host="test.local",
            username="test", 
            password="test",
            auto_reconnect=True,
            reconnect_delay=0.1
        )
        
        client = CresNextWSClient(config)
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
            client._connected = False
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Set up mock WebSocket that raises ConnectionClosed
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock(side_effect=ConnectionClosed(rcvd=None, sent=None))
        
        client._connected = True
        client._websocket = mock_websocket
        
        # ws_get should raise ConnectionClosed AND trigger reconnection
        with pytest.raises(ConnectionClosed):
            await client.ws_get("/test/path")
        
        # Give time for background task to execute
        await asyncio.sleep(0.1)
        
        assert len(reconnection_triggered) > 0, "Reconnection should have been triggered"

    @pytest.mark.asyncio
    async def test_websocket_exception_triggers_reconnection(self):
        """Test that WebSocketException triggers reconnection when auto_reconnect=True."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test", 
            auto_reconnect=True,
            reconnect_delay=0.1
        )
        
        client = CresNextWSClient(config)
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
            client._connected = False
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Set up mock WebSocket that raises WebSocketException
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock(side_effect=WebSocketException("Connection error"))
        
        client._connected = True
        client._websocket = mock_websocket
        
        # ws_post should raise WebSocketException AND trigger reconnection
        with pytest.raises(WebSocketException):
            await client.ws_post({"test": "data"})
        
        # Give time for background task to execute
        await asyncio.sleep(0.1)
        
        assert len(reconnection_triggered) > 0, "Reconnection should have been triggered"

    @pytest.mark.asyncio
    async def test_connection_error_no_reconnection_when_disabled(self):
        """Test that no reconnection occurs when auto_reconnect=False."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            auto_reconnect=False  # Disabled
        )
        
        client = CresNextWSClient(config)
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Set up mock WebSocket that raises ConnectionClosed
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock(side_effect=ConnectionClosed(rcvd=None, sent=None))
        
        client._connected = True
        client._websocket = mock_websocket
        
        # ws_post should raise ConnectionClosed but NOT trigger reconnection
        with pytest.raises(ConnectionClosed):
            await client.ws_post({"test": "data"})
        
        # Give time for any potential background task
        await asyncio.sleep(0.1)
        
        assert len(reconnection_triggered) == 0, "Reconnection should NOT have been triggered when disabled"

    @pytest.mark.asyncio  
    async def test_other_exceptions_do_not_trigger_reconnection(self):
        """Test that non-connection exceptions don't trigger reconnection."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            auto_reconnect=True
        )
        
        client = CresNextWSClient(config)
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Set up mock WebSocket that raises a generic Exception (not connection-related)
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock(side_effect=ValueError("Invalid data"))
        
        client._connected = True
        client._websocket = mock_websocket
        
        # ws_post should raise ValueError but NOT trigger reconnection
        with pytest.raises(ValueError):
            await client.ws_post({"test": "data"})
        
        # Give time for any potential background task
        await asyncio.sleep(0.1)
        
        assert len(reconnection_triggered) == 0, "Reconnection should NOT be triggered for non-connection errors"