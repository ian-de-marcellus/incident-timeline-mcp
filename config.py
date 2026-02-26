"""
Configuration management for incident-timeline-mcp.

Reads settings from a .env file using pydantic-settings.
See .env.example for available options.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    llm_enrichment: str = "none"  # "none" | "low" | "regular"


def get_settings() -> Settings:
    """Load settings from .env file (or environment variables)."""
    return Settings()
