"""Shared USPTO MCP response-size guard (char-measured, stdlib-only).

VENDORED MODULE — intended to be byte-identical across `uspto_fpd_mcp`,
`uspto_ptab_mcp` and `uspto_pfw_mcp`, exactly like
`uspto_shared_rate_limiter.py`: **stdlib imports only, zero package-relative
imports, no repo-specific constants**. Everything repo-specific (which bags
to slim, which fields are heavy, which tool + parameters to name in a
recovery note) arrives as a parameter. Do not add project imports here.

⚠️ DIVERGED 2026-08-30, and PTAB is now the newer copy. ``_window.unit``
reported ``"page"`` while every counter in the block was characters; it now
always reports ``"char"`` and the snapping fact moved to ``_window.edges``
(see MARKER VOCABULARY below). The fix is generic, carries no PTAB-specific
anything, and belongs in all three repos: **re-vendor this file FROM
uspto_ptab_mcp into uspto_fpd_mcp and uspto_pfw_mcp**, rather than copying
the older FPD file back over it, until those two are caught up.

WHY CHARACTERS, NOT TOKENS
--------------------------
claude.ai replaces an oversized tool result with a *client-side* truncation
error that the server never sees: the model gets no data at all and no way
to recover. The cap is enforced on the serialized payload, so the budget is
a CHARACTER budget, measured as ``len(json.dumps(payload, default=str))`` —
never a token estimate. Callers that return JSON strings run the guard on
the dict *before* their own ``json.dumps``.

THE TWO GUARDS
--------------
1. ``bound_structured_response`` — for structured (record-list) responses.
   Stage 1 "slimmed": every record in a configured bag is reduced to the
   bag's ``keep_fields``. Stage 2 "truncated": each configured bag is halved
   repeatedly down to its ``min_items`` floor until the payload fits.
2. ``window_text`` / ``apply_text_window`` — for large document content the
   caller explicitly asked for. Nothing is dropped, it is *paged*: the
   window plus a cursor telling the caller how to fetch the remainder.

MARKER VOCABULARY (must match verbatim across all three repos)
--------------------------------------------------------------
``_bounds`` — attached ONLY when the guard actually changed the payload. A
no-op returns the identical object with no ``_bounds`` key at all::

    "_bounds": {
        "applied": True,
        "reason": "size",              # "size" | "window"
        "size_chars": 39812,           # measured size of the RETURNED payload
        "size_limit": 40000,
        "stages": ["slimmed", "truncated"],   # only the stages applied
        "slimmed_fields": ["downloadOptionBag", ...],  # fields REMOVED in stage 1
        "items_returned": 20,
        "items_total": 137,
        "note": "<recovery text naming the exact tool + params to narrow>",
    }

``_window`` — attached ONLY when the text was actually windowed (offset > 0
or more text remains)::

    "_window": {
        "unit": "char",                # the unit of every counter below;
                                       # always "char" — see EDGES below
        "edges": "page",               # "page" when the window edges were
                                       # snapped to page markers, else "char"
        "offset": 0,                   # CHARACTER offset of the window start
        "returned": 120000,            # characters returned
        "total": 480000,               # characters in the full text
        "has_more": True,
        "next_offset": 120000,         # feed back as the next offset (None at end)
        "note": "<how to fetch the next window>",
    }

``offset``/``returned``/``total``/``next_offset`` are ALWAYS character
counts, so ``next_offset`` can be passed straight back into the caller's
offset parameter — and ``unit`` says so, always reading ``"char"``.

EDGES. ``unit`` used to read ``"page"`` whenever the window edges had been
snapped to ``=== PAGE N ===`` markers, sitting directly above four counters
that were characters either way. A consumer that read the label and divided
by a page count got nonsense. The snapping fact is real and worth reporting,
so it kept its own key: ``edges`` is ``"page"`` when the window starts and
ends on page boundaries and ``"char"`` when it is a raw character slice
(including a single page too large for the whole budget, which degrades to
a character window).

``items_returned``/``items_total`` count the response's primary unit:
records for a structured response, and — for callers that hand-build a
``_bounds`` marker around a paged upstream operation, such as an OCR page
cap — pages. ``items_total`` is ``null`` when the true total is genuinely
unknown; it is never guessed.

RULES
-----
* Never truncate without a marker.
* No-op is an identity return (same object, byte-identical serialization).
* Repos keep their pre-existing marker keys as ALIASES alongside the new
  vocabulary via the ``aliases`` parameter, so no consumer breaks.

ENVIRONMENT
-----------
* ``USPTO_MAX_RESPONSE_CHARS``       (default 40000)
* ``USPTO_MAX_CONTENT_CHARS``        (default 120000)
* ``USPTO_RESPONSE_BOUNDS_ENABLED``  (default true)
"""

