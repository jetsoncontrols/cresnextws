"""
Test cases for WebSocket health check functionality.

These tests verify that the client properly performs health checks to detect
stale connections, particularly after system sleep/wake cycles.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from cresnextws import CresNextWSClient, ClientConfig
from websockets.exceptions import ConnectionClosed


class TestWebSocketHealthCheck:
    """Test WebSocket health check behavior."""

    @pytest.mark.asyncio
    async def test_health_check_configuration(self):
        """Test that health check configuration is properly initialized."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            health_check_interval=60.0,
            health_check_timeout=10.0
        )
        
        client = CresNextWSClient(config)
        
        assert client.config.health_check_interval == 60.0
        assert client.config.health_check_timeout == 10.0
        assert not client._health_check_pending
        assert client._health_check_task is None

    @pytest.mark.asyncio
    async def test_health_check_defaults(self):
        """Test that health check has reasonable defaults."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test"
        )
        
        client = CresNextWSClient(config)
        
        assert client.config.health_check_interval == 5.0  # Default
        assert client.config.health_check_timeout == 2.0    # Default

    @pytest.mark.asyncio  
    async def test_health_check_task_basic_functionality(self):
        """Test basic health check task functionality."""
        config = ClientConfig(
            host="test.local", 
            username="test",
            password="test",
            health_check_interval=0.1  # Fast for testing
        )
        
        client = CresNextWSClient(config)
        
        # Verify health check task is initially None
        assert client._health_check_task is None
        
        # Simulate connection state and start health check manually
        client._connected = True
        mock_websocket = Mock()
        pong_future = asyncio.Future()
        pong_future.set_result(None)
        mock_websocket.ping = AsyncMock(return_value=pong_future)
        client._websocket = mock_websocket
        
        # Start health check task manually
        client._health_check_task = asyncio.create_task(client._health_check_loop())
        
        # Let it run briefly
        await asyncio.sleep(0.2)
        
        # Verify health check task is running
        assert client._health_check_task is not None
        assert not client._health_check_task.done()
        
        # Clean up
        client._connected = False
        client._health_check_task.cancel()
        try:
            await client._health_check_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_health_check_ping_success(self):
        """Test that successful health check pings don't trigger reconnection."""
        config = ClientConfig(
            host="test.local",
            username="test", 
            password="test",
            health_check_interval=0.1,  # Fast for testing
            health_check_timeout=1.0
        )
        
        client = CresNextWSClient(config)
        
        # Mock WebSocket with successful ping
        mock_websocket = Mock()
        
        # Create a proper awaitable future for the pong waiter
        pong_future = asyncio.Future()
        pong_future.set_result(None)
        mock_websocket.ping = AsyncMock(return_value=pong_future)
        
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
        
        # Verify no reconnection was triggered
        assert len(reconnection_triggered) == 0

    @pytest.mark.asyncio
    async def test_health_check_ping_timeout_triggers_reconnection(self):
        """Test that health check ping timeout triggers reconnection."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test", 
            health_check_interval=0.1,  # Fast for testing
            health_check_timeout=0.1    # Very short timeout
        )
        
        client = CresNextWSClient(config)
        
        # Mock WebSocket with ping that times out
        mock_websocket = Mock()
        
        async def slow_ping():
            # Mock a pong waiter that takes too long
            await asyncio.sleep(0.2)  # Longer than timeout
            return Mock()
        
        mock_websocket.ping = AsyncMock(return_value=slow_ping())
        
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
        await asyncio.sleep(0.5)
        
        # Cancel the task
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        
        # Verify reconnection was triggered due to timeout
        assert len(reconnection_triggered) > 0

    @pytest.mark.asyncio
    async def test_health_check_connection_closed_triggers_reconnection(self):
        """Test that ConnectionClosed during health check triggers reconnection."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            health_check_interval=0.1,  # Fast for testing
            health_check_timeout=1.0
        )
        
        client = CresNextWSClient(config)
        
        # Mock WebSocket with ping that raises ConnectionClosed
        mock_websocket = Mock()
        mock_websocket.ping = AsyncMock(side_effect=ConnectionClosed(rcvd=None, sent=None))
        
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
        
        # Verify reconnection was triggered
        assert len(reconnection_triggered) > 0

    @pytest.mark.asyncio
    async def test_health_check_disabled_when_auto_reconnect_false(self):
        """Test that health check doesn't trigger reconnection when auto_reconnect=False."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            auto_reconnect=False,  # Disabled
            health_check_interval=0.1,
            health_check_timeout=0.1
        )
        
        client = CresNextWSClient(config)
        
        # Mock WebSocket with ping that times out
        mock_websocket = Mock()
        
        async def slow_ping():
            await asyncio.sleep(0.2)  # Longer than timeout
            return Mock()
        
        mock_websocket.ping = AsyncMock(return_value=slow_ping())
        
        client._connected = True
        client._websocket = mock_websocket
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Start the health check task manually
        health_task = asyncio.create_task(client._health_check_loop())
        
        # Let it run for enough time to trigger health check
        await asyncio.sleep(0.5)
        
        # Cancel the task
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        
        # Verify no reconnection was triggered (auto_reconnect=False)
        assert len(reconnection_triggered) == 0

    @pytest.mark.asyncio
    async def test_health_check_cleanup_on_disconnect(self):
        """Test that health check task is properly cleaned up on disconnect."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test"
        )
        
        client = CresNextWSClient(config)
        
        # Create a real health check task and then clean it up
        client._connected = True
        mock_websocket = Mock()
        pong_future = asyncio.Future()
        pong_future.set_result(None)
        mock_websocket.ping = AsyncMock(return_value=pong_future)
        client._websocket = mock_websocket
        
        # Start a real health check task
        client._health_check_task = asyncio.create_task(client._health_check_loop())
        
        # Verify task exists and is running
        assert client._health_check_task is not None
        assert not client._health_check_task.done()
        
        # Trigger cleanup
        await client._cleanup_connection()
        
        # Verify health check task was cleaned up
        assert client._health_check_task is None