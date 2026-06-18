"""Custom exceptions for Misskey Reaction Bot."""


class BotException(Exception):
    """Base exception for all bot-related errors."""

    pass


class ConfigurationError(BotException):
    """Raised when configuration is invalid or missing."""

    pass


class MisskeyAPIError(BotException):
    """Raised when Misskey API returns an error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMAPIError(BotException):
    """Raised when LLM API returns an error."""

    pass


class WebSocketError(BotException):
    """Raised when WebSocket connection fails."""

    pass


class EmojiDataError(BotException):
    """Raised when emoji data cannot be loaded or processed."""

    pass


class ReactionError(BotException):
    """Raised when reaction generation or application fails."""

    pass
