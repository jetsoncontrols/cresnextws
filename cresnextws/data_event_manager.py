"""
Data Event Manager for CresNext WebSocket API Client

This module provides a manager class that monitors WebSocket messages from a CresNext
client and triggers callbacks based on path-based subscriptions.
"""

import asyncio
import logging
from typing import Dict, Any, List, Callable, Optional, Tuple
from dataclasses import dataclass, field
import fnmatch
from .client import CresNextWSClient


logger = logging.getLogger(__name__)

# Global counter for unique subscription IDs
_subscription_counter = 0


def _generate_subscription_id() -> str:
    """Generate a unique subscription ID."""
    global _subscription_counter
    _subscription_counter += 1
    return f"sub_{_subscription_counter}"


@dataclass
class Subscription:
    """
    Represents a subscription to a specific path pattern.

    Attributes:
        path_pattern (str): The path pattern to match (supports wildcards)
        callback (Callable): The callback function to invoke when data matches
        match_children (bool): Whether to match child paths (default: True)
        full_message (bool): Whether to pass the full JSON message to callback (default: False)
    """

    path_pattern: str
    callback: Callable[[str, Any], None]
    match_children: bool = True
    full_message: bool = False
    subscription_id: str = field(default_factory=_generate_subscription_id)


class DataEventManager:
    """
    Data Event Manager for monitoring WebSocket messages and triggering callbacks.

    This manager accepts a CresNextWSClient and monitors its WebSocket connection
    for incoming messages. It allows software to subscribe to specific paths and
    triggers callbacks when matching data is received.
    """

    def __init__(self, client: CresNextWSClient):
        """
        Initialize the Data Event Manager.

        Args:
            client (CresNextWSClient): The WebSocket client to monitor
        """
        self.client = client
        self._subscriptions: Dict[str, Subscription] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

        logger.debug("DataEventManager initialized")

    def subscribe(
        self,
        path_pattern: str,
        callback: Callable[[str, Any], None],
        match_children: bool = True,
        full_message: bool = False,
    ) -> str:
        """
        Subscribe to a path pattern with a callback function.

        Args:
            path_pattern (str): The path pattern to match. Supports wildcards (*) and
                               exact matches. Examples:
                               - "/Device/Config" (exact match)
                               - "/Device/*" (wildcard match)
                               - "/Device/Network/Interface*" (prefix wildcard)
            callback (Callable[[str, Any], None]): Function to call when data matches.
                                                   Receives (path, data) as arguments.
            match_children (bool): If True, also matches child paths beneath the pattern.
                                  If False, only matches the exact pattern.
            full_message (bool): If True, passes the full JSON message as the data parameter.
                                If False, passes only the changed value (default behavior).

        Returns:
            str: Subscription ID that can be used to unsubscribe
        """
        subscription = Subscription(
            path_pattern=path_pattern,
            callback=callback,
            match_children=match_children,
            full_message=full_message,
        )

        subscription_id = subscription.subscription_id
        self._subscriptions[subscription_id] = subscription

        logger.debug(
            f"Added subscription {subscription_id} for pattern: {path_pattern}"
        )
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        Remove a subscription by its ID.

        Args:
            subscription_id (str): The subscription ID returned by subscribe()

        Returns:
            bool: True if subscription was found and removed, False otherwise
        """
        if subscription_id in self._subscriptions:
            subscription = self._subscriptions.pop(subscription_id)
            logger.debug(
                f"Removed subscription {subscription_id} for pattern: {subscription.path_pattern}"
            )
            return True
        else:
            logger.warning(f"Subscription {subscription_id} not found")
            return False

    def clear_subscriptions(self) -> None:
        """Remove all subscriptions."""
        count = len(self._subscriptions)
        self._subscriptions.clear()
        logger.debug(f"Cleared {count} subscriptions")

    def get_subscriptions(self) -> List[Dict[str, Any]]:
        """
        Get information about all current subscriptions.

        Returns:
            List[Dict[str, Any]]: List of subscription information dictionaries
        """
        return [
            {
                "subscription_id": sub_id,
                "path_pattern": sub.path_pattern,
                "match_children": sub.match_children,
                "full_message": sub.full_message,
            }
            for sub_id, sub in self._subscriptions.items()
        ]

    def _path_matches_pattern(self, path: str, subscription: Subscription) -> bool:
        """
        Check if a path matches a subscription pattern.

        Args:
            path (str): The data path to check
            subscription (Subscription): The subscription to check against

        Returns:
            bool: True if the path matches the subscription pattern
        """
        pattern = subscription.path_pattern

        # Exact match
        if path == pattern:
            return True

        # Wildcard pattern matching
        if fnmatch.fnmatch(path, pattern):
            return True

        # Child path matching (if enabled)
        if subscription.match_children:
            # Check if path is a child of the pattern
            # Remove trailing wildcards for child matching
            clean_pattern = pattern.rstrip("*")
            if clean_pattern.endswith("/"):
                clean_pattern = clean_pattern[:-1]

            # Path should start with the pattern followed by a slash
            if path.startswith(clean_pattern + "/"):
                return True

            # Also handle case where pattern doesn't end with slash
            if not pattern.endswith("/") and not pattern.endswith("*"):
                if path.startswith(pattern + "/"):
                    return True

        return False

    def _extract_paths_from_nested_data(
        self, data: Dict[str, Any], parent_path: str = ""
    ) -> List[Tuple[str, Any]]:
        """
        Recursively extract all paths and their values from nested data.

        Args:
            data (Dict[str, Any]): The nested data structure
            parent_path (str): The parent path (for recursion)

        Returns:
            List[Tuple[str, Any]]: List of (path, value) tuples
        """
        paths = []

        if not isinstance(data, dict):
            return [(parent_path, data)] if parent_path else []

        for key, value in data.items():
            # Special case: if key starts with "/" it's already a full path
            if key.startswith("/"):
                current_path = key
                # For full paths, just add the path with its value (don't recurse)
                paths.append((current_path, value))
            else:
                current_path = f"{parent_path}/{key}" if parent_path else f"/{key}"

                if isinstance(value, dict):
                    # Add the current path with the dict value
                    paths.append((current_path, value))
                    # Recursively extract nested paths
                    paths.extend(
                        self._extract_paths_from_nested_data(value, current_path)
                    )
                else:
                    # Leaf node - add the path with its value
                    paths.append((current_path, value))

        return paths

    def _process_message(self, message: Dict[str, Any]) -> None:
        """
        Process an incoming WebSocket message and trigger matching callbacks.

        Args:
            message (Dict[str, Any]): The message received from the WebSocket
        """
        try:
            logger.debug(f"Processing message: {message}")

            # Handle messages with explicit path/data keys (both lowercase and uppercase)
            explicit_path = message.get("path") or message.get("Path")
            explicit_data = message.get("data") or message.get("Data")

            if explicit_path is not None:
                # Direct path/data message format
                paths_and_data = [(explicit_path, explicit_data)]
            else:
                # Extract all paths from nested structure
                # For messages like {'Device': {'Ethernet': {'HostName': 'DM-NAX-4ZSP'}}}
                paths_and_data = self._extract_paths_from_nested_data(message)

            if not paths_and_data:
                logger.debug(f"No paths could be extracted from message: {message}")
                return

            total_matches = 0

            # Process each extracted path
            for path, data in paths_and_data:
                # Ensure path is a string
                if not isinstance(path, str):
                    logger.debug(f"Skipping non-string path: {path}")
                    continue

                # Find matching subscriptions for this path
                matched_subscriptions = []
                for sub_id, subscription in self._subscriptions.items():
                    if self._path_matches_pattern(path, subscription):
                        matched_subscriptions.append((sub_id, subscription))

                # Trigger callbacks for matching subscriptions
                for sub_id, subscription in matched_subscriptions:
                    try:
                        logger.debug(
                            f"Triggering callback for subscription {sub_id} (pattern: {subscription.path_pattern}, path: {path})"
                        )
                        # Pass either the full message or just the specific data based on subscription setting
                        callback_data = message if subscription.full_message else data
                        subscription.callback(path, callback_data)
                    except Exception as e:
                        logger.error(
                            f"Error in callback for subscription {sub_id}: {e}"
                        )

                if matched_subscriptions:
                    logger.debug(
                        f"Path {path} matched {len(matched_subscriptions)} subscriptions"
                    )
                    total_matches += len(matched_subscriptions)

            if total_matches > 0:
                logger.debug(
                    f"Processed message with {total_matches} total subscription matches"
                )
            else:
                logger.debug("No subscriptions matched any paths in message")

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def start_monitoring(self) -> None:
        """
        Start monitoring the WebSocket client for messages.

        This method starts a background task that continuously monitors the client's
        WebSocket connection for incoming messages and processes them.

        Raises:
            RuntimeError: If the client is not connected or monitoring is already running
        """
        if not self.client.connected:
            raise RuntimeError("Client is not connected. Call client.connect() first.")

        if self._running:
            logger.warning("Monitoring is already running")
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Started WebSocket message monitoring")

    async def stop_monitoring(self) -> None:
        """
        Stop monitoring the WebSocket client for messages.

        This method stops the background monitoring task and cleans up resources.
        """
        if not self._running:
            logger.debug("Monitoring is not running")
            return

        self._running = False

        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        logger.info("Stopped WebSocket message monitoring")

    async def _monitor_loop(self) -> None:
        """
        Background task that monitors the WebSocket client for incoming messages.

        This loop continuously calls next_message() on the client and processes
        any received messages through the subscription system.
        """
        logger.debug("Starting message monitoring loop")

        try:
            while self._running and self.client.connected:
                try:
                    # Wait for next message with a timeout to allow graceful shutdown
                    message = await self.client.next_message(timeout=1.0)

                    if message is not None:
                        self._process_message(message)

                except asyncio.TimeoutError:
                    # Timeout is expected, continue monitoring
                    continue
                except Exception as e:
                    logger.error(f"Error in monitoring loop: {e}")
                    # Continue monitoring unless explicitly stopped
                    if self._running:
                        await asyncio.sleep(1.0)  # Brief pause before retrying

        except asyncio.CancelledError:
            logger.debug("Message monitoring loop cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in monitoring loop: {e}")
        finally:
            logger.debug("Message monitoring loop ended")

    @property
    def is_monitoring(self) -> bool:
        """
        Check if the manager is currently monitoring for messages.

        Returns:
            bool: True if monitoring is active, False otherwise
        """
        return (
            self._running
            and self._monitor_task is not None
            and not self._monitor_task.done()
        )

    @property
    def subscription_count(self) -> int:
        """
        Get the number of active subscriptions.

        Returns:
            int: Number of active subscriptions
        """
        return len(self._subscriptions)

    async def __aenter__(self) -> "DataEventManager":
        """Async context manager entry."""
        await self.start_monitoring()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        """Async context manager exit."""
        await self.stop_monitoring()
