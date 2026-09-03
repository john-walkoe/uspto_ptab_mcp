"""Environment-backed settings for the OAuth authorization server.

PFW has no central pydantic Settings class (config is read from env at the
point of use), so the auth stack gets a small frozen dataclass mirroring the
attribute names the shared provider port expects (auth_*). All values come
from PTAB_AUTH_* environment variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthSettings:
    auth_mode: str = "none"  # "none" (today's behavior) | "oauth"
    auth_base_url: str = ""  # public https origin, e.g. https://mcp.example.com
    auth_jwt_secret: str = ""  # >=32 random chars; rotating invalidates all sessions
    auth_google_client_id: str = ""
    auth_google_client_secret: str = ""
    auth_ms_client_id: str = ""
    auth_ms_client_secret: str = ""
    auth_ms_tenant: str = "common"  # "common" | "organizations" | tenant GUID
    auth_internal_token: str = ""  # static bearer for headless clients (internal gateways)
    auth_internal_admin_token: str = ""  # static bearer granting ptab:admin too
    auth_register_url: str = ""  # "Request access" link on the Not-registered page
    auth_access_ttl: int = 3600
    auth_refresh_ttl: int = 2592000  # 30 d idle timeout
    auth_db_path: str = "data/mcp_auth.db"  # SQLite: users + OAuth AS state

    @classmethod
    def from_env(cls) -> "AuthSettings":
        return cls(
            auth_mode=os.getenv("PTAB_AUTH_MODE", "none"),
            auth_base_url=os.getenv("PTAB_AUTH_BASE_URL", ""),
            auth_jwt_secret=os.getenv("PTAB_AUTH_JWT_SECRET", ""),
            auth_google_client_id=os.getenv("PTAB_AUTH_GOOGLE_CLIENT_ID", ""),
            auth_google_client_secret=os.getenv("PTAB_AUTH_GOOGLE_CLIENT_SECRET", ""),
            auth_ms_client_id=os.getenv("PTAB_AUTH_MS_CLIENT_ID", ""),
            auth_ms_client_secret=os.getenv("PTAB_AUTH_MS_CLIENT_SECRET", ""),
            auth_ms_tenant=os.getenv("PTAB_AUTH_MS_TENANT", "common"),
            auth_internal_token=os.getenv("PTAB_AUTH_INTERNAL_TOKEN", ""),
            auth_internal_admin_token=os.getenv("PTAB_AUTH_INTERNAL_ADMIN_TOKEN", ""),
            auth_register_url=os.getenv("PTAB_AUTH_REGISTER_URL", ""),
            auth_access_ttl=int(os.getenv("PTAB_AUTH_ACCESS_TTL", "3600")),
            auth_refresh_ttl=int(os.getenv("PTAB_AUTH_REFRESH_TTL", "2592000")),
            auth_db_path=os.getenv("PTAB_AUTH_DB_PATH", "data/mcp_auth.db"),
        )
