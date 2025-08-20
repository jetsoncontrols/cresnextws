"""
cresnextws - Crestron CresNext WebSocket API Client

A Python library for interacting with Crestron CresNext WebSocket API.
"""

__version__ = "0.1.0"
__author__ = "Jetson Controls"
__email__ = ""
__description__ = "Crestron CresNext WebSocket API Client"

from .client import CresNextWSClient, ClientConfig

__all__ = [
    "CresNextWSClient",
    "ClientConfig",
    "__version__",
]
