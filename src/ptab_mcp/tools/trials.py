"""Trial (IPR/PGR/CBM) search tools — minimal/balanced/complete tiers."""

from typing import List, Optional, Union

from fastmcp.apps import AppConfig

from ..app_uris import SEARCH_URI
from ..config.filter_field_mapping import TrialFilterFields
from ..runtime import _client, field_manager
from ..shared.safe_logger import get_safe_logger
from ..util.filter_builder import FilterBuilder
from ..util.party_scope import build_party_scope_query, strip_scoped_filters
from ..util.response_formatter import JSON_INDENT, from_api_envelope
from ..util.search_runner import (
    is_no_matches_error,
    mcp_tool_error_envelope,
    resolve_field_selection,
    run_search,
)
from ..validation.validators import (
    build_and_query,
    validate_date_range,
    validate_limit,
    validate_party_name,
    validate_patent_number,
    validate_trial_number,
    validate_trial_type,
)

logger = get_safe_logger(__name__)

# USPTO POST-search hard page cap — bulk trial lookups chunk at this size
_API_CHUNK_SIZE = 100

# Compact serialization; see util/response_formatter.JSON_INDENT.
_JSON_INDENT = JSON_INDENT

# Party-name role scoping (see util/party_scope.py). A `filters` entry naming
# a party field is NOT restricted to that side of the proceeding, so both
# party filters are lifted out of `filters` and re-expressed as a field-scoped
# `q` clause. The patent-owner clause ORs the populated field with the
# unpopulated legacy one so it self-heals if USPTO ever fills the latter in.
_PETITIONER_SCOPE_FIELDS = (TrialFilterFields.PETITIONER_NAME,)
_PATENT_OWNER_SCOPE_FIELDS = (
    TrialFilterFields.PATENT_OWNER_NAME,
    TrialFilterFields.PATENT_OWNER_NAME_LEGACY,
)

_PARTY_SCOPE_NOTE = (
    "petitioner_name and patent_owner_name are matched against that party's "
    "side of the proceeding only. The listed fields appear in `filters` for "
    "provenance, but they were sent as the endpoint's field-scoped `q` query: "
    "a plain filter on a party field matches EITHER party, so "
    "petitioner_name='WIZ' used to return the proceedings in which Wiz is the "
    "patent owner as well."
)


def _scope_party_filters(filters, petitioner_name, patent_owner_name):
    """Lift the party-name filters into a role-scoped `q` clause.

    Returns (q, upstream_filters, query_info_extra); all three are None when
    neither party filter was supplied, which leaves the request byte-identical
    to what it was before role scoping existed.
    """
    q = build_party_scope_query((
        (_PETITIONER_SCOPE_FIELDS, petitioner_name),
        (_PATENT_OWNER_SCOPE_FIELDS, patent_owner_name),
    ))
    if not q:
        return None, None, None
    scoped = []
    if petitioner_name:
        scoped.append(TrialFilterFields.PETITIONER_NAME)
    if patent_owner_name:
        scoped.append(TrialFilterFields.PATENT_OWNER_NAME)
    extra = {
        "party_role_scoped": scoped,
        "party_role_scope_note": _PARTY_SCOPE_NOTE,
    }
    return q, strip_scoped_filters(filters, scoped), extra



def _normalize_trial_number_input(trial_number):
    """Validate a single trial number or a bulk list (<=200 entries).

    Returns (normalized_value, bulk_lookup).
    """
    if not trial_number:
        return trial_number, False
    if isinstance(trial_number, list):
        if len(trial_number) > 200:
            raise ValueError("trial_number list exceeds maximum of 200 entries")
        return [validate_trial_number(tn) for tn in trial_number], len(trial_number) > 1
    return validate_trial_number(trial_number), False


#: Only the minimal tier carries the chunking machinery a bulk list needs, so
#: the other two tiers say which tool takes the list instead of falling into
#: validate_trial_number's `.strip()` and returning a bare AttributeError
#: ("'list' object has no attribute 'strip'", measured on prod 2026-09-03).
_BULK_LIST_TIER_ERROR = (
    "trial_number takes a SINGLE trial number on this tier (e.g. "
    "'IPR2024-01353'). A LIST of trial numbers is accepted only by "
    "PTAB_search_trials_minimal, which fetches every entry in chunks of 100 "
    "(up to 200 entries) and reports unmatched_input_count for the "
    "identifiers that matched nothing. Run the bulk lookup there, then "
    "re-query on this tier the few trials whose extra fields you need."
)


def _reject_bulk_trial_number(trial_number):
    """Guided error for a bulk list handed to the balanced/complete tiers."""
    if isinstance(trial_number, (list, tuple, set)):
        raise ValueError(_BULK_LIST_TIER_ERROR)
    return trial_number


def _validate_party_inputs(*names):
    """AND-join and validate any party or counsel name that was supplied.

    The trials endpoint OR-matches unquoted multi-word values, so "Apple Inc."
    would otherwise match every petitioner containing "Inc.". The
    build_and_query(validate_party_name(...)) pair appeared six times across
    the three tiers (D-4).
    """
    return tuple(build_and_query(validate_party_name(n)) if n else n for n in names)


