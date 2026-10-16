"""Tests for the shared response-size guard (shared/response_bounds.py) and
its attach point, the tools/__init__.py registration proxy.

The module itself is VENDORED byte-identically from uspto_fpd_mcp, so the
module-level tests below are FPD's, ported only by import path — if they
diverge, the vendored copy has drifted and should be re-copied rather than
patched. The registration-proxy tests are adapted to PTAB, whose tools return
JSON STRINGS rather than dicts.

Hermetic: no network, no FastMCP server. The registration-proxy tests drive a
stand-in `mcp` object that records what was registered.
"""

import json

import pytest

from src.ptab_mcp.shared.response_bounds import (
    BOUNDS_KEY,
    WINDOW_KEY,
    apply_text_window,
    bound_structured_response,
    bounds_config,
    content_char_budget,
    measure_chars,
    response_char_budget,
    window_text,
)

_BAG_PATH = ["records", "*", "documentBag"]


def _doc(i: int) -> dict:
    return {
        "documentIdentifier": f"DOC{i:04d}",
        "documentCode": "PET",
        "pageCount": 3,
        # The payload hog the guard is meant to shed.
        "downloadOptionBag": [
            {"mimeTypeIdentifier": "PDF", "downloadUrl": "https://api.uspto.gov/" + "x" * 200}
            for _ in range(3)
        ],
    }


def _payload(n_docs: int = 40) -> dict:
    return {"records": [{"id": "abc", "documentBag": [_doc(i) for i in range(n_docs)]}]}


def _spec(min_items: int = 10) -> dict:
    return {
        "path": _BAG_PATH,
        "keep_fields": ("documentIdentifier", "documentCode", "pageCount"),
        "min_items": min_items,
        "label": "documentBag",
    }


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

def test_env_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("USPTO_MAX_RESPONSE_CHARS", raising=False)
    monkeypatch.delenv("USPTO_MAX_CONTENT_CHARS", raising=False)
    monkeypatch.delenv("USPTO_RESPONSE_BOUNDS_ENABLED", raising=False)
    assert response_char_budget() == 40_000
    assert content_char_budget() == 120_000
    assert bounds_config()["enabled"] is True

    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "12345")
    monkeypatch.setenv("USPTO_MAX_CONTENT_CHARS", "9999")
    monkeypatch.setenv("USPTO_RESPONSE_BOUNDS_ENABLED", "false")
    config = bounds_config()
    assert config["max_response_chars"] == 12345
    assert config["max_content_chars"] == 9999
    assert config["enabled"] is False

    # Garbage and non-positive values fall back to the defaults rather than
    # disabling the guard by accident.
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "not-a-number")
    assert response_char_budget() == 40_000
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "0")
    assert response_char_budget() == 40_000


# ---------------------------------------------------------------------------
# Guard 1: structured responses
# ---------------------------------------------------------------------------

def test_no_op_is_identity_and_byte_equal():
    payload = _payload(2)
    before = json.dumps(payload, default=str)

    result = bound_structured_response(payload, bags=(_spec(),), limit=1_000_000)

    assert result is payload  # same object, not a copy
    assert json.dumps(result, default=str) == before
    assert BOUNDS_KEY not in result


def test_disabled_guard_is_identity_even_when_oversized(monkeypatch):
    monkeypatch.setenv("USPTO_RESPONSE_BOUNDS_ENABLED", "0")
    payload = _payload(40)
    before = json.dumps(payload, default=str)

    result = bound_structured_response(payload, bags=(_spec(),), limit=500)

    assert result is payload
    assert json.dumps(result, default=str) == before
    assert BOUNDS_KEY not in result


def test_stage_1_slims_heavy_fields_only():
    payload = _payload(20)
    limit = 4_000
    assert measure_chars(payload) > limit

    result = bound_structured_response(payload, bags=(_spec(),), limit=limit, note="recover me")

    bounds = result[BOUNDS_KEY]
    assert bounds["stages"] == ["slimmed"]  # halving was not needed
    assert bounds["slimmed_fields"] == ["downloadOptionBag"]
    assert bounds["items_returned"] == bounds["items_total"] == 20
    assert bounds["note"] == "recover me"
    assert measure_chars(result) <= limit
    docs = result["records"][0]["documentBag"]
    assert all("downloadOptionBag" not in d for d in docs)
    assert docs[0]["documentIdentifier"] == "DOC0000"


