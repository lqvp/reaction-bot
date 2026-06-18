"""Configuration management for Misskey Reaction Bot."""

import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, computed_field

# Load environment variables
load_dotenv("config/.env")


class MisskeyConfig(BaseModel):
    """Misskey API configuration."""

    http_host: str = Field(default_factory=lambda: os.getenv("MISSKEY_HTTP_HOST", ""))
    ws_host: str = Field(default_factory=lambda: os.getenv("MISSKEY_WS_HOST", ""))
    token: str = Field(default_factory=lambda: os.getenv("MISSKEY_TOKEN", ""))
    api_secure: bool = Field(
        default_factory=lambda: os.getenv("API_SECURE", "true").lower()
        in ["true", "1", "yes"]
    )
    ws_secure: bool = Field(
        default_factory=lambda: os.getenv("WS_SECURE", "true").lower()
        in ["true", "1", "yes"]
    )
    http_user_agent: str = Field(
        default_factory=lambda: os.getenv("HTTP_USER_AGENT", "MisskeyReactionBot/1.0")
    )

    @computed_field  # type: ignore[misc]
    @property
    def api_protocol(self) -> str:
        """Get API protocol (http or https)."""
        return "https" if self.api_secure else "http"

    @computed_field  # type: ignore[misc]
    @property
    def ws_protocol(self) -> str:
        """Get WebSocket protocol (ws or wss)."""
        return "wss" if self.ws_secure else "ws"

    @computed_field  # type: ignore[misc]
    @property
    def api_url(self) -> str:
        """Get full API URL."""
        return f"{self.api_protocol}://{self.http_host}/api"

    @computed_field  # type: ignore[misc]
    @property
    def ws_url(self) -> str:
        """Get full WebSocket URL."""
        return f"{self.ws_protocol}://{self.ws_host}/streaming?i={self.token}"


class LLMConfig(BaseModel):
    """LLM API configuration (OpenAI-compatible)."""

    api_key: str = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY", "")
    )
    base_url: str = Field(
        default_factory=lambda: os.getenv(
            "OPENAI_BASE_URL", "http://localhost:11434/v1"
        )
    )
    model: str = Field(default_factory=lambda: os.getenv("LLM_MODEL", "gemma3:1b"))


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()  # type: ignore
    )
    max_note_text_length: int = Field(
        default_factory=lambda: int(os.getenv("MAX_NOTE_TEXT_LENGTH", "50"))
    )


class ReactionConfig(BaseModel):
    """Reaction behavior configuration."""

    probability: float = Field(
        default_factory=lambda: float(os.getenv("REACTION_PROBABILITY", "1.0")),
        ge=0.0,
        le=1.0,
    )
    react_to_replies: bool = Field(
        default_factory=lambda: os.getenv("REACT_TO_REPLIES", "false").lower()
        in ["true", "1", "yes"]
    )
    react_to_followers: bool = Field(
        default_factory=lambda: os.getenv("REACT_TO_FOLLOWERS", "false").lower()
        in ["true", "1", "yes"]
    )


class RetryConfig(BaseModel):
    """Retry configuration."""

    max_retries: int = Field(default_factory=lambda: int(os.getenv("MAX_RETRIES", "3")))
    retry_delay: int = Field(default_factory=lambda: int(os.getenv("RETRY_DELAY", "2")))


class WebSocketConfig(BaseModel):
    """WebSocket reconnection configuration."""

    reconnect_delay_initial: int = Field(
        default_factory=lambda: int(os.getenv("WS_RECONNECT_DELAY_INITIAL", "5"))
    )
    reconnect_delay_max: int = Field(
        default_factory=lambda: int(os.getenv("WS_RECONNECT_DELAY_MAX", "60"))
    )
    reconnect_factor: float = Field(
        default_factory=lambda: float(os.getenv("WS_RECONNECT_FACTOR", "1.5"))
    )
    user_agent: str = Field(
        default_factory=lambda: os.getenv("WS_USER_AGENT", "MisskeyReactionBot/1.0")
    )


class StatsConfig(BaseModel):
    """Statistics configuration."""

    interval: int = Field(
        default_factory=lambda: int(os.getenv("STATS_INTERVAL", "3600"))
    )


class Config(BaseModel):
    """Main configuration container."""

    misskey: MisskeyConfig = Field(default_factory=MisskeyConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    reaction: ReactionConfig = Field(default_factory=ReactionConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    stats: StatsConfig = Field(default_factory=StatsConfig)

    def validate_required_fields(self) -> None:
        """Validate that all required fields are set."""
        errors = []

        if not self.misskey.http_host:
            errors.append("MISSKEY_HTTP_HOST is required")
        if not self.misskey.ws_host:
            errors.append("MISSKEY_WS_HOST is required")
        if not self.misskey.token:
            errors.append("MISSKEY_TOKEN is required")
        if not self.llm.api_key:
            errors.append("OPENAI_API_KEY is required")

        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")


# Global config instance
config = Config()
