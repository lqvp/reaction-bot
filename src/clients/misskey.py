"""Misskey API client."""

import logging
from typing import Any, Dict

import aiohttp

from src.core.config import config
from src.core.exceptions import MisskeyAPIError

logger = logging.getLogger(__name__)


class MisskeyClient:
    """Client for interacting with Misskey API."""

    def __init__(self) -> None:
        """Initialize Misskey client."""
        self.api_url = config.misskey.api_url
        self.token = config.misskey.token
        self.headers = {"Content-Type": "application/json"}

    async def _make_request(
        self, endpoint: str, data: Dict[str, Any] | None = None
    ) -> Dict[str, Any] | None:
        """Make a request to Misskey API.

        Args:
            endpoint: API endpoint (e.g., "notes/reactions/create")
            data: Request data

        Returns:
            Response data or None

        Raises:
            MisskeyAPIError: If API request fails
        """
        url = f"{self.api_url}/{endpoint}"
        if data is None:
            data = {}
        data["i"] = self.token

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url, headers=self.headers, json=data
                ) as response:
                    if response.status in (200, 204):
                        if response.status == 204:
                            return None
                        return await response.json()
                    else:
                        error_text = await response.text()
                        raise MisskeyAPIError(
                            f"API request failed: {error_text}", response.status
                        )
            except aiohttp.ClientError as e:
                logger.error(f"Network error during API request: {e}")
                raise MisskeyAPIError(f"Network error: {str(e)}")

    async def get_account_info(self) -> Dict[str, Any]:
        """Get current account information.

        Returns:
            Account information dictionary

        Raises:
            MisskeyAPIError: If request fails
        """
        logger.info("Fetching account information")
        result = await self._make_request("i")
        if result is None:
            raise MisskeyAPIError("Failed to get account information")
        return result

    async def add_reaction(self, note_id: str, reaction: str) -> bool:
        """Add a reaction to a note.

        Args:
            note_id: ID of the note to react to
            reaction: Reaction emoji (e.g., ":blobcat_uwu:" or "👍")

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"Adding reaction {reaction} to note {note_id}")
        try:
            await self._make_request(
                "notes/reactions/create", {"noteId": note_id, "reaction": reaction}
            )
            return True
        except MisskeyAPIError as e:
            logger.error(f"Failed to add reaction: {e}")
            return False

    async def fetch_custom_emojis(self) -> list[Dict[str, Any]]:
        """Fetch custom emojis from the server.

        Returns:
            List of emoji data

        Raises:
            MisskeyAPIError: If request fails
        """
        logger.info("Fetching custom emojis")
        result = await self._make_request("emojis")
        if result is None:
            return []
        return result.get("emojis", [])
