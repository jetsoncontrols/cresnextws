# cresnextws

Crestron CresNext WebSocket API Client

A Python library for interacting with Crestron CresNext systems via WebSocket API.

## Installation

Install from PyPI (when published):

```bash
pip install cresnextws
```

Or install from source:

```bash
git clone https://github.com/jetsoncontrols/cresnextws.git
cd cresnextws
pip install .
```

## Quick Start

### Basic HTTP Operations

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig

async def main():
    # Create configuration (required)
    config = ClientConfig(
        host="your-cresnext-host.local",
        username="your_username",
        password="your_password",
        auto_reconnect=True  # Enable automatic reconnection
    )
    
    # Create client instance with config
    client = CresNextWSClient(config)
    
    # Connect to the system
    await client.connect()
    
    # HTTP GET request
    response = await client.http_get("/Device/Ethernet/HostName")
    print(f"Hostname: {response}")
    
    # HTTP POST request (update configuration)
    data = {"Device": {"Ethernet": {"HostName": "new-hostname"}}}
    response = await client.http_post("/Device/Ethernet/HostName", data)
    print(f"Update response: {response}")
    
    # Disconnect when done
    await client.disconnect()

# Run the example
asyncio.run(main())
```

### Health Check Configuration

The library includes a health check mechanism to detect stale connections (particularly after system sleep/wake cycles) and automatically trigger reconnection:

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig

async def main():
    config = ClientConfig(
        host="your-cresnext-host.local",
        username="your_username",
        password="your_password",
        auto_reconnect=True,            # Enable automatic reconnection (required for health check)
        health_check_interval=5.0,      # Check connection health every 5 seconds (default)
        health_check_timeout=2.0,       # Health check ping timeout in seconds (default)
        health_check_path="/Device/DeviceInfo/Model"  # Optional WebSocket path for enhanced health checks
    )
    
    client = CresNextWSClient(config)
    await client.connect()
    
    # Health check runs automatically in the background
    # If a ping fails or times out, it will trigger reconnection
    
    # Your application logic here...
    await asyncio.sleep(300)  # Run for 5 minutes
    
    await client.disconnect()

asyncio.run(main())
```

**Health Check Features:**
- **Automatic Detection**: Detects stale WebSocket connections after system sleep/wake cycles
- **Configurable Intervals**: Customize how often to check connection health
- **Timeout Handling**: Configurable timeout for ping responses
- **Enhanced Validation**: Optional WebSocket GET requests during health checks for real API validation
- **Seamless Integration**: Works alongside existing reconnection system
- **Zero Configuration**: Enabled by default with sensible defaults when `auto_reconnect=True`

**Note**: Health check only runs when `auto_reconnect=True`. If auto-reconnection is disabled, health checks are automatically disabled as well.
```

### WebSocket Operations

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig

async def main():
    config = ClientConfig(
        host="your-cresnext-host.local",
        username="your_username",
        password="your_password",
        health_check_interval=5.0,  # Ping every 5 seconds (default)
        health_check_timeout=2.0,   # 2 second ping timeout (default)
        health_check_path="/Device/DeviceInfo/Model"  # Optional WebSocket GET for enhanced validation
    )
    
    async with CresNextWSClient(config) as client:
        # WebSocket GET - subscribe to data updates
        await client.ws_get("/Device/DeviceInfo/Model")
        
        # WebSocket POST - send configuration updates
        data = {"Device": {"Config": {"SomeValue": "new_value"}}}
        await client.ws_post(data)
        
        # Listen for incoming messages
        message = await client.next_message(timeout=5.0)
        print(f"Received: {message}")

asyncio.run(main())
```

### Connection Status Events

Monitor connection state changes with event callbacks:

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig, ConnectionStatus

def on_status_change(status: ConnectionStatus):
    if status == ConnectionStatus.CONNECTED:
        print("🟢 Connected to device!")
    elif status == ConnectionStatus.DISCONNECTED:
        print("🔴 Disconnected from device")
    elif status == ConnectionStatus.CONNECTING:
        print("🟡 Connecting...")
    elif status == ConnectionStatus.RECONNECTING:
        print("🟠 Reconnecting...")

async def main():
    config = ClientConfig(
        host="your-cresnext-host.local",
        username="your_username", 
        password="your_password",
        auto_reconnect=True
    )
    
    client = CresNextWSClient(config)
    
    # Subscribe to connection status events
    client.add_connection_status_handler(on_status_change)
    
    # Get current status
    print(f"Current status: {client.get_connection_status()}")
    
    # Connect (will trigger status events)
    await client.connect()
    
    # Your application logic here...
    
    # Cleanup
    client.remove_connection_status_handler(on_status_change)
    await client.disconnect()

