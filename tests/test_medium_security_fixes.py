"""Regression tests for the Medium-severity audit fixes (M-1..M-7)."""

import os
import stat

import httpx
import pytest
from httpx import ASGITransport

from ptab_mcp.proxy.server import create_proxy_app, _get_proxy_token


# ---------------------------------------------------------------- M-5

def test_email_masking_actually_masks():
    from ptab_mcp.shared.log_sanitizer import LogSanitizer

    sanitizer = LogSanitizer()
    out = sanitizer.sanitize_string("login ok for jdoe@example.com via google")
    assert "jdoe@example.com" not in out
    assert "j***@example.com" in out


# ---------------------------------------------------------------- M-1

def test_sqlite_files_owner_only(tmp_path):
    from ptab_mcp.util.database import create_secure_connection

    db_path = str(tmp_path / "perm_test.db")
    conn = create_secure_connection(db_path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()
    # Reconnect so the chmod pass sees the file (and any sidecars)
    conn = create_secure_connection(db_path)
    conn.close()
    mode = stat.S_IMODE(os.stat(db_path).st_mode)
    assert mode == 0o600


# ---------------------------------------------------------------- M-2

@pytest.mark.asyncio
async def test_download_route_rejects_bad_identifier():
    app = create_proxy_app(api_key="test_key_12345", port=8083)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"X-Proxy-Token": _get_proxy_token()}
        # Quote-breakout attempt in identifier
        resp = await client.get(
            '/download/trial/IPR2024-01353%22%3B%20foo%3Dbar/170603095',
            headers=headers,
        )
        assert resp.status_code == 400

        # Bad identifier_type
        resp = await client.get(
            "/download/docket/IPR2024-01353/170603095", headers=headers
        )
        assert resp.status_code == 400

        # Bad document_id (shell/URL metacharacters in one path segment)
        resp = await client.get(
            "/download/trial/IPR2024-01353/doc%22id%3Bevil", headers=headers
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------- M-3

@pytest.mark.asyncio
async def test_request_size_limit_content_length():
    app = create_proxy_app(api_key="test_key_12345", port=8083)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/register-download",
            content=b"x",
            headers={
                "X-Proxy-Token": _get_proxy_token(),
                "Content-Length": str(10 * 1024 * 1024),
            },
        )
        assert resp.status_code == 413


@pytest.mark.asyncio
async def test_request_size_limit_streamed_body():
    """Chunked upload (no Content-Length) still hits the byte-count cap."""
    app = create_proxy_app(api_key="test_key_12345", port=8083)

    async def big_body():
        chunk = b"y" * 65536
        for _ in range(32):  # 2 MB total, over the 1 MB cap
            yield chunk

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/register-download",
            content=big_body(),
            headers={"X-Proxy-Token": _get_proxy_token()},
        )
        assert resp.status_code == 413


# ---------------------------------------------------------------- M-4

@pytest.mark.asyncio
async def test_ocr_rate_limit_is_per_caller(monkeypatch):
    from ptab_mcp.services.ocr_service import OCRService

    monkeypatch.setenv("MISTRAL_API_KEY", "not-a-real-key-but-long-enough-xyz")
    service = OCRService()
    # Exhaust tenant A's budget
    for _ in range(service.ocr_rate_limit):
        assert service._check_ocr_rate_limit("tenant-a") is True
    assert service._check_ocr_rate_limit("tenant-a") is False
    # Tenant B is unaffected (M-4: no shared global bucket)
    assert service._check_ocr_rate_limit("tenant-b") is True


# ---------------------------------------------------------------- M-7

def test_link_cache_uses_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PTAB_DATA_DIR", str(tmp_path / "data"))
    from ptab_mcp.proxy.secure_link_cache import SecureLinkCache

    cache = SecureLinkCache()
    assert str(tmp_path / "data") in cache.db_path
    dir_mode = stat.S_IMODE(os.stat(tmp_path / "data").st_mode)
    assert dir_mode == 0o700
    url = cache.generate_persistent_link(
        identifier_type="trial",
        identifier="IPR2024-01353",
        document_id="170603095",
        file_download_uri="https://developer.uspto.gov/ptab-files/x.pdf",
        enhanced_filename="PTAB-TEST.pdf",
    )
    link_hash = url.rsplit("/", 1)[-1]
    resolved = cache.resolve_persistent_link(link_hash)
    assert resolved["identifier"] == "IPR2024-01353"


def test_data_dir_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("PTAB_DATA_DIR", str(tmp_path / "newhome"))
    from ptab_mcp.config.storage_paths import migrate_data_file

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "some.db").write_bytes(b"payload")
    (legacy_dir / "some.db-wal").write_bytes(b"wal")

    target = migrate_data_file("some.db", legacy_dir)
    assert target.read_bytes() == b"payload"
    assert (target.parent / "some.db-wal").read_bytes() == b"wal"
    assert not (legacy_dir / "some.db").exists()


# ---------------------------------------------------------------- M-6

@pytest.mark.asyncio
async def test_admin_audit_log_records_actions(tmp_path):
    import aiosqlite
    from ptab_mcp.auth.store import McpUserStore

    db_path = tmp_path / "auth.db"
    store = McpUserStore(db_path)
    await store.record_admin_action(
        actor="admin@example.com", action="set_role",
        target="user@example.com", role="admin", success=True,
    )
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT actor, action, target, role, success FROM admin_audit_log"
        )
        rows = await cur.fetchall()
    assert rows == [("admin@example.com", "set_role", "user@example.com", "admin", 1)]
    # M-1: auth DB is owner-only
    assert stat.S_IMODE(os.stat(db_path).st_mode) == 0o600