def test_stage_2_halves_down_to_the_floor():
    payload = _payload(400)
    limit = 2_000

    result = bound_structured_response(payload, bags=(_spec(min_items=10),), limit=limit)

    bounds = result[BOUNDS_KEY]
    assert bounds["stages"] == ["slimmed", "truncated"]
    assert bounds["items_total"] == 400
    assert bounds["items_returned"] >= 10  # floor respected
    assert bounds["items_returned"] < 400
    assert len(result["records"][0]["documentBag"]) == bounds["items_returned"]


def test_floor_is_respected_even_when_it_cannot_fit():
    """The floor wins over the budget: dropping below it would leave the
    caller with nothing useful. The marker still tells the truth."""
    payload = _payload(40)

    result = bound_structured_response(payload, bags=(_spec(min_items=30),), limit=1_000)

    assert result[BOUNDS_KEY]["items_returned"] == 30


def test_marker_vocabulary_is_exact():
    result = bound_structured_response(_payload(400), bags=(_spec(),), limit=2_000)

    assert set(result[BOUNDS_KEY]) == {
        "applied",
        "reason",
        "size_chars",
        "size_limit",
        "stages",
        "slimmed_fields",
        "items_returned",
        "items_total",
        "note",
    }
    assert result[BOUNDS_KEY]["applied"] is True
    assert result[BOUNDS_KEY]["reason"] == "size"
    assert result[BOUNDS_KEY]["size_limit"] == 2_000
    assert result[BOUNDS_KEY]["size_chars"] == measure_chars(result)


def test_legacy_aliases_are_mirrored():
    aliases = {
        "items_returned": "documents_returned",
        "items_total": "documents_total",
        "note": "documents_note",
    }
    result = bound_structured_response(
        _payload(400), bags=(_spec(),), limit=2_000, note="use PTAB_get_document_download", aliases=aliases
    )

    assert result["documents_total"] == 400
    assert result["documents_returned"] == result[BOUNDS_KEY]["items_returned"]
    assert result["documents_note"] == "use PTAB_get_document_download"


def test_text_fallback_truncates_the_largest_string_with_a_marker():
    payload = {"extracted_content": "z" * 50_000, "meta": "small"}

    result = bound_structured_response(payload, bags=(), limit=5_000, text_fallback=True)

    assert measure_chars(result) <= 5_000
    assert result[BOUNDS_KEY]["stages"] == ["truncated"]
    assert "extracted_content" in result[BOUNDS_KEY]["note"]
    assert len(result["extracted_content"]) < 50_000


def test_oversized_with_nothing_to_shed_is_still_marked():
    payload = {"extracted_content": "z" * 50_000}

    result = bound_structured_response(payload, bags=(), limit=5_000, text_fallback=False)

    # Nothing could be dropped, but the caller is told the client may reject it.
    assert result[BOUNDS_KEY]["applied"] is True
    assert result[BOUNDS_KEY]["stages"] == []


# ---------------------------------------------------------------------------
# Guard 2: text windows
# ---------------------------------------------------------------------------

_PAGES = "\n\n".join(f"=== PAGE {i} ===\n{'abcde ' * 100}" for i in range(1, 21))


def test_window_text_no_op_when_everything_fits():
    result = window_text("short text", max_chars=1_000)

    assert result == {"text": "short text"}
    assert WINDOW_KEY not in result


def test_window_text_char_unit():
    text = "y" * 10_000

    result = window_text(text, offset=0, max_chars=1_000, note="next")

    window = result[WINDOW_KEY]
    assert window["unit"] == "char"
    assert window["edges"] == "char"
    assert window["offset"] == 0
    assert window["returned"] == 1_000
    assert window["total"] == 10_000
    assert window["has_more"] is True
    assert window["next_offset"] == 1_000
    assert window["note"] == "next"
    assert result["text"] == text[:1_000]