asyncio.run(main())
```

### Configuration and Utilities

Access configuration details and utility methods:

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig

async def main():
    config = ClientConfig(
        host="your-cresnext-host.local",
        username="your_username",
        password="your_password"
    )
    
    client = CresNextWSClient(config)
    
    # Get the base HTTPS endpoint URL
    base_url = client.get_base_endpoint()
    print(f"Base endpoint: {base_url}")  # Output: https://your-cresnext-host.local
    
    # This is useful for constructing custom URLs or understanding the connection target
    # The base endpoint is used internally for all HTTP requests and WebSocket origins
    
    await client.connect()
    # ... your application logic ...
    await client.disconnect()

asyncio.run(main())
```

### DataEventManager - Real-time Monitoring

The `DataEventManager` provides automatic monitoring of WebSocket messages with path-based subscriptions:

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig, DataEventManager

async def main():
    config = ClientConfig(
        host="your-cresnext-host.local",
        username="your_username",
        password="your_password"
    )
    
    client = CresNextWSClient(config)
    await client.connect()
    
    # Create data event manager
    data_manager = DataEventManager(client)
    
    # Define callback function
    def on_device_update(path: str, data):
        print(f"Device updated: {path} = {data}")
    
    def on_network_change(path: str, data):
        print(f"Network change: {path} = {data}")
    
    # Subscribe to different data paths
    data_manager.subscribe("/Device/DeviceInfo/*", on_device_update)
    data_manager.subscribe("/Device/Network/*", on_network_change)
    
    # Start monitoring
    await data_manager.start_monitoring()
    
    # Request data to trigger callbacks
    await client.ws_get("/Device/DeviceInfo/Model")
    await client.ws_get("/Device/Network/Interface")
    
    # Monitor for 30 seconds
    await asyncio.sleep(30)
    
    # Clean up
    await data_manager.stop_monitoring()
    await client.disconnect()

