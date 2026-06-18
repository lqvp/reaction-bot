"""Emoji service for managing and categorizing custom emojis."""

import json
import logging
import os
from typing import Any, Dict, List

from src.clients.llm import LLMClient
from src.clients.misskey import MisskeyClient
from src.core.constants import (
    EMOJI_DATA_PATH,
    EMOTION_CATEGORIES,
    RAW_EMOJI_DATA_PATH,
)
from src.core.exceptions import EmojiDataError

logger = logging.getLogger(__name__)


class EmojiService:
    """Service for managing emoji data and operations."""

    def __init__(self) -> None:
        """Initialize emoji service."""
        self._emoji_data: Dict[str, Any] | None = None
        self._valid_emoji_names: set[str] = set()
        self._load_emoji_data()

    def get_emoji_data(self) -> Dict[str, Any] | None:
        """Get loaded emoji data.

        Returns:
            Emoji data dictionary or None if not loaded
        """
        return self._emoji_data

    def is_valid_emoji_name(self, emoji_name: str) -> bool:
        """Check if an emoji name is valid.

        Args:
            emoji_name: Name of the emoji (without colons)

        Returns:
            True if valid, False otherwise
        """
        return emoji_name in self._valid_emoji_names

    async def preprocess_emojis(
        self, misskey_client: MisskeyClient, llm_client: LLMClient
    ) -> None:
        """Fetch and categorize custom emojis.

        Args:
            misskey_client: Misskey API client
            llm_client: LLM API client

        Raises:
            EmojiDataError: If preprocessing fails
        """
        logger.info("Starting emoji preprocessing")

        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)

        # Fetch emojis from Misskey
        logger.info("Fetching custom emojis from Misskey")
        try:
            all_emojis = await misskey_client.fetch_custom_emojis()
        except Exception as e:
            raise EmojiDataError(f"Failed to fetch emojis: {str(e)}")

        if not all_emojis:
            raise EmojiDataError("No emojis fetched from server")

        logger.info(f"Fetched {len(all_emojis)} custom emojis")

        # Save raw emoji data
        raw_data = {"emojis": all_emojis}
        with open(RAW_EMOJI_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved raw emoji data to {RAW_EMOJI_DATA_PATH}")

        # Categorize emojis
        categorized_emojis = await self._categorize_emojis(all_emojis, llm_client)

        # Calculate statistics
        stats = {cat: len(emojis) for cat, emojis in categorized_emojis.items()}

        # Save processed data
        result = {
            "stats": stats,
            "categories": list(categorized_emojis.keys()),
            "emotion_categories": list(EMOTION_CATEGORIES.keys()),
            "categorized_emojis": categorized_emojis,
        }

        with open(EMOJI_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved processed emoji data to {EMOJI_DATA_PATH}")
        self._log_categorization_stats(stats)

        # Reload the data
        self._load_emoji_data()

    def _load_emoji_data(self) -> None:
        """Load preprocessed emoji data from file."""
        try:
            with open(EMOJI_DATA_PATH, "r", encoding="utf-8") as f:
                self._emoji_data = json.load(f)

            # Build valid emoji names set
            self._valid_emoji_names.clear()
            if self._emoji_data:
                categorized = self._emoji_data.get("categorized_emojis", {})
                for category_emojis in categorized.values():
                    for emoji in category_emojis:
                        self._valid_emoji_names.add(emoji["name"])

            logger.info(
                f"Loaded emoji data: {len(self._emoji_data.get('categories', []))} categories, "
                f"{len(self._valid_emoji_names)} emojis"
            )

        except FileNotFoundError:
            logger.warning(f"Emoji data file not found: {EMOJI_DATA_PATH}")
            logger.warning(
                "Run preprocessing mode to generate emoji data: python main.py --mode preprocess"
            )
            self._emoji_data = None
            self._valid_emoji_names.clear()
        except Exception as e:
            logger.error(f"Failed to load emoji data: {e}")
            self._emoji_data = None
            self._valid_emoji_names.clear()

    async def _categorize_emojis(
        self, emojis: List[Dict[str, Any]], llm_client: LLMClient
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Categorize emojis using LLM API or fallback method.

        Args:
            emojis: List of emoji data
            llm_client: LLM API client

        Returns:
            Dictionary mapping categories to emoji lists
        """
        try:
            logger.info("Attempting to categorize emojis using LLM API")
            allowed_categories = list(EMOTION_CATEGORIES.keys())
            llm_categories = await llm_client.categorize_emojis(
                emojis, allowed_categories
            )

            # Build categorized emojis dictionary
            categorized_emojis: Dict[str, List[Dict[str, Any]]] = {}
            for category, emoji_names in llm_categories.items():
                categorized_emojis[category] = [
                    emoji for emoji in emojis if emoji.get("name") in emoji_names
                ]

            logger.info("Successfully categorized emojis using LLM API")
            return categorized_emojis

        except Exception as e:
            logger.error(f"LLM categorization failed: {e}")
            logger.info("Falling back to keyword-based categorization")
            return self._categorize_emojis_fallback(emojis)

    def _categorize_emojis_fallback(
        self, emojis: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Categorize emojis using keyword matching as fallback.

        Args:
            emojis: List of emoji data

        Returns:
            Dictionary mapping categories to emoji lists
        """
        categorized_emojis: Dict[str, List[Dict[str, Any]]] = {
            cat: [] for cat in EMOTION_CATEGORIES.keys()
        }
        categorized_emojis["other"] = []

        for emoji in emojis:
            categories = self._categorize_single_emoji(emoji)
            emoji_with_categories = emoji.copy()
            emoji_with_categories["emotion_categories"] = categories

            for cat in categories:
                if cat in categorized_emojis:
                    categorized_emojis[cat].append(emoji_with_categories)
                else:
                    categorized_emojis.setdefault(cat, []).append(emoji_with_categories)

        return categorized_emojis

    def _categorize_single_emoji(self, emoji: Dict[str, Any]) -> List[str]:
        """Categorize a single emoji based on keywords.

        Args:
            emoji: Emoji data

        Returns:
            List of category names
        """
        name = emoji.get("name", "").lower()
        category = emoji.get("category", "").lower()
        search_text = f"{name} {category}"

        assigned_categories = []

        # Check each emotion category
        for emotion, keywords in EMOTION_CATEGORIES.items():
            for keyword in keywords:
                if keyword.lower() in search_text:
                    assigned_categories.append(emotion)
                    break

        # Keep original category with prefix
        if category:
            raw_category = f"raw_{category}"
            assigned_categories.append(raw_category)

        # Default to "other" if no categories assigned
        if not assigned_categories:
            assigned_categories.append("other")

        return assigned_categories

    def _log_categorization_stats(self, stats: Dict[str, int]) -> None:
        """Log categorization statistics.

        Args:
            stats: Dictionary mapping categories to counts
        """
        logger.info("Categorization statistics:")
        for cat, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
            if count > 0:
                logger.info(f"  {cat}: {count} emojis")
