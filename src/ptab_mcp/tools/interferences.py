"""Interference search tools — minimal/balanced/complete tiers."""

from typing import List, Optional

from fastmcp.apps import AppConfig

from ..app_uris import SEARCH_URI
from ..config.filter_field_mapping import InterferenceFilterFields
from ..runtime import _client, field_manager
from ..shared.safe_logger import get_safe_logger
from ..util.filter_builder import FilterBuilder
from ..util.search_runner import mcp_tool_error_envelope, run_search
from ..validation.validators import (
    validate_date_range,
    validate_interference_number,
    validate_limit,
    validate_party_name,
    validate_patent_number,
)

logger = get_safe_logger(__name__)

@mcp_tool_error_envelope
async def search_interferences_minimal(
    interference_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    party_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 50
) -> str:
    """Ultra-minimal interference proceeding discovery (95-99% context reduction).

    BASIC USAGE:
    - Core Purpose: Fast discovery of patent interference proceedings with essential fields only
    - Returns: 6-10 core fields per interference (number, parties, patent, decision date)
    - Context Reduction: 95-99% vs complete tier
    - Typical Volume: 50-100 results for priority dispute research

    WHEN TO USE THIS TOOL:
    - Initial Discovery: Finding relevant interference proceedings by patent or party
    - Priority Dispute Research: Identifying cases involving invention priority
    - Historical Analysis: Reviewing legacy interference proceedings (pre-AIA)
    - Progressive Disclosure Stage 1: Broad exploration before detailed analysis

    PROGRESSIVE DISCLOSURE WORKFLOW:
    1. Use search_interferences_minimal for discovery (this tool) - Get 50-100 candidates
    2. Present top results to user for selection
    3. Use search_interferences_balanced for detailed analysis of selected interferences
    4. Use ptab_get_documents for decision documents
    5. Use ptab_get_document_download for browser-accessible PDFs

    RELATED TOOLS:
    - Next Step: search_interferences_balanced (after user selects interferences from minimal results)
    - Documents: ptab_get_documents (get decision documents for selected interferences)
    - Cross-MCP: pfw_search_applications_minimal (correlate to prosecution history)
    - Trials: search_trials_minimal (if looking for IPR/PGR instead of interferences)

    CUSTOM FIELDS PARAMETER:
    All search tools support ultra-minimal mode via the 'fields' parameter:

    Example - Only 2 fields (99% context reduction):
      search_interferences_minimal(
          patent_number='8524787',
          fields=['interferenceNumber', 'decisionDate'],
          limit=100
      )

    This reduces token cost from ~15KB (preset minimal) to ~3KB (custom 2 fields).

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: ptab_get_guidance(section='tools')
    - For field customization: ptab_get_guidance(section='fields')
    - For cost optimization: ptab_get_guidance(section='cost')

    Args:
        interference_number: Interference number (106,123)
        patent_number: Patent number (8524787, US8524787, etc.)
        party_name: Party name (senior/junior party)
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        fields: Optional custom field list (overrides predefined minimal set).
                Use dot notation for nested fields.
                Examples: ["interferenceNumber", "decisionDate"]
                If not provided, uses predefined "interferences_minimal" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 50, max 100)

    Returns:
        JSON string with filtered interference data (minimal or custom field set)

    Example Response:
        {"data_type": "interferences", "field_set": "interferences_minimal",
         "count": 2, "results": [...], "context_reduction": {...}}
    """
    api_client = _client()

    # Validate inputs
    if interference_number:
        interference_number = validate_interference_number(interference_number)

    if patent_number:
        patent_number = validate_patent_number(patent_number)

    if party_name:
        party_name = validate_party_name(party_name)

    if decision_date_from or decision_date_to:
        decision_date_from, decision_date_to = validate_date_range(
            decision_date_from, decision_date_to
        )

    limit = validate_limit(limit, max_limit=100)

    # Build filters using FilterBuilder pattern

    filters, range_filters = (FilterBuilder()
        .add_if(InterferenceFilterFields.INTERFERENCE_NUMBER, interference_number)
        # Note: Interferences have separate senior/junior fields
        # Searching senior party by default (can add junior search if needed)
        .add_if(InterferenceFilterFields.SENIOR_PATENT_NUMBER, patent_number)
        .add_if(InterferenceFilterFields.SENIOR_PARTY_NAME, party_name)
        # Note: Interferences use DECLARATION_DATE instead of DECISION_DATE
        .add_range_if(InterferenceFilterFields.DECLARATION_DATE, decision_date_from, decision_date_to)
        .build())

    return await run_search(
        proceeding="interferences", tier="minimal",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit,
    )


