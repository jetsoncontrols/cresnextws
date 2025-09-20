"""
Tests for the DataEventManager class.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from cresnextws import CresNextWSClient, DataEventManager


@pytest.fixture
def mock_client():
    """Create a mock CresNextWSClient for testing."""
    client = Mock(spec=CresNextWSClient)
    client.connected = True
    client.next_message = AsyncMock()
    return client


@pytest.fixture
def data_manager(mock_client):
    """Create a DataEventManager with a mock client."""
    return DataEventManager(mock_client)


class TestDataEventManager:
    """Test cases for DataEventManager."""

    def test_init(self, mock_client):
        """Test DataEventManager initialization."""
        manager = DataEventManager(mock_client)
        assert manager.client == mock_client
        assert manager.subscription_count == 0
        assert not manager.is_monitoring

    def test_subscribe(self, data_manager):
        """Test subscribing to a path pattern."""
        callback = Mock()
        
        sub_id = data_manager.subscribe("/Device/Config", callback)
        
        assert isinstance(sub_id, str)
        assert data_manager.subscription_count == 1
        
        subscriptions = data_manager.get_subscriptions()
        assert len(subscriptions) == 1
        assert subscriptions[0]["path_pattern"] == "/Device/Config"
        assert subscriptions[0]["match_children"] is True

    def test_subscribe_no_children(self, data_manager):
        """Test subscribing with match_children=False."""
        callback = Mock()
        
        data_manager.subscribe("/Device/Config", callback, match_children=False)
        
        subscriptions = data_manager.get_subscriptions()
        assert subscriptions[0]["match_children"] is False

    def test_unsubscribe(self, data_manager):
        """Test unsubscribing from a path pattern."""
        callback = Mock()
        
        sub_id = data_manager.subscribe("/Device/Config", callback)
        assert data_manager.subscription_count == 1
        
        result = data_manager.unsubscribe(sub_id)
        assert result is True
        assert data_manager.subscription_count == 0

    def test_unsubscribe_nonexistent(self, data_manager):
        """Test unsubscribing from a non-existent subscription."""
        result = data_manager.unsubscribe("nonexistent-id")
        assert result is False

    def test_clear_subscriptions(self, data_manager):
        """Test clearing all subscriptions."""
        callback1 = Mock()
        callback2 = Mock()
        
        data_manager.subscribe("/Device/Config", callback1)
        data_manager.subscribe("/Device/Network", callback2)
        assert data_manager.subscription_count == 2
        
        data_manager.clear_subscriptions()
        assert data_manager.subscription_count == 0

    def test_path_matches_exact(self, data_manager):
        """Test exact path matching.""" 
        from cresnextws.data_event_manager import Subscription
        
        subscription = Subscription("/Device/Config", Mock())
        
        assert data_manager._path_matches_pattern("/Device/Config", subscription)
        assert not data_manager._path_matches_pattern("/Device/Network", subscription)

    def test_path_matches_wildcard(self, data_manager):
        """Test wildcard path matching."""
        from cresnextws.data_event_manager import Subscription
        
        subscription = Subscription("/Device/*", Mock())
        
        assert data_manager._path_matches_pattern("/Device/Config", subscription)
        assert data_manager._path_matches_pattern("/Device/Network", subscription)
        assert not data_manager._path_matches_pattern("/System/Info", subscription)

    def test_path_matches_children(self, data_manager):
        """Test child path matching."""
        from cresnextws.data_event_manager import Subscription
        
        subscription = Subscription("/Device/Config", Mock(), match_children=True)
        
        assert data_manager._path_matches_pattern("/Device/Config", subscription)
        assert data_manager._path_matches_pattern("/Device/Config/SubConfig", subscription)
        assert data_manager._path_matches_pattern("/Device/Config/Sub/Deep", subscription)
        assert not data_manager._path_matches_pattern("/Device/Network", subscription)

    def test_path_matches_no_children(self, data_manager):
        """Test path matching without children."""
        from cresnextws.data_event_manager import Subscription
        
        subscription = Subscription("/Device/Config", Mock(), match_children=False)
        
        assert data_manager._path_matches_pattern("/Device/Config", subscription)
        assert not data_manager._path_matches_pattern("/Device/Config/SubConfig", subscription)

    def test_process_message_with_path_key(self, data_manager):
        """Test processing a message with 'path' key."""
        callback = Mock()
        data_manager.subscribe("/Device/Config", callback)
        
        message = {
            "path": "/Device/Config",
            "data": {"value": "test"}
        }
        
        data_manager._process_message(message)
        
        callback.assert_called_once_with("/Device/Config", {"value": "test"})

    def test_process_message_with_Path_key(self, data_manager):
        """Test processing a message with 'Path' key (capital P)."""
        callback = Mock()
        data_manager.subscribe("/Device/Config", callback)
        
        message = {
            "Path": "/Device/Config", 
            "Data": {"value": "test"}
        }
        
        data_manager._process_message(message)
        
        callback.assert_called_once_with("/Device/Config", {"value": "test"})

    def test_process_message_single_key_value(self, data_manager):
        """Test processing a message with single key-value pair."""
        callback = Mock()
        data_manager.subscribe("/Device/Config", callback)
        
        message = {"/Device/Config": {"value": "test"}}
        
        data_manager._process_message(message)
        
        callback.assert_called_once_with("/Device/Config", {"value": "test"})

    def test_process_message_no_match(self, data_manager):
        """Test processing a message that doesn't match any subscription."""
        callback = Mock()
        data_manager.subscribe("/Device/Config", callback)
        
        message = {
            "path": "/Device/Network", 
            "data": {"value": "test"}
        }
        
        data_manager._process_message(message)
        
        callback.assert_not_called()

    def test_process_message_multiple_matches(self, data_manager):
        """Test processing a message that matches multiple subscriptions."""
        callback1 = Mock()
        callback2 = Mock()
        
        data_manager.subscribe("/Device/*", callback1)
        data_manager.subscribe("/Device/Config", callback2)
        
        message = {
            "path": "/Device/Config",
            "data": {"value": "test"}
        }
        
        data_manager._process_message(message)
        
        callback1.assert_called_once_with("/Device/Config", {"value": "test"})
        callback2.assert_called_once_with("/Device/Config", {"value": "test"})

    def test_subscribe_with_full_message(self, data_manager):
        """Test subscribing with full_message=True."""
        callback = Mock()
        
        data_manager.subscribe("/Device/Config", callback, full_message=True)
        
        subscriptions = data_manager.get_subscriptions()
        assert subscriptions[0]["full_message"] is True

    def test_subscribe_default_full_message(self, data_manager):
        """Test subscribing with default full_message=False."""
        callback = Mock()
        
        data_manager.subscribe("/Device/Config", callback)
        
        subscriptions = data_manager.get_subscriptions()
        assert subscriptions[0]["full_message"] is False

    def test_process_message_with_full_message_true(self, data_manager):
        """Test processing a message with full_message=True passes entire message."""
        callback = Mock()
        data_manager.subscribe("/Device/Config", callback, full_message=True)
        
        message = {
            "path": "/Device/Config",
            "data": {"value": "test"},
            "timestamp": "2023-01-01T00:00:00Z",
            "other_field": "extra_data"
        }
        
        data_manager._process_message(message)
        
        # With full_message=True, callback should receive the entire message
        callback.assert_called_once_with("/Device/Config", message)

    def test_process_message_with_full_message_false(self, data_manager):
        """Test processing a message with full_message=False passes only data."""
        callback = Mock()
        data_manager.subscribe("/Device/Config", callback, full_message=False)
        
        message = {
            "path": "/Device/Config",
            "data": {"value": "test"},
            "timestamp": "2023-01-01T00:00:00Z",
            "other_field": "extra_data"
        }
        
        data_manager._process_message(message)
        
        # With full_message=False, callback should receive only the data portion
        callback.assert_called_once_with("/Device/Config", {"value": "test"})

    def test_process_message_nested_structure_with_full_message(self, data_manager):
        """Test processing nested message structure with full_message=True."""
        callback = Mock()
        data_manager.subscribe("/Device/Config", callback, full_message=True, match_children=False)
        
        message = {
            "Device": {
                "Config": {"value": "test"}
            },
            "timestamp": "2023-01-01T00:00:00Z"
        }
        
        data_manager._process_message(message)
        
        # With full_message=True and match_children=False, callback should be called once with the entire message
        callback.assert_called_once_with("/Device/Config", message)

    def test_process_message_multiple_subscriptions_mixed_full_message(self, data_manager):
        """Test processing message with mixed full_message settings."""
        callback_full = Mock()
        callback_data_only = Mock()
        
        data_manager.subscribe("/Device/Config", callback_full, full_message=True)
        data_manager.subscribe("/Device/Config", callback_data_only, full_message=False)
        
        message = {
            "path": "/Device/Config",
            "data": {"value": "test"},
            "timestamp": "2023-01-01T00:00:00Z"
        }
        
        data_manager._process_message(message)
        
        # First callback should get full message
        callback_full.assert_called_once_with("/Device/Config", message)
        # Second callback should get only data
        callback_data_only.assert_called_once_with("/Device/Config", {"value": "test"})

    @pytest.mark.asyncio
    async def test_start_monitoring_not_connected(self, data_manager):
        """Test starting monitoring when client is not connected - should succeed."""
        data_manager.client.connected = False
        
        await data_manager.start_monitoring()
        assert data_manager.is_monitoring
        
        # Clean up
        await data_manager.stop_monitoring()

    @pytest.mark.asyncio
    async def test_start_monitoring_already_running(self, data_manager):
        """Test starting monitoring when already running."""
        data_manager._running = True
        
        await data_manager.start_monitoring()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_monitoring_not_running(self, data_manager):
        """Test stopping monitoring when not running."""
        await data_manager.stop_monitoring()  # Should not raise


