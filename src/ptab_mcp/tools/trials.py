"""Trial (IPR/PGR/CBM) search tools — minimal/balanced/complete tiers."""

import json
from typing import List, Optional, Union

from fastmcp.apps import AppConfig

from ..app_uris import SEARCH_URI
from ..config.filter_field_mapping import TrialFilterFields
from ..runtime import _client, field_manager
from ..shared.safe_logger import get_safe_logger
from ..util.filter_builder import FilterBuilder
from ..util.search_runner import (
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


def _validate_optional_date_range(date_from, date_to):
    """validate_date_range only when either bound is provided."""
    if date_from or date_to:
        return validate_date_range(date_from, date_to)
    return date_from, date_to


async def _fetch_bulk_trials(
    api_client, trial_number, filters, range_filters, fields, limit,
    patent_number, petitioner_name, patent_owner_name,
    trial_type, trial_status, tech_center,
):
    """Bulk trial-number lookup with transparent >100-entry auto-chunking.

    Chunks are sequential (USPTO burst=1). Returns
    (error_json_or_None, raw_response, extra_query_info).
    """
    chunks_used = 1
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

            chunk_resp = await api_client.search_trials(
                filters=chunk_filters if chunk_filters else None,
                range_filters=range_filters if range_filters else None,
                pagination={"offset": 0, "limit": _API_CHUNK_SIZE},
                fields=field_list
            )

            if chunk_resp.get("error"):
                return json.dumps(chunk_resp, indent=2), None, None

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
            fields=field_list
        )
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2), None, None

    matched_count = raw_response.get("count", 0)
    extra_query_info = {
        "bulk_lookup": True,
        "input_count": len(trial_number),
        "matched_count": matched_count,
        "chunks_used": chunks_used,
    }
    if matched_count < len(trial_number):
        extra_query_info["truncated"] = True
    return None, raw_response, extra_query_info


