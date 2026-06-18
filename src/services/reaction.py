"""Reaction service for generating and applying reactions to notes."""

import asyncio
import logging
import random
import re
from typing import Any, Dict

from src.clients.llm import LLMClient
from src.clients.misskey import MisskeyClient
from src.core.config import config
from src.core.constants import DEFAULT_EMOJI, EMOTION_CATEGORIES
from src.services.emoji import EmojiService

logger = logging.getLogger(__name__)


class ReactionService:
    """Service for handling reactions to Misskey notes."""

    def __init__(
        self,
        misskey_client: MisskeyClient,
        llm_client: LLMClient,
        emoji_service: EmojiService,
    ) -> None:
        """Initialize reaction service.

        Args:
            misskey_client: Misskey API client
            llm_client: LLM API client
            emoji_service: Emoji data service
        """
        self.misskey_client = misskey_client
        self.llm_client = llm_client
        self.emoji_service = emoji_service
        self.last_reaction_source: str = "unknown"

    async def generate_reaction(self, note_text: str) -> str:
        """Generate an appropriate reaction for the given note text.

        Args:
            note_text: Text content of the note

        Returns:
            Reaction emoji string

        Raises:
            ReactionError: If reaction generation fails
        """
        # Try to generate custom emoji reaction
        reaction = await self._generate_custom_emoji_reaction(note_text)
        if reaction:
            return reaction

        # Fallback to unicode emoji
        reaction = await self._generate_unicode_emoji_reaction(note_text)
        if reaction:
            return reaction

        # Final fallback
        logger.warning("All reaction generation methods failed, using default emoji")
        self.last_reaction_source = "unicode"
        return DEFAULT_EMOJI

    async def apply_reaction(self, note_id: str, reaction: str) -> bool:
        """Apply a reaction to a note.

        Args:
            note_id: ID of the note to react to
            reaction: Reaction emoji

        Returns:
            True if successful, False otherwise
        """
        success = await self.misskey_client.add_reaction(note_id, reaction)
        if success:
            logger.info(f"Successfully added reaction {reaction} to note {note_id}")
        else:
            logger.error(f"Failed to add reaction {reaction} to note {note_id}")
        return success

    async def _generate_custom_emoji_reaction(self, note_text: str) -> str | None:
        """Generate a custom emoji reaction using LLM API.

        Args:
            note_text: Text content of the note

        Returns:
            Custom emoji string or None if generation fails
        """
        # Get emoji examples from emoji service
        emoji_examples = self._prepare_emoji_examples()
        if not emoji_examples:
            logger.warning("No emoji examples available")
            return None

        # Try to generate reaction with retries
        for attempt in range(config.retry.max_retries):
            try:
                reaction = await self.llm_client.generate_reaction(
                    note_text, emoji_examples
                )
                if reaction and self._is_valid_custom_emoji(reaction):
                    logger.debug(f"Generated custom emoji reaction: {reaction}")
                    self.last_reaction_source = "llm"
                    return reaction
                else:
                    logger.warning(
                        f"Invalid reaction generated (attempt {attempt + 1}): {reaction}"
                    )
            except Exception as e:
                logger.error(
                    f"Error generating custom emoji (attempt {attempt + 1}): {e}"
                )
                if attempt == config.retry.max_retries - 1:
                    break
                await asyncio.sleep(config.retry.retry_delay)

        # Fallback to random emoji
        result = self._get_random_custom_emoji()
        if result:
            self.last_reaction_source = "random"
        return result

    async def _generate_unicode_emoji_reaction(self, note_text: str) -> str:
        """Generate a unicode emoji reaction as fallback.

        Args:
            note_text: Text content of the note

        Returns:
            Unicode emoji string
        """
        try:
            result = await self.llm_client.generate_fallback_reaction(note_text)
            self.last_reaction_source = "unicode"
            return result
        except Exception as e:
            logger.error(f"Error generating unicode emoji: {e}")
            self.last_reaction_source = "unicode"
            return DEFAULT_EMOJI

    def _prepare_emoji_examples(self) -> list[str]:
        """Prepare emoji examples for Gemini prompt.

        Returns:
            List of emoji example strings by category
        """
        emoji_data = self.emoji_service.get_emoji_data()
        if not emoji_data:
            return []

        examples = []
        categorized_emojis = emoji_data.get("categorized_emojis", {})

        # Get examples from each emotion category
        for category in EMOTION_CATEGORIES.keys():
            emojis = categorized_emojis.get(category, [])
            if emojis:
                # Sample up to 5 emojis from each category
                sample_size = min(5, len(emojis))
                sample_emojis = random.sample(emojis, sample_size)
                emoji_names = [f":{e['name']}:" for e in sample_emojis]
                examples.append(f"- {category} (例: {', '.join(emoji_names)})")

        return examples

    def _is_valid_custom_emoji(self, emoji_code: str) -> bool:
        """Check if the emoji code is a valid custom emoji.

        Args:
            emoji_code: Emoji code to validate

        Returns:
            True if valid, False otherwise
        """
        # Check format
        match = re.match(r"^:([^:]+):$", emoji_code)
        if not match:
            return False

        emoji_name = match.group(1)
        return self.emoji_service.is_valid_emoji_name(emoji_name)

    def _get_random_custom_emoji(self) -> str | None:
        """Get a random custom emoji.

        Returns:
            Random custom emoji string or None if no emojis available
        """
        emoji_data = self.emoji_service.get_emoji_data()
        if not emoji_data:
            return None

        # Prefer emotion categories
        random_category = random.choice(list(EMOTION_CATEGORIES.keys()))
        categorized_emojis = emoji_data.get("categorized_emojis", {})

        # Find a category with emojis
        for _ in range(len(EMOTION_CATEGORIES)):
            emojis = categorized_emojis.get(random_category, [])
            if emojis:
                random_emoji = random.choice(emojis)
                return f":{random_emoji['name']}:"
            random_category = random.choice(list(EMOTION_CATEGORIES.keys()))

        return None

    def should_react(self, note: Dict[str, Any], bot_user_id: str) -> bool:
        """Determine if the bot should react to this note.

        Args:
            note: Note data
            bot_user_id: Bot's user ID

        Returns:
            True if should react, False otherwise
        """
        # Check if it's bot's own note
        user_id = note.get("user", {}).get("id")
        if user_id == bot_user_id:
            logger.debug(f"Skipping own note: {note.get('id')}")
            return False

        # Check if note has text
        if not note.get("text"):
            logger.debug(f"Skipping empty note: {note.get('id')}")
            return False

        # Check visibility
        visibility = note.get("visibility")
        allowed_visibilities = ["public", "home"]
        if config.reaction.react_to_followers:
            allowed_visibilities.append("followers")

        if visibility not in allowed_visibilities:
            logger.debug(
                f"Skipping note with visibility '{visibility}': {note.get('id')}"
            )
            return False

        # Check if it's a reply or renote
        if (
            note.get("replyId") or note.get("renoteId")
        ) and not config.reaction.react_to_replies:
            logger.debug(f"Skipping reply/renote: {note.get('id')}")
            return False

        # Check reaction probability
        if random.random() > config.reaction.probability:
            logger.debug(f"Skipping due to probability: {note.get('id')}")
            return False

        return True
