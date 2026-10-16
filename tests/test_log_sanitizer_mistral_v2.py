"""The 2026-09 Mistral key shape (prefix_<32>_<suffix>) must be redacted whole."""
from ptab_mcp.shared.log_sanitizer import LogSanitizer

FAKE = "mstrx_Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1W_Xy12Zq"  # synthetic, not a real key


def test_new_shape_is_redacted_whole() -> None:
    out = LogSanitizer.sanitize_string(f"mistral auth failed for key {FAKE}")
    assert FAKE not in out
    assert "mstrx_" not in out and "_Xy12Zq" not in out