@mcp_tool_error_envelope
async def search_trials_minimal(
    trial_number: Optional[Union[str, List[str]]] = None,
    patent_number: Optional[str] = None,
    petitioner_name: Optional[str] = None,
    patent_owner_name: Optional[str] = None,
    filing_date_from: Optional[str] = None,
    filing_date_to: Optional[str] = None,
    trial_type: Optional[str] = None,
    trial_status: Optional[str] = None,
    tech_center: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 50
) -> str:
    """Ultra-minimal trial proceeding discovery (68% context reduction).

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
    1. Use search_trials_minimal for discovery (this tool) - Get 50-100 candidates
    2. Present top results to user for selection
    3. Use search_trials_balanced for detailed analysis of selected trials
    4. Use ptab_get_documents for document lists
    5. Use ptab_get_document_download for browser-accessible PDFs

    RELATED TOOLS:
    - Next Step: search_trials_balanced (after user selects trials from minimal results)
    - Documents: ptab_get_documents (get document lists for selected trials)
    - Cross-MCP: pfw_search_applications_minimal (correlate to prosecution history)

    CUSTOM FIELDS PARAMETER:
    All search tools support ultra-minimal mode via the 'fields' parameter:

    Example - Only 2 fields (99% context reduction):
      search_trials_minimal(
          petitioner_name='Apple Inc',
          fields=['trialNumber', 'patentOwnerData.patentNumber'],
          limit=100
      )

    This reduces token cost from ~40KB (preset minimal) to ~5KB (custom 2 fields).

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: ptab_get_guidance(section='tools')
    - For field customization: ptab_get_guidance(section='fields')
    - For PFW integration workflows: ptab_get_guidance(section='workflows_pfw')
    - For cost optimization: ptab_get_guidance(section='cost')

    Args:
        trial_number: Single trial number (IPR2024-00123) OR list for bulk lookup
                      (["IPR2024-00123", "IPR2024-00965", ...]  up to 200).
                      Bulk list executes as a single API call (OR semantics).
        patent_number: Patent number (8524787, US8524787, etc.)
        petitioner_name: Petitioner party name (e.g., "Apple Inc")
        patent_owner_name: Patent owner name (e.g., "Samsung Electronics")
        filing_date_from: Filing date start (YYYY-MM-DD)
        filing_date_to: Filing date end (YYYY-MM-DD)
        trial_type: Trial type code (IPR, PGR, CBM, DER)
        trial_status: Trial status (Terminated, Instituted, etc.)
        tech_center: Technology center number
        fields: Optional custom field list (overrides predefined minimal set).
                Use dot notation for nested fields.
                Examples: ["trialNumber", "trialMetaData.trialStatusCategory"]
                If not provided, uses predefined "trials_minimal" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 50). Normal max: 100. Bulk lookup max: 200.
               Auto-raised to len(trial_number) when a list is passed.

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

    # Trials endpoint OR-matches unquoted multi-word values — AND-join tokens
    # so "Apple Inc." matches Apple Inc., not every petitioner containing "Inc."
    if petitioner_name:
        petitioner_name = build_and_query(validate_party_name(petitioner_name))

    if patent_owner_name:
        patent_owner_name = build_and_query(validate_party_name(patent_owner_name))

    filing_date_from, filing_date_to = _validate_optional_date_range(filing_date_from, filing_date_to)

    if trial_type:
        trial_type = validate_trial_type(trial_type)

    # For bulk lookups, auto-chunking handles lists > 100 transparently.
    # The per-chunk limit is always 100 (USPTO API hard cap).
    # For single-value queries, enforce the normal 100 ceiling.
    if bulk_lookup:
        limit = 100  # each chunk uses this; total results = chunks × matches
    else:
        limit = validate_limit(limit, max_limit=100)

    # Build filters using FilterBuilder pattern

    filters, range_filters = (FilterBuilder()
        .add_if(TrialFilterFields.TRIAL_NUMBER, trial_number)
        .add_if(TrialFilterFields.PATENT_NUMBER, patent_number)
        .add_if(TrialFilterFields.PETITIONER_NAME, petitioner_name)
        .add_if(TrialFilterFields.PATENT_OWNER_NAME, patent_owner_name)
        .add_if(TrialFilterFields.TRIAL_TYPE, trial_type)
        .add_if(TrialFilterFields.TRIAL_STATUS, trial_status)
        .add_if(TrialFilterFields.TECH_CENTER, tech_center)
        .add_range_if(TrialFilterFields.FILING_DATE, filing_date_from, filing_date_to)
        .build())

    raw_response = None
    extra_query_info = None
    if bulk_lookup:
        error_json, raw_response, extra_query_info = await _fetch_bulk_trials(
            api_client, trial_number, filters, range_filters, fields, limit,
            patent_number, petitioner_name, patent_owner_name,
            trial_type, trial_status, tech_center,
        )
        if error_json is not None:
            return error_json

    return await run_search(
        proceeding="trials", tier="minimal",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit,
        extra_query_info=extra_query_info,
        raw_response=raw_response,
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
    final_decision_date_from: Optional[str] = None,
    final_decision_date_to: Optional[str] = None,
    trial_type: Optional[str] = None,
    trial_status: Optional[str] = None,
    tech_center: Optional[str] = None,
    petitioner_counsel: Optional[str] = None,
    patent_owner_counsel: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 20
) -> str:
    """Comprehensive trial analysis after user selection (13.5% context reduction vs complete).

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
    1. search_trials_minimal - Discovery (50-100 candidates)
    2. User selects trials of interest
    3. search_trials_balanced (this tool) - Detailed analysis of 10-20 trials
    4. ptab_get_documents - Get document lists if needed
    5. search_trials_complete - Only if balanced tier insufficient

    RELATED TOOLS:
    - Previous Step: search_trials_minimal (discovery phase)
    - Next Step: ptab_get_documents (get document lists) or search_trials_complete (full data)
    - Cross-MCP: pfw_search_applications_balanced (prosecution history with similar detail level)

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: ptab_get_guidance(section='tools')
    - For field customization: ptab_get_guidance(section='fields')
    - For PFW integration workflows: ptab_get_guidance(section='workflows_pfw')

    Args:
        trial_number: Trial number (IPR2024-00123)
        patent_number: Patent number (8524787)
        petitioner_name: Petitioner party name
        patent_owner_name: Patent owner name
        filing_date_from: Filing date start (YYYY-MM-DD)
        filing_date_to: Filing date end (YYYY-MM-DD)
        institution_date_from: Institution date start (YYYY-MM-DD)
        institution_date_to: Institution date end (YYYY-MM-DD)
        final_decision_date_from: Final decision date start (YYYY-MM-DD)
        final_decision_date_to: Final decision date end (YYYY-MM-DD)
        trial_type: Trial type (IPR, PGR, CBM, DER)
        trial_status: Trial status
        tech_center: Technology center number
        petitioner_counsel: Petitioner counsel name
        patent_owner_counsel: Patent owner counsel name
        fields: Optional custom field list (overrides predefined balanced set).
                Use dot notation for nested fields.
                Examples: ["trialNumber", "trialMetaData.trialStatusCategory"]
                If not provided, uses predefined "trials_balanced" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 20, max 100)

    Returns:
        JSON string with comprehensive trial data (balanced or custom field set)
    """
    api_client = _client()

    # Validate inputs
    if trial_number:
        trial_number = validate_trial_number(trial_number)

    if patent_number:
        patent_number = validate_patent_number(patent_number)

    # Trials endpoint OR-matches unquoted multi-word values — AND-join tokens
    # so "Apple Inc." matches Apple Inc., not every petitioner containing "Inc."
    if petitioner_name:
        petitioner_name = build_and_query(validate_party_name(petitioner_name))

    if patent_owner_name:
        patent_owner_name = build_and_query(validate_party_name(patent_owner_name))

    # Counsel names get the same AND-join: any multi-word text value
    # OR-matches on the trials endpoint
    if petitioner_counsel:
        petitioner_counsel = build_and_query(validate_party_name(petitioner_counsel))

    if patent_owner_counsel:
        patent_owner_counsel = build_and_query(validate_party_name(patent_owner_counsel))

    filing_date_from, filing_date_to = _validate_optional_date_range(filing_date_from, filing_date_to)

    institution_date_from, institution_date_to = _validate_optional_date_range(institution_date_from, institution_date_to)

    final_decision_date_from, final_decision_date_to = _validate_optional_date_range(final_decision_date_from, final_decision_date_to)

    if trial_type:
        trial_type = validate_trial_type(trial_type)

    limit = validate_limit(limit, max_limit=100)

    # Build filters using FilterBuilder pattern

    filters, range_filters = (FilterBuilder()
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
        .add_range_if(TrialFilterFields.FILING_DATE, filing_date_from, filing_date_to)
        .add_range_if(TrialFilterFields.INSTITUTION_DATE, institution_date_from, institution_date_to)
        .add_range_if(TrialFilterFields.FINAL_DECISION_DATE, final_decision_date_from, final_decision_date_to)
        .build())

    return await run_search(
        proceeding="trials", tier="balanced",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit,
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
    limit: int = 10
) -> str:
    """Complete trial data access (no field filtering).

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
    - Initial Discovery: Use search_trials_minimal instead
    - Routine Analysis: Use search_trials_balanced instead
    - Large Result Sets: Complete tier generates excessive tokens

    RELATED TOOLS:
    - Better Alternatives: search_trials_minimal or search_trials_balanced (95% of use cases)
    - Documents: ptab_get_documents (for document lists)
    - Cross-MCP: pfw_search_applications_complete (full prosecution data)

    GUIDANCE REFERENCES:
    - For progressive disclosure decision tree: ptab_get_guidance(section='tools')
    - For field customization: ptab_get_guidance(section='fields')

    Args:
        trial_number: Trial number (IPR2024-00123)
        patent_number: Patent number (8524787)
        petitioner_name: Petitioner party name
        patent_owner_name: Patent owner name
        filing_date_from: Filing date start (YYYY-MM-DD)
        filing_date_to: Filing date end (YYYY-MM-DD)
        trial_type: Trial type (IPR, PGR, CBM, DER)
        trial_status: Trial status
        fields: Optional custom field list (overrides predefined complete set).
                Use dot notation for nested fields.
                Examples: ["trialNumber", "trialMetaData.trialStatusCategory"]
                If not provided, uses predefined "trials_complete" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 10, max 50)

    Returns:
        JSON string with complete trial data (all fields or custom field set)
    """
    api_client = _client()

    # Validate inputs (same as minimal)
    if trial_number:
        trial_number = validate_trial_number(trial_number)

    if patent_number:
        patent_number = validate_patent_number(patent_number)

    # Trials endpoint OR-matches unquoted multi-word values — AND-join tokens
    # so "Apple Inc." matches Apple Inc., not every petitioner containing "Inc."
    if petitioner_name:
        petitioner_name = build_and_query(validate_party_name(petitioner_name))

    if patent_owner_name:
        patent_owner_name = build_and_query(validate_party_name(patent_owner_name))

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

    return await run_search(
        proceeding="trials", tier="complete",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit,
    )


def register(mcp) -> None:
    """Register the three trial search tools (names/schemas unchanged)."""
    mcp.tool(app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": False, "readOnlyHint": True})(search_trials_minimal)
    mcp.tool(app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(search_trials_balanced)
    mcp.tool(app=AppConfig(resource_uri=SEARCH_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(search_trials_complete)