def _validate_optional_date_range(date_from, date_to):
    """validate_date_range only when either bound is provided."""
    if date_from or date_to:
        return validate_date_range(date_from, date_to)
    return date_from, date_to


#: The field final_decision_date_* actually ranges on. There is no
#: finalDecisionDate in the payload, so the alias was quietly re-pointed here;
#: query_info now SAYS so on every call that uses it.
_LATEST_DECISION_DATE_FIELD = TrialFilterFields.LATEST_DECISION_DATE

_FINAL_DECISION_ALIAS_NOTE = (
    "final_decision_date_from/final_decision_date_to is a DEPRECATED alias and "
    f"this search ranged on {_LATEST_DECISION_DATE_FIELD}. That field is the "
    "most recent decision DOCKETED in the proceeding, which includes a Federal "
    "Circuit order entered into the PTAB record: on IPR2024-00990 it reads "
    "2026-07-21, the date a Fed. Cir. dismissal was docketed, while the "
    "Board's final written decision issued 2025-12-09. THERE IS NO "
    "FINAL-DECISION-DATE FIELD. Use latest_decision_date_from/"
    "latest_decision_date_to for this range, filter "
    "trial_status='Final Written Decision' to find trials that reached one, "
    "and read the decision's own date from the paper "
    "(PTAB_get_documents document_category='FINAL')."
)

_FINAL_DECISION_ALIAS_IGNORED_NOTE = (
    "latest_decision_date_* was supplied for the same bound, so the deprecated "
    "alias listed in deprecated_alias_ignored was NOT used for this search."
)


def _fold_decision_date_alias(latest_from, latest_to, final_from, final_to):
    """Fold final_decision_date_* into latest_decision_date_*.

    Returns (from, to, alias_query_info); alias_query_info is None unless the
    deprecated spelling was supplied, and names the field the range really ran
    on so a Federal Circuit docketing date is never read as an FWD date.
    """
    applied, ignored = [], []
    for name, alias_value, honest_value in (
        ("final_decision_date_from", final_from, latest_from),
        ("final_decision_date_to", final_to, latest_to),
    ):
        if not alias_value:
            continue
        (ignored if honest_value else applied).append(name)

    if latest_from is None:
        latest_from = final_from
    if latest_to is None:
        latest_to = final_to
    latest_from, latest_to = _validate_optional_date_range(latest_from, latest_to)

    if not applied and not ignored:
        return latest_from, latest_to, None
    info = {
        "deprecated_alias_ranged_on": _LATEST_DECISION_DATE_FIELD,
        "deprecated_alias_note": _FINAL_DECISION_ALIAS_NOTE,
    }
    if applied:
        info["deprecated_alias_used"] = applied
    if ignored:
        info["deprecated_alias_ignored"] = ignored
        info["deprecated_alias_ignored_note"] = _FINAL_DECISION_ALIAS_IGNORED_NOTE
    return latest_from, latest_to, info


def _decision_date_ranges(
    builder, institution_date_from, institution_date_to,
    latest_decision_date_from, latest_decision_date_to,
):
    """Add the institution and latest-decision ranges to a FilterBuilder.

    One builder for all three tiers. The two ranges are a property of the
    trials ENDPOINT, not of a tier's field set, so the minimal tier accepts
    them too. It used to reject them at the schema with a raw pydantic
    "Unexpected keyword argument" (measured on prod 2026-09-03).
    """
    return (builder
            .add_range_if(TrialFilterFields.INSTITUTION_DECISION_DATE,
                          institution_date_from, institution_date_to)
            .add_range_if(TrialFilterFields.LATEST_DECISION_DATE,
                          latest_decision_date_from, latest_decision_date_to))


