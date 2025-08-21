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

### Create a Client with Configuration

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig

async def main():
    # Create configuration (required)
    config = ClientConfig(
        host="your-cresnext-host.local",
        port=443,
        ssl=True,
        auto_reconnect=True  # Enable automatic reconnection
    )
    
    # Create client instance with config
    client = CresNextWSClient(config)
    
    # Connect to the system
    await client.connect(username="your_username", password="your_password")
    
    # Send a command
    response = await client.send_command("get_status")
    print(f"Response: {response}")
    
    # Disconnect when done
    await client.disconnect()

# Run the example
asyncio.run(main())
```

## Using Context Manager

```python
import asyncio
from cresnextws import CresNextWSClient, ClientConfig

async def main():
    # Using configuration object (required)
    config = ClientConfig(host="your-cresnext-host.local", auto_reconnect=True)
    async with CresNextWSClient(config) as client:
        response = await client.send_command("get_status")
        print(f"Response: {response}")

asyncio.run(main())
```

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
```

### Code Formatting

```bash
black cresnextws/
```

### Type Checking

```bash
mypy cresnextws/
```

## Features

- Async/await support for non-blocking operations
- Context manager support for automatic connection management
- Type hints for better development experience
- Comprehensive logging support
- Easy-to-use API for Crestron CresNext systems

## Requirements

- Python 3.8 or higher
- websockets>=11.0
- aiohttp>=3.8.0

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
