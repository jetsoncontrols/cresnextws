"""
Test for connection status events functionality.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from cresnextws.client import CresNextWSClient, ClientConfig, ConnectionStatus


def test_connection_status_handler_management():
    """Test adding and removing connection status handlers."""
    config = ClientConfig(
        host="test.example.com",
        username="test",
        password="test"
    )
    client = CresNextWSClient(config)
    
    # Initial status should be disconnected
    assert client.get_connection_status() == ConnectionStatus.DISCONNECTED
    
    # Test adding handlers
    handler1 = Mock()
    handler2 = Mock()
    
    client.add_connection_status_handler(handler1)
    client.add_connection_status_handler(handler2)
    
    # Handlers should be in the list
    assert len(client._connection_status_handlers) == 2
    assert handler1 in client._connection_status_handlers
    assert handler2 in client._connection_status_handlers
    
    # Adding the same handler again should not duplicate it
    client.add_connection_status_handler(handler1)
    assert len(client._connection_status_handlers) == 2
    
    # Test removing handlers
    client.remove_connection_status_handler(handler1)
    assert len(client._connection_status_handlers) == 1
    assert handler1 not in client._connection_status_handlers
    assert handler2 in client._connection_status_handlers
    
    # Removing non-existent handler should not raise error
    client.remove_connection_status_handler(handler1)
    assert len(client._connection_status_handlers) == 1


def test_connection_status_notifications():
    """Test that status change notifications are sent to handlers."""
    config = ClientConfig(
        host="test.example.com",
        username="test",
        password="test"
    )
    client = CresNextWSClient(config)
    
    handler = Mock()
    client.add_connection_status_handler(handler)
    
    # Test status change notifications
    client._notify_status_change(ConnectionStatus.CONNECTING)
    handler.assert_called_once_with(ConnectionStatus.CONNECTING)
    assert client.get_connection_status() == ConnectionStatus.CONNECTING
    
    handler.reset_mock()
    
    client._notify_status_change(ConnectionStatus.CONNECTED)
    handler.assert_called_once_with(ConnectionStatus.CONNECTED)
    assert client.get_connection_status() == ConnectionStatus.CONNECTED
    
    handler.reset_mock()
    
    # Same status should not trigger notification
    client._notify_status_change(ConnectionStatus.CONNECTED)
    handler.assert_not_called()
    assert client.get_connection_status() == ConnectionStatus.CONNECTED
    
    handler.reset_mock()
    
    client._notify_status_change(ConnectionStatus.DISCONNECTED)
    handler.assert_called_once_with(ConnectionStatus.DISCONNECTED)
    assert client.get_connection_status() == ConnectionStatus.DISCONNECTED


def test_connection_status_handler_error_handling():
    """Test that errors in handlers don't break the client."""
    config = ClientConfig(
        host="test.example.com",
        username="test",
        password="test"
    )
    client = CresNextWSClient(config)
    
    # Create handlers - one that works and one that raises an exception
    good_handler = Mock()
    bad_handler = Mock(side_effect=Exception("Handler error"))
    
    client.add_connection_status_handler(good_handler)
    client.add_connection_status_handler(bad_handler)
    
    # Status change should still work even with a failing handler
    client._notify_status_change(ConnectionStatus.CONNECTING)
    
    # Good handler should be called
    good_handler.assert_called_once_with(ConnectionStatus.CONNECTING)
    
    # Bad handler should be called but error should be caught
    bad_handler.assert_called_once_with(ConnectionStatus.CONNECTING)
    
    # Status should still be updated
    assert client.get_connection_status() == ConnectionStatus.CONNECTING


@pytest.mark.asyncio
async def test_connection_status_during_operations():
    """Test that connection status is updated during connect/disconnect operations."""
    config = ClientConfig(
        host="test.example.com", 
        username="test",
        password="test"
    )
    client = CresNextWSClient(config)
    
    handler = Mock()
    client.add_connection_status_handler(handler)
    
    # Mock the authentication method to fail (so we can test without real connection)
    client._authenticate = AsyncMock(return_value=None)
    
    # Test failed connection
    result = await client.connect()
    assert result is False
    
    # Should have received CONNECTING then DISCONNECTED status
    expected_calls = [
        ((ConnectionStatus.CONNECTING,),),
        ((ConnectionStatus.DISCONNECTED,),)
    ]
    assert handler.call_args_list == expected_calls
    assert client.get_connection_status() == ConnectionStatus.DISCONNECTED
    
    # Reset for disconnect test
    handler.reset_mock()
    
    # Test disconnect when already disconnected
    await client.disconnect()
    
    # Should not trigger any status changes since already disconnected
    handler.assert_not_called()
    assert client.get_connection_status() == ConnectionStatus.DISCONNECTED


def test_connection_status_enum_values():
    """Test that ConnectionStatus enum has expected values."""
    assert ConnectionStatus.CONNECTED.value == "connected"
    assert ConnectionStatus.DISCONNECTED.value == "disconnected"
    assert ConnectionStatus.CONNECTING.value == "connecting"
    assert ConnectionStatus.RECONNECTING.value == "reconnecting"