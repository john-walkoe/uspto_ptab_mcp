"""Ex parte appeal search tools — minimal/balanced/complete tiers."""

from typing import List, Optional

from fastmcp.apps import AppConfig

from ..app_uris import SEARCH_URI
from ..config.filter_field_mapping import AppealFilterFields
from ..runtime import _client, field_manager
from ..shared.safe_logger import get_safe_logger
from ..util.filter_builder import FilterBuilder
from ..util.search_runner import mcp_tool_error_envelope, run_search
from ..validation.validators import (
    validate_appeal_number,
    validate_date_range,
    validate_limit,
    validate_party_name,
)

logger = get_safe_logger(__name__)

# Per-tier result ceilings, matching each tool's own docstring. `complete` is
# deliberately lower: it applies no field filtering (fields: ["*"] short-circuits
# the tier filter), so a full page of complete records is exactly the payload the
# response-size guard exists to catch. tools/trials.py:736 makes the same choice.
_TIER_MAX_LIMIT = {"minimal": 100, "balanced": 100, "complete": 50}


async def _run_appeal_search(
    tier: str,
    *,
    appeal_number: Optional[str] = None,
    application_number: Optional[str] = None,
    appellant_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    art_unit: Optional[str] = None,
    technology_center: Optional[str] = None,
    decision_type: Optional[str] = None,
    decision_outcome: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Shared body for the three appeal tiers.

    The three public tools keep their own signatures and docstrings (the
    signature IS the published MCP input schema) and differ only in which
    parameters they expose and in `_TIER_MAX_LIMIT[tier]`. The minimal tier does
    not expose technology_center/decision_type/decision_outcome, which arrive
    here as None and are no-ops in FilterBuilder.add_if.
    """
    api_client = _client()

    # Validate inputs
    if appeal_number:
        appeal_number = validate_appeal_number(appeal_number)

    if appellant_name:
        appellant_name = validate_party_name(appellant_name)

    if decision_date_from or decision_date_to:
        decision_date_from, decision_date_to = validate_date_range(
            decision_date_from, decision_date_to
        )

    limit = validate_limit(limit, max_limit=_TIER_MAX_LIMIT[tier])

    # Build filters using FilterBuilder pattern

    filters, range_filters = (FilterBuilder()
        .add_if(AppealFilterFields.APPEAL_NUMBER, appeal_number)
        .add_if(AppealFilterFields.APPLICATION_NUMBER, application_number)
        .add_if(AppealFilterFields.APPELLANT_NAME, appellant_name)
        .add_if(AppealFilterFields.ART_UNIT, art_unit)
        .add_if(AppealFilterFields.TECH_CENTER, technology_center)
        .add_if(AppealFilterFields.DECISION_TYPE, decision_type)
        .add_if(AppealFilterFields.DECISION_OUTCOME, decision_outcome)
        .add_range_if(AppealFilterFields.DECISION_DATE, decision_date_from, decision_date_to)
        .build())

    return await run_search(
        proceeding="appeals", tier=tier,
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit, offset=offset,
    )


@mcp_tool_error_envelope
async def search_appeals_minimal(
    appeal_number: Optional[str] = None,
    application_number: Optional[str] = None,
    appellant_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    art_unit: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 50,
    offset: int = 0
) -> str:
    """Ultra-minimal ex parte appeal discovery (95-99% context reduction).
    Ex parte appeal, appeal of an examiner rejection, Board decision, affirmed, reversed, appellant, art unit, technology center.

    BASIC USAGE:
    - Core Purpose: Fast discovery of ex parte appeals to PTAB with essential fields only
    - Returns: 9 core fields per appeal (appealNumber, application number,
      filing and decision dates, TC/art unit, decision type, outcome,
      appellant name). The examiner is NOT among them: the appeals search
      payload carries no examiner data at any tier.
    - Context Reduction: 95-99% vs complete tier
    - Typical Volume: 50-100 results for art unit screening

    WHEN TO USE THIS TOOL:
    - Initial Discovery: Finding relevant ex parte appeals by art unit,
      application number or appellant name. There is no examiner filter,
      because the payload has no examiner field to filter on; screen by art
      unit here and resolve to the examiner in PFW.
    - Art Unit Pattern Analysis: Reviewing 50+ appeals to identify reversal trends
    - Application-to-Appeal Mapping: Correlating applications to appeal outcomes
    - Progressive Disclosure Stage 1: Broad exploration before detailed analysis

    PROGRESSIVE DISCLOSURE WORKFLOW:
    1. Use PTAB_search_appeals_minimal for discovery (this tool) - Get 50-100 candidates
    2. Present top results to user for selection
    3. Use PTAB_search_appeals_balanced for detailed analysis of selected appeals
    4. Use PTAB_get_documents for decision documents
    5. Use PTAB_get_document_download for browser-accessible PDFs

    RELATED TOOLS:
    - Next Step: PTAB_search_appeals_balanced (after user selects appeals from minimal results)
    - Documents: PTAB_get_documents (get decision documents for selected appeals)
    - Cross-MCP: PFW_search_applications_minimal (correlate to prosecution history)
    - Trials: PTAB_search_trials_minimal (if looking for IPR/PGR instead of ex parte appeals)

    CUSTOM FIELDS PARAMETER:
    All search tools support ultra-minimal mode via the 'fields' parameter:

    Example - Only 2 fields (99% context reduction):
      PTAB_search_appeals_minimal(
          art_unit='2128',
          fields=['appealNumber', 'decisionData.appealOutcomeCategory'],
          limit=100
      )

    This reduces token cost from ~20KB (preset minimal) to ~3KB (custom 2 fields).
    Use the FULL dotted path. A path the payload does not carry is dropped
    silently by the API, so it comes back reported in `fields_absent` rather
    than as an error; PTAB_get_field_configs lists the real ones.

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: PTAB_get_guidance(section='tools')
    - For field customization: PTAB_get_guidance(section='fields')
    - For PFW integration workflows: PTAB_get_guidance(section='workflows_pfw')
    - For context optimization: PTAB_get_guidance(section='cost')

    Args:
        appeal_number: Appeal number (2024-001234). 10 digits with or without
                      the hyphen, so an 8-digit patent or application number
                      passed here is rejected as a format error rather than
                      returning nothing.
        application_number: Application number (e.g., "17/888,602"). This is the APPLICATION
                      serial, not a patent number. An 8-digit granted patent
                      number passed here returns an EMPTY result that reads as
                      "no appeals exist" rather than an error; patent numbers
                      passed 10,000,000 in mid-2018, so the two namespaces now
                      collide at 8 digits. Map a patent number to its
                      application with the PFW MCP:
                      PFW_search_applications_minimal(query='patentNumber:<n>').
        appellant_name: Appellant/applicant name
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        art_unit: Art unit number
        fields: Optional custom field list (overrides predefined minimal set).
                Use dot notation for nested fields.
                Examples: ["appealNumber", "decisionDate"]
                If not provided, uses predefined "appeals_minimal" field set.
                NOTE: documentBag fields are forbidden (use PTAB_get_documents instead)
        limit: Maximum results (default 50, max 100)
        offset: Zero-based index of the first record to return (default 0).
                Page with the response's `paging.next_offset`; without it,
                results past the first page are unreachable.

    Returns:
        JSON string with filtered appeal data (minimal or custom field set)

    Example Response:
        {"data_type": "appeals", "field_set": "appeals_minimal",
         "count": 5, "results": [...], "context_reduction": {...}}
    """
    return await _run_appeal_search(
        "minimal",
        appeal_number=appeal_number,
        application_number=application_number,
        appellant_name=appellant_name,
        decision_date_from=decision_date_from,
        decision_date_to=decision_date_to,
        art_unit=art_unit,
        fields=fields, limit=limit, offset=offset,
    )


@mcp_tool_error_envelope
async def search_appeals_balanced(
    appeal_number: Optional[str] = None,
    application_number: Optional[str] = None,
    appellant_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    art_unit: Optional[str] = None,
    technology_center: Optional[str] = None,
    decision_type: Optional[str] = None,
    decision_outcome: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 20,
    offset: int = 0
) -> str:
    """Comprehensive ex parte appeal analysis after user selection (13.5% context reduction vs complete).
    Ex parte appeal, appeal of an examiner rejection, Board decision, affirmed, reversed, appellant, art unit, technology center.

    BASIC USAGE:
    - Core Purpose: Detailed analysis of user-selected appeals with comprehensive data
    - Returns: 20-30 fields per appeal (full appellant, appeal metadata,
      document metadata and decision bags, including the statutory issues
      decided). There is NO examiner, panel or claim-level data in the
      appeals payload at any tier: no examiner name, no judge names, and no
      claim-by-claim affirmed/reversed breakdown. Those live only in the text
      of the decision (PTAB_get_documents then PTAB_get_document_content).
    - Context Reduction: 13.5% vs complete tier (still efficient)
    - Typical Volume: 10-20 results for focused analysis

    WHEN TO USE THIS TOOL:
    - Post-Selection Analysis: After minimal search identifies candidates
    - Reversal Analysis: Outcome plus the statutory issues decided
      (decisionData.issueTypeBag: 102, 103, 112 and so on) across a set of appeals
    - Art Unit Quality Assessment: Understand reversal patterns by art unit
      and technology center
    - Progressive Disclosure Stage 2: After minimal discovery, before complete data

    PROGRESSIVE DISCLOSURE WORKFLOW:
    1. PTAB_search_appeals_minimal - Discovery (50-100 candidates)
    2. User selects appeals of interest
    3. PTAB_search_appeals_balanced (this tool) - Detailed analysis of 10-20 appeals
    4. PTAB_get_documents - Get decision documents if needed
    5. PTAB_search_appeals_complete - Only if balanced tier insufficient

    RELATED TOOLS:
    - Previous Step: PTAB_search_appeals_minimal (discovery phase)
    - Next Step: PTAB_get_documents (get decision documents) or PTAB_search_appeals_complete (full data)
    - Cross-MCP: PFW_search_applications_balanced (prosecution history with similar detail level)
    - Trials: PTAB_search_trials_balanced (if looking for IPR/PGR instead of ex parte appeals)

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: PTAB_get_guidance(section='tools')
    - For field customization: PTAB_get_guidance(section='fields')
    - For PFW integration workflows: PTAB_get_guidance(section='workflows_pfw')

    Args:
        appeal_number: Appeal number (2024-001234). 10 digits with or without
                      the hyphen, so an 8-digit patent or application number
                      passed here is rejected as a format error rather than
                      returning nothing.
        application_number: Application number. This is the APPLICATION
                      serial, not a patent number. An 8-digit granted patent
                      number passed here returns an EMPTY result that reads as
                      "no appeals exist" rather than an error; patent numbers
                      passed 10,000,000 in mid-2018, so the two namespaces now
                      collide at 8 digits. Map a patent number to its
                      application with the PFW MCP:
                      PFW_search_applications_minimal(query='patentNumber:<n>').
        appellant_name: Appellant party name
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        art_unit: Art unit number
        technology_center: Technology center number
        decision_type: Decision type
        decision_outcome: Decision outcome (Affirmed, Reversed, etc.)
        fields: Optional custom field list (overrides predefined balanced set).
                Use dot notation for nested fields.
                Examples: ["appealNumber", "decisionDate"]
                If not provided, uses predefined "appeals_balanced" field set.
                NOTE: documentBag fields are forbidden (use PTAB_get_documents instead)
        limit: Maximum results (default 20, max 100)
        offset: Zero-based index of the first record to return (default 0).
                Page with the response's `paging.next_offset`; without it,
                results past the first page are unreachable.

    Returns:
        JSON string with comprehensive appeal data (balanced or custom field set)
    """
    return await _run_appeal_search(
        "balanced",
        appeal_number=appeal_number,
        application_number=application_number,
        appellant_name=appellant_name,
        decision_date_from=decision_date_from,
        decision_date_to=decision_date_to,
        art_unit=art_unit,
        technology_center=technology_center,
        decision_type=decision_type,
        decision_outcome=decision_outcome,
        fields=fields, limit=limit, offset=offset,
    )


@mcp_tool_error_envelope
async def search_appeals_complete(
    appeal_number: Optional[str] = None,
    application_number: Optional[str] = None,
    appellant_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    art_unit: Optional[str] = None,
    technology_center: Optional[str] = None,
    decision_type: Optional[str] = None,
    decision_outcome: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 10,
    offset: int = 0
) -> str:
    """Complete ex parte appeal data access (no field filtering).
    Ex parte appeal, appeal of an examiner rejection, Board decision, affirmed, reversed, appellant, art unit, technology center.

    BASIC USAGE:
    - Core Purpose: Access all available appeal data fields for expert analysis
    - Returns: All fields from USPTO API (60-80 fields per appeal)
    - Context Reduction: Minimal (returns complete data)
    - Typical Volume: 1-10 appeals (use sparingly due to token cost)

    WHEN TO USE THIS TOOL:
    - Expert Analysis: Need obscure fields not in balanced tier
    - Data Export/Archiving: Complete appeal records for offline analysis
    - Custom Analysis: Exploring unknown fields for new use cases
    - Progressive Disclosure Stage 3: Only when minimal and balanced insufficient

    WHEN NOT TO USE:
    - Initial Discovery: Use PTAB_search_appeals_minimal instead
    - Routine Analysis: Use PTAB_search_appeals_balanced instead
    - Large Result Sets: Complete tier generates excessive tokens

    RELATED TOOLS:
    - Better Alternatives: PTAB_search_appeals_minimal or PTAB_search_appeals_balanced (95% of use cases)
    - Documents: PTAB_get_documents (for decision documents)
    - Cross-MCP: PFW_search_applications_complete (full prosecution data)
    - Trials: PTAB_search_trials_complete (if looking for IPR/PGR instead of ex parte appeals)

    GUIDANCE REFERENCES:
    - For progressive disclosure decision tree: PTAB_get_guidance(section='tools')
    - For field customization: PTAB_get_guidance(section='fields')

    Args:
        appeal_number: Appeal number (2024-001234). 10 digits with or without
                      the hyphen, so an 8-digit patent or application number
                      passed here is rejected as a format error rather than
                      returning nothing.
        application_number: Application number. This is the APPLICATION
                      serial, not a patent number. An 8-digit granted patent
                      number passed here returns an EMPTY result that reads as
                      "no appeals exist" rather than an error; patent numbers
                      passed 10,000,000 in mid-2018, so the two namespaces now
                      collide at 8 digits. Map a patent number to its
                      application with the PFW MCP:
                      PFW_search_applications_minimal(query='patentNumber:<n>').
        appellant_name: Appellant party name
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        art_unit: Art unit number
        technology_center: Technology center number
        decision_type: Decision type
        decision_outcome: Decision outcome (Affirmed, Reversed, etc.)
        fields: Optional custom field list (overrides predefined complete set).
                Use dot notation for nested fields.
                Examples: ["appealNumber", "decisionDate"]
                If not provided, uses predefined "appeals_complete" field set.
                NOTE: documentBag fields are forbidden (use PTAB_get_documents instead)
        limit: Maximum results (default 10, max 50)
        offset: Zero-based index of the first record to return (default 0).
                Page with the response's `paging.next_offset`; without it,
                results past the first page are unreachable.

    Returns:
        JSON string with complete appeal data (all fields or custom field set)
    """
    return await _run_appeal_search(
        "complete",
        appeal_number=appeal_number,
        application_number=application_number,
        appellant_name=appellant_name,
        decision_date_from=decision_date_from,
        decision_date_to=decision_date_to,
        art_unit=art_unit,
        technology_center=technology_center,
        decision_type=decision_type,
        decision_outcome=decision_outcome,
        fields=fields, limit=limit, offset=offset,
    )


def register(mcp) -> None:
    """Register the three appeal search tools (schemas unchanged; PTAB_ display names)."""
    for name, fn in (("PTAB_search_appeals_minimal", search_appeals_minimal),
                     ("PTAB_search_appeals_balanced", search_appeals_balanced),
                     ("PTAB_search_appeals_complete", search_appeals_complete)):
        mcp.tool(name=name, app=AppConfig(resource_uri=SEARCH_URI),
                 annotations={"defer_loading": True, "readOnlyHint": True})(fn)