def test_window_text_page_edges_snap_to_page_boundaries():
    result = window_text(_PAGES, offset=0, max_chars=2_000)

    window = result[WINDOW_KEY]
    # `edges` records the snapping; `unit` names the counters, which are
    # characters whether or not the edges snapped.
    assert window["edges"] == "page"
    assert window["unit"] == "char"
    assert window["returned"] <= 2_000
    # The window ends exactly where a page marker begins.
    assert _PAGES[window["next_offset"]:].startswith("=== PAGE ")
    assert result["text"].startswith("=== PAGE 1 ===")


def test_window_text_cursor_walks_the_whole_document():
    seen, offset, guard = [], 0, 0
    while True:
        guard += 1
        assert guard < 100
        result = window_text(_PAGES, offset=offset, max_chars=2_000)
        seen.append(result["text"])
        window = result.get(WINDOW_KEY)
        if not window or not window["has_more"]:
            break
        offset = window["next_offset"]

    # Pages are never split and nothing is lost.
    assert "".join(seen) == _PAGES


def test_window_text_offset_snaps_back_to_the_containing_page():
    first_page_len = _PAGES.index("=== PAGE 2 ===")

    result = window_text(_PAGES, offset=first_page_len - 5, max_chars=2_000)

    assert result[WINDOW_KEY]["offset"] == 0
    assert result["text"].startswith("=== PAGE 1 ===")


def test_window_text_single_oversized_page_degrades_to_char_edges():
    text = "=== PAGE 1 ===\n" + "q" * 5_000

    result = window_text(text, max_chars=1_000)

    assert result[WINDOW_KEY]["edges"] == "char"
    assert result[WINDOW_KEY]["unit"] == "char"
    assert result[WINDOW_KEY]["returned"] == 1_000


def test_window_unit_always_reports_characters():
    """The counters are characters in every case, and the label says so.

    `unit` used to read "page" whenever the edges snapped to page markers,
    directly above four character counters — a consumer that believed the
    label and divided by a page count got nonsense.
    """
    paged = window_text(_PAGES, offset=0, max_chars=2_000)[WINDOW_KEY]
    raw = window_text("y" * 10_000, max_chars=1_000)[WINDOW_KEY]

    assert paged["unit"] == raw["unit"] == "char"
    assert (paged["edges"], raw["edges"]) == ("page", "char")
    # And the counters really are characters, in both.
    assert paged["total"] == len(_PAGES)
    assert raw["returned"] == 1_000


def test_window_marker_vocabulary_is_exact():
    result = window_text("y" * 10_000, max_chars=1_000)

    assert set(result[WINDOW_KEY]) == {
        "unit",
        "edges",
        "offset",
        "returned",
        "total",
        "has_more",
        "next_offset",
        "note",
    }


def test_apply_text_window_attaches_markers_and_aliases():
    payload = {"extracted_content": "y" * 10_000}

    apply_text_window(
        payload,
        "extracted_content",
        max_chars=1_000,
        note="call again with char_offset",
        aliases={"applied": "truncated", "note": "truncation_note"},
    )

    assert payload[WINDOW_KEY]["has_more"] is True
    assert payload["truncated"] is True
    assert payload["truncation_note"] == "call again with char_offset"
    assert payload[BOUNDS_KEY]["reason"] == "window"


def test_apply_text_window_is_identity_when_it_fits():
    payload = {"extracted_content": "short"}
    before = json.dumps(payload)

    apply_text_window(payload, "extracted_content", max_chars=1_000)

    assert json.dumps(payload) == before
    assert WINDOW_KEY not in payload
    assert BOUNDS_KEY not in payload



# ---------------------------------------------------------------------------
# Attach point: the tools/__init__.py registration proxy
# ---------------------------------------------------------------------------