async def _fetch_bulk_trials(
    api_client, trial_number, filters, range_filters, fields, limit,
    patent_number, petitioner_name, patent_owner_name,
    trial_type, trial_status, tech_center,
    party_q=None, party_scoped_fields=(),
):
    """Bulk trial-number lookup with transparent >100-entry auto-chunking.

    Chunks are sequential (USPTO burst=1). Returns
    (error_json_or_None, raw_response, extra_query_info, no_matches).

    `party_q` carries the role-scoped party clause (see _scope_party_filters);
    `party_scoped_fields` names the filter entries it replaced, which are
    dropped from every chunk's upstream filter list.
    """
    party_kwargs = {"q": party_q} if party_q else {}
    chunks_used = 1
    no_matches = False
    chunks_with_no_match = 0
    if len(trial_number) > _API_CHUNK_SIZE:
        _, field_list, _ = resolve_field_selection(
            field_manager, "trials", "minimal", fields
        )
        chunks = [
            trial_number[i:i + _API_CHUNK_SIZE]
            for i in range(0, len(trial_number), _API_CHUNK_SIZE)
        ]
        merged_bag = []
        merged_count = 0

        for chunk in chunks:
            chunk_filters, _ = (FilterBuilder()
                .add_if(TrialFilterFields.TRIAL_NUMBER, chunk)
                .add_if(TrialFilterFields.PATENT_NUMBER, patent_number)
                .add_if(TrialFilterFields.PETITIONER_NAME, petitioner_name)
                .add_if(TrialFilterFields.PATENT_OWNER_NAME, patent_owner_name)
                .add_if(TrialFilterFields.TRIAL_TYPE, trial_type)
                .add_if(TrialFilterFields.TRIAL_STATUS, trial_status)
                .add_if(TrialFilterFields.TECH_CENTER, tech_center)
                .build())
            chunk_filters = strip_scoped_filters(chunk_filters, party_scoped_fields)

            chunk_resp = await api_client.search_trials(
                filters=chunk_filters if chunk_filters else None,
                range_filters=range_filters if range_filters else None,
                pagination={"offset": 0, "limit": _API_CHUNK_SIZE},
                fields=field_list,
                **party_kwargs,
            )

            if chunk_resp.get("error"):
                if is_no_matches_error(chunk_resp):
                    # This chunk's trial numbers matched nothing — not a
                    # service error, just zero records for this slice. Counted
                    # rather than silently skipped, so the caller can tell a
                    # partly-empty bulk lookup from a complete one.
                    no_matches = True
                    chunks_with_no_match += 1
                    continue
                return from_api_envelope(chunk_resp), None, None, False

            merged_bag.extend(chunk_resp.get("patentTrialProceedingDataBag", []))
            merged_count += chunk_resp.get("count", 0)

        raw_response = {"patentTrialProceedingDataBag": merged_bag, "count": merged_count}
        chunks_used = len(chunks)
    else:
        _, field_list, _ = resolve_field_selection(
            field_manager, "trials", "minimal", fields
        )
        raw_response = await api_client.search_trials(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list,
            **party_kwargs,
        )
        if raw_response.get("error"):
            if is_no_matches_error(raw_response):
                raw_response = {"patentTrialProceedingDataBag": [], "count": 0}
                no_matches = True
                chunks_with_no_match = 1
            else:
                return from_api_envelope(raw_response), None, None, False

    matched_count = raw_response.get("count", 0)
    extra_query_info = {
        "bulk_lookup": True,
        "input_count": len(trial_number),
        "matched_count": matched_count,
        "chunks_used": chunks_used,
    }
    if chunks_with_no_match:
        extra_query_info["chunks_with_no_match"] = chunks_with_no_match
    # INPUT that matched nothing — NOT truncated OUTPUT. These were one
    # `truncated: true` flag, which read as "records were dropped from this
    # response" when it actually meant "some trial numbers you asked for do
    # not exist". Output truncation is now reported only by the response-size
    # guard's `_bounds` marker; unmatched input gets its own count and note.
    if matched_count < len(trial_number):
        extra_query_info["unmatched_input_count"] = len(trial_number) - matched_count
        extra_query_info["unmatched_input_note"] = (
            f"{len(trial_number) - matched_count} of the {len(trial_number)} trial "
            "numbers supplied matched no PTAB record. Nothing was dropped from this "
            "response — check those identifiers for typos or wrong proceeding years."
        )
    return None, raw_response, extra_query_info, no_matches


