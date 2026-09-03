"""Dispatch, validation and audit for ptab_manage_users.

`tests/test_user_management_gate.py` covers only the registration gate (does
the tool exist at all), so the list/add/set_role/activate/deactivate dispatch,
the audit path and the error path had no test. Nothing here touches a real
database or the network: the store is a stub recording the calls made against
it.
"""

import pytest

from src.ptab_mcp.tools import admin


class FakeStore:
    def __init__(self, users=None, set_active_result=True):
        self._users = list(users or [])
        self.set_active_result = set_active_result
        self.upserts = []
        self.set_actives = []
        self.audits = []

    async def upsert_user(self, email, role=None, display_name=None, notes=None,
                          active=None):
        self.upserts.append(
            {"email": email, "role": role, "display_name": display_name,
             "notes": notes, "active": active}
        )

    async def get_user(self, email):
        for u in self._users:
            if u["email"] == email:
                return u
        return None

    async def set_active(self, email, active):
        self.set_actives.append((email, active))
        return self.set_active_result

    async def list_users(self):
        return self._users

    async def record_admin_action(self, **kwargs):
        self.audits.append(kwargs)


def _row(email="a@b.com", role="user", active=True):
    return {"email": email, "display_name": None, "role": role, "active": active,
            "added_at": None, "last_login_at": None, "last_login_idp": None,
            "notes": None}


@pytest.fixture
def store(monkeypatch):
    s = FakeStore(users=[_row()])
    monkeypatch.setattr(admin, "_get_user_store", lambda: s)
    return s


class TestDispatch:
    async def test_list_returns_the_table_and_writes_no_audit_row(self, store):
        result = await admin.ptab_manage_users(action="list")

        assert result["action"] == "list"
        assert result["users"][0]["email"] == "a@b.com"
        assert store.audits == []

    async def test_add_upserts_and_audits(self, store):
        result = await admin.ptab_manage_users(
            action="add", email="New@Example.COM", role="admin", notes="n")

        assert store.upserts[0]["email"] == "new@example.com"  # normalized
        assert store.upserts[0]["role"] == "admin"
        assert store.audits[0]["success"] is True
        assert store.audits[0]["action"] == "add"
        assert "new@example.com" in result["message"]

    async def test_set_role_on_a_missing_user_fails_and_audits_the_failure(self, store):
        result = await admin.ptab_manage_users(
            action="set_role", email="nobody@example.com", role="admin")

        assert "no such user" in result["error"]
        assert store.audits[0]["success"] is False
        assert store.upserts == []

    async def test_set_role_preserves_the_active_flag(self, monkeypatch):
        s = FakeStore(users=[_row(active=False)])
        monkeypatch.setattr(admin, "_get_user_store", lambda: s)

        await admin.ptab_manage_users(action="set_role", email="a@b.com", role="admin")

        assert s.upserts[0]["active"] is False

    async def test_deactivate_calls_set_active_false(self, store):
        await admin.ptab_manage_users(action="deactivate", email="a@b.com")

        assert store.set_actives == [("a@b.com", False)]

    async def test_deactivating_a_missing_user_audits_the_failure(self, monkeypatch):
        s = FakeStore(users=[], set_active_result=False)
        monkeypatch.setattr(admin, "_get_user_store", lambda: s)

        result = await admin.ptab_manage_users(action="activate", email="a@b.com")

        assert "no such user" in result["error"]
        assert s.audits[0]["success"] is False


class TestValidation:
    async def test_an_unknown_action_is_rejected_before_the_store_is_touched(self, store):
        result = await admin.ptab_manage_users(action="drop_table", email="a@b.com")

        assert "action must be one of" in result["error"]
        assert store.upserts == [] and store.audits == []

    async def test_a_malformed_email_is_rejected(self, store):
        result = await admin.ptab_manage_users(action="add", email="not-an-email")

        assert "invalid email address" in result["error"]
        assert store.upserts == []

    async def test_an_unknown_role_is_rejected(self, store):
        result = await admin.ptab_manage_users(
            action="add", email="a@b.com", role="superuser")

        assert "role must be" in result["error"]
        assert store.upserts == []


