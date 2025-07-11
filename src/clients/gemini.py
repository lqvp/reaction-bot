"""Gemini API client."""

import json
import logging
from typing import Any, Dict, List

import google.generativeai as genai
from pydantic import BaseModel, Field

from src.core.config import config
from src.core.exceptions import GeminiAPIError

logger = logging.getLogger(__name__)

# Configure Gemini API
genai.configure(api_key=config.gemini.api_key)


class ReactionResponse(BaseModel):
    """Response model for reaction generation."""

    reactions: str = Field(
        description="Suggested Misskey custom emoji (e.g., :blobcat_uwu:)"
    )


class EmojiCategory(BaseModel):
    """A single category with a list of emoji names."""

    category_name: str = Field(description="Name of the emoji category.")
    emoji_names: List[str] = Field(description="List of emoji names in this category.")


class EmojiCategorizationResponse(BaseModel):
    """Response model for emoji categorization."""

    categories: List[EmojiCategory] = Field(description="List of emoji categories.")


class GeminiClient:
    """Client for interacting with Gemini API."""

    def __init__(self) -> None:
        """Initialize Gemini client."""
        self.model = genai.GenerativeModel(config.gemini.model)
        self._safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

    async def generate_reaction(
        self, note_text: str, emoji_examples: List[str]
    ) -> str | None:
        """Generate a reaction emoji for the given note text.

        Args:
            note_text: The text of the note to react to
            emoji_examples: List of example emojis by category

        Returns:
            Reaction emoji string or None if generation fails
        """
        prompt = self._create_reaction_prompt(note_text, emoji_examples)

        generation_config = genai.types.GenerationConfig(
            response_mime_type="application/json",
            response_schema=ReactionResponse,
        )

        try:
            response = await self.model.generate_content_async(
                contents=prompt,
                generation_config=generation_config,
                safety_settings=self._safety_settings,
            )

            if response.text:
                try:
                    parsed_data = ReactionResponse.model_validate_json(response.text)
                    return parsed_data.reactions
                except Exception as e:
                    logger.warning(
                        f"Failed to parse reaction response: {e}, Response: {response.text}"
                    )
                    return None
            else:
                logger.warning(f"Empty response from Gemini: {response}")
                return None

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise GeminiAPIError(f"Failed to generate reaction: {str(e)}")

    async def generate_fallback_reaction(self, note_text: str) -> str:
        """Generate a fallback Unicode emoji reaction.

        Args:
            note_text: The text of the note to react to

        Returns:
            Unicode emoji string
        """
        prompt = self._create_fallback_prompt(note_text)

        try:
            result = await self.model.generate_content_async(prompt)
            response_text = result.text.strip()

            # Try to parse JSON response
            try:
                response_json = json.loads(response_text)
                reaction = response_json.get("reaction")
                if reaction:
                    return reaction
            except json.JSONDecodeError:
                # Try to extract emoji from the response
                import re

                emoji_match = re.search(
                    r'["\']([\p{Emoji}]+)["\']', response_text, re.UNICODE
                )
                if emoji_match:
                    return emoji_match.group(1)

            # Final fallback
            return "👍"

        except Exception as e:
            logger.error(f"Fallback reaction generation error: {e}")
            return "👍"

    async def categorize_emojis(
        self, emojis: List[Dict[str, Any]], allowed_categories: List[str]
    ) -> Dict[str, List[str]]:
        """Categorize emojis using Gemini API.

        Args:
            emojis: List of emoji data
            allowed_categories: List of allowed category names

        Returns:
            Dictionary mapping categories to emoji names
        """
        # Process in chunks
        chunk_size = 50
        all_categories: Dict[str, List[str]] = {}

        for i in range(0, len(emojis), chunk_size):
            chunk = emojis[i : i + chunk_size]
            emoji_list_text = "\n".join(
                [
                    f"名前: {emoji.get('name', '')}, 元のカテゴリ: {emoji.get('category', '')}"
                    for emoji in chunk
                ]
            )

            prompt = self._create_categorization_prompt(
                emoji_list_text, allowed_categories
            )

            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json",
                response_schema=EmojiCategorizationResponse,
            )

            try:
                response = await self.model.generate_content_async(
                    contents=prompt,
                    generation_config=generation_config,
                    safety_settings=self._safety_settings,
                )

                if response.text:
                    parsed_data = EmojiCategorizationResponse.model_validate_json(
                        response.text
                    )
                    chunk_categories_list = parsed_data.categories

                    # Convert list of objects to dict
                    chunk_categories = {
                        item.category_name: item.emoji_names
                        for item in chunk_categories_list
                    }

                    # Merge categories
                    for cat, emoji_names in chunk_categories.items():
                        if cat in all_categories:
                            all_categories[cat].extend(emoji_names)
                        else:
                            all_categories[cat] = emoji_names

            except Exception as e:
                logger.error(f"Failed to categorize emoji chunk {i}: {e}")
                raise GeminiAPIError(f"Emoji categorization failed: {str(e)}")

        # Filter to allowed categories
        allowed_set = set(allowed_categories)
        if "other" not in allowed_set:
            allowed_set.add("other")

        filtered_categories = {key: [] for key in allowed_set}
        for cat, emoji_names in all_categories.items():
            if cat in allowed_set:
                filtered_categories[cat].extend(emoji_names)
            else:
                filtered_categories["other"].extend(emoji_names)

        return filtered_categories

    def _create_reaction_prompt(self, note_text: str, emoji_examples: List[str]) -> str:
        """Create prompt for reaction generation."""
        return f"""
        以下のノートに対して、文脈に最も適したMisskeyカスタム絵文字を1つ提案してください。

        ルール:
        1. ノートの感情、トーン、内容に合わせて最適なカスタム絵文字を選ぶこと
        2. 単調にならないよう、多様な絵文字を使用すること
        3. 返答は必ず `:emoji_name:` 形式のカスタム絵文字のリストとすること
        4. 通常の Unicode 絵文字 (例: 😊 👍) は使わないでください
        5. カスタム絵文字の名前は、後述する「利用可能なカスタム絵文字のカテゴリーと例」に示されている形式および名前の範囲から選んでください。
        6. カスタム絵文字は必ず一個だけ返してください

        利用可能なカスタム絵文字のカテゴリーと例:
        {chr(10).join(emoji_examples)}

        出力は以下のJSON形式で返してください：
        {{"reactions": ":emoji_name:"}}

        ノート: "{note_text}"
        """

    def _create_fallback_prompt(self, note_text: str) -> str:
        """Create prompt for fallback reaction generation."""
        return f"""
        以下のノートに対して、文脈に最も適したリアクション絵文字を1つだけ選んでください。

        ルール:
        1. ノートの感情、トーン、内容に合わせて最適な絵文字を選ぶこと
        2. 単調にならないよう、多様な絵文字を使用すること
        3. 「👍」は、他に適切な絵文字がない場合の最終手段としてのみ使用すること
        4. 単語やフレーズではなく、必ず1つの絵文字だけを返すこと

        推奨絵文字の例:
        - 楽しい内容: 😄 😊 🎉 🥳
        - 悲しい内容: 😢 😭 🥺 💔
        - 驚き: 😲 😮 😱 🤯
        - 質問/疑問: 🤔 ❓ 🧐
        - 怒り/不満: 😠 😡 👿
        - 愛/好意: ❤️ 💕 💖
        - 自然/食べ物: 🌸 🌈 🍜 🍣
        - 同意/支持: 👍 ✅ 💯
        - 応援: 📣 🙌 💪

        出力は以下のJSON形式で返してください：
        {{"reaction": "絵文字"}}

        ノート: "{note_text}"
        """

    def _create_categorization_prompt(
        self, emoji_list_text: str, allowed_categories: List[str]
    ) -> str:
        """Create prompt for emoji categorization."""
        from src.core.constants import EMOTION_CATEGORIES

        categories_str = ", ".join([f'"{cat}"' for cat in allowed_categories])
        return f"""Misskeyのカスタム絵文字再分類タスク:
        - 各絵文字には元のカテゴリが設定されていますが、これらを以下の「許可されたカテゴリ」のいずれかに再分類してください。
        - 【重要】絶対に許可されたカテゴリのみを使用し、新しいカテゴリは作成しないでください。
        - 絵文字は必ず以下のカテゴリのいずれかに分類してください。該当するカテゴリがない場合は「other」に分類してください。

        許可されたカテゴリ一覧:
        {categories_str}

        以下は各カテゴリに関連するキーワードです:
        {json.dumps(EMOTION_CATEGORIES, ensure_ascii=False, indent=2)}

        結果は必ず以下のJSON形式で返してください（使用するカテゴリキーは上記の許可されたカテゴリのみ）:
        {{
            "categories": [
                {{"category_name": "happy", "emoji_names": ["emoji_name1", "emoji_name2"]}},
                {{"category_name": "sad", "emoji_names": ["emoji_name3"]}},
                ...
            ]
        }}

        絵文字一覧:
        {emoji_list_text}
        """
