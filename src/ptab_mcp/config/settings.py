"""Settings configuration for PTAB MCP using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    """PTAB MCP configuration settings.

    Loads configuration from environment variables with PTAB_MCP_ prefix.
    Falls back to secure storage or .env file for API keys.
    """

    model_config = SettingsConfigDict(
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
    # NOTE (RF-3): request timeouts and retry counts are owned by PTABClient
    # via USPTO_TIMEOUT / USPTO_DOWNLOAD_TIMEOUT / USPTO_MAX_RETRIES — the
    # previous api_timeout/download_timeout/max_retries fields here were
    # never read anywhere, so operator changes to them were silently ignored.
    api_base_url: str = "https://api.uspto.gov/api/v1/patent"

    # Transport (HTTP mode). Stateless streamable HTTP: no server-side session
    # table, every request is self-contained. Required for clients that don't
    # replay mcp-session-id (GitHub Copilot) and for load-balanced/multi-replica
    # deploys. Stateful clients still work — they just get an ephemeral session
    # per request. Request-scoped features (ctx.report_progress) are unaffected.
    fastmcp_stateless_http: bool = True

    # Proxy Configuration
    ptab_proxy_port: int = 8083
    centralized_proxy_port: Optional[str] = "none"
    enable_always_on_proxy: bool = True

    # Externally reachable base URL of the PTAB proxy (Docker/reverse proxy).
    # Unset = http://localhost:{ptab_proxy_port}
    ptab_proxy_base_url: Optional[str] = None
    # Full base URL of the PFW centralized proxy; takes precedence over
    # centralized_proxy_port (e.g. http://pfw:8080 in Docker)
    centralized_proxy_url: Optional[str] = None

    # Internal Auth (for centralized proxy)
    internal_auth_secret: Optional[str] = None

    # Logging (content-minimization posture: flow metadata only, see
    # config/log_config.py). File logs are opt-in via PTAB_LOG_DIR.
    log_level: str = "INFO"
    structured_logging: bool = True
    ptab_log_dir: Optional[str] = None
    ptab_log_max_bytes: int = 10 * 1024 * 1024
    ptab_log_backup_count: int = 5

    # Field Configuration
    field_config_path: Optional[Path] = None
