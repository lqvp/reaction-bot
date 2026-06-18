"""Logging configuration for Misskey Reaction Bot."""

import logging
import sys
from typing import Any, Dict, Optional

from src.core.config import config


# Custom log level
SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")


class CustomLogger(logging.Logger):
    """Custom logger with success method."""

    def success(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Log a success message.

        Args:
            message: The message to log
            *args: Positional arguments for message formatting
            **kwargs: Keyword arguments for logging
        """
        if self.isEnabledFor(SUCCESS_LEVEL):
            self._log(SUCCESS_LEVEL, message, args, **kwargs)


# Set the custom logger class
logging.setLoggerClass(CustomLogger)


class NameSimplifyingFilter(logging.Filter):
    """A logging filter to simplify logger names."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Simplify the logger name in the log record.

        Args:
            record: The log record to be processed.

        Returns:
            Always True to process the record.
        """
        record.name = record.name.split(".")[-1]
        if record.name == "__main__":
            record.name = "main"
        return True


class ColoredFormatter(logging.Formatter):
    """Custom formatter with color support and symbols for console output."""

    # Configuration for different log levels
    LEVEL_CONFIG: Dict[str, Dict[str, str]] = {
        "DEBUG": {"color": "\033[36m", "symbol": "⚙️"},  # Cyan
        "INFO": {"color": "\033[32m", "symbol": "ℹ️"},  # Green
        "SUCCESS": {"color": "\033[92m", "symbol": "✅"},  # Bright Green
        "WARNING": {"color": "\033[33m", "symbol": "⚠️"},  # Yellow
        "ERROR": {"color": "\033[31m", "symbol": "❌"},  # Red
        "CRITICAL": {"color": "\033[35m", "symbol": "🔥"},  # Magenta
    }
    RESET_COLOR = "\033[0m"
    DEFAULT_SYMBOL = "•"

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        enable_colors: bool = True,
        compact_names: bool = True,
    ) -> None:
        """Initialize the colored formatter.

        Args:
            fmt: Format string
            datefmt: Date format string
            enable_colors: Whether to enable color output
            compact_names: Whether to remove padding from logger names
        """
        super().__init__(fmt, datefmt)
        self.enable_colors = enable_colors
        self.compact_names = compact_names

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors and symbols.

        Args:
            record: The log record to format

        Returns:
            Formatted log message
        """
        level_config = self.LEVEL_CONFIG.get(record.levelname, {})

        # Add symbol to the record
        record.symbol = level_config.get("symbol", self.DEFAULT_SYMBOL)

        # Format the message
        log_message = super().format(record)

        # Remove extra spaces from logger name if compact_names is enabled
        if self.compact_names:
            # This regex removes extra spaces between the logger name brackets
            import re

            log_message = re.sub(r"\[([^\]]+)\s+\]", r"[\1]", log_message)

        # Apply color if enabled and output is a terminal
        if self.enable_colors and sys.stdout.isatty():
            color = level_config.get("color", "")
            return f"{color}{log_message}{self.RESET_COLOR}"

        return log_message


def _get_log_level(level_name: str) -> int:
    """Get numeric log level from string name.

    Args:
        level_name: Name of the log level

    Returns:
        Numeric log level

    Raises:
        ValueError: If the log level is invalid
    """
    level_name = level_name.upper()

    # Handle custom level
    if level_name == "SUCCESS":
        return SUCCESS_LEVEL

    # Get standard levels
    numeric_level = getattr(logging, level_name, None)
    if numeric_level is None:
        raise ValueError(f"Invalid log level: {level_name}")

    return numeric_level


def _create_console_handler(
    log_level: int, formatter: logging.Formatter
) -> logging.StreamHandler:
    """Create and configure console handler.

    Args:
        log_level: Numeric log level
        formatter: Log formatter

    Returns:
        Configured console handler
    """
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(NameSimplifyingFilter())
    return console_handler


def _configure_third_party_loggers() -> None:
    """Configure log levels for third-party libraries."""
    third_party_loggers = {
        "websockets": logging.WARNING,
        "aiohttp": logging.WARNING,
        "httpx": logging.WARNING,
    }

    for logger_name, level in third_party_loggers.items():
        logging.getLogger(logger_name).setLevel(level)


def setup_logging(enable_colors: bool = True, compact_names: bool = True) -> None:
    """Set up logging configuration for the application.

    Args:
        enable_colors: Whether to enable colored output
        compact_names: Whether to remove padding from logger names

    Raises:
        ValueError: If the configured log level is invalid
    """
    try:
        # Get and validate log level
        log_level_name = config.logging.level
        log_level = _get_log_level(log_level_name)
    except (AttributeError, ValueError) as e:
        # Fallback to INFO if configuration is invalid
        log_level = logging.INFO
        log_level_name = "INFO"
        print(
            f"Warning: Invalid log level configuration, using INFO: {e}",
            file=sys.stderr,
        )

    # Create formatter
    formatter = ColoredFormatter(
        fmt="%(symbol)s %(asctime)s [%(name)s] %(message)s",  # Removed padding
        datefmt="%Y-%m-%d %H:%M:%S",
        enable_colors=enable_colors,
        compact_names=compact_names,
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add console handler
    console_handler = _create_console_handler(log_level, formatter)
    root_logger.addHandler(console_handler)

    # Configure third-party loggers
    _configure_third_party_loggers()

    # Log initialization message
    logger = get_logger(__name__)
    logger.info(f"Logging initialized at {log_level_name} level")


def get_logger(name: str) -> CustomLogger:
    """Get a logger instance with the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Custom logger instance with success method
    """
    return logging.getLogger(name)  # type: ignore[return-value]
