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

    @pytest.mark.asyncio
    async def test_start_monitoring_not_connected(self, data_manager):
        """Test starting monitoring when client is not connected."""
        data_manager.client.connected = False
        
        with pytest.raises(RuntimeError, match="Client is not connected"):
            await data_manager.start_monitoring()

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
        assert isinstance(sub.subscription_id, str)

    def test_subscription_no_children(self):
        """Test creating a subscription with match_children=False."""
        from cresnextws.data_event_manager import Subscription
        
        callback = Mock()
        sub = Subscription("/Device/Config", callback, match_children=False)
        
        assert sub.match_children is False