class _FakeMCP:
    """Records what a register() call would have registered."""

    def __init__(self):
        self.registered = {}

    def tool(self, *args, **kwargs):
        def decorator(fn):
            self.registered[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorator


async def test_registration_proxy_guards_json_string_returns():
    """PTAB tools return JSON STRINGS (json.dumps of the response dict), so the
    proxy has to parse, guard and re-serialize rather than guard a dict."""
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def big_tool(identifier: str, limit: int = 50):
        return json.dumps({
            "data_type": "trials",
            "results": [{"trialNumber": f"IPR2024-{i:05d}", "blob": "z" * 400}
                        for i in range(400)],
        })

    _BoundedRegistrar(fake).tool(name="PTAB_search_trials_minimal")(big_tool)
    registered = fake.registered["PTAB_search_trials_minimal"]

    # Signature is preserved, so FastMCP derives the same input schema.
    import inspect

    assert list(inspect.signature(registered).parameters) == ["identifier", "limit"]

    raw = await registered("IPR2024-01353")
    assert isinstance(raw, str)
    parsed = json.loads(raw)
    assert parsed[BOUNDS_KEY]["applied"] is True
    assert parsed[BOUNDS_KEY]["items_total"] == 400
    assert len(parsed["results"]) == parsed[BOUNDS_KEY]["items_returned"] < 400
    assert len(raw) <= response_char_budget()


async def test_registration_proxy_is_byte_transparent_for_small_responses():
    """A response that already fits comes back as the IDENTICAL string — no
    reparse, no reserialization, no `_bounds` key."""
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()
    payload = json.dumps({"data_type": "trials", "results": [], "count": 0}, indent=2)

    async def small_tool():
        return payload

    _BoundedRegistrar(fake).tool(name="PTAB_search_trials_minimal")(small_tool)

    result = await fake.registered["PTAB_search_trials_minimal"]()
    assert result == payload
    assert BOUNDS_KEY not in json.loads(result)


async def test_registration_proxy_passes_plain_strings_through():
    """PTAB_get_guidance returns markdown, not JSON — it must not be touched."""
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def guidance_tool(section: str = "overview"):
        return "# Markdown guidance\n\nnot JSON at all"

    _BoundedRegistrar(fake).tool(name="PTAB_get_guidance")(guidance_tool)

    assert await fake.registered["PTAB_get_guidance"]() == "# Markdown guidance\n\nnot JSON at all"


async def test_registration_proxy_guards_dict_returns_too():
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def dict_tool():
        return {"text": "z" * 200_000}

    _BoundedRegistrar(fake).tool(name="PTAB_get_document_download")(dict_tool)

    result = await fake.registered["PTAB_get_document_download"]()
    assert isinstance(result, dict)
    assert measure_chars(result) <= response_char_budget()
    assert result[BOUNDS_KEY]["applied"] is True


async def test_unlisted_tool_gets_the_default_budget_and_text_fallback():
    """Coverage is 100% without per-tool wiring: a tool with no _TOOL_BOUNDS
    entry still gets the response budget plus the largest-string fallback."""
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def unlisted():
        return json.dumps({"config_file": "field_configs.yaml", "blob": "y" * 200_000})

    _BoundedRegistrar(fake).tool(name="PTAB_get_field_configs")(unlisted)

    parsed = json.loads(await fake.registered["PTAB_get_field_configs"]())
    assert parsed[BOUNDS_KEY]["stages"] == ["truncated"]
    assert len(parsed["blob"]) < 200_000


async def test_content_tool_uses_the_higher_content_budget():
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()
    size = response_char_budget() + 20_000
    assert size < content_char_budget()

    async def content_tool():
        return json.dumps({"text": "z" * size})

    _BoundedRegistrar(fake).tool(name="PTAB_get_document_content")(content_tool)

    raw = await fake.registered["PTAB_get_document_content"]()
    # Comfortably over the RESPONSE budget but under the CONTENT budget, so
    # the guard leaves it alone.
    assert len(raw) > response_char_budget()
    assert BOUNDS_KEY not in json.loads(raw)


async def test_complete_tier_slims_heavy_bags_before_dropping_records():
    """The *_complete tiers use fields=['*'], which short-circuits tier
    filtering in config/field_manager.py, so whatever the record carries ships
    whole. documentOCRText is the first thing to go."""
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def complete_tool():
        return json.dumps({
            "data_type": "trials",
            "field_set": "trials_complete",
            "results": [
                {
                    "trialNumber": f"IPR2024-{i:05d}",
                    "documentBag": [
                        {
                            "documentIdentifier": f"1711{i}{j}",
                            "documentTitleText": "Final Written Decision",
                            "documentOCRText": "Final Written Decision. " * 40,
                        }
                        for j in range(12)
                    ],
                }
                for i in range(20)
            ],
        })

    _BoundedRegistrar(fake).tool(name="PTAB_search_trials_complete")(complete_tool)

    parsed = json.loads(await fake.registered["PTAB_search_trials_complete"]())
    bounds = parsed[BOUNDS_KEY]
    assert "slimmed" in bounds["stages"]
    assert "documentOCRText" in bounds["slimmed_fields"]
    for record in parsed["results"]:
        for doc in record["documentBag"]:
            assert "documentOCRText" not in doc
            assert "documentIdentifier" in doc


def test_registration_proxy_passes_other_attributes_through():
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()
    fake.custom_route = lambda *a, **k: "routed"

    assert _BoundedRegistrar(fake).custom_route() == "routed"


def test_every_registered_tool_name_is_covered():
    """Either an explicit _TOOL_BOUNDS entry or the default config — the point
    is that no tool escapes the guard."""
    from src.ptab_mcp.tools import _DEFAULT_BOUNDS, _TOOL_BOUNDS, _bound_result

    for name in list(_TOOL_BOUNDS) + ["PTAB_get_document_download", "ptab_manage_users"]:
        # A small payload is a no-op for every configuration.
        assert _bound_result({"ok": True}, name) == {"ok": True}
    assert _DEFAULT_BOUNDS["bags"] == ()


# ---------------------------------------------------------------------------
# Paging honesty: a trimmed page reports what it carries. Ported from FPD
# (eval tr-cost-02, 2026-09-11). FPD_Search_petitions_minimal(decision_type="DENIED", limit=100)
# went over the budget, the guard kept 50 rows, and `paging` still said
# returned 100 / next_offset 100, so a caller paging by next_offset skipped
# rows 50-99 without being told.
# ---------------------------------------------------------------------------

_PAGING_SPEC = {"key": "paging", "path": ["rows"]}


def _page(offset: int, n: int, total: int, blob: int = 400) -> dict:
    has_more = offset + n < total
    return {
        "rows": [{"i": offset + k, "blob": "z" * blob} for k in range(n)],
        "paging": {
            "limit_requested": n,
            "limit_applied": n,
            "offset": offset,
            "returned": n,
            "total": total,
            "has_more": has_more,
            "next_offset": offset + n if has_more else None,
        },
    }


def _rows_spec(floor: int = 5) -> dict:
    return {"path": ["rows"], "keep_fields": (), "min_items": floor, "label": "rows"}


def test_trimmed_page_reports_the_rows_it_carries():
    payload = _page(offset=0, n=100, total=7481)

    result = bound_structured_response(
        payload, bags=(_rows_spec(),), limit=20_000, paging=_PAGING_SPEC
    )

    kept = len(result["rows"])
    assert 5 <= kept < 100
    assert result[BOUNDS_KEY]["items_returned"] == kept
    assert result["paging"]["returned"] == kept
    assert result["paging"]["next_offset"] == kept
    assert result["paging"]["has_more"] is True
    assert result["paging"]["total"] == 7481  # the result set, untouched
    assert result["paging"]["offset"] == 0
    assert result["paging"]["limit_applied"] == 100  # what upstream was asked for


def test_trimmed_page_cursor_is_offset_plus_kept():
    payload = _page(offset=300, n=100, total=7481)

    result = bound_structured_response(
        payload, bags=(_rows_spec(),), limit=20_000, paging=_PAGING_SPEC
    )

    kept = len(result["rows"])
    assert result["rows"][0]["i"] == 300  # the head of the page is what stays
    assert result["paging"]["next_offset"] == 300 + kept


def test_trimmed_last_page_gets_a_cursor_back():
    """A last page has has_more false and no cursor. Once the guard drops some
    of its rows there IS more to fetch, so both have to come back."""
    payload = _page(offset=7400, n=81, total=7481)
    assert payload["paging"]["has_more"] is False
    assert payload["paging"]["next_offset"] is None

    result = bound_structured_response(
        payload, bags=(_rows_spec(),), limit=15_000, paging=_PAGING_SPEC
    )

    kept = len(result["rows"])
    assert kept < 81
    assert result["paging"]["has_more"] is True
    assert result["paging"]["next_offset"] == 7400 + kept


def test_paging_without_a_cursor_keeps_next_offset():
    """`cursor: False` is for a tool with no offset parameter to follow: the
    count and has_more are corrected, next_offset is not invented."""
    payload = _page(offset=0, n=100, total=0)
    payload["paging"].update({"total": None, "has_more": False, "next_offset": None})

    result = bound_structured_response(
        payload,
        bags=(_rows_spec(),),
        limit=20_000,
        paging={"key": "paging", "path": ["rows"], "cursor": False},
    )

    kept = len(result["rows"])
    assert result["paging"]["returned"] == kept < 100
    assert result["paging"]["has_more"] is True
    assert result["paging"]["next_offset"] is None


def test_paging_untouched_when_nothing_was_dropped():
    # Fits: identity, no marker, paging exactly as built.
    small = _page(offset=0, n=3, total=10)
    before = json.dumps(small)
    assert bound_structured_response(
        small, bags=(_rows_spec(),), limit=1_000_000, paging=_PAGING_SPEC
    ) is small
    assert json.dumps(small) == before

    # Over budget but shed by slimming alone: every row survives, so the
    # cursor was already right and must not move.
    slimmable = {
        "rows": [{"i": k, "heavy": "z" * 500} for k in range(20)],
        "paging": {"offset": 0, "returned": 20, "total": 40, "has_more": True, "next_offset": 20},
    }
    result = bound_structured_response(
        slimmable,
        bags=({"path": ["rows"], "keep_fields": ("i",), "min_items": 5, "label": "rows"},),
        limit=5_000,
        paging=_PAGING_SPEC,
    )
    assert result[BOUNDS_KEY]["stages"] == ["slimmed"]
    assert result["paging"] == {
        "offset": 0, "returned": 20, "total": 40, "has_more": True, "next_offset": 20,
    }


def test_paging_untouched_without_a_paging_spec():
    """Back-compat: a caller that passes no spec gets the old behaviour."""
    payload = _page(offset=0, n=100, total=7481)

    result = bound_structured_response(payload, bags=(_rows_spec(),), limit=20_000)

    assert len(result["rows"]) < 100
    assert result["paging"]["returned"] == 100
    assert result["paging"]["next_offset"] == 100



# ---------------------------------------------------------------------------
# Paging honesty through PTAB's registrar: the nine search tools
# ---------------------------------------------------------------------------

_SEARCH_TOOLS = [
    f"PTAB_search_{proceeding}_{tier}"
    for proceeding in ("trials", "appeals", "interferences")
    for tier in ("minimal", "balanced", "complete")
]


def _search_page(offset: int, limit: int, corpus: list, total: int) -> str:
    """A search response as util/search_runner.run_search returns it: a JSON
    string, `count` the API's TOTAL, `paging` built before the guard runs."""
    rows = corpus[offset:offset + limit]
    has_more = offset + len(rows) < total
    return json.dumps({
        "data_type": "trials",
        "count": total,
        "results": [dict(r) for r in rows],
        "paging": {
            "limit_requested": limit,
            "limit_applied": limit,
            "offset": offset,
            "returned": len(rows),
            "total": total,
            "has_more": has_more,
            "next_offset": offset + len(rows) if has_more else None,
        },
    }, indent=2)


@pytest.mark.parametrize("tool", _SEARCH_TOOLS)
async def test_paging_by_next_offset_visits_every_record_exactly_once(tool, monkeypatch):
    """Walk a result set whose every page overflows the budget, through the
    real registrar wiring, feeding back only `paging.next_offset`. Before the
    fix a trimmed page kept `next_offset = offset + limit` and the walk
    skipped every record the guard dropped."""
    from src.ptab_mcp.tools import _BoundedRegistrar

    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "12000")
    total = 437
    corpus = [
        {"trialNumber": f"IPR2024-{k:05d}", "blob": "z" * (200 + (k % 7) * 40)}
        for k in range(total)
    ]

    fake = _FakeMCP()

    async def search(limit: int = 100, offset: int = 0):
        return _search_page(offset, limit, corpus, total)

    _BoundedRegistrar(fake).tool(name=tool)(search)
    registered = fake.registered[tool]

    seen: list = []
    offset, trimmed_pages = 0, 0
    for _ in range(total):  # a loop guard, never reached
        page = json.loads(await registered(limit=100, offset=offset))
        rows = page["results"]
        assert page["paging"]["returned"] == len(rows)
        assert page["count"] == total  # the API total, never the page size
        if BOUNDS_KEY in page:
            trimmed_pages += 1
            assert page[BOUNDS_KEY]["items_returned"] == len(rows)
        seen.extend(r["trialNumber"] for r in rows)
        if not page["paging"]["has_more"]:
            assert page["paging"]["next_offset"] is None
            break
        assert page["paging"]["next_offset"] == offset + len(rows)
        offset = page["paging"]["next_offset"]

    assert trimmed_pages > 0  # the walk really did go through the guard
    assert seen == [r["trialNumber"] for r in corpus]