import json
import os
import re
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

ENV_MAX_RESPONSE_CHARS = "USPTO_MAX_RESPONSE_CHARS"
ENV_MAX_CONTENT_CHARS = "USPTO_MAX_CONTENT_CHARS"
ENV_ENABLED = "USPTO_RESPONSE_BOUNDS_ENABLED"

DEFAULT_MAX_RESPONSE_CHARS = 40_000
DEFAULT_MAX_CONTENT_CHARS = 120_000

BOUNDS_KEY = "_bounds"
WINDOW_KEY = "_window"

STAGE_SLIMMED = "slimmed"
STAGE_TRUNCATED = "truncated"

REASON_SIZE = "size"
REASON_WINDOW = "window"

#: Default recognizer for the ``=== PAGE 3 ===`` markers the OCR tiers emit.
PAGE_MARKER_PATTERN = r"^=== PAGE \d+ ===[ \t]*$"

#: Headroom reserved for the ``_bounds`` marker itself, so attaching it can
#: never push a bounded payload back over the caller's limit.
_MARKER_RESERVE_CHARS = 700

#: Never shrink a payload below this, regardless of how small the limit is.
_MIN_EFFECTIVE_LIMIT = 1_000

_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

def _env_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def bounds_enabled() -> bool:
    """USPTO_RESPONSE_BOUNDS_ENABLED — anything but an explicit false value
    leaves the guard on (fail-safe: the failure mode of a disabled guard is
    an unrecoverable client-side truncation error)."""
    raw = os.getenv(ENV_ENABLED)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSE_VALUES


def response_char_budget() -> int:
    """USPTO_MAX_RESPONSE_CHARS — ceiling for structured tool responses."""
    return _env_positive_int(ENV_MAX_RESPONSE_CHARS, DEFAULT_MAX_RESPONSE_CHARS)


def content_char_budget() -> int:
    """USPTO_MAX_CONTENT_CHARS — ceiling for document-content responses the
    caller explicitly asked for (higher: the guard is against pathological
    size, and the cursor keeps the remainder reachable)."""
    return _env_positive_int(ENV_MAX_CONTENT_CHARS, DEFAULT_MAX_CONTENT_CHARS)


def bounds_config() -> Dict[str, Any]:
    """The active budgets, for status/configuration surfaces."""
    return {
        "enabled": bounds_enabled(),
        "max_response_chars": response_char_budget(),
        "max_content_chars": content_char_budget(),
        "env": {
            "enabled": ENV_ENABLED,
            "max_response_chars": ENV_MAX_RESPONSE_CHARS,
            "max_content_chars": ENV_MAX_CONTENT_CHARS,
        },
    }


def measure_chars(payload: Any) -> int:
    """Serialized character count — the quantity the client cap applies to."""
    try:
        return len(json.dumps(payload, default=str))
    except (TypeError, ValueError):
        return len(str(payload))


# ---------------------------------------------------------------------------
# Path walking (bag specs)
# ---------------------------------------------------------------------------

def _walk(node: Any, segments: Sequence[Any]) -> Iterator[Any]:
    """Yield every node reachable by ``segments``.

    Segments are dict keys, list indices (``int``), or ``"*"`` (fan out over
    every element of a list). Missing paths yield nothing.
    """
    if not segments:
        yield node
        return
    head, rest = segments[0], segments[1:]
    if head == "*":
        if isinstance(node, list):
            for item in node:
                yield from _walk(item, rest)
        return
    if isinstance(head, int) and not isinstance(head, bool):
        if isinstance(node, list) and -len(node) <= head < len(node):
            yield from _walk(node[head], rest)
        return
    if isinstance(node, dict) and head in node:
        yield from _walk(node[head], rest)


