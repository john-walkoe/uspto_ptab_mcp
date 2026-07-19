"""Component initialization tests for PTAB MCP.

Run this script to verify Phase 0 infrastructure setup is complete:
    uv run python test_server.py
"""


def test_import_modules():
    """Test that all modules can be imported."""
    from ptab_mcp.config.settings import Settings
    from ptab_mcp.shared.circuit_breaker import CircuitBreaker
    from ptab_mcp.shared.error_utils import format_error_response
    from ptab_mcp.config import api_constants
    print("[OK] All modules imported successfully")


def test_settings_initialization():
    """Test that settings can be loaded."""
    import os
    # Note: Settings has env_prefix="" so env var is "USPTO_API_KEY" not "PTAB_MCP_USPTO_API_KEY"
    os.environ["USPTO_API_KEY"] = "test_key_123"

    from ptab_mcp.config.settings import Settings
    settings = Settings()
    assert settings.uspto_api_key == "test_key_123"
    assert settings.api_base_url == "https://api.uspto.gov/api/v1/patent"
    print("[OK] Settings initialized successfully")


def test_circuit_breaker():
    """Test circuit breaker instantiation."""
    from ptab_mcp.shared.circuit_breaker import CircuitBreaker, CircuitState
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60, name="Test")
    assert cb.state == CircuitState.CLOSED
    print("[OK] Circuit breaker initialized successfully")


if __name__ == "__main__":
    test_import_modules()
    test_settings_initialization()
    test_circuit_breaker()
    print("\n[SUCCESS] All component tests passed!")
    print("\nPhase 0 infrastructure setup complete!")
    print("Ready to launch api-client-agent for Phase 1.")