async def test_trimmed_bulk_lookup_does_not_invent_a_cursor():
    """A bulk trial-number lookup forces offset to 0 and says offset is not
    used, so a guard-written next_offset would send a pager round the same
    page forever. It stays null, has_more says rows were dropped, and the
    note names the lever that works."""
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()
    rows = [{"trialNumber": f"IPR2024-{k:05d}", "blob": "z" * 600} for k in range(150)]

    async def bulk():
        return json.dumps({
            "data_type": "trials",
            "query_info": {"bulk_lookup": True, "input_count": 150, "matched_count": 150},
            "count": 150,
            "results": rows,
            "paging": {
                "limit_requested": 10, "limit_applied": 100, "offset": 0,
                "returned": 150, "total": 150, "has_more": False, "next_offset": None,
                "note": "Bulk trial-number lookup: ... offset is not used.",
            },
        })

    _BoundedRegistrar(fake).tool(name="PTAB_search_trials_minimal")(bulk)
    page = json.loads(await fake.registered["PTAB_search_trials_minimal"]())

    kept = len(page["results"])
    assert BOUNDS_KEY in page and kept < 150
    assert page["paging"]["returned"] == kept
    assert page["paging"]["has_more"] is True
    assert page["paging"]["next_offset"] is None
    assert "fewer trial numbers" in page[BOUNDS_KEY]["note"]