asyncio.run(main())
```

#### Path Pattern Matching

The DataEventManager supports flexible path matching:

- **Exact match**: `/Device/Config` - matches only that specific path
- **Wildcard match**: `/Device/*` - matches any direct child of `/Device/`
- **Child matching**: `/Device/Config` with `match_children=True` - matches the path and all sub-paths

```python
# Examples of path patterns
data_manager.subscribe("/Device/Config", callback)                    # Exact match
data_manager.subscribe("/Device/*", callback)                         # Wildcard
data_manager.subscribe("/Device/Config", callback, match_children=True)  # Include children
```

#### Full Message Access

By default, callbacks receive only the changed value. Use `full_message=True` to access the complete WebSocket message including metadata:

```python
def value_only_callback(path: str, data):
    print(f"Value: {data}")  # Only the changed data

def full_message_callback(path: str, message):
    print(f"Full message: {message}")  # Complete JSON with timestamps, etc.

# Traditional behavior (default)
data_manager.subscribe("/Device/Config", value_only_callback, full_message=False)

# New: Access full message including metadata
data_manager.subscribe("/Device/Config", full_message_callback, full_message=True)
```

#### Context Manager Usage

```python
async def monitor_with_context():
    config = ClientConfig(host="your-host.local", username="admin", password="password")
    
    async with CresNextWSClient(config) as client:
        async with DataEventManager(client) as data_manager:
            # Add subscriptions
            data_manager.subscribe("/Device/*", lambda path, data: print(f"{path}: {data}"))
            
            # Request data
            await client.ws_get("/Device/Info")
            
            # Monitor for a while
            await asyncio.sleep(10)
            
    # Automatic cleanup when exiting context

asyncio.run(monitor_with_context())
```

## API Reference

### CresNextWSClient Methods

#### Connection Management
- `await client.connect()` - Connect to the CresNext system
- `await client.disconnect()` - Disconnect from the system
- `client.connected` - Check connection status

#### HTTP Operations
- `await client.http_get(path)` - Send HTTP GET request
- `await client.http_post(path, data)` - Send HTTP POST request with JSON data

#### WebSocket Operations  
- `await client.ws_get(path)` - Subscribe to WebSocket data updates for a path
- `await client.ws_post(data)` - Send data via WebSocket
- `await client.next_message(timeout=None)` - Get next WebSocket message

### DataEventManager Methods

#### Subscription Management
- `subscribe(path_pattern, callback, match_children=True, full_message=False)` - Add subscription
  - `full_message=True` - Pass complete JSON message to callback (includes metadata)
  - `full_message=False` - Pass only the changed value to callback (default behavior)
- `unsubscribe(subscription_id)` - Remove subscription
- `clear_subscriptions()` - Remove all subscriptions
- `get_subscriptions()` - List current subscriptions

#### Monitoring Control
- `await start_monitoring()` - Begin monitoring WebSocket messages
- `await stop_monitoring()` - Stop monitoring

### Common API Paths

Based on integration testing, common device paths include:

```python
# Device Information
"/Device/DeviceInfo/Model"
"/Device/DeviceInfo/SerialNumber" 
"/Device/DeviceInfo/FirmwareVersion"

# Network Configuration
"/Device/Ethernet/HostName"
"/Device/Ethernet/IPAddress"
"/Device/Ethernet/MACAddress"

# Device Configuration
"/Device/Config/*"
"/Device/Network/*"
"/Device/State/*"
```

## Examples

For comprehensive examples, see `examples.py` in the repository:

```bash
python3 examples.py
```

The examples demonstrate:
- Basic HTTP and WebSocket operations
- DataEventManager usage with subscriptions
- Context manager patterns
- Error handling and cleanup
- Batch operations
- Real-time device monitoring

## Development

### Setup Development Environment

```bash
git clone https://github.com/jetsoncontrols/cresnextws.git
cd cresnextws
pip install -e .[dev]
```

### Running Tests

```bash
pytest

To run integration tests:
pytest -m integration --run-integration --systems <systems entries from services.json>
```

### Service-driven Integration Tests

You can provide real system connection details to pytest without hard-coding them in tests.

1) Create a services file:
     - Copy `tests/services.example.json` to `tests/services.json`
     - Edit values or set environment variables referenced by `${VARS}`

2) Run integration tests by opting in:

```bash
pytest --run-integration --systems all
```

Alternatively, since integration tests are marked with `@pytest.mark.integration` and excluded by default via project config, you can select them explicitly:

```bash
pytest -m integration --run-integration [other flags]
```

Flags and environment variables:
- `--services-file PATH` or `CRESNEXTWS_SERVICES_FILE=PATH` to point to a JSON file
- `--systems name1,name2` or `CRESNEXTWS_SYSTEMS=name1,name2` to select systems
- Use `--systems all` to include all systems with `"enabled": true`

Example JSON structure:

```json
{
    "systems": {
        "local_sim": {
            "enabled": true,
            "host": "test.local",
            "auth": {"username": "${CRESNEXTWS_USER}", "password": "${CRESNEXTWS_PASS}"}
        }
    }
}
```

Notes:
- Integration tests are skipped unless `--run-integration` is supplied.
- Missing systems or disabled entries are automatically skipped.

### Code Formatting

```bash
black cresnextws/
```

### Type Checking

```bash
mypy cresnextws/
```

## Features

- **Async/await support** for non-blocking operations
- **HTTP and WebSocket APIs** for comprehensive device interaction
- **DataEventManager** for real-time monitoring with path-based subscriptions
- **Full message access** option for receiving complete WebSocket messages with metadata
- **Connection Status Events** for monitoring connect/disconnect states
- **Context manager support** for automatic connection management
- **Type hints** for better development experience
- **Comprehensive logging** support
- **Automatic reconnection** capabilities with connection health monitoring
- **Health check mechanism** to detect stale connections after system sleep/wake cycles
- **Flexible path pattern matching** with wildcard and child path support
- Easy-to-use API for Crestron CresNext systems

## Requirements

- Python 3.8 or higher
- websockets>=11.0
- aiohttp>=3.8.0

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Publishing

This project is automatically published to PyPI using GitHub Actions. The publishing workflow is triggered by:

### For Development Releases (Test PyPI)
- **Pushes to main branch**: Automatically publishes to Test PyPI for testing
- **Manual workflow dispatch**: Can be triggered manually with option to publish to Test PyPI

### For Production Releases (PyPI)
- **Version tags**: Create and push a version tag (e.g., `v1.0.0`, `v0.2.1`) to trigger a production release to PyPI

### Setting up PyPI Credentials

To enable automatic publishing, you need to configure the following secrets in your GitHub repository:

1. **For Test PyPI publishing** (pushes to main branch):
   - Go to [Test PyPI](https://test.pypi.org/manage/account/), create an API token
   - Add the token as `TEST_PYPI_API_TOKEN` in GitHub repository secrets

2. **For PyPI publishing** (version tags):
   - Go to [PyPI](https://pypi.org/manage/account/), create an API token
   - Add the token as `PYPI_API_TOKEN` in GitHub repository secrets

### Creating a Release

To create a new release:

1. Update the version in `pyproject.toml`
2. Commit your changes
3. Create and push a tag:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

The GitHub Action will automatically:
- Run tests across multiple Python versions
- Build the package
- Publish to PyPI
- Create a GitHub release with release notes

### Manual Testing

To test the package build locally before releasing:

```bash
# Install build tools
pip install build twine

# Build the package
python -m build --no-isolation

# Check the package
python -m twine check dist/*

# Test upload to Test PyPI (optional)
python -m twine upload --repository testpypi dist/*
```
