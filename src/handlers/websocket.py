"""WebSocket handler for Misskey streaming API."""

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict

import websockets
import websockets.exceptions

from src.core.config import config
from src.core.constants import (
    HEARTBEAT_INTERVAL,
    HOME_TIMELINE_CHANNEL,
    HOME_TIMELINE_ID,
)

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """Handles WebSocket connection to Misskey streaming API."""

    def __init__(
        self,
        on_note_callback: Callable[[Dict[str, Any]], Awaitable[None]],
        on_disconnect_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize WebSocket handler.

        Args:
            on_note_callback: Async function to call when a note is received
            on_disconnect_callback: Optional async function to call on disconnect
        """
        self.url = config.misskey.ws_url
        self.user_agent = config.websocket.user_agent
        self.on_note_callback = on_note_callback
        self.on_disconnect_callback = on_disconnect_callback
        self._reconnect_delay = config.websocket.reconnect_delay_initial
        self._running = False

    async def start(self) -> None:
        """Start the WebSocket connection with automatic reconnection."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
                # Reset reconnect delay on successful connection
                self._reconnect_delay = config.websocket.reconnect_delay_initial
            except websockets.exceptions.ConnectionClosed as e:
                logger.error(f"WebSocket connection closed: {e}")
                if self.on_disconnect_callback:
                    await self.on_disconnect_callback()
                await self._handle_reconnect()
            except Exception as e:
                logger.error(f"WebSocket error: {e}", exc_info=True)
                if self.on_disconnect_callback:
                    await self.on_disconnect_callback()
                await self._handle_reconnect()

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._running = False

    async def _connect_and_listen(self) -> None:
        """Establish WebSocket connection and listen for messages."""
        logger.info(f"Connecting to WebSocket (User-Agent: {self.user_agent})")

        async with websockets.connect(
            self.url, user_agent_header=self.user_agent
        ) as websocket:
            logger.info("WebSocket connected successfully")

            # Subscribe to home timeline
            await self._subscribe_to_timeline(websocket)

            # Start heartbeat and message handling
            last_heartbeat = time.time()

            while self._running:
                try:
                    # Wait for message with timeout
                    message = await asyncio.wait_for(
                        websocket.recv(), timeout=HEARTBEAT_INTERVAL
                    )
                    await self._handle_message(message)

                except asyncio.TimeoutError:
                    # Send heartbeat if needed
                    current_time = time.time()
                    if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                        logger.debug("Sending heartbeat")
                        await websocket.send(json.dumps({"type": "ping"}))
                        last_heartbeat = current_time

    async def _subscribe_to_timeline(
        self, websocket: websockets.WebSocketClientProtocol
    ) -> None:
        """Subscribe to home timeline channel.

        Args:
            websocket: Active WebSocket connection
        """
        subscribe_message = {
            "type": "connect",
            "body": {"channel": HOME_TIMELINE_CHANNEL, "id": HOME_TIMELINE_ID},
        }
        await websocket.send(json.dumps(subscribe_message))
        logger.info("Subscribed to home timeline")

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message.

        Args:
            message: Raw message string from WebSocket
        """
        try:
            data = json.loads(message)

            if (
                data.get("type") == "channel"
                and data.get("body", {}).get("type") == "note"
            ):
                note = data["body"]["body"]
                logger.debug(f"Received note: {note.get('id')}")
                await self.on_note_callback(note)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse WebSocket message: {e}")
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}", exc_info=True)

    async def _handle_reconnect(self) -> None:
        """Handle reconnection with exponential backoff."""
        if not self._running:
            return

        logger.info(f"Reconnecting in {self._reconnect_delay} seconds...")
        await asyncio.sleep(self._reconnect_delay)

        # Exponential backoff
        self._reconnect_delay = min(
            self._reconnect_delay * config.websocket.reconnect_factor,
            config.websocket.reconnect_delay_max,
        )