def _bag_targets(
    payload: Dict[str, Any], bags: Sequence[Mapping[str, Any]]
) -> List[Tuple[Dict[str, Any], Any, Mapping[str, Any]]]:
    """Resolve bag specs to concrete ``(parent_dict, key, spec)`` triples.

    A bag spec is::

        {"path": ["petitionDecisionDataBag", "*", "documentBag"],
         "keep_fields": ("documentIdentifier", ...),   # stage 1
         "min_items": 10,                              # stage 2 floor
         "label": "documentBag"}                       # used in notes
    """
    targets: List[Tuple[Dict[str, Any], Any, Mapping[str, Any]]] = []
    for spec in bags or ():
        path = list(spec.get("path") or ())
        if not path:
            continue
        key = path[-1]
        for parent in _walk(payload, path[:-1]):
            if isinstance(parent, dict) and isinstance(parent.get(key), list) and parent[key]:
                targets.append((parent, key, spec))
    return targets


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------

def _slim_records(records: List[Any], keep_fields: Sequence[str]) -> Tuple[List[Any], set]:
    """Stage 1 — reduce each dict record to ``keep_fields``. Returns the
    slimmed list plus the set of field names that were dropped."""
    dropped: set = set()
    slimmed: List[Any] = []
    for record in records:
        if isinstance(record, dict):
            dropped.update(k for k in record if k not in keep_fields)
            slimmed.append({k: record[k] for k in keep_fields if k in record})
        else:
            slimmed.append(record)
    return slimmed, dropped


def _stage_slim(targets: Sequence[Tuple[Dict[str, Any], Any, Mapping[str, Any]]]) -> set:
    """Stage 1 across every resolved bag. Returns the dropped field names."""
    slimmed_fields: set = set()
    for parent, key, spec in targets:
        keep_fields = tuple(spec.get("keep_fields") or ())
        if not keep_fields:
            continue
        slimmed, dropped = _slim_records(parent[key], keep_fields)
        if dropped:
            parent[key] = slimmed
            slimmed_fields |= dropped
    return slimmed_fields


