"""Persistent-link lifetime: one day by default, PFW's shape (TTL days + max uses).

- PTAB_LINK_TTL_DAYS (default 1, as PFW_LINK_TTL_DAYS) never resolves below
  1 day, so a link the tool hands out lives a day whatever the env says.
- PTAB_LINK_MAX_USES (default 25, PFW's PFW_LINK_MAX_USES default; 0 or
  below disables) bounds a leaked hash on a second axis.
- The served text (tool note, 404 detail, both downloads pages) is built
  from those settings, never a hard-coded "7 days".

Temp-file SQLite only; no network.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from ptab_mcp.proxy import secure_link_cache as slc
from ptab_mcp.proxy.secure_link_cache import SecureLinkCache

_DOC = dict(identifier_type="trial", identifier="IPR2024-01353", document_id="170603095",
            file_download_uri="https://api.uspto.gov/x.pdf", enhanced_filename="x.pdf")


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("PTAB_DATA_DIR", str(tmp_path / "data"))
    for name in ("PTAB_LINK_ENCRYPTION_KEY",
                 "PTAB_AUTH_JWT_SECRET", "PTAB_LINK_TTL_DAYS", "PTAB_LINK_MAX_USES"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _hash(url):
    return url.rsplit("/", 1)[-1]


class TestSettings:
    def test_defaults(self, data_dir):
        cache = SecureLinkCache(db_path=str(data_dir / "l.db"))

        assert cache.cache_duration == timedelta(days=1)
        assert cache.max_uses == 25
        assert slc.link_lifetime_text() == "1 day, up to 25 downloads"

    @pytest.mark.parametrize("raw", ["0", "-3"])
    def test_the_ttl_never_drops_below_one_day(self, data_dir, monkeypatch, raw):
        monkeypatch.setenv("PTAB_LINK_TTL_DAYS", raw)

        assert SecureLinkCache(db_path=str(data_dir / "l.db")).cache_duration == timedelta(days=1)

    def test_max_uses_is_configurable(self, data_dir, monkeypatch):
        monkeypatch.setenv("PTAB_LINK_MAX_USES", "3")

        assert SecureLinkCache(db_path=str(data_dir / "l.db")).max_uses == 3

    def test_a_garbage_max_uses_falls_back(self, data_dir, monkeypatch):
        monkeypatch.setenv("PTAB_LINK_MAX_USES", "lots")

        assert SecureLinkCache(db_path=str(data_dir / "l.db")).max_uses == 25

    def test_lifetime_text(self):
        assert slc.link_lifetime_text(7, 25) == "7 days, up to 25 downloads"
        assert slc.link_lifetime_text(1, 1) == "1 day, up to 1 download"
        assert slc.link_lifetime_text(2, 0) == "2 days"


class TestUseCeilingLocal:
    def test_the_link_works_max_uses_times_then_is_removed(self, data_dir):
        cache = SecureLinkCache(db_path=str(data_dir / "l.db"), max_uses=2)
        link_hash = _hash(cache.generate_persistent_link(**_DOC))

        assert cache.resolve_persistent_link(link_hash)["access_count"] == 1
        assert cache.resolve_persistent_link(link_hash)["access_count"] == 2
        assert cache.resolve_persistent_link(link_hash) is None
        # Removed, so raising the ceiling later does not revive it.
        assert SecureLinkCache(db_path=str(data_dir / "l.db"), max_uses=0) \
            .resolve_persistent_link(link_hash) is None

    def test_zero_disables_the_ceiling(self, data_dir):
        cache = SecureLinkCache(db_path=str(data_dir / "l.db"), max_uses=0)
        link_hash = _hash(cache.generate_persistent_link(**_DOC))

        for _ in range(30):
            assert cache.resolve_persistent_link(link_hash) is not None


class TestUseCeilingUnderConcurrency:
    """FPD audit S5 / PFW L20 / July L21: the ceiling was read, compared and
    incremented separately, so parallel downloads could all pass it."""

    def test_parallel_local_resolves_never_pass_the_ceiling(self, data_dir):
        from concurrent.futures import ThreadPoolExecutor

        cache = SecureLinkCache(db_path=str(data_dir / "l.db"), max_uses=25)
        link_hash = _hash(cache.generate_persistent_link(**_DOC))

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: cache.resolve_persistent_link(link_hash), range(30)))

        served = [r for r in results if r is not None]
        assert len(served) == 25
        assert sorted(r["access_count"] for r in served) == list(range(1, 26))

    async def test_parallel_async_resolves_never_pass_the_ceiling(self, data_dir):
        import asyncio

        cache = SecureLinkCache(db_path=str(data_dir / "l.db"), max_uses=25)
        link_hash = _hash(await cache.mint_persistent_link(**_DOC))

        results = await asyncio.gather(
            *(cache.resolve_persistent_link_async(link_hash) for _ in range(30)))

        assert sum(r is not None for r in results) == 25


class TestServedText:
    async def test_the_404_states_the_configured_lifetime(self, data_dir, monkeypatch):
        import httpx
        from httpx import ASGITransport

        from ptab_mcp.proxy.server import create_proxy_app

        monkeypatch.setenv("PTAB_LINK_TTL_DAYS", "2")
        monkeypatch.setenv("PTAB_LINK_MAX_USES", "10")
        app = create_proxy_app(api_key="test_key_12345", port=8083)
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://test") as client:
            response = await client.get("/download/persistent/" + "0" * 24)

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "2 days, up to 10 downloads" in detail
        assert "7 days" not in detail

    async def test_the_local_note_states_the_cache_lifetime(self, data_dir, monkeypatch):
        from ptab_mcp.tools import documents as doc_tools

        cache = SecureLinkCache(db_path=str(data_dir / "l.db"), cache_duration_days=3,
                                max_uses=5)

        async def _no_centralized(**kwargs):
            return None

        async def _proxy_up(port):
            return True

        monkeypatch.setattr(doc_tools, "register_with_centralized_proxy", _no_centralized)
        monkeypatch.setattr(doc_tools, "_ensure_local_proxy_running", _proxy_up)
        monkeypatch.setattr(doc_tools, "settings",
                            SimpleNamespace(uspto_api_key="k", internal_auth_secret="s"))
        monkeypatch.setattr(slc, "get_link_cache", lambda: cache)

        url, mode, note, _ = await doc_tools._resolve_download_delivery(
            identifier="IPR2024-01353", identifier_type="trial", document_id="170603095",
            download_url="https://api.uspto.gov/x.pdf", patent_number=None,
            application_number=None, enhanced_filename="x.pdf")

        assert mode == "local"
        assert "3 days, up to 5 downloads" in note
        assert cache.resolve_persistent_link(_hash(url)) is not None

    async def test_the_centralized_note_names_pfw_as_the_owner(self, monkeypatch):
        from ptab_mcp.tools import documents as doc_tools

        async def _centralized(**kwargs):
            return "https://pfw.example/document/persistent/abc"

        monkeypatch.setattr(doc_tools, "register_with_centralized_proxy", _centralized)
        monkeypatch.setattr(doc_tools, "settings",
                            SimpleNamespace(uspto_api_key="k", internal_auth_secret="s"))

        _, mode, note, _ = await doc_tools._resolve_download_delivery(
            identifier="IPR2024-01353", identifier_type="trial", document_id="170603095",
            download_url="https://api.uspto.gov/x.pdf", patent_number=None,
            application_number=None, enhanced_filename="x.pdf")

        assert mode == "centralized"
        assert "PFW_LINK_TTL_DAYS" in note
        assert "7 days" not in note

    async def test_the_downloads_pages_read_the_setting(self, data_dir, monkeypatch):
        import httpx
        from httpx import ASGITransport

        from ptab_mcp.proxy.server import create_proxy_app
        from ptab_mcp.ui.views import DOWNLOADS_HTML

        monkeypatch.setenv("PTAB_LINK_TTL_DAYS", "3")
        monkeypatch.setenv("PTAB_LINK_MAX_USES", "0")
        app = create_proxy_app(api_key="test_key_12345", port=8083)
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://test") as client:
            page = (await client.get("/downloads")).text
        panel = slc.render_link_lifetime(DOWNLOADS_HTML)

        for html in (page, panel):
            assert "Links stay valid for 3 days." in html
            assert slc.LINK_LIFETIME_PLACEHOLDER not in html

    def test_no_served_string_hard_codes_seven_days(self):
        from pathlib import Path

        root = Path(slc.__file__).resolve().parent.parent
        for rel in ("ui/views.py", "proxy/server.py", "tools/documents.py",
                    "config/tool_reflections.py",
                    "prompts/complete_trial_litigation_package.py"):
            text = (root / rel).read_text(encoding="utf-8")
            assert "valid for 7 days" not in text, rel
            assert "7-day" not in text, rel