@mcp_tool_error_envelope
async def search_trials_minimal(
    trial_number: Optional[Union[str, List[str]]] = None,
    patent_number: Optional[str] = None,
    petitioner_name: Optional[str] = None,
    patent_owner_name: Optional[str] = None,
    filing_date_from: Optional[str] = None,
    filing_date_to: Optional[str] = None,
    institution_date_from: Optional[str] = None,
    institution_date_to: Optional[str] = None,
    latest_decision_date_from: Optional[str] = None,
    latest_decision_date_to: Optional[str] = None,
    final_decision_date_from: Optional[str] = None,
    final_decision_date_to: Optional[str] = None,
    trial_type: Optional[str] = None,
    trial_status: Optional[str] = None,
    tech_center: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 50,
    offset: int = 0
) -> str:
    """Ultra-minimal trial proceeding discovery (68% context reduction).

    ⚠️ NO CLAIM-LEVEL OUTCOMES AT ANY TIER. Which claims were challenged,
    instituted, cancelled, amended or upheld is NOT in this payload, and is
    not in the balanced or complete tiers either — a trial record carries
    exactly five bags (trialNumber, lastModifiedDateTime, trialMetaData,
    regularPetitionerData, patentOwnerData) and there is no decision bag.
    `trialStatusCategory` says "Final Written Decision" and stops there.
    Never report "claims held unpatentable" from this metadata. Read the
    decision itself: PTAB_get_documents(identifier=...,
    document_category='FINAL') then PTAB_get_document_content on that paper.

    BASIC USAGE:
    - Core Purpose: Fast discovery of IPR/PGR/CBM proceedings with essential fields only
    - Returns: 10-15 core fields per trial (trialNumber, filing dates, parties, patent numbers)
    - Context Reduction: 68% vs balanced tier, 80%+ vs complete tier
    - Typical Volume: 50-100 results for portfolio screening

    WHEN TO USE THIS TOOL:
    - Initial discovery: Finding relevant IPR/PGR/CBM proceedings by patent, party, or date
    - Portfolio screening: Reviewing 50+ trials to identify candidates
    - Patent-to-trial mapping: Correlating patents to PTAB challenges
    - Progressive Disclosure Stage 1: Broad exploration before detailed analysis

    PROGRESSIVE DISCLOSURE WORKFLOW:
    1. Use PTAB_search_trials_minimal for discovery (this tool) - Get 50-100 candidates
    2. Present top results to user for selection
    3. Use PTAB_search_trials_balanced for detailed analysis of selected trials
    4. Use PTAB_get_documents for document lists
    5. Use PTAB_get_document_download for browser-accessible PDFs

    RELATED TOOLS:
    - Next Step: PTAB_search_trials_balanced (after user selects trials from minimal results)
    - Documents: PTAB_get_documents (get document lists for selected trials)
    - Cross-MCP: PFW_search_applications_minimal (correlate to prosecution history)

    CUSTOM FIELDS PARAMETER:
    All search tools support ultra-minimal mode via the 'fields' parameter:

    Example - Only 2 fields (99% context reduction):
      PTAB_search_trials_minimal(
          petitioner_name='Apple Inc',
          fields=['trialNumber', 'patentOwnerData.patentNumber'],
          limit=100
      )

    This reduces token cost from ~40KB (preset minimal) to ~5KB (custom 2 fields).

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: PTAB_get_guidance(section='tools')
    - For field customization: PTAB_get_guidance(section='fields')
    - For PFW integration workflows: PTAB_get_guidance(section='workflows_pfw')
    - For context optimization: PTAB_get_guidance(section='cost')

    Args:
        trial_number: Single trial number (IPR2024-01353) OR list for bulk lookup
                      (["IPR2024-01353", "IPR2024-00965", ...]  up to 200).
                      Bulk list executes as a single API call (OR semantics).
        patent_number: Patent number (7883848, US7883848, etc.). This is the GRANTED PATENT
                      number, not an application serial. An 8-digit value is also a
                      valid application serial (patent numbers passed 10,000,000 in
                      mid-2018), and the wrong kind of number returns an EMPTY result
                      that reads as "no proceedings exist" rather than an error. Map a
                      patent number to its application, or the reverse, with the PFW
                      MCP: PFW_search_applications_minimal(query='patentNumber:<n>')
                      or query='applicationNumberText:<n>'.
        petitioner_name: Petitioner party name (e.g., "Apple Inc"). Matched
                      against the PETITIONER side only — the proceedings this
                      party filed, not the ones filed against it. Matches
                      regularPetitionerData.realPartyInInterestName.
        patent_owner_name: Patent owner name (e.g., "Samsung Electronics").
                      Matched against the PATENT OWNER side only. Matches
                      patentOwnerData.realPartyInInterestName — the field the
                      payload actually populates; patentOwnerData.patentOwnerName
                      is empty in every live record and is OR-ed in only as a
                      fallback in case USPTO ever fills it.
        filing_date_from: Filing date start (YYYY-MM-DD)
        filing_date_to: Filing date end (YYYY-MM-DD)
        institution_date_from: Institution DECISION date start (YYYY-MM-DD).
                Ranges on trialMetaData.institutionDecisionDate, which the
                minimal field set also returns.
        institution_date_to: Institution decision date end (YYYY-MM-DD)
        latest_decision_date_from: Start of a range on
                trialMetaData.latestDecisionDate (YYYY-MM-DD). This is the
                honest name for the date. Read the caveat: latestDecisionDate
                is the most recent decision DOCKETED IN THE PROCEEDING, which
                includes a Federal Circuit order entered into the PTAB record.
                It is NOT a final-written-decision date (on IPR2024-00990 it
                reads 2026-07-21, the date a Fed. Cir. dismissal was docketed,
                while the Board's FWD issued 2025-12-09), and THERE IS NO
                FINAL-DECISION-DATE FIELD. To find trials that reached a final
                written decision, filter trial_status='Final Written Decision';
                to get the FWD's own date, read the paper (PTAB_get_documents
                document_category='FINAL'). The filter works on this tier; the
                date itself is returned by PTAB_search_trials_balanced, which
                carries the whole trialMetaData bag.
        latest_decision_date_to: End of that range (YYYY-MM-DD)
        final_decision_date_from: DEPRECATED alias for latest_decision_date_from.
                It ranges on trialMetaData.latestDecisionDate, and the response's
                query_info says so (deprecated_alias_ranged_on /
                deprecated_alias_note). Prefer the honest name above.
        final_decision_date_to: DEPRECATED alias for latest_decision_date_to
        trial_type: Trial type code (IPR, PGR, CBM, DER)
        trial_status: Trial status (Terminated, Instituted, etc.)
        tech_center: Technology center number
        fields: Optional custom field list (overrides predefined minimal set).
                Use dot notation for nested fields.
                Examples: ["trialNumber", "trialMetaData.trialStatusCategory"]
                If not provided, uses predefined "trials_minimal" field set.
                NOTE: documentBag fields are forbidden (use PTAB_get_documents instead)
        limit: Maximum results (default 50). Normal max: 100. Bulk lookup max: 200.
               Auto-raised to len(trial_number) when a list is passed.
        offset: Zero-based index of the first record to return (default 0).
                Page with the response's `paging.next_offset`; without it,
                results past the first page are unreachable. Ignored for a
                bulk trial_number list (every entry is fetched by chunking).

    Returns:
        JSON string with filtered trial data (minimal or custom field set)

    Example:
        {"data_type": "trials", "field_set": "trials_minimal",
         "count": 2, "results": [...], "context_reduction": {...}}
    """
    api_client = _client()

    # Validate inputs
    trial_number, bulk_lookup = _normalize_trial_number_input(trial_number)

    if patent_number:
        patent_number = validate_patent_number(patent_number)

    petitioner_name, patent_owner_name = _validate_party_inputs(
        petitioner_name, patent_owner_name)

    filing_date_from, filing_date_to = _validate_optional_date_range(filing_date_from, filing_date_to)

    institution_date_from, institution_date_to = _validate_optional_date_range(
        institution_date_from, institution_date_to)

    (latest_decision_date_from, latest_decision_date_to,
     alias_query_info) = _fold_decision_date_alias(
        latest_decision_date_from, latest_decision_date_to,
        final_decision_date_from, final_decision_date_to,
    )

    if trial_type:
        trial_type = validate_trial_type(trial_type)

    # For bulk lookups, auto-chunking handles lists > 100 transparently.
    # The per-chunk limit is always 100 (USPTO API hard cap).
    # For single-value queries, enforce the normal 100 ceiling.
    limit_requested = limit
    paging_note = None
    if bulk_lookup:
        limit = 100  # each chunk uses this; total results = chunks × matches
        offset = 0  # every supplied trial number is fetched; paging is moot
        paging_note = (
            f"Bulk trial-number lookup: the requested limit ({limit_requested}) does "
            "not apply — every supplied identifier is fetched in chunks of 100 and "
            "offset is not used. `limit_applied` reports the per-chunk page size."
        )
    else:
        limit = validate_limit(limit, max_limit=100)

    # Build filters using FilterBuilder pattern

    filters, range_filters = (_decision_date_ranges(
        FilterBuilder()
        .add_if(TrialFilterFields.TRIAL_NUMBER, trial_number)
        .add_if(TrialFilterFields.PATENT_NUMBER, patent_number)
        .add_if(TrialFilterFields.PETITIONER_NAME, petitioner_name)
        .add_if(TrialFilterFields.PATENT_OWNER_NAME, patent_owner_name)
        .add_if(TrialFilterFields.TRIAL_TYPE, trial_type)
        .add_if(TrialFilterFields.TRIAL_STATUS, trial_status)
        .add_if(TrialFilterFields.TECH_CENTER, tech_center)
        .add_range_if(TrialFilterFields.FILING_DATE, filing_date_from, filing_date_to),
        institution_date_from, institution_date_to,
        latest_decision_date_from, latest_decision_date_to)
        .build())

    party_q, upstream_filters, party_scope_info = _scope_party_filters(
        filters, petitioner_name, patent_owner_name
    )

    extra_query_info = {**(party_scope_info or {}), **(alias_query_info or {})} or None
    raw_response = None
    no_matches = False
    if bulk_lookup:
        error_json, raw_response, bulk_query_info, no_matches = await _fetch_bulk_trials(
            api_client, trial_number,
            filters if upstream_filters is None else upstream_filters,
            range_filters, fields, limit,
            patent_number, petitioner_name, patent_owner_name,
            trial_type, trial_status, tech_center,
            party_q=party_q,
            party_scoped_fields=(party_scope_info or {}).get("party_role_scoped", ()),
        )
        if error_json is not None:
            return error_json
        extra_query_info = {**(extra_query_info or {}), **(bulk_query_info or {})}

    return await run_search(
        proceeding="trials", tier="minimal",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit_requested, offset=offset,
        limit_applied=limit,
        paging_note=paging_note,
        extra_query_info=extra_query_info,
        raw_response=raw_response,
        no_matches=no_matches,
        q=party_q,
        upstream_filters=upstream_filters,
    )


