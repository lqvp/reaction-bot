#!/usr/bin/env python3
"""
Misskey Reaction Bot - Unified Entry Point
Supports both bot operation and emoji preprocessing
"""

import argparse
import asyncio

from src.bot import main as bot_main
from src.preprocess import main as preprocess_main


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(description="Misskey Reaction Bot")
    parser.add_argument(
        "--mode",
        choices=["bot", "preprocess"],
        default="bot",
        help="Operation mode: 'bot' for the reaction bot, 'preprocess' for emoji preprocessing",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    if args.mode == "bot":
        asyncio.run(bot_main())
    elif args.mode == "preprocess":
        asyncio.run(preprocess_main())


if __name__ == "__main__":
    main()
