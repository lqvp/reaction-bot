#!/usr/bin/env python3
"""
Misskey Reaction Bot - Unified Entry Point
Supports both bot operation and emoji preprocessing
"""

import asyncio
import argparse
from src.bot import main
from src.preprocess_emojis import process_and_save_emojis


def parse_args():
    parser = argparse.ArgumentParser(description="Misskey Reaction Bot")
    parser.add_argument(
        "--mode",
        choices=["bot", "preprocess"],
        default="bot",
        help="Operation mode: 'bot' for the reaction bot, 'preprocess' for emoji preprocessing",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.mode == "bot":
        asyncio.run(main())
    elif args.mode == "preprocess":
        asyncio.run(process_and_save_emojis())
    else:
        print("Invalid mode. Use 'bot' or 'preprocess'.")
