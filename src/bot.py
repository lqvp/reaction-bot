"""Main bot module for Misskey Reaction Bot."""

import asyncio
from typing import Any, Dict

from src.clients.gemini import GeminiClient
from src.clients.misskey import MisskeyClient
from src.core.config import config
from src.core.constants import NOTE_PROCESSING_DELAY
from src.core.exceptions import ConfigurationError, MisskeyAPIError
from src.core.logging import get_logger, setup_logging
from src.handlers.websocket import WebSocketHandler
from src.services.emoji import EmojiService
from src.services.reaction import ReactionService
from src.services.stats import StatsService

logger = get_logger(__name__)


class MisskeyReactionBot:
    """Main bot class that coordinates all components."""

    def __init__(self) -> None:
        """Initialize the bot with all necessary components."""
        # Validate configuration
        try:
            config.validate_required_fields()
        except ValueError as e:
            raise ConfigurationError(str(e))

        # Initialize clients
        self.misskey_client = MisskeyClient()
        self.gemini_client = GeminiClient()

        # Initialize services
        self.emoji_service = EmojiService()
        self.stats_service = StatsService()
        self.reaction_service = ReactionService(
            self.misskey_client, self.gemini_client, self.emoji_service
        )

        # Initialize handler
        self.websocket_handler = WebSocketHandler(
            on_note_callback=self._handle_note,
            on_disconnect_callback=self._handle_disconnect,
        )

        # Bot state
        self.bot_user_id: str | None = None
        self._running = False

    async def start(self) -> None:
        """Start the bot."""
        logger.info("Starting Misskey Reaction Bot")

        # Get bot account information
        await self._initialize_bot_account()

        # Start statistics logging
        await self.stats_service.start_periodic_logging()

        # Display startup banner
        self._display_banner()

        # Start WebSocket connection
        self._running = True
        try:
            await self.websocket_handler.start()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the bot gracefully."""
        logger.info("Stopping Misskey Reaction Bot")
        self._running = False

        # Stop components
        await self.websocket_handler.stop()
        await self.stats_service.stop_periodic_logging()

        # Log final statistics
        logger.info(self.stats_service.get_stats_summary())

    async def _initialize_bot_account(self) -> None:
        """Initialize bot account information."""
        try:
            account_info = await self.misskey_client.get_account_info()
            self.bot_user_id = account_info.get("id")
            username = account_info.get("username", "unknown")
            logger.info(f"Bot account: @{username} (ID: {self.bot_user_id})")
        except MisskeyAPIError as e:
            logger.error(f"Failed to get account information: {e}")
            raise ConfigurationError("Cannot proceed without bot account information")

    async def _handle_note(self, note: Dict[str, Any]) -> None:
        """Handle incoming note from WebSocket.

        Args:
            note: Note data from Misskey
        """
        self.stats_service.increment("processed_notes")

        # Check if we should react to this note
        if not self.reaction_service.should_react(note, self.bot_user_id):
            self.stats_service.increment("skipped_notes")
            return

        # Extract note information
        note_id = note.get("id", "unknown")
        note_text = note.get("text", "")
        username = note.get("user", {}).get("username", "unknown")

        try:
            # Generate reaction
            reaction = await self.reaction_service.generate_reaction(note_text)

            # Track reaction generation source
            if reaction.startswith(":") and reaction.endswith(":"):
                self.stats_service.increment("gemini_success_count")
            elif len(reaction) == 1:  # Unicode emoji
                self.stats_service.increment("unicode_fallback_count")
            else:
                self.stats_service.increment("random_fallback_count")

            # Apply reaction
            success = await self.reaction_service.apply_reaction(note_id, reaction)

            if success:
                self.stats_service.increment("reactions_sent")
                self.stats_service.increment_reaction(reaction)
                self.stats_service.log_reaction(username, note_text, reaction)
                await asyncio.sleep(NOTE_PROCESSING_DELAY)
            else:
                self.stats_service.increment("errors")

        except Exception as e:
            logger.error(f"Error processing note {note_id}: {e}", exc_info=True)
            self.stats_service.increment("errors")

    async def _handle_disconnect(self) -> None:
        """Handle WebSocket disconnection."""
        self.stats_service.increment("ws_disconnect_count")
        logger.warning("WebSocket disconnected")

    def _display_banner(self) -> None:
        """Display startup banner."""
        banner = """
================================================================================
 Misskey リアクションボット 稼働中
================================================================================
        """
        logger.info(banner)


async def main() -> None:
    """Main entry point for the bot."""
    # Set up logging
    setup_logging()

    # Create and run bot
    bot = MisskeyReactionBot()
    try:
        await bot.start()
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        return
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return


if __name__ == "__main__":
    asyncio.run(main())