def _stage_halve(
    payload: Dict[str, Any],
    targets: Sequence[Tuple[Dict[str, Any], Any, Mapping[str, Any]]],
    effective_limit: int,
) -> bool:
    """Stage 2 — halve every bag toward its floor until the payload fits.
    Returns True if any record was dropped. The floor wins over the budget:
    shrinking past it would leave the caller nothing useful, and the marker
    reports the real counts either way."""
    truncated = False
    while targets and measure_chars(payload) > effective_limit:
        progressed = False
        for parent, key, spec in targets:
            current = parent.get(key) or []
            floor = max(0, int(spec.get("min_items", 1) or 0))
            if len(current) > floor:
                parent[key] = current[: max(floor, len(current) // 2)]
                progressed = True
                truncated = True
        if not progressed:
            break
    return truncated


def _stage_truncate_text(payload: Dict[str, Any], effective_limit: int) -> Optional[str]:
    """Last resort — halve the payload's largest string until it fits.
    Returns the truncated field's name, or None if nothing was done."""
    if measure_chars(payload) <= effective_limit:
        return None
    holder, field, _length = _largest_string_field(payload)
    if holder is None or field is None:
        return None
    while measure_chars(payload) > effective_limit and len(holder[field]) > 500:
        holder[field] = holder[field][: max(500, len(holder[field]) // 2)]
    return field


def _largest_string_field(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
    """Locate the (container, key) holding the longest string in the payload
    — the last-resort target when a response has no configured bag to slim."""
    best: Tuple[Optional[Dict[str, Any]], Optional[str], int] = (None, None, 0)
    stack: List[Any] = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str):
                    if len(value) > best[2] and not str(key).startswith("_"):
                        best = (node, key, len(value))
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(item for item in node if isinstance(item, (dict, list)))
    return best


# ---------------------------------------------------------------------------
# Marker helpers
# ---------------------------------------------------------------------------

def _apply_aliases(
    payload: Dict[str, Any], marker: Mapping[str, Any], aliases: Optional[Mapping[str, str]]
) -> None:
    """Mirror canonical marker sub-keys onto this repo's pre-existing
    top-level keys (``{"items_returned": "documents_returned", ...}``), so
    consumers written against the old vocabulary keep working."""
    for canonical, legacy in (aliases or {}).items():
        if canonical in marker:
            payload[legacy] = marker[canonical]


def _attach_bounds(payload: Dict[str, Any], marker: Dict[str, Any], aliases) -> Dict[str, Any]:
    payload[BOUNDS_KEY] = marker
    _apply_aliases(payload, marker, aliases)
    # Two passes: the first measurement is taken with the placeholder size,
    # the second reports the size of the payload actually returned.
    marker["size_chars"] = measure_chars(payload)
    marker["size_chars"] = measure_chars(payload)
    return payload


# ---------------------------------------------------------------------------
# Guard 1: structured responses
# ---------------------------------------------------------------------------

def bound_structured_response(
    payload: Dict[str, Any],
    *,
    bags: Sequence[Mapping[str, Any]] = (),
    limit: Optional[int] = None,
    note: str = "",
    aliases: Optional[Mapping[str, str]] = None,
    text_fallback: bool = False,
    enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """Keep a structured response under a character budget.

    Args:
        payload: the response dict (mutated in place when bounding applies).
        bags: bag specs — see :func:`_bag_targets`. Order matters only for
            note-building; every bag is slimmed and halved.
        limit: character ceiling (default ``USPTO_MAX_RESPONSE_CHARS``).
        note: recovery text naming the exact tool + parameters that would
            narrow the request. Embedded in ``_bounds.note``.
        aliases: canonical marker key -> this repo's legacy top-level key.
        text_fallback: when nothing configured can shed enough size, truncate
            the payload's largest string field (always marked) rather than
            let the client discard the whole response.
        enabled: override the env flag (tests).

    Returns:
        The payload. When the guard was a no-op the SAME object is returned
        with no ``_bounds`` key — byte-identical to the input.
    """
    if not isinstance(payload, dict):
        return payload
    if enabled is None:
        enabled = bounds_enabled()
    if not enabled:
        return payload

    limit = int(limit) if limit else response_char_budget()
    if measure_chars(payload) <= limit:
        return payload

    effective = max(_MIN_EFFECTIVE_LIMIT, limit - _MARKER_RESERVE_CHARS)
    targets = _bag_targets(payload, bags)
    items_total = sum(len(parent[key]) for parent, key, _ in targets)

    stages: List[str] = []

    slimmed_fields = _stage_slim(targets)
    if slimmed_fields:
        stages.append(STAGE_SLIMMED)

    if _stage_halve(payload, targets, effective):
        stages.append(STAGE_TRUNCATED)

    items_returned = sum(len(parent.get(key) or []) for parent, key, _ in targets)

    text_truncated_field = (
        _stage_truncate_text(payload, effective) if text_fallback else None
    )
    if text_truncated_field and STAGE_TRUNCATED not in stages:
        stages.append(STAGE_TRUNCATED)

    if not stages:
        # Nothing configured could shed size; returning the payload unchanged
        # is still the honest outcome, but the caller must be told the client
        # may reject it.
        return _attach_bounds(
            payload,
            {
                "applied": True,
                "reason": REASON_SIZE,
                "size_chars": 0,
                "size_limit": limit,
                "stages": [],
                "slimmed_fields": [],
                "items_returned": items_returned,
                "items_total": items_total,
                "note": (
                    note
                    or "Response exceeds the client response-size limit and no "
                       "narrowing was configured for it; request fewer records."
                ),
            },
            aliases,
        )

    full_note = note
    if text_truncated_field:
        suffix = (
            f" The '{text_truncated_field}' text field was truncated to fit; "
            "re-request it with a narrower selection to see the remainder."
        )
        full_note = (full_note + suffix) if full_note else suffix.strip()

    return _attach_bounds(
        payload,
        {
            "applied": True,
            "reason": REASON_SIZE,
            "size_chars": 0,
            "size_limit": limit,
            "stages": stages,
            "slimmed_fields": sorted(slimmed_fields),
            "items_returned": items_returned,
            "items_total": items_total,
            "note": full_note,
        },
        aliases,
    )


# ---------------------------------------------------------------------------
# Guard 2: text windows
# ---------------------------------------------------------------------------

def _page_starts(text: str, pattern: str) -> List[int]:
    """Character offsets of every page marker in ``text``."""
    return [m.start() for m in re.finditer(pattern, text, re.MULTILINE)]


def window_text(
    text: str,
    *,
    offset: int = 0,
    max_chars: Optional[int] = None,
    note: str = "",
    page_markers: bool = True,
    page_marker_pattern: str = PAGE_MARKER_PATTERN,
) -> Dict[str, Any]:
    """Return a bounded window of ``text`` plus cursor metadata.

    When page markers are present the window edges snap to page boundaries
    (``edges: "page"``) so a page is never split mid-way; otherwise the window
    is a raw character slice (``edges: "char"``). A page larger than the whole
    budget degrades to a character window rather than overshooting.

    ``unit`` is the unit of the ``offset``/``returned``/``total``/
    ``next_offset`` counters and is therefore always ``"char"``, whatever the
    edges did.

    Returns ``{"text": <window>}``, plus a ``_window`` key when the window is
    not the entire text starting at offset 0.
    """
    if not isinstance(text, str):
        return {"text": text}

    total = len(text)
    budget = max(1, int(max_chars) if max_chars else content_char_budget())
    start = max(0, int(offset or 0))
    if start >= total:
        start = total

    # `edges` records how the window boundaries were chosen; the counters
    # below are characters in every case, which is what `unit` reports.
    edges = "char"
    starts = _page_starts(text, page_marker_pattern) if page_markers else []
    if starts:
        edges = "page"
        # Snap the start back to the page marker that contains `offset`.
        page_start = 0 if start < starts[0] else max(s for s in starts if s <= start)
        start = page_start
        # Take as many WHOLE pages as fit: the furthest page boundary (or the
        # end of the text) still inside the budget.
        candidates = [b for b in starts if b > start]
        candidates.append(total)
        fitting = [c for c in candidates if c - start <= budget]
        if fitting:
            end = max(fitting)
        else:
            # Even one page is larger than the budget — fall back to chars.
            edges = "char"
            end = start + budget
    else:
        end = min(total, start + budget)

    returned = end - start
    has_more = end < total
    window = {
        "text": text[start:end],
    }
    if start == 0 and not has_more:
        return window

    window[WINDOW_KEY] = {
        "unit": "char",
        "edges": edges,
        "offset": start,
        "returned": returned,
        "total": total,
        "has_more": has_more,
        "next_offset": end if has_more else None,
        "note": note,
    }
    return window


def apply_text_window(
    payload: Dict[str, Any],
    field: str,
    *,
    offset: int = 0,
    max_chars: Optional[int] = None,
    note: str = "",
    aliases: Optional[Mapping[str, str]] = None,
    page_markers: bool = True,
    page_marker_pattern: str = PAGE_MARKER_PATTERN,
    enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """Window ``payload[field]`` in place and attach the ``_window`` marker.

    No-op (identity return, no marker) when the whole field already fits and
    ``offset`` is 0.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get(field), str):
        return payload
    if enabled is None:
        enabled = bounds_enabled()
    if not enabled:
        return payload

    windowed = window_text(
        payload[field],
        offset=offset,
        max_chars=max_chars,
        note=note,
        page_markers=page_markers,
        page_marker_pattern=page_marker_pattern,
    )
    if WINDOW_KEY not in windowed:
        return payload

    payload[field] = windowed["text"]
    payload[WINDOW_KEY] = windowed[WINDOW_KEY]
    # `_bounds` is the size-guard vocabulary; a window is its own reason.
    payload.setdefault(
        BOUNDS_KEY,
        {
            "applied": True,
            "reason": REASON_WINDOW,
            "size_chars": len(windowed["text"]),
            "size_limit": max(1, int(max_chars) if max_chars else content_char_budget()),
            "stages": [STAGE_TRUNCATED],
            "slimmed_fields": [],
            "items_returned": windowed[WINDOW_KEY]["returned"],
            "items_total": windowed[WINDOW_KEY]["total"],
            "note": note,
        },
    )
    # Aliases may map "applied" (not a `_window` sub-key) onto a legacy
    # boolean such as `truncated`, so alias against the window marker plus
    # that implicit flag.
    alias_source = dict(windowed[WINDOW_KEY])
    alias_source["applied"] = True
    _apply_aliases(payload, alias_source, aliases)
    return payload
