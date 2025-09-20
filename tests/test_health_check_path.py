"""
Test cases for WebSocket health check path functionality.

These tests verify that the client properly sends WebSocket GET requests
during health checks when health_check_path is configured.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from cresnextws import CresNextWSClient, ClientConfig
from websockets.exceptions import ConnectionClosed


class TestWebSocketHealthCheckPath:
    """Test WebSocket health check path functionality."""

    @pytest.mark.asyncio
    async def test_health_check_path_configuration(self):
        """Test that health_check_path configuration is properly initialized."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            health_check_path="/Device/DeviceInfo/Model"
        )
        
        client = CresNextWSClient(config)
        
        assert client.config.health_check_path == "/Device/DeviceInfo/Model"

    @pytest.mark.asyncio
    async def test_health_check_path_default_none(self):
        """Test that health_check_path defaults to None."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test"
        )
        
        client = CresNextWSClient(config)
        
        assert client.config.health_check_path is None

    @pytest.mark.asyncio
    async def test_health_check_with_path_sends_ws_get(self):
        """Test that health check sends WebSocket GET when path is configured."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            health_check_interval=0.1,  # Fast for testing
            health_check_timeout=1.0,
            health_check_path="/Device/DeviceInfo/Model"
        )
        
        client = CresNextWSClient(config)
        
        # Mock WebSocket with successful ping
        mock_websocket = Mock()
        
        # Create a proper awaitable future for the pong waiter
        pong_future = asyncio.Future()
        pong_future.set_result(None)
        mock_websocket.ping = AsyncMock(return_value=pong_future)
        mock_websocket.send = AsyncMock()
        
        client._connected = True
        client._websocket = mock_websocket
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Start the health check task manually
        health_task = asyncio.create_task(client._health_check_loop())
        
        # Let it run for a short time
        await asyncio.sleep(0.3)
        
        # Cancel the task
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        
        # Verify ping was called
        assert mock_websocket.ping.called
        
        # Verify WebSocket GET was sent with the configured path
        mock_websocket.send.assert_called_with("/Device/DeviceInfo/Model")
        
        # Verify no reconnection was triggered
        assert len(reconnection_triggered) == 0

    @pytest.mark.asyncio
    async def test_health_check_without_path_skips_ws_get(self):
        """Test that health check skips WebSocket GET when path is None."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            health_check_interval=0.1,  # Fast for testing
            health_check_timeout=1.0,
            health_check_path=None  # Explicitly set to None
        )
        
        client = CresNextWSClient(config)
        
        # Mock WebSocket with successful ping
        mock_websocket = Mock()
        
        # Create a proper awaitable future for the pong waiter
        pong_future = asyncio.Future()
        pong_future.set_result(None)
        mock_websocket.ping = AsyncMock(return_value=pong_future)
        mock_websocket.send = AsyncMock()
        
        client._connected = True
        client._websocket = mock_websocket
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Start the health check task manually
        health_task = asyncio.create_task(client._health_check_loop())
        
        # Let it run for a short time
        await asyncio.sleep(0.3)
        
        # Cancel the task
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        
        # Verify ping was called
        assert mock_websocket.ping.called
        
        # Verify WebSocket GET was NOT sent
        mock_websocket.send.assert_not_called()
        
        # Verify no reconnection was triggered
        assert len(reconnection_triggered) == 0

    @pytest.mark.asyncio
    async def test_health_check_ws_get_failure_triggers_reconnection(self):
        """Test that WebSocket GET failure during health check triggers reconnection."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            health_check_interval=0.1,  # Fast for testing
            health_check_timeout=1.0,
            health_check_path="/Device/DeviceInfo/Model"
        )
        
        client = CresNextWSClient(config)
        
        # Mock WebSocket with successful ping but failing send
        mock_websocket = Mock()
        
        # Create a proper awaitable future for the pong waiter
        pong_future = asyncio.Future()
        pong_future.set_result(None)
        mock_websocket.ping = AsyncMock(return_value=pong_future)
        mock_websocket.send = AsyncMock(side_effect=ConnectionClosed(rcvd=None, sent=None))
        
        client._connected = True
        client._websocket = mock_websocket
        client.config.auto_reconnect = True
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
            client._connected = False  # Stop the health check loop
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Start the health check task manually
        health_task = asyncio.create_task(client._health_check_loop())
        
        # Let it run for enough time to trigger health check
        await asyncio.sleep(0.3)
        
        # Cancel the task
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        
        # Verify ping was called
        assert mock_websocket.ping.called
        
        # Verify WebSocket GET was attempted
        mock_websocket.send.assert_called_with("/Device/DeviceInfo/Model")
        
        # Verify reconnection was triggered due to send failure
        assert len(reconnection_triggered) > 0