@mcp_tool_error_envelope
async def search_interferences_balanced(
    interference_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    party_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    technology_center: Optional[str] = None,
    senior_party: Optional[str] = None,
    junior_party: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 20
) -> str:
    """Comprehensive interference analysis after user selection (13.5% context reduction vs complete).

    BASIC USAGE:
    - Core Purpose: Detailed analysis of user-selected interferences with comprehensive data
    - Returns: 15-25 fields per interference (all party, patent, decision, tech center data)
    - Context Reduction: 13.5% vs complete tier (still efficient)
    - Typical Volume: 10-20 results for focused analysis

    WHEN TO USE THIS TOOL:
    - Post-Selection Analysis: After minimal search identifies candidates
    - Priority Determination: Need senior/junior party details, decision reasoning
    - Historical Research: Understand pre-AIA interference patterns
    - Progressive Disclosure Stage 2: After minimal discovery, before complete data

    PROGRESSIVE DISCLOSURE WORKFLOW:
    1. search_interferences_minimal - Discovery (50-100 candidates)
    2. User selects interferences of interest
    3. search_interferences_balanced (this tool) - Detailed analysis of 10-20 interferences
    4. ptab_get_documents - Get decision documents if needed
    5. search_interferences_complete - Only if balanced tier insufficient

    RELATED TOOLS:
    - Previous Step: search_interferences_minimal (discovery phase)
    - Next Step: ptab_get_documents (get decision documents) or search_interferences_complete (full data)
    - Cross-MCP: pfw_search_applications_balanced (prosecution history with similar detail level)
    - Trials: search_trials_balanced (if looking for IPR/PGR instead of interferences)

    GUIDANCE REFERENCES:
    - For progressive disclosure strategy: ptab_get_guidance(section='tools')
    - For field customization: ptab_get_guidance(section='fields')

    Args:
        interference_number: Interference number (106,123)
        patent_number: Patent number (8524787)
        party_name: Party name (senior/junior party)
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        technology_center: Technology center number
        senior_party: Senior party name
        junior_party: Junior party name
        fields: Optional custom field list (overrides predefined balanced set).
                Use dot notation for nested fields.
                Examples: ["interferenceNumber", "decisionDate"]
                If not provided, uses predefined "interferences_balanced" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 20, max 100)

    Returns:
        JSON string with comprehensive interference data (balanced or custom field set)
    """
    api_client = _client()

    # Validate inputs
    if interference_number:
        interference_number = validate_interference_number(interference_number)

    if patent_number:
        patent_number = validate_patent_number(patent_number)

    if party_name:
        party_name = validate_party_name(party_name)

    if senior_party:
        senior_party = validate_party_name(senior_party)

    if junior_party:
        junior_party = validate_party_name(junior_party)

    if decision_date_from or decision_date_to:
        decision_date_from, decision_date_to = validate_date_range(
            decision_date_from, decision_date_to
        )

    limit = validate_limit(limit, max_limit=100)

    # Build filters using FilterBuilder pattern

    filters, range_filters = (FilterBuilder()
        .add_if(InterferenceFilterFields.INTERFERENCE_NUMBER, interference_number)
        # Note: Interferences have separate senior/junior patent fields
        .add_if(InterferenceFilterFields.SENIOR_PATENT_NUMBER, patent_number)
        # Note: Using SENIOR_PARTY_NAME (not PARTY_NAME which doesn't exist)
        .add_if(InterferenceFilterFields.SENIOR_PARTY_NAME, party_name)
        # Note: Using SENIOR_TECH_CENTER (interferences have separate senior/junior tech centers)
        .add_if(InterferenceFilterFields.SENIOR_TECH_CENTER, technology_center)
        .add_if(InterferenceFilterFields.SENIOR_PARTY_NAME, senior_party)
        .add_if(InterferenceFilterFields.JUNIOR_PARTY_NAME, junior_party)
        # Note: Interferences use DECLARATION_DATE instead of DECISION_DATE
        .add_range_if(InterferenceFilterFields.DECLARATION_DATE, decision_date_from, decision_date_to)
        .build())

    return await run_search(
        proceeding="interferences", tier="balanced",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit,
    )