async def test_documents_backstop_rewrites_paging_and_the_legacy_counters():
    """The registrar guard runs AFTER PTAB_get_documents built `paging` and its
    legacy top-level `next_offset`, so a trim there has to keep all of them
    (and `count` / `returned_count`) on the documents actually returned."""
    from src.ptab_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()
    docs = [{"documentIdentifier": str(170000000 + k), "documentTitleText": "t" * 600}
            for k in range(80)]

    async def documents_tool():
        return json.dumps({
            "identifier": "IPR2024-00864", "identifier_type": "trial",
            "count": 80, "returned_count": 80, "documents": docs,
            "paging": {"limit_requested": 80, "limit_applied": 80, "offset": 100,
                       "returned": 80, "scanned": 80, "total": 305, "has_more": True,
                       "next_offset": 180},
            "next_offset": 180,
        })

    _BoundedRegistrar(fake).tool(name="PTAB_get_documents")(documents_tool)
    page = json.loads(await fake.registered["PTAB_get_documents"]())

    kept = len(page["documents"])
    assert BOUNDS_KEY in page and kept < 80
    assert page["paging"]["returned"] == kept
    assert page["paging"]["next_offset"] == 100 + kept
    assert page["next_offset"] == 100 + kept
    assert page["count"] == page["returned_count"] == kept