class TestErrorPath:
    async def test_the_store_exception_text_does_not_reach_the_caller(self, monkeypatch):
        """An aiosqlite error carries the absolute path of the shared auth DB
        and a constraint violation carries column names."""
        class Boom(FakeStore):
            async def upsert_user(self, *a, **k):
                raise RuntimeError("unable to open database file /srv/secret/mcp_auth.db")

        s = Boom(users=[])
        monkeypatch.setattr(admin, "_get_user_store", lambda: s)

        result = await admin.ptab_manage_users(action="add", email="a@b.com")

        assert result["error"] == "User management failed: RuntimeError"
        assert "mcp_auth.db" not in result["error"]
        assert s.audits[0]["success"] is False


class TestStoreResolution:
    def test_the_provider_store_is_read_through_the_public_property(self, monkeypatch):
        """Reading `_users` off the provider breaks silently on a rename."""
        sentinel = object()

        class Provider:
            users = sentinel

        monkeypatch.setattr(admin, "_auth_provider", Provider())

        assert admin._get_user_store() is sentinel


class TestStaleAdminScope:
    """Access tokens are stateless JWTs with a 3600s TTL and no revocation, so
    the ptab:admin scope FastMCP checks was baked in at issue time.
    Deactivating a compromised admin did not revoke it for up to an hour, and
    inside that hour the identity could use THIS tool to re-activate itself in
    the shared table (PT-05)."""

    @pytest.fixture
    def oauth_mode(self, monkeypatch):
        monkeypatch.setattr(admin, "_auth_provider", object())
        monkeypatch.setattr(admin, "get_authenticated_identity",
                            lambda: "actor@example.com")

    async def test_a_deactivated_actor_cannot_reactivate_itself(
            self, monkeypatch, oauth_mode):
        s = FakeStore(users=[_row("actor@example.com", role="admin", active=False)])
        monkeypatch.setattr(admin, "_get_user_store", lambda: s)

        result = await admin.ptab_manage_users(
            action="activate", email="actor@example.com")

        assert "revoked" in result["error"]
        assert s.set_actives == []
        assert s.audits[0]["success"] is False

    async def test_a_demoted_actor_cannot_re_promote_itself(
            self, monkeypatch, oauth_mode):
        s = FakeStore(users=[_row("actor@example.com", role="user", active=True)])
        monkeypatch.setattr(admin, "_get_user_store", lambda: s)

        result = await admin.ptab_manage_users(
            action="set_role", email="actor@example.com", role="admin")

        assert "revoked" in result["error"]
        assert s.upserts == []

    async def test_a_still_valid_admin_is_unaffected(self, monkeypatch, oauth_mode):
        s = FakeStore(users=[_row("actor@example.com", role="admin", active=True)])
        monkeypatch.setattr(admin, "_get_user_store", lambda: s)

        result = await admin.ptab_manage_users(
            action="add", email="new@example.com", role="user")

        assert "error" not in result
        assert s.upserts[0]["email"] == "new@example.com"

    async def test_list_is_not_gated_by_the_live_read(self, monkeypatch, oauth_mode):
        s = FakeStore(users=[_row("actor@example.com", role="admin", active=False)])
        monkeypatch.setattr(admin, "_get_user_store", lambda: s)

        result = await admin.ptab_manage_users(action="list")

        assert "error" not in result

    async def test_outside_oauth_there_is_no_actor_to_re_read(self, monkeypatch):
        """stdio / plain HTTP: `actor` is the placeholder "local-process" and
        the tool is reached through the registration gate plus the transport
        secret, which scripts/manage_mcp_users.py also holds."""
        monkeypatch.setattr(admin, "_auth_provider", None)
        s = FakeStore(users=[])
        monkeypatch.setattr(admin, "_get_user_store", lambda: s)

        result = await admin.ptab_manage_users(action="add", email="new@example.com")

        assert "error" not in result
