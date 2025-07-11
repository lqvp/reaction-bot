"""Emoji preprocessing module for Misskey Reaction Bot."""

import asyncio

from src.clients.gemini import GeminiClient
from src.clients.misskey import MisskeyClient
from src.core.config import config
from src.core.exceptions import ConfigurationError, EmojiDataError
from src.core.logging import get_logger, setup_logging
from src.services.emoji import EmojiService

logger = get_logger(__name__)


async def main() -> None:
    """Main entry point for emoji preprocessing."""
    # Set up logging
    setup_logging()

    logger.info("Starting emoji preprocessing")

    # Validate configuration
    try:
        config.validate_required_fields()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return

    # Initialize clients
    misskey_client = MisskeyClient()
    gemini_client = GeminiClient()

    # Initialize emoji service
    emoji_service = EmojiService()

    try:
        # Process emojis
        await emoji_service.preprocess_emojis(misskey_client, gemini_client)
        logger.info("Emoji preprocessing completed successfully")
    except EmojiDataError as e:
        logger.error(f"Emoji processing error: {e}")
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
