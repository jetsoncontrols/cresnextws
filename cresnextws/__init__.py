"""
cresnextws - Crestron CresNext WebSocket API Client

A Python library for interacting with Crestron CresNext WebSocket API.
"""

try:
    from importlib.metadata import PackageNotFoundError, metadata

    # Get package metadata
    pkg_metadata = metadata("cresnextws")
    __version__ = pkg_metadata["Version"]
    __description__ = pkg_metadata["Summary"]
    __author__ = pkg_metadata.get("Author") or ""
    __email__ = pkg_metadata.get("Author-email") or ""

except (ImportError, PackageNotFoundError):
    # Fallback for development or when package is not installed
    __version__ = "0.0.0"
    __author__ = ""
    __email__ = ""
    __description__ = "Crestron CresNext WebSocket API Client"

from .client import CresNextWSClient, ClientConfig, ConnectionStatus
from .data_event_manager import DataEventManager, Subscription

__all__ = [
    "CresNextWSClient",
    "ClientConfig",
    "ConnectionStatus",
    "DataEventManager",
    "Subscription",
    "__version__",
    "__author__",
    "__email__",
    "__description__",
]
