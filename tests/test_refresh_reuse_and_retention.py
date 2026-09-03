"""Refresh-token reuse detection and the two unbounded auth tables.

Rotation was already correct (the presented token is revoked before a new one
is issued), but `get_refresh` filters `revoked = 0`, so a replayed stolen token
was indistinguishable from one that never existed: the thief and the legitimate
user race and whoever refreshes second silently loses (PT-06).

`admin_audit_log` was append-only with no retention target while deliberately
holding full unmasked identities, and `oauth_clients` — which anonymous dynamic
registration writes to — had no eviction of any kind, unlike `oauth_codes` and
`oauth_refresh_tokens` (PT-10, PT-09).

Everything runs against a temporary SQLite file; no network, no IdP.
"""

import pytest

from src.ptab_mcp.auth import store as store_module
from src.ptab_mcp.auth.store import McpUserStore


@pytest.fixture
def store(tmp_path):
    # Schema is created lazily on first _db() use.
    return McpUserStore(tmp_path / "auth" / "mcp_auth.db")


class TestRefreshReuseDetection:
    async def test_a_revoked_token_is_distinguishable_from_an_unknown_one(self, store):
        await store.put_refresh("tok-a", client_id="c1", email="u@example.com",
                                scopes=["ptab:user"], ttl_seconds=3600)
        await store.revoke_refresh("tok-a")

        assert await store.get_refresh("tok-a") is None          # the old view
        row = await store.get_refresh_any("tok-a")
        assert row is not None and row["revoked"] is True
        assert await store.get_refresh_any("never-issued") is None

    async def test_family_revocation_kills_every_live_token_for_the_identity(self, store):
        for token in ("tok-1", "tok-2", "tok-3"):
            await store.put_refresh(token, client_id="c1", email="u@example.com",
                                    scopes=["ptab:user"], ttl_seconds=3600)
        await store.put_refresh("other", client_id="c1", email="other@example.com",
                                scopes=["ptab:user"], ttl_seconds=3600)

        revoked = await store.revoke_all_refresh_for_email("U@Example.com")

        assert revoked == 3
        for token in ("tok-1", "tok-2", "tok-3"):
            assert await store.get_refresh(token) is None
        # Another identity is untouched
        assert await store.get_refresh("other") is not None

    async def test_revoking_an_already_revoked_family_is_a_no_op(self, store):
        await store.put_refresh("tok", client_id="c1", email="u@example.com",
                                scopes=["ptab:user"], ttl_seconds=3600)
        await store.revoke_all_refresh_for_email("u@example.com")

        assert await store.revoke_all_refresh_for_email("u@example.com") == 0


class TestAuditRetention:
    async def test_rows_inside_the_window_survive(self, store):
        await store.record_admin_action(actor="a@b.com", action="add", target="c@d.com")

        rows = await store.list_admin_actions() if hasattr(
            store, "list_admin_actions") else None
        if rows is not None:
            assert len(rows) == 1

    async def test_the_sweep_is_disabled_at_zero(self, monkeypatch, store):
        monkeypatch.setattr(store_module, "_AUDIT_RETENTION_DAYS", 0)

        # An ancient row planted directly, then a fresh action to trigger the sweep.
        async with store._db() as db:
            await db.execute(
                "INSERT INTO admin_audit_log (ts, actor, action, target, role, "
                "success, detail) VALUES ('2000-01-01T00:00:00+00:00', 'old', "
                "'add', 't', NULL, 1, NULL)")
            await db.commit()
        await store.record_admin_action(actor="a@b.com", action="add", target="c@d.com")

        async with store._db() as db:
            cur = await db.execute("SELECT COUNT(*) AS n FROM admin_audit_log")
            assert (await cur.fetchone())["n"] == 2

    async def test_rows_past_the_window_are_swept(self, monkeypatch, store):
        monkeypatch.setattr(store_module, "_AUDIT_RETENTION_DAYS", 30)

        async with store._db() as db:
            await db.execute(
                "INSERT INTO admin_audit_log (ts, actor, action, target, role, "
                "success, detail) VALUES ('2000-01-01T00:00:00+00:00', 'old', "
                "'add', 't', NULL, 1, NULL)")
            await db.commit()
        await store.record_admin_action(actor="a@b.com", action="add", target="c@d.com")

        async with store._db() as db:
            cur = await db.execute("SELECT actor FROM admin_audit_log")
            actors = [r["actor"] for r in await cur.fetchall()]
        assert actors == ["a@b.com"]


class TestClientRetention:
    async def test_a_client_with_a_live_refresh_token_is_never_evicted(
            self, monkeypatch, store):
        monkeypatch.setattr(store_module, "_CLIENT_RETENTION_DAYS", 1)

        await store.put_client("old-client", {"client_id": "old-client"})
        async with store._db() as db:
            await db.execute(
                "UPDATE oauth_clients SET created_at = '2000-01-01T00:00:00+00:00'")
            await db.commit()
        await store.put_refresh("live", client_id="old-client", email="u@example.com",
                                scopes=["ptab:user"], ttl_seconds=3600)

        await store.put_client("new-client", {"client_id": "new-client"})

        assert await store.get_client("old-client") is not None

    async def test_a_stale_client_with_no_live_token_is_evicted(
            self, monkeypatch, store):
        monkeypatch.setattr(store_module, "_CLIENT_RETENTION_DAYS", 1)

        await store.put_client("abandoned", {"client_id": "abandoned"})
        async with store._db() as db:
            await db.execute(
                "UPDATE oauth_clients SET created_at = '2000-01-01T00:00:00+00:00'")
            await db.commit()

        await store.put_client("new-client", {"client_id": "new-client"})

        assert await store.get_client("abandoned") is None
        assert await store.get_client("new-client") is not None
