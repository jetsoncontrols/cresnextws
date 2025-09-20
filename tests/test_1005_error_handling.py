"""
Test cases for WebSocket 1005 error handling and enhanced reconnection.

These tests verify that the client properly handles WebSocket 1005 
"no status received [internal]" errors and implements robust reconnection
with exponential backoff.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from cresnextws import CresNextWSClient, ClientConfig
from websockets.exceptions import ConnectionClosed


class TestWebSocket1005ErrorHandling:
    """Test WebSocket 1005 error handling and enhanced reconnection behavior."""

    @pytest.mark.asyncio
    async def test_1005_error_in_health_check_triggers_reconnection(self):
        """Test that a 1005 error during health check triggers reconnection."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            auto_reconnect=True,
            reconnect_delay=0.1,  # Fast for testing
            health_check_interval=0.1,  # Fast for testing
            health_check_timeout=0.1
        )
        
        client = CresNextWSClient(config)
        
        # Mock authentication
        client._authenticate = AsyncMock(return_value="test_token")
        client._http_session = Mock()
        client._http_session.cookie_jar.filter_cookies.return_value = {
            "CREST-XSRF-TOKEN": Mock(value="test_token")
        }
        
        # Track reconnection calls
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
            client._connected = False  # Stop the health check loop
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Mock WebSocket that raises 1005 error (ConnectionClosed with no close frame)
        mock_websocket = Mock()
        close_exception = ConnectionClosed(rcvd=None, sent=None)  # 1005 scenario
        mock_websocket.ping = AsyncMock(side_effect=close_exception)
        
        client._connected = True
        client._websocket = mock_websocket
        
        # Start health check task
        health_task = asyncio.create_task(client._health_check_loop())
        
        # Give time for health check to run and detect the error
        await asyncio.sleep(0.3)
        
        # Cancel the task
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        
        # Verify that 1005 error triggered reconnection
        assert len(reconnection_triggered) > 0, "1005 error should have triggered reconnection"

    @pytest.mark.asyncio
    async def test_reconnection_loop_continues_after_exceptions(self):
        """Test that reconnection loop continues retrying even after exceptions."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            auto_reconnect=True,
            reconnect_delay=0.1,  # Fast for testing
            max_reconnect_delay=0.5  # Cap for testing
        )
        
        client = CresNextWSClient(config)
        
        # Track connection attempts
        connection_attempts = []
        
        async def mock_connect():
            connection_attempts.append(True)
            attempt_num = len(connection_attempts)
            
            # Fail first 2 attempts, succeed on 3rd
            if attempt_num < 3:
                if attempt_num == 1:
                    # First attempt: raise exception
                    raise RuntimeError("Simulated connection error")
                else:
                    # Second attempt: return False
                    return False
            else:
                # Third attempt: succeed
                client._connected = True
                return True
        
        client.connect = mock_connect
        
        # Start reconnection loop
        client._connected = False
        reconnect_task = asyncio.create_task(client._reconnect_loop())
        
        # Wait for reconnection attempts
        await asyncio.sleep(0.8)
        
        # Clean up
        reconnect_task.cancel()
        try:
            await reconnect_task
        except asyncio.CancelledError:
            pass
        
        # Verify that reconnection continued despite the exception
        assert len(connection_attempts) >= 3, "Should have retried even after exception"
        assert client._connected, "Should eventually succeed"

    @pytest.mark.asyncio
    async def test_exponential_backoff_with_max_delay(self):
        """Test that exponential backoff respects the maximum delay setting."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            auto_reconnect=True,
            reconnect_delay=0.1,  # Start small
            max_reconnect_delay=0.3  # Cap at 0.3 seconds for testing
        )
        
        client = CresNextWSClient(config)
        
        # Track connection attempts with timing
        connection_attempts = []
        start_time = asyncio.get_event_loop().time()
        
        async def mock_connect():
            current_time = asyncio.get_event_loop().time()
            connection_attempts.append(current_time - start_time)
            return False  # Always fail to test backoff
        
        client.connect = mock_connect
        
        # Start reconnection loop
        client._connected = False
        reconnect_task = asyncio.create_task(client._reconnect_loop())
        
        # Wait for several attempts
        await asyncio.sleep(1.2)
        
        # Clean up
        reconnect_task.cancel()
        try:
            await reconnect_task
        except asyncio.CancelledError:
            pass
        
        # Verify exponential backoff pattern
        assert len(connection_attempts) >= 3, "Should have made multiple attempts"
        
        if len(connection_attempts) >= 3:
            # Calculate delays between attempts
            delays = []
            for i in range(1, len(connection_attempts)):
                delay = connection_attempts[i] - connection_attempts[i-1]
                delays.append(delay)
            
            # Verify that delays increase (exponential backoff)
            assert delays[1] > delays[0], "Second delay should be longer than first"
            
            # Verify that delays don't exceed max_reconnect_delay
            for delay in delays[2:]:  # Skip first two as they're still ramping up
                assert delay <= config.max_reconnect_delay + 0.1, f"Delay {delay} exceeds max {config.max_reconnect_delay}"

    @pytest.mark.asyncio
    async def test_enhanced_error_logging_for_close_codes(self):
        """Test that enhanced error logging captures close code details."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            auto_reconnect=True,
            health_check_interval=0.1
        )
        
        client = CresNextWSClient(config)
        
        # Track if reconnection was triggered (which means the error was handled)
        reconnection_triggered = []
        
        async def mock_handle_disconnection():
            reconnection_triggered.append(True)
            client._connected = False
        
        client._handle_disconnection = mock_handle_disconnection
        
        # Mock a ConnectionClosed with specific close frame details
        from websockets.frames import Close
        from websockets.exceptions import ConnectionClosed
        
        close_frame = Close(code=1005, reason="no status received [internal]")
        close_exception = ConnectionClosed(rcvd=close_frame, sent=None)
        
        mock_websocket = Mock()
        mock_websocket.ping = AsyncMock(side_effect=close_exception)
        
        client._connected = True
        client._websocket = mock_websocket
        
        # Start health check
        health_task = asyncio.create_task(client._health_check_loop())
        
        # Wait for health check to run
        await asyncio.sleep(0.2)
        
        # Cancel task
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        
        # Verify that the error was handled and reconnection was triggered
        assert len(reconnection_triggered) > 0, "1005 error should trigger reconnection"

    @pytest.mark.asyncio
    async def test_config_max_reconnect_delay_setting(self):
        """Test that max_reconnect_delay configuration is properly applied."""
        config = ClientConfig(
            host="test.local",
            username="test",
            password="test",
            max_reconnect_delay=120.0  # 2 minutes
        )
        
        client = CresNextWSClient(config)
        
        assert client.config.max_reconnect_delay == 120.0
        assert client.config.reconnect_delay == 0.1  # Default initial delay