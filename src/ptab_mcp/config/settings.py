"""Settings configuration for PTAB MCP using pydantic-settings."""

from pydantic import ConfigDict
from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    """PTAB MCP configuration settings.

    Loads configuration from environment variables with PTAB_MCP_ prefix.
    Falls back to secure storage or .env file for API keys.
    """

    model_config = ConfigDict(
        env_prefix="",  # No prefix - read from .env directly
        case_sensitive=False,
        env_file=".env",
        extra="ignore"  # Ignore extra fields like PROXY_PORT
    )

    # API Keys (loaded from secure storage or env)
    # These are Optional because they can be loaded from DPAPI secure storage
    # instead of environment variables (see shared_secure_storage.py)
    uspto_api_key: Optional[str] = None
    mistral_api_key: Optional[str] = None

    # API Configuration
    api_base_url: str = "https://api.uspto.gov/api/v1/patent"
    api_timeout: int = 30
    download_timeout: int = 60
    max_retries: int = 3

    # Proxy Configuration
    ptab_proxy_port: int = 8083
    centralized_proxy_port: Optional[str] = "none"
    enable_always_on_proxy: bool = True

    # Internal Auth (for centralized proxy)
    internal_auth_secret: Optional[str] = None

    # Logging
    log_level: str = "INFO"
    structured_logging: bool = True

    # Field Configuration
    field_config_path: Optional[Path] = None
