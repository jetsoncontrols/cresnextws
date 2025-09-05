# DataEventManager Usage Guide

The `DataEventManager` is a powerful component of the CresNextWS library that provides automatic monitoring of WebSocket messages and path-based subscription capabilities.

## Overview

The DataEventManager monitors the WebSocket connection from a `CresNextWSClient` and allows you to subscribe to specific data paths. When data matching your subscriptions is received, your callback functions are automatically triggered.

## Basic Usage

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig, DataEventManager

async def main():
    # Create and connect client
    config = ClientConfig(
        host="192.168.1.100",
        username="admin",
        password="password"
    )
    
    client = CresNextWSClient(config)
    await client.connect()
    
    # Create data event manager
    data_manager = DataEventManager(client)
    
    # Define callback function
    def on_device_update(path: str, data):
        print(f"Device updated: {path} = {data}")
    
    # Subscribe to device updates
    subscription_id = data_manager.subscribe(
        path_pattern="/Device/*",
        callback=on_device_update,
        match_children=True
    )
    
    # Start monitoring
    await data_manager.start_monitoring()
    
    # Request some data to trigger callbacks
    await client.ws_get("/Device/Config")
    
    # Let it monitor for a while
    await asyncio.sleep(10)
    
    # Clean up
    await data_manager.stop_monitoring()
    await client.disconnect()

asyncio.run(main())
```

## Path Patterns

The DataEventManager supports flexible path matching:

### Exact Match
```python
data_manager.subscribe("/Device/Config", callback)
# Matches only: /Device/Config
```

### Wildcard Match
```python
data_manager.subscribe("/Device/*", callback)
# Matches: /Device/Config, /Device/Network, etc.
```

### Child Path Matching
```python
data_manager.subscribe("/Device/Config", callback, match_children=True)
# Matches: /Device/Config, /Device/Config/SubItem, /Device/Config/Sub/Deep
```

### Disable Child Matching
```python
data_manager.subscribe("/Device/Config", callback, match_children=False)
# Matches only: /Device/Config (exact match only)
```

## Subscription Management

### Adding Subscriptions
```python
# Subscribe and get subscription ID
sub_id = data_manager.subscribe(
    path_pattern="/Device/Network/*",
    callback=my_callback,
    match_children=True
)
```

### Removing Subscriptions
```python
# Remove specific subscription
success = data_manager.unsubscribe(sub_id)

# Remove all subscriptions
data_manager.clear_subscriptions()
```

### Listing Subscriptions
```python
# Get info about all subscriptions
subscriptions = data_manager.get_subscriptions()
for sub in subscriptions:
    print(f"ID: {sub['subscription_id']}")
    print(f"Pattern: {sub['path_pattern']}")
    print(f"Match Children: {sub['match_children']}")
```

## Multiple Subscriptions

You can have multiple subscriptions that may overlap:

```python
def general_callback(path: str, data):
    print(f"General: {path} = {data}")

def specific_callback(path: str, data):
    print(f"Specific: {path} = {data}")

# Both will trigger for /Device/Config
data_manager.subscribe("/Device/*", general_callback)
data_manager.subscribe("/Device/Config", specific_callback)
```

## Message Format Handling

The DataEventManager automatically handles different message formats:

### Standard Format
```json
{
    "path": "/Device/Config",
    "data": {"value": "some_value"}
}
```

### Alternative Format
```json
{
    "Path": "/Device/Config",
    "Data": {"value": "some_value"}
}
```

### Simple Format
```json
{
    "/Device/Config": {"value": "some_value"}
}
```

## Context Manager Usage

For automatic cleanup, use as an async context manager:

```python
async def monitor_with_context():
    config = ClientConfig(host="192.168.1.100", username="admin", password="password")
    
    async with CresNextWSClient(config) as client:
        async with DataEventManager(client) as data_manager:
            # Add subscriptions
            data_manager.subscribe("/Device/*", lambda path, data: print(f"{path}: {data}"))
            
            # Request data
            await client.ws_get("/Device/Info")
            
            # Monitor for a while
            await asyncio.sleep(10)
            
    # Automatic cleanup when exiting context
```

## Error Handling

Callbacks should handle their own errors. If a callback raises an exception, it will be logged but won't stop other callbacks from executing:

```python
def safe_callback(path: str, data):
    try:
        # Your processing logic here
        process_data(path, data)
    except Exception as e:
        print(f"Error processing {path}: {e}")

data_manager.subscribe("/Device/*", safe_callback)
```

## Performance Considerations

- Callbacks are executed synchronously, so keep them fast
- For heavy processing, consider using asyncio.create_task() or threading
- Use specific path patterns to reduce unnecessary callback executions
- Monitor `subscription_count` property to track active subscriptions

## Example: Real-time Device Monitoring

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig, DataEventManager

class DeviceMonitor:
    def __init__(self, client):
        self.data_manager = DataEventManager(client)
        self.device_states = {}
        
    def setup_subscriptions(self):
        # Monitor all device state changes
        self.data_manager.subscribe("/Device/State/*", self.on_state_change)
        
        # Monitor configuration changes
        self.data_manager.subscribe("/Device/Config/*", self.on_config_change)
        
        # Monitor network status
        self.data_manager.subscribe("/Device/Network/*", self.on_network_change)
    
    def on_state_change(self, path: str, data):
        device_id = path.split("/")[-1]
        self.device_states[device_id] = data
        print(f"Device {device_id} state: {data}")
    
    def on_config_change(self, path: str, data):
        print(f"Configuration changed: {path} = {data}")
    
    def on_network_change(self, path: str, data):
        print(f"Network update: {path} = {data}")
    
    async def start_monitoring(self):
        self.setup_subscriptions()
        await self.data_manager.start_monitoring()
    
    async def stop_monitoring(self):
        await self.data_manager.stop_monitoring()

async def main():
    config = ClientConfig(host="192.168.1.100", username="admin", password="password")
    
    async with CresNextWSClient(config) as client:
        monitor = DeviceMonitor(client)
        await monitor.start_monitoring()
        
        # Request initial state
        await client.ws_get("/Device/State")
        
        # Monitor for 30 seconds
        await asyncio.sleep(30)
        
        await monitor.stop_monitoring()

if __name__ == "__main__":
    asyncio.run(main())
```

This comprehensive example shows how to build a real-time device monitoring system using the DataEventManager.