@mcp_tool_error_envelope
async def search_interferences_complete(
    interference_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    party_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    technology_center: Optional[str] = None,
    senior_party: Optional[str] = None,
    junior_party: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: int = 10
) -> str:
    """Complete interference data access (no field filtering).

    BASIC USAGE:
    - Core Purpose: Access all available interference data fields for expert analysis
    - Returns: All fields from USPTO API (40-60 fields per interference)
    - Context Reduction: Minimal (returns complete data)
    - Typical Volume: 1-10 interferences (use sparingly due to token cost)

    WHEN TO USE THIS TOOL:
    - Expert Analysis: Need obscure fields not in balanced tier
    - Data Export/Archiving: Complete interference records for offline analysis
    - Custom Analysis: Exploring unknown fields for new use cases
    - Progressive Disclosure Stage 3: Only when minimal and balanced insufficient

    WHEN NOT TO USE:
    - Initial Discovery: Use search_interferences_minimal instead
    - Routine Analysis: Use search_interferences_balanced instead
    - Large Result Sets: Complete tier generates excessive tokens

    RELATED TOOLS:
    - Better Alternatives: search_interferences_minimal or search_interferences_balanced (95% of use cases)
    - Documents: ptab_get_documents (for decision documents)
    - Cross-MCP: pfw_search_applications_complete (full prosecution data)
    - Trials: search_trials_complete (if looking for IPR/PGR instead of interferences)

    GUIDANCE REFERENCES:
    - For progressive disclosure decision tree: ptab_get_guidance(section='tools')
    - For field customization: ptab_get_guidance(section='fields')

    Args:
        interference_number: Interference number (106,123)
        patent_number: Patent number (8524787)
        party_name: Party name (senior/junior party)
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        technology_center: Technology center number
        senior_party: Senior party name
        junior_party: Junior party name
        fields: Optional custom field list (overrides predefined complete set).
                Use dot notation for nested fields.
                Examples: ["interferenceNumber", "decisionDate"]
                If not provided, uses predefined "interferences_complete" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 10, max 50)

    Returns:
        JSON string with complete interference data (all fields or custom field set)
    """
    api_client = _client()

    # Validate inputs
    if interference_number:
        interference_number = validate_interference_number(interference_number)

    if patent_number:
        patent_number = validate_patent_number(patent_number)

    if party_name:
        party_name = validate_party_name(party_name)

    if senior_party:
        senior_party = validate_party_name(senior_party)

    if junior_party:
        junior_party = validate_party_name(junior_party)

    if decision_date_from or decision_date_to:
        decision_date_from, decision_date_to = validate_date_range(
            decision_date_from, decision_date_to
        )

    limit = validate_limit(limit, max_limit=100)

    # Build filters using FilterBuilder pattern

    filters, range_filters = (FilterBuilder()
        .add_if(InterferenceFilterFields.INTERFERENCE_NUMBER, interference_number)
        # Note: Interferences have separate senior/junior patent fields
        .add_if(InterferenceFilterFields.SENIOR_PATENT_NUMBER, patent_number)
        # Note: Using SENIOR_PARTY_NAME (not PARTY_NAME which doesn't exist)
        .add_if(InterferenceFilterFields.SENIOR_PARTY_NAME, party_name)
        # Note: Using SENIOR_TECH_CENTER (interferences have separate senior/junior tech centers)
        .add_if(InterferenceFilterFields.SENIOR_TECH_CENTER, technology_center)
        .add_if(InterferenceFilterFields.SENIOR_PARTY_NAME, senior_party)
        .add_if(InterferenceFilterFields.JUNIOR_PARTY_NAME, junior_party)
        # Note: Interferences use DECLARATION_DATE instead of DECISION_DATE
        .add_range_if(InterferenceFilterFields.DECLARATION_DATE, decision_date_from, decision_date_to)
        .build())

    return await run_search(
        proceeding="interferences", tier="complete",
        client=api_client, field_manager=field_manager,
        filters=filters, range_filters=range_filters,
        fields=fields, limit=limit,
    )


def register(mcp) -> None:
    """Register the three interference search tools (names/schemas unchanged)."""
    for fn in (search_interferences_minimal, search_interferences_balanced,
               search_interferences_complete):
        mcp.tool(app=AppConfig(resource_uri=SEARCH_URI),
                 annotations={"defer_loading": True, "readOnlyHint": True})(fn)
