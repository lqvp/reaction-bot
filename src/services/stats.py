"""Statistics service for tracking bot metrics and performance."""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Dict

from src.core.config import config

logger = logging.getLogger(__name__)


class StatsService:
    """Service for tracking and reporting bot statistics."""

    def __init__(self) -> None:
        """Initialize statistics service."""
        self.stats: Dict[str, int | float | defaultdict] = {
            "processed_notes": 0,
            "reactions_sent": 0,
            "skipped_notes": 0,
            "errors": 0,
            "ws_disconnect_count": 0,
            "llm_success_count": 0,
            "random_fallback_count": 0,
            "unicode_fallback_count": 0,
            "reaction_counts": defaultdict(int),
            "start_time_monotonic": time.monotonic(),
        }
        self._running = False
        self._stats_task = None

    async def start_periodic_logging(self) -> None:
        """Start the periodic statistics logging task."""
        if self._running:
            return
        self._running = True
        self._stats_task = asyncio.create_task(self._periodic_logger())
        logger.info(f"Started statistics logging (interval: {config.stats.interval}s)")

    async def stop_periodic_logging(self) -> None:
        """Stop the periodic statistics logging task."""
        self._running = False
        if self._stats_task:
            self._stats_task.cancel()
            try:
                await self._stats_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped statistics logging")

    def increment(self, metric: str, value: int = 1) -> None:
        """Increment a metric counter.

        Args:
            metric: Name of the metric to increment
            value: Amount to increment by (default: 1)
        """
        if metric in self.stats and isinstance(self.stats[metric], (int, float)):
            self.stats[metric] += value

    def increment_reaction(self, reaction: str) -> None:
        """Increment reaction count for a specific emoji.

        Args:
            reaction: The reaction emoji
        """
        self.stats["reaction_counts"][reaction] += 1

    def log_reaction(self, username: str, note_text: str, reaction: str) -> None:
        """Log a reaction event.

        Args:
            username: Username of the note author
            note_text: Text content of the note
            reaction: Reaction emoji applied
        """
        # Truncate text for logging
        max_length = config.logging.max_note_text_length
        short_text = (
            note_text[:max_length] + "..." if len(note_text) > max_length else note_text
        )
        short_text = short_text.replace("\n", " ")  # Remove newlines
        logger.info(f"REACTION: @{username}: {short_text} -> {reaction}")

    def get_stats_summary(self) -> str:
        """Get a formatted summary of current statistics.

        Returns:
            Formatted statistics string
        """
        current_time_monotonic = time.monotonic()
        elapsed_seconds = current_time_monotonic - self.stats["start_time_monotonic"]

        # Format uptime
        hours, remainder = divmod(elapsed_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"

        summary = [
            f"\n--- 統計情報 (稼働時間: {uptime_str}) ---",
            f"  処理ノート数: {self.stats['processed_notes']}",
            f"  リアクション送信数: {self.stats['reactions_sent']}",
            f"  スキップノート数: {self.stats['skipped_notes']}",
            f"  エラー発生数: {self.stats['errors']}",
            f"  WebSocket切断回数: {self.stats['ws_disconnect_count']}",
            "\n  リアクション絵文字別カウント:",
        ]

        # Reaction counts
        reaction_counts = self.stats["reaction_counts"]
        if reaction_counts:
            for emoji, count in sorted(reaction_counts.items()):
                summary.append(f"    - {emoji}: {count}")
        else:
            summary.append("    - (まだリアクションはありません)")

        # Reaction generation sources
        summary.extend(
            [
                "\n  リアクション生成ソース:",
                f"    - LLM API成功: {self.stats['llm_success_count']}",
                f"    - ランダム絵文字フォールバック: {self.stats['random_fallback_count']}",
                f"    - Unicode絵文字フォールバック: {self.stats['unicode_fallback_count']}",
            ]
        )

        # Average values
        if elapsed_seconds > 0:
            notes_per_hour = (self.stats["processed_notes"] / elapsed_seconds) * 3600
            reactions_per_hour = (self.stats["reactions_sent"] / elapsed_seconds) * 3600
            errors_per_hour = (self.stats["errors"] / elapsed_seconds) * 3600
            summary.extend(
                [
                    "\n  平均値 (1時間あたり):",
                    f"    - 平均処理ノート数: {notes_per_hour:.2f}",
                    f"    - 平均リアクション数: {reactions_per_hour:.2f}",
                    f"    - 平均エラー数: {errors_per_hour:.2f}",
                ]
            )

        summary.append("-----------------------------------")
        return "\n".join(summary)

    async def _periodic_logger(self) -> None:
        """Periodically log statistics summary."""
        while self._running:
            await asyncio.sleep(config.stats.interval)
            try:
                summary = self.get_stats_summary()
                logger.info(summary)
            except Exception as e:
                logger.error(
                    f"Error logging statistics: {e}",
                    exc_info=True,
                )