@mcp_tool_error_envelope
async def search_trials_balanced(
    trial_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    petitioner_name: Optional[str] = None,
    patent_owner_name: Optional[str] = None,
    filing_date_from: Optional[str] = None,
    filing_date_to: Optional[str] = None,
    institution_date_from: Optional[str] = None,
    institution_date_to: Optional[str] = None,
    latest_decision_date_from: Optional[str] = None,
    latest_decision_date_to: Optional[str] = None,
    final_decision_date_from: Optional[str] = None,
    final_decision_date_to: Optional[str] = None,
    trial_type: Optional[str] = None,
    trial_status: Optional[str] = None,
    tech_center: Optional[str] = None,
    petitioner_counsel: Optional[str] = None,
    patent_owner_counsel: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 20,
    offset: int = 0
) -> str:
    """Comprehensive trial analysis after user selection (13.5% context reduction vs complete).
    IPR, PGR, CBM, inter partes review, post-grant review, covered business method, patent validity challenge, petitioner, patent owner, institution, trial docket.

    ⚠️ NO CLAIM-LEVEL OUTCOMES AT ANY TIER. Which claims were challenged,
    instituted, cancelled, amended or upheld is NOT in this payload, and is
    not in the balanced or complete tiers either — a trial record carries
    exactly five bags (trialNumber, lastModifiedDateTime, trialMetaData,
    regularPetitionerData, patentOwnerData) and there is no decision bag.
    `trialStatusCategory` says "Final Written Decision" and stops there.
    Never report "claims held unpatentable" from this metadata. Read the
    decision itself: PTAB_get_documents(identifier=...,
    document_category='FINAL') then PTAB_get_document_content on that paper.

    BASIC USAGE:
    - Core Purpose: Detailed analysis of user-selected trials with comprehensive data
    - Returns: 30-50 fields per trial (all party, patent, decision, counsel data)
    - Context Reduction: 13.5% vs complete tier (still efficient)
    - Typical Volume: 10-20 results for focused analysis

    WHEN TO USE THIS TOOL:
    - Post-Selection Analysis: After minimal search identifies candidates
    - Strategy Development: Need counsel names, decision dates, claim details
    - Outcome Analysis: Understand decision outcomes and reasoning
    - Progressive Disclosure Stage 2: After minimal discovery, before complete data

    PROGRESSIVE DISCLOSURE WORKFLOW:
    1. PTAB_search_trials_minimal - Discovery (50-100 candidates)
    2. User selects trials of interest
    3. PTAB_search_trials_balanced (this tool) - Detailed analysis of 10-20 trials
    4. PTAB_get_documents - Get document lists if needed
    5. PTAB_search_trials_complete - Only if balanced tier insufficient

    RELATED TOOLS:
    - Previous Step: PTAB_search_trials_minimal (discovery phase)
    - Next Step: PTAB_get_documents (get document lists) or PTAB_search_trials_complete (full data)
    - Cross-MCP: PFW_search_applications_balanced (prosecution history with similar detail level)

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: PTAB_get_guidance(section='tools')
    - For field customization: PTAB_get_guidance(section='fields')
    - For PFW integration workflows: PTAB_get_guidance(section='workflows_pfw')

    Args:
        trial_number: Trial number (IPR2024-01353). A SINGLE number on this
                      tier; a list of trial numbers is accepted only by
                      PTAB_search_trials_minimal, which chunks the lookup.
        patent_number: Patent number (7883848). This is the GRANTED PATENT
                      number, not an application serial. An 8-digit value is also a
                      valid application serial (patent numbers passed 10,000,000 in
                      mid-2018), and the wrong kind of number returns an EMPTY result
                      that reads as "no proceedings exist" rather than an error. Map a
                      patent number to its application, or the reverse, with the PFW
                      MCP: PFW_search_applications_minimal(query='patentNumber:<n>')
                      or query='applicationNumberText:<n>'.
        petitioner_name: Petitioner party name. Matched against the
                      PETITIONER side only (regularPetitionerData.
                      realPartyInInterestName) — the proceedings this party
                      filed, not the ones filed against it.
        patent_owner_name: Patent owner name. Matched against the PATENT
                      OWNER side only, on patentOwnerData.
                      realPartyInInterestName (patentOwnerData.patentOwnerName
                      is unpopulated in every live record and is OR-ed in only
                      as a fallback).
        filing_date_from: Filing date start (YYYY-MM-DD)
        filing_date_to: Filing date end (YYYY-MM-DD)
        institution_date_from: Institution DECISION date start (YYYY-MM-DD).
                Filters trialMetaData.institutionDecisionDate.
        institution_date_to: Institution decision date end (YYYY-MM-DD)
        latest_decision_date_from: Start of a range on
                trialMetaData.latestDecisionDate (YYYY-MM-DD). ⚠️ READ THIS:
                latestDecisionDate is the date of the most recent decision
                DOCKETED IN THE PROCEEDING, which includes a Federal Circuit
                order entered into the PTAB record. It is NOT a final-written-
                decision date. On IPR2024-00990 it reads 2026-07-21, the date
                a Fed. Cir. dismissal was docketed, while the Board's FWD
                issued 2025-12-09. THERE IS NO FINAL-DECISION-DATE FIELD. To
                find trials that reached a final written decision, filter
                trial_status='Final Written Decision'; to get the FWD's own
                date, read the paper (PTAB_get_documents
                document_category='FINAL').
        latest_decision_date_to: End of that range (YYYY-MM-DD)
        final_decision_date_from: DEPRECATED alias for latest_decision_date_from.
                It used to map to trialMetaData.finalDecisionDate, a field the
                payload does not carry, so every range returned zero
                (verified live 2026-08-30). It now ranges on
                trialMetaData.latestDecisionDate, and the response's query_info
                says so explicitly (deprecated_alias_used,
                deprecated_alias_ranged_on, deprecated_alias_note) so the
                Federal Circuit docketing trap above cannot be read as a
                final-written-decision date. Prefer the correctly named
                parameter.
        final_decision_date_to: DEPRECATED alias for latest_decision_date_to
        trial_type: Trial type (IPR, PGR, CBM, DER)
        trial_status: Trial status
        tech_center: Technology center number
        petitioner_counsel: Petitioner counsel name
        patent_owner_counsel: Patent owner counsel name
        fields: Optional custom field list (overrides predefined balanced set).
                Use dot notation for nested fields.
                Examples: ["trialNumber", "trialMetaData.trialStatusCategory"]
                If not provided, uses predefined "trials_balanced" field set.
                NOTE: documentBag fields are forbidden (use PTAB_get_documents instead)
        limit: Maximum results (default 20, max 100)
        offset: Zero-based index of the first record to return (default 0).
                Page with the response's `paging.next_offset`; without it,
                results past the first page are unreachable.

    Returns:
        JSON string with comprehensive trial data (balanced or custom field set)
    """
    api_client = _client()

    # Validate inputs
    trial_number = _reject_bulk_trial_number(trial_number)
    if trial_number:
        trial_number = validate_trial_number(trial_number)

    if patent_number:
        patent_number = validate_patent_number(patent_number)

    petitioner_name, patent_owner_name = _validate_party_inputs(
        petitioner_name, patent_owner_name)

    petitioner_counsel, patent_owner_counsel = _validate_party_inputs(
        petitioner_counsel, patent_owner_counsel)

    filing_date_from, filing_date_to = _validate_optional_date_range(filing_date_from, filing_date_to)

    institution_date_from, institution_date_to = _validate_optional_date_range(institution_date_from, institution_date_to)

    # final_decision_date_* is the deprecated spelling of the same range.
    # It used to point at trialMetaData.finalDecisionDate, which does not
    # exist, so it silently returned nothing for every window; it ranges on
    # latestDecisionDate now, and query_info says which field that is.
    (latest_decision_date_from, latest_decision_date_to,
     alias_query_info) = _fold_decision_date_alias(
        latest_decision_date_from, latest_decision_date_to,
        final_decision_date_from, final_decision_date_to,
    )

    if trial_type:
        trial_type = validate_trial_type(trial_type)

    limit = validate_limit(limit, max_limit=100)

    # Build filters using FilterBuilder pattern

    filters, range_filters = (_decision_date_ranges(
        FilterBuilder()
        .add_if(TrialFilterFields.TRIAL_NUMBER, trial_number)
        .add_if(TrialFilterFields.PATENT_NUMBER, patent_number)
        .add_if(TrialFilterFields.PETITIONER_NAME, petitioner_name)
        .add_if(TrialFilterFields.PATENT_OWNER_NAME, patent_owner_name)
        .add_if(TrialFilterFields.TRIAL_TYPE, trial_type)
        .add_if(TrialFilterFields.TRIAL_STATUS, trial_status)
        .add_if(TrialFilterFields.TECH_CENTER, tech_center)
        # examiner_name/art_unit/assignee_name/decision_outcome removed:
        # trial records have no respondentData or decisionData bags, so
        # those filters always returned "no matching records" (verified
        # live 2026-07-02). The appeals tools' equivalents remain valid.
        .add_if(TrialFilterFields.PETITIONER_COUNSEL, petitioner_counsel)
        .add_if(TrialFilterFields.PATENT_OWNER_COUNSEL, patent_owner_counsel)
        .add_range_if(TrialFilterFields.FILING_DATE, filing_date_from, filing_date_to),
        institution_date_from, institution_date_to,
        latest_decision_date_from, latest_decision_date_to)
        .build())

    party_q, upstream_filters, party_scope_info = _scope_party_filters(
        filters, petitioner_name, patent_owner_name
    )

    return await run_search(
        proceeding="trials", tier="balanced",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit, offset=offset,
        extra_query_info={**(party_scope_info or {}),
                          **(alias_query_info or {})} or None,
        q=party_q, upstream_filters=upstream_filters,
    )


