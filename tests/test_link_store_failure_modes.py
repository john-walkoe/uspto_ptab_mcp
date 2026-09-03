"""A key we cannot read is not a key we may replace.

`_get_file_based_key` used to regenerate the Fernet key whenever the existing
one could not be read (permissions changed, container UID mismatch — a
documented hazard in this fleet). Every row in `download_links` then failed its
decrypt, and `resolve_persistent_link` DELETED each one as it failed. The user
saw "link not found or expired" for links that worked a minute earlier, and the
rows were gone. The write-failure path had the same shape one restart later: it
returned an in-memory-only key, so links minted that process lifetime died
silently.

Separately, every failure mode of `resolve_persistent_link` collapsed into the
same `None`, so a disk-full or locked database was reported to the user as an
expired link with advice ("generate a new one") that fails identically.
"""

import os
import sqlite3
from unittest.mock import patch

import pytest

from ptab_mcp.proxy.secure_link_cache import LinkStoreUnavailable, SecureLinkCache


def _cache(tmp_path):
    return SecureLinkCache(db_path=str(tmp_path / "links.db"))


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PTAB_DATA_DIR", str(tmp_path))
    return tmp_path


class TestKeyHandling:
    def test_an_unreadable_key_file_raises_instead_of_re_keying(self, cache_dir, tmp_path):
        cache = _cache(tmp_path)
        key_file = cache_dir / ".ptab_proxy_encryption_key"
        key_file.write_bytes(cache.encryption_key)
        os.chmod(key_file, 0o000)

        try:
            with pytest.raises(OSError):
                cache._get_file_based_key(key_file)
        finally:
            os.chmod(key_file, 0o600)

    def test_a_readable_key_file_is_returned_unchanged(self, cache_dir, tmp_path):
        cache = _cache(tmp_path)
        key_file = cache_dir / ".ptab_proxy_key2"
        key_file.write_bytes(b"an-existing-key")

        assert cache._get_file_based_key(key_file) == b"an-existing-key"

    def test_the_key_file_is_created_owner_only(self, cache_dir, tmp_path):
        cache = _cache(tmp_path)
        key_file = cache_dir / ".ptab_proxy_key3"

        cache._get_file_based_key(key_file)

        assert oct(key_file.stat().st_mode)[-3:] == "600"

    def test_an_unpersistable_key_disables_link_minting(self, cache_dir, tmp_path):
        """Returning an in-memory-only key mints links that 404 after the next
        restart. Refuse instead."""
        cache = _cache(tmp_path)
        key_file = cache_dir / "no-such-dir" / ".ptab_proxy_encryption_key"

        cache._get_file_based_key(key_file)

        assert cache._degraded is True
        with pytest.raises(LinkStoreUnavailable):
            cache.generate_persistent_link(
                identifier_type="trial",
                identifier="IPR2024-01353",
                document_id="170603095",
                file_download_uri="https://api.uspto.gov/x.pdf",
                enhanced_filename="x.pdf",
            )


class TestResolveFailureModes:
    def test_an_unreadable_store_is_not_reported_as_an_expired_link(self, tmp_path):
        cache = _cache(tmp_path)

        with patch("ptab_mcp.proxy.secure_link_cache.create_secure_connection",
                   side_effect=sqlite3.OperationalError("database is locked")):
            with pytest.raises(LinkStoreUnavailable):
                cache.resolve_persistent_link("0" * 24)

    def test_a_genuinely_absent_link_still_returns_none(self, tmp_path):
        cache = _cache(tmp_path)

        assert cache.resolve_persistent_link("0" * 24) is None


class TestKeySourcing:
    """On Linux the file key is written in PLAINTEXT beside the database it
    encrypts, so "encrypted at rest" there means encrypted with a key stored
    next to the ciphertext (PT-11)."""

    def test_a_mounted_secret_wins(self, cache_dir, tmp_path, monkeypatch):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("PTAB_LINK_ENCRYPTION_KEY", key)

        cache = SecureLinkCache(db_path=str(tmp_path / "l.db"))

        assert cache.encryption_key == key.encode()

    def test_the_key_is_derived_from_the_jwt_secret_when_no_file_exists(
            self, cache_dir, tmp_path, monkeypatch):
        monkeypatch.delenv("PTAB_LINK_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("PTAB_AUTH_JWT_SECRET", "x" * 40)

        first = SecureLinkCache(db_path=str(tmp_path / "a.db")).encryption_key
        second = SecureLinkCache(db_path=str(tmp_path / "b.db")).encryption_key

        # Deterministic across instances (so replicas agree) and no key file
        # was written beside the ciphertext.
        assert first == second
        assert not (cache_dir / ".ptab_proxy_encryption_key").exists()

    def test_a_different_secret_derives_a_different_key(
            self, cache_dir, tmp_path, monkeypatch):
        monkeypatch.delenv("PTAB_LINK_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("PTAB_AUTH_JWT_SECRET", "x" * 40)
        first = SecureLinkCache(db_path=str(tmp_path / "a.db")).encryption_key
        monkeypatch.setenv("PTAB_AUTH_JWT_SECRET", "y" * 40)
        second = SecureLinkCache(db_path=str(tmp_path / "b.db")).encryption_key

        assert first != second

    def test_an_existing_key_file_is_never_superseded(
            self, cache_dir, tmp_path, monkeypatch):
        """Adopting a derived key would fail every outstanding link's decrypt,
        and this class DELETES a row whose token will not decrypt."""

        monkeypatch.delenv("PTAB_LINK_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("PTAB_AUTH_JWT_SECRET", raising=False)
        existing = SecureLinkCache(db_path=str(tmp_path / "a.db")).encryption_key
        assert (cache_dir / ".ptab_proxy_encryption_key").exists()

        monkeypatch.setenv("PTAB_AUTH_JWT_SECRET", "x" * 40)

        assert SecureLinkCache(db_path=str(tmp_path / "b.db")).encryption_key == existing


class TestLinkTtl:
    def test_the_default_is_seven_days(self, cache_dir, tmp_path, monkeypatch):
        monkeypatch.delenv("PTAB_LINK_TTL_DAYS", raising=False)

        assert SecureLinkCache(db_path=str(tmp_path / "l.db")).cache_duration.days == 7

    def test_the_ttl_is_configurable(self, cache_dir, tmp_path, monkeypatch):
        """A persistent link is an unrevocable capability delegating the
        server's ODP key for one document; its life is the only lever bounding
        the exposure, and an OAuth deployment should shorten it (PT-15)."""
        monkeypatch.setenv("PTAB_LINK_TTL_DAYS", "1")

        assert SecureLinkCache(db_path=str(tmp_path / "l.db")).cache_duration.days == 1

    def test_a_garbage_ttl_falls_back(self, cache_dir, tmp_path, monkeypatch):
        monkeypatch.setenv("PTAB_LINK_TTL_DAYS", "a week")

        assert SecureLinkCache(db_path=str(tmp_path / "l.db")).cache_duration.days == 7