class TestSubscription:
    """Test cases for Subscription dataclass."""

    def test_subscription_creation(self):
        """Test creating a subscription."""
        from cresnextws.data_event_manager import Subscription
        
        callback = Mock()
        sub = Subscription("/Device/Config", callback)
        
        assert sub.path_pattern == "/Device/Config"
        assert sub.callback == callback
        assert sub.match_children is True
        assert sub.full_message is False
        assert isinstance(sub.subscription_id, str)

    def test_subscription_no_children(self):
        """Test creating a subscription with match_children=False."""
        from cresnextws.data_event_manager import Subscription
        
        callback = Mock()
        sub = Subscription("/Device/Config", callback, match_children=False)
        
        assert sub.match_children is False
        assert sub.full_message is False

    def test_subscription_full_message(self):
        """Test creating a subscription with full_message=True."""
        from cresnextws.data_event_manager import Subscription
        
        callback = Mock()
        sub = Subscription("/Device/Config", callback, full_message=True)
        
        assert sub.full_message is True
        assert sub.match_children is True


class TestDataEventManagerAutoRestart:
    """Test cases for DataEventManager auto-restart functionality."""

    @pytest.fixture
    def mock_client_with_handlers(self):
        """Create a mock client with connection status handler support."""
        client = Mock(spec=CresNextWSClient)
        client.connected = True
        client.next_message = AsyncMock()
        client.add_connection_status_handler = Mock()
        client.remove_connection_status_handler = Mock()
        return client

    def test_init_default(self, mock_client_with_handlers):
        """Test DataEventManager initialization."""
        manager = DataEventManager(mock_client_with_handlers)
        
        assert manager.client == mock_client_with_handlers
        assert manager._was_monitoring_before_disconnect is False
        
        # Should have registered a connection status handler
        mock_client_with_handlers.add_connection_status_handler.assert_called_once()

    def test_cleanup_removes_handler(self, mock_client_with_handlers):
        """Test that cleanup removes the connection status handler."""
        manager = DataEventManager(mock_client_with_handlers)
        
        # Verify handler was added
        mock_client_with_handlers.add_connection_status_handler.assert_called_once()
        
        # Call cleanup
        manager.cleanup()
        
        # Verify handler was removed
        mock_client_with_handlers.remove_connection_status_handler.assert_called_once()

    def test_connection_status_handler_disconnect(self, mock_client_with_handlers):
        """Test connection status handler on disconnect."""
        from cresnextws import ConnectionStatus
        
        manager = DataEventManager(mock_client_with_handlers)
        manager._running = True  # Simulate monitoring was active
        
        # Get the registered handler
        call_args = mock_client_with_handlers.add_connection_status_handler.call_args
        handler = call_args[0][0]
        
        # Simulate disconnect
        handler(ConnectionStatus.DISCONNECTED)
        
        # Should remember that monitoring was active
        assert manager._was_monitoring_before_disconnect is True

    def test_connection_status_handler_connect_with_restart(self, mock_client_with_handlers):
        """Test connection status handler on connect - monitoring always restarts."""
        from cresnextws import ConnectionStatus
        
        manager = DataEventManager(mock_client_with_handlers)
        manager._was_monitoring_before_disconnect = True  # Simulate previous monitoring
        manager._running = False  # Currently not monitoring
        
        # Mock start_monitoring
        manager.start_monitoring = AsyncMock()
        
        # Get the registered handler
        call_args = mock_client_with_handlers.add_connection_status_handler.call_args
        handler = call_args[0][0]
        
        # Simulate reconnect
        handler(ConnectionStatus.CONNECTED)
        
        # Note: The actual start_monitoring call happens in an async task,
        # so we can't directly verify it was called in this synchronous test.
        # This tests that the handler logic executes without error.

    @pytest.mark.asyncio
    async def test_context_manager_cleanup(self, mock_client_with_handlers):
        """Test that async context manager calls cleanup on exit."""
        async with DataEventManager(mock_client_with_handlers) as manager:
            # Verify handler was added during init
            mock_client_with_handlers.add_connection_status_handler.assert_called_once()
            # Verify the manager is created properly
            assert manager.client == mock_client_with_handlers
        
        # Verify handler was removed during cleanup
        mock_client_with_handlers.remove_connection_status_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_monitoring_async_success(self, mock_client_with_handlers):
        """Test successful restart of monitoring."""
        manager = DataEventManager(mock_client_with_handlers)
        manager.start_monitoring = AsyncMock()
        
        await manager._restart_monitoring_async()
        
        manager.start_monitoring.assert_called_once()

    @pytest.mark.asyncio 
    async def test_restart_monitoring_async_failure(self, mock_client_with_handlers):
        """Test restart of monitoring with failure."""
        manager = DataEventManager(mock_client_with_handlers)
        manager.start_monitoring = AsyncMock(side_effect=Exception("Connection failed"))
        
        # Should not raise exception, just log error
        await manager._restart_monitoring_async()
        
        manager.start_monitoring.assert_called_once()