@mcp_tool_error_envelope
async def search_trials_complete(
    trial_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    petitioner_name: Optional[str] = None,
    patent_owner_name: Optional[str] = None,
    filing_date_from: Optional[str] = None,
    filing_date_to: Optional[str] = None,
    trial_type: Optional[str] = None,
    trial_status: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 10,
    offset: int = 0
) -> str:
    """Complete trial data access (no field filtering).
    IPR, PGR, CBM, inter partes review, post-grant review, covered business method, patent validity challenge, petitioner, patent owner, institution, trial docket.

    ⚠️ NO CLAIM-LEVEL OUTCOMES AT ANY TIER. Which claims were challenged,
    instituted, cancelled, amended or upheld is NOT in this payload, and is
    not in the balanced or complete tiers either — a trial record carries
    exactly five bags (trialNumber, lastModifiedDateTime, trialMetaData,
    regularPetitionerData, patentOwnerData) and there is no decision bag.
    `trialStatusCategory` says "Final Written Decision" and stops there.
    Never report "claims held unpatentable" from this metadata. Read the
    decision itself: PTAB_get_documents(identifier=...,
    document_category='FINAL') then PTAB_get_document_content on that paper.

    BASIC USAGE:
    - Core Purpose: Access all available trial data fields for expert analysis
    - Returns: All fields from USPTO API (80-120 fields per trial)
    - Context Reduction: Minimal (returns complete data)
    - Typical Volume: 1-10 trials (use sparingly due to token cost)

    WHEN TO USE THIS TOOL:
    - Expert Analysis: Need obscure fields not in balanced tier
    - Data Export/Archiving: Complete trial records for offline analysis
    - Custom Analysis: Exploring unknown fields for new use cases
    - Progressive Disclosure Stage 3: Only when minimal and balanced insufficient

    WHEN NOT TO USE:
    - Initial Discovery: Use PTAB_search_trials_minimal instead
    - Routine Analysis: Use PTAB_search_trials_balanced instead
    - Large Result Sets: Complete tier generates excessive tokens

    RELATED TOOLS:
    - Better Alternatives: PTAB_search_trials_minimal or PTAB_search_trials_balanced (95% of use cases)
    - Documents: PTAB_get_documents (for document lists)
    - Cross-MCP: PFW_search_applications_complete (full prosecution data)

    GUIDANCE REFERENCES:
    - For progressive disclosure decision tree: PTAB_get_guidance(section='tools')
    - For field customization: PTAB_get_guidance(section='fields')

    Args:
        trial_number: Trial number (IPR2024-01353). A SINGLE number on this
                      tier; a list of trial numbers is accepted only by
                      PTAB_search_trials_minimal, which chunks the lookup.
        patent_number: Patent number (7883848). This is the GRANTED PATENT
                      number, not an application serial. An 8-digit value is also a
                      valid application serial (patent numbers passed 10,000,000 in
                      mid-2018), and the wrong kind of number returns an EMPTY result
                      that reads as "no proceedings exist" rather than an error. Map a
                      patent number to its application, or the reverse, with the PFW
                      MCP: PFW_search_applications_minimal(query='patentNumber:<n>')
                      or query='applicationNumberText:<n>'.
        petitioner_name: Petitioner party name. Matched against the
                      PETITIONER side only (regularPetitionerData.
                      realPartyInInterestName) — the proceedings this party
                      filed, not the ones filed against it.
        patent_owner_name: Patent owner name. Matched against the PATENT
                      OWNER side only, on patentOwnerData.
                      realPartyInInterestName (patentOwnerData.patentOwnerName
                      is unpopulated in every live record and is OR-ed in only
                      as a fallback).
        filing_date_from: Filing date start (YYYY-MM-DD)
        filing_date_to: Filing date end (YYYY-MM-DD)
        trial_type: Trial type (IPR, PGR, CBM, DER)
        trial_status: Trial status
        fields: Optional custom field list (overrides predefined complete set).
                Use dot notation for nested fields.
                Examples: ["trialNumber", "trialMetaData.trialStatusCategory"]
                If not provided, uses predefined "trials_complete" field set.
                NOTE: documentBag fields are forbidden (use PTAB_get_documents instead)
        limit: Maximum results (default 10, max 50)
        offset: Zero-based index of the first record to return (default 0).
                Page with the response's `paging.next_offset`; without it,
                results past the first page are unreachable.

    Returns:
        JSON string with complete trial data (all fields or custom field set)
    """
    api_client = _client()

    # Validate inputs (same as minimal)
    trial_number = _reject_bulk_trial_number(trial_number)
    if trial_number:
        trial_number = validate_trial_number(trial_number)

    if patent_number:
        patent_number = validate_patent_number(patent_number)

    petitioner_name, patent_owner_name = _validate_party_inputs(
        petitioner_name, patent_owner_name)

    filing_date_from, filing_date_to = _validate_optional_date_range(filing_date_from, filing_date_to)

    if trial_type:
        trial_type = validate_trial_type(trial_type)

    limit = validate_limit(limit, max_limit=50)  # Lower limit for complete data

    # Build filters using FilterBuilder pattern

    filters, range_filters = (FilterBuilder()
        .add_if(TrialFilterFields.TRIAL_NUMBER, trial_number)
        .add_if(TrialFilterFields.PATENT_NUMBER, patent_number)
        .add_if(TrialFilterFields.PETITIONER_NAME, petitioner_name)
        .add_if(TrialFilterFields.PATENT_OWNER_NAME, patent_owner_name)
        .add_if(TrialFilterFields.TRIAL_TYPE, trial_type)
        .add_if(TrialFilterFields.TRIAL_STATUS, trial_status)
        .add_range_if(TrialFilterFields.FILING_DATE, filing_date_from, filing_date_to)
        .build())

    party_q, upstream_filters, party_scope_info = _scope_party_filters(
        filters, petitioner_name, patent_owner_name
    )

    return await run_search(
        proceeding="trials", tier="complete",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit, offset=offset,
        extra_query_info=party_scope_info,
        q=party_q, upstream_filters=upstream_filters,
    )


def register(mcp) -> None:
    """Register the three trial search tools (schemas unchanged; PTAB_ display names)."""
    mcp.tool(name="PTAB_search_trials_minimal", app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": False, "readOnlyHint": True})(search_trials_minimal)
    mcp.tool(name="PTAB_search_trials_balanced", app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(search_trials_balanced)
    mcp.tool(name="PTAB_search_trials_complete", app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(search_trials_complete)
