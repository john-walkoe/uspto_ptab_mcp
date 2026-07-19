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

@mcp_tool_error_envelope
async def search_appeals_minimal(
    appeal_number: Optional[str] = None,
    application_number: Optional[str] = None,
    appellant_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    art_unit: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 50
) -> str:
    """Ultra-minimal ex parte appeal discovery (95-99% context reduction).

    BASIC USAGE:
    - Core Purpose: Fast discovery of ex parte appeals to PTAB with essential fields only
    - Returns: 8-12 core fields per appeal (appealNumber, decision dates, examiner, outcome)
    - Context Reduction: 95-99% vs complete tier
    - Typical Volume: 50-100 results for examiner/art unit screening

    WHEN TO USE THIS TOOL:
    - Initial Discovery: Finding relevant ex parte appeals by examiner, art unit, or application
    - Examiner Pattern Analysis: Reviewing 50+ appeals to identify reversal trends
    - Application-to-Appeal Mapping: Correlating applications to appeal outcomes
    - Progressive Disclosure Stage 1: Broad exploration before detailed analysis

    PROGRESSIVE DISCLOSURE WORKFLOW:
    1. Use search_appeals_minimal for discovery (this tool) - Get 50-100 candidates
    2. Present top results to user for selection
    3. Use search_appeals_balanced for detailed analysis of selected appeals
    4. Use ptab_get_documents for decision documents
    5. Use ptab_get_document_download for browser-accessible PDFs

    RELATED TOOLS:
    - Next Step: search_appeals_balanced (after user selects appeals from minimal results)
    - Documents: ptab_get_documents (get decision documents for selected appeals)
    - Cross-MCP: pfw_search_applications_minimal (correlate to prosecution history)
    - Trials: search_trials_minimal (if looking for IPR/PGR instead of ex parte appeals)

    CUSTOM FIELDS PARAMETER:
    All search tools support ultra-minimal mode via the 'fields' parameter:

    Example - Only 2 fields (99% context reduction):
      search_appeals_minimal(
          art_unit='2128',
          fields=['appealNumber', 'decisionOutcome'],
          limit=100
      )

    This reduces token cost from ~20KB (preset minimal) to ~3KB (custom 2 fields).

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: ptab_get_guidance(section='tools')
    - For field customization: ptab_get_guidance(section='fields')
    - For PFW integration workflows: ptab_get_guidance(section='workflows_pfw')
    - For cost optimization: ptab_get_guidance(section='cost')

    Args:
        appeal_number: Appeal number (2024-001234)
        application_number: Application number (e.g., "16/123,456")
        appellant_name: Appellant/applicant name
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        art_unit: Art unit number
        fields: Optional custom field list (overrides predefined minimal set).
                Use dot notation for nested fields.
                Examples: ["appealNumber", "decisionDate"]
                If not provided, uses predefined "appeals_minimal" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 50, max 100)

    Returns:
        JSON string with filtered appeal data (minimal or custom field set)

    Example Response:
        {"data_type": "appeals", "field_set": "appeals_minimal",
         "count": 5, "results": [...], "context_reduction": {...}}
    """
    api_client = _client()

    # Validate inputs
    if appeal_number:
        appeal_number = validate_appeal_number(appeal_number)

    if decision_date_from or decision_date_to:
        decision_date_from, decision_date_to = validate_date_range(
            decision_date_from, decision_date_to
        )

    if appellant_name:
        appellant_name = validate_party_name(appellant_name)

    limit = validate_limit(limit, max_limit=100)

    # Build filters using FilterBuilder pattern

    filters, range_filters = (FilterBuilder()
        .add_if(AppealFilterFields.APPEAL_NUMBER, appeal_number)
        .add_if(AppealFilterFields.APPLICATION_NUMBER, application_number)
        .add_if(AppealFilterFields.APPELLANT_NAME, appellant_name)
        .add_if(AppealFilterFields.ART_UNIT, art_unit)
        .add_range_if(AppealFilterFields.DECISION_DATE, decision_date_from, decision_date_to)
        .build())

    return await run_search(
        proceeding="appeals", tier="minimal",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit,
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
    limit: int = 20
) -> str:
    """Comprehensive ex parte appeal analysis after user selection (13.5% context reduction vs complete).

    BASIC USAGE:
    - Core Purpose: Detailed analysis of user-selected appeals with comprehensive data
    - Returns: 20-30 fields per appeal (all examiner, panel, decision, claim data)
    - Context Reduction: 13.5% vs complete tier (still efficient)
    - Typical Volume: 10-20 results for focused analysis

    WHEN TO USE THIS TOOL:
    - Post-Selection Analysis: After minimal search identifies candidates
    - Examiner Reversal Analysis: Need panel members, decision reasoning, claim-by-claim outcomes
    - Art Unit Quality Assessment: Understand reversal patterns and examiner performance
    - Progressive Disclosure Stage 2: After minimal discovery, before complete data

    PROGRESSIVE DISCLOSURE WORKFLOW:
    1. search_appeals_minimal - Discovery (50-100 candidates)
    2. User selects appeals of interest
    3. search_appeals_balanced (this tool) - Detailed analysis of 10-20 appeals
    4. ptab_get_documents - Get decision documents if needed
    5. search_appeals_complete - Only if balanced tier insufficient

    RELATED TOOLS:
    - Previous Step: search_appeals_minimal (discovery phase)
    - Next Step: ptab_get_documents (get decision documents) or search_appeals_complete (full data)
    - Cross-MCP: pfw_search_applications_balanced (prosecution history with similar detail level)
    - Trials: search_trials_balanced (if looking for IPR/PGR instead of ex parte appeals)

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: ptab_get_guidance(section='tools')
    - For field customization: ptab_get_guidance(section='fields')
    - For PFW integration workflows: ptab_get_guidance(section='workflows_pfw')

    Args:
        appeal_number: Appeal number (2024-001234)
        application_number: Application number
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
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 20, max 100)

    Returns:
        JSON string with comprehensive appeal data (balanced or custom field set)
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

    limit = validate_limit(limit, max_limit=100)

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
        proceeding="appeals", tier="balanced",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit,
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
    limit: int = 10
) -> str:
    """Complete ex parte appeal data access (no field filtering).

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
    - Initial Discovery: Use search_appeals_minimal instead
    - Routine Analysis: Use search_appeals_balanced instead
    - Large Result Sets: Complete tier generates excessive tokens

    RELATED TOOLS:
    - Better Alternatives: search_appeals_minimal or search_appeals_balanced (95% of use cases)
    - Documents: ptab_get_documents (for decision documents)
    - Cross-MCP: pfw_search_applications_complete (full prosecution data)
    - Trials: search_trials_complete (if looking for IPR/PGR instead of ex parte appeals)

    GUIDANCE REFERENCES:
    - For progressive disclosure decision tree: ptab_get_guidance(section='tools')
    - For field customization: ptab_get_guidance(section='fields')

    Args:
        appeal_number: Appeal number (2024-001234)
        application_number: Application number
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
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 10, max 50)

    Returns:
        JSON string with complete appeal data (all fields or custom field set)
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

    limit = validate_limit(limit, max_limit=100)

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
        proceeding="appeals", tier="complete",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit,
    )


def register(mcp) -> None:
    """Register the three appeal search tools (names/schemas unchanged)."""
    for fn in (search_appeals_minimal, search_appeals_balanced, search_appeals_complete):
        mcp.tool(app=AppConfig(resource_uri=SEARCH_URI),
                 annotations={"defer_loading": True, "readOnlyHint": True})(fn)
