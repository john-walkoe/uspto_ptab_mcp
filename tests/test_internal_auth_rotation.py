"""INTERNAL_AUTH_SECRET rotation overlap window and HKDF-derived service
tokens (PT-14: the secret has no key id and no rotation path, requiring a
synchronized four-service restart to rotate)."""

import base64
import hashlib
import hmac
import json

from ptab_mcp.shared.internal_auth import InternalAuthToken

_SECRET = "rotation-test-secret-value-aaaaaaaa"
_PREVIOUS = "rotation-test-secret-value-bbbbbbbb"


class TestMiddlewareGate:
    def test_split_secret_candidates_dedupes_strips_and_orders(self):
        from ptab_mcp.shared_secure_storage import split_secret_candidates

        assert split_secret_candidates("a, b ,a,,  ") == ["a", "b"]
        assert split_secret_candidates("solo") == ["solo"]
        assert split_secret_candidates(None) == []
        assert split_secret_candidates("") == []

    def test_the_gate_accepts_current_and_previous(self):
        from ptab_mcp.middleware import _matches_any_candidate

        candidates = ["current-value", "previous-value"]
        assert _matches_any_candidate("current-value", candidates) is True
        assert _matches_any_candidate("previous-value", candidates) is True

    def test_the_gate_rejects_a_value_not_in_the_rotation_window(self):
        from ptab_mcp.middleware import _matches_any_candidate

        candidates = ["current-value", "previous-value"]
        assert _matches_any_candidate("some-other-value", candidates) is False
        assert _matches_any_candidate(None, candidates) is False


class TestSecretRotation:
    def test_a_comma_separated_secret_is_current_then_previous(self):
        token = InternalAuthToken(f"{_SECRET},{_PREVIOUS}").create_token("fpd-mcp")

        assert InternalAuthToken(_SECRET).validate_token(token)[0] is True
        assert (
            InternalAuthToken(f"{_SECRET},{_PREVIOUS}").validate_token(token)[0]
            is True
        )
        # A verifier that only knows the previous root, alone, rejects a
        # token signed under the current one.
        assert InternalAuthToken(_PREVIOUS).validate_token(token)[0] is False

    def test_tokens_are_always_signed_with_the_current_secret(self):
        """The previous secret verifies; it must never sign."""
        token = InternalAuthToken(f"{_SECRET},{_PREVIOUS}").create_token("fpd-mcp")

        assert InternalAuthToken(_SECRET).validate_token(token)[0] is True
        assert InternalAuthToken(_PREVIOUS).validate_token(token)[0] is False


class TestServiceTokenKeyDerivation:
    def test_hkdf_derivation_is_deterministic_and_root_specific(self):
        from ptab_mcp.shared.internal_auth import _derive_service_token_key

        key_a = _derive_service_token_key(_SECRET)
        key_a_again = _derive_service_token_key(_SECRET)
        key_b = _derive_service_token_key(_PREVIOUS)

        assert key_a == key_a_again
        assert key_a != key_b
        assert len(key_a) == 32

    def test_key_id_round_trips_on_a_minted_token(self):
        from ptab_mcp.shared.internal_auth import _service_token_key_id

        token = InternalAuthToken(_SECRET).create_token("fpd-mcp")
        data = json.loads(base64.b64decode(token))

        assert data["key_id"] == _service_token_key_id(_SECRET)

    def test_a_token_verifies_under_a_previous_root_by_key_derivation(self):
        """New-style tokens (with key_id) verify against the HKDF-derived
        key for every candidate root, not just the current one."""
        token = InternalAuthToken(_PREVIOUS).create_token("fpd-mcp")

        verifier = InternalAuthToken(f"{_SECRET},{_PREVIOUS}")
        valid, payload = verifier.validate_token(token)

        assert valid is True
        assert payload["service"] == "fpd-mcp"

    def test_a_legacy_no_key_id_token_still_verifies(self):
        """A sibling still on an older vendored copy signs the raw root
        directly with no key_id. The verifier must accept it against every
        candidate root using the pre-HKDF scheme."""
        payload = {
            "service": "fpd-mcp",
            "client_ip": "127.0.0.1",
            "issued_at": 0,
            "expires_at": 2**31,
            "metadata": {},
        }
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        signature = hmac.new(
            _PREVIOUS.encode("utf-8"), payload_bytes, hashlib.sha256
        ).hexdigest()
        legacy_token = base64.b64encode(
            json.dumps({"payload": payload, "signature": signature}).encode("utf-8")
        ).decode("utf-8")

        verifier = InternalAuthToken(f"{_SECRET},{_PREVIOUS}")
        assert verifier.validate_token(legacy_token)[0] is True

    def test_a_legacy_token_signed_with_an_unknown_root_is_rejected(self):
        payload = {
            "service": "fpd-mcp",
            "client_ip": "127.0.0.1",
            "issued_at": 0,
            "expires_at": 2**31,
            "metadata": {},
        }
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        signature = hmac.new(
            b"some-unknown-root", payload_bytes, hashlib.sha256
        ).hexdigest()
        legacy_token = base64.b64encode(
            json.dumps({"payload": payload, "signature": signature}).encode("utf-8")
        ).decode("utf-8")

        verifier = InternalAuthToken(f"{_SECRET},{_PREVIOUS}")
        assert verifier.validate_token(legacy_token)[0] is False
