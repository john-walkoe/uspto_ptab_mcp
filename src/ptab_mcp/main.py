"""
USPTO PTAB MCP Server - FastMCP Implementation

Provides access to USPTO Patent Trial and Appeal Board (PTAB) data via the Open Data Portal API.
Implements progressive disclosure through tiered field configurations (minimal, balanced, complete).

Core Tools:
- 3 Trials Search Tools: search_trials_minimal/balanced/complete
- 3 Shared Document Tools: ptab_get_documents/download/content (work for all identifier types)
"""

from mcp.server.fastmcp import FastMCP
from .api.ptab_client import PTABClient
from .config.settings import Settings
from .config.field_manager import FieldManager
from .config.tool_reflections import get_guidance_section
from .util.response_formatter import (
    format_trial_response,
    format_document_list,
    format_error_response,
    create_query_info
)
from .validation.validators import (
    validate_trial_number,
    validate_patent_number,
    validate_date_range,
    validate_party_name,
    validate_trial_type,
    validate_limit,
    validate_identifier_type,
    validate_appeal_number,
    validate_interference_number,
    validate_custom_fields
)
from .proxy.centralized_integration import (
    register_with_centralized_proxy,
    generate_enhanced_filename
)
from .services.ocr_service import OCRService
from .shared.safe_logger import get_safe_logger
import json
import logging
from typing import Optional, List
from datetime import datetime
from pathlib import Path
import os
import sys
import asyncio
import time
import requests

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = get_safe_logger(__name__)

# =============================================================================
# SERVER INSTRUCTIONS FOR TOOL SEARCH OPTIMIZATION
# =============================================================================
# These instructions guide Claude on tool usage patterns when tool search is enabled.
# With tool search, most tools are deferred (loaded on-demand) to save context tokens.
# The instructions help Claude discover and use the right tools efficiently.

SERVER_INSTRUCTIONS = """
PTAB MCP provides USPTO Patent Trial and Appeal Board data through 15 tools.

ALWAYS-AVAILABLE TOOLS (non-deferred, immediate access):
1. search_trials_minimal - Primary discovery for IPR/PGR/CBM proceedings
2. ptab_get_guidance - Workflow guidance and documentation (use section parameter)
3. ptab_get_documents - Document lists for trials/appeals/interferences

PROGRESSIVE WORKFLOW:
1. Discovery: Use search_trials_minimal (or appeals/interferences variants)
2. Analysis: Search for balanced/complete tools for detailed data
3. Documents: Use ptab_get_documents to list available documents
4. Content: Search for ptab_get_document_content (OCR extraction) or ptab_get_document_download

TOOL CATEGORIES TO SEARCH:
- Trial search tools: "search_trials" (minimal/balanced/complete tiers)
- Appeal search tools: "search_appeals" (minimal/balanced/complete tiers)
- Interference search tools: "search_interferences" (minimal/balanced/complete tiers)
- Document tools: "document" (get_documents, download, content extraction)
- Utility tools: "field_configs", "validate_identifiers"

For workflow guidance, call: ptab_get_guidance(section="tools")
For cross-MCP integration: ptab_get_guidance(section="workflows_pfw")
"""

# Initialize FastMCP with server instructions for tool search optimization
mcp = FastMCP("ptab-mcp", instructions=SERVER_INSTRUCTIONS)

# Initialize components
settings = Settings()

# Load API keys from secure storage if not in environment variables (DPAPI mode)
if not settings.uspto_api_key:
    from .shared_secure_storage import get_uspto_api_key
    settings.uspto_api_key = get_uspto_api_key()
    if settings.uspto_api_key:
        logger.info("Loaded USPTO API key from DPAPI secure storage")

if not settings.mistral_api_key:
    from .shared_secure_storage import get_mistral_api_key
    settings.mistral_api_key = get_mistral_api_key()
    if settings.mistral_api_key:
        logger.info("Loaded Mistral API key from DPAPI secure storage")

# Validate that we have the required USPTO API key
if not settings.uspto_api_key:
    logger.error("USPTO API key not found in environment variables or secure storage!")
    logger.error("Please run: ./deploy/windows_setup.ps1 to configure API keys")
    sys.exit(1)

api_client = PTABClient(api_key=settings.uspto_api_key)


def get_api_client() -> PTABClient:
    """
    Lazily initialize and return the API client.

    This ensures the client is properly initialized even in complex async contexts
    where the event loop lifecycle may vary between MCP clients.

    Returns:
        PTABClient instance
    """
    global api_client
    if api_client is None:
        logger.info("Initializing PTAB API client")
        api_client = PTABClient(api_key=settings.uspto_api_key)
    return api_client


# Initialize field manager with config path
config_path = Path(__file__).parent.parent.parent / "field_configs.yaml"
field_manager = FieldManager(config_path=config_path)

# Initialize OCR service for document content extraction
ocr_service = OCRService()

logger.info("PTAB MCP Server initialized with FastMCP")
logger.info(f"Field configuration loaded from: {config_path}")
if ocr_service.mistral_api_key:
    logger.info("Mistral OCR service configured and ready")
else:
    logger.warning("Mistral API key not configured - OCR extraction unavailable")

# Register prompt templates
from .prompts import register_prompts
register_prompts(mcp)
logger.info("Registered 11 PTAB workflow prompt templates")

# Global state for proxy server management
_proxy_server_running = False
_proxy_server_task = None
_proxy_startup_lock = asyncio.Lock()  # Prevents concurrent proxy startup attempts


# =============================================================================
# PROXY PORT CONFIGURATION
# =============================================================================

def get_local_proxy_port() -> int:
    """
    Safely parse local proxy port from environment variables.

    Checks PTAB_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic).
    Handles special value "none" which indicates no proxy configured.

    Returns:
        int: Proxy port number (default: 8083)
    """
    port_str = os.getenv('PTAB_PROXY_PORT') or os.getenv('PROXY_PORT') or '8083'

    # CRITICAL: Handle "none" sentinel value BEFORE int conversion
    if port_str.lower() == 'none':
        return 8083

    try:
        return int(port_str)
    except ValueError:
        logger.warning(f"Invalid proxy port value '{port_str}', using default 8083")
        return 8083


# ==========================================
# TRIALS SEARCH TOOLS (3 tools)
# ==========================================

@mcp.tool()
async def search_trials_minimal(
    trial_number: Optional[str] = None,
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
        trial_number: Trial number (IPR2024-00123, PGR2025-00045, CBM2023-00001)
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
        limit: Maximum results (default 50, max 100)

    Returns:
        JSON string with filtered trial data (minimal or custom field set)

    Example:
        {"data_type": "trials", "field_set": "trials_minimal",
         "count": 2, "results": [...], "context_reduction": {...}}
    """
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for trial search")
            api_client = get_api_client()

        # Validate inputs
        if trial_number:
            trial_number = validate_trial_number(trial_number)

        if patent_number:
            patent_number = validate_patent_number(patent_number)

        if petitioner_name:
            petitioner_name = validate_party_name(petitioner_name)

        if patent_owner_name:
            patent_owner_name = validate_party_name(patent_owner_name)

        if filing_date_from or filing_date_to:
            filing_date_from, filing_date_to = validate_date_range(filing_date_from, filing_date_to)

        if trial_type:
            trial_type = validate_trial_type(trial_type)

        limit = validate_limit(limit, max_limit=100)

        # Build filters using FilterBuilder pattern
        from .util.filter_builder import FilterBuilder
        from .config.filter_field_mapping import TrialFilterFields as Fields

        filters, range_filters = (FilterBuilder()
            .add_if(Fields.TRIAL_NUMBER, trial_number)
            .add_if(Fields.PATENT_NUMBER, patent_number)
            .add_if(Fields.PETITIONER_NAME, petitioner_name)
            .add_if(Fields.PATENT_OWNER_NAME, patent_owner_name)
            .add_if(Fields.TRIAL_TYPE, trial_type)
            .add_if(Fields.TRIAL_STATUS, trial_status)
            .add_if(Fields.TECH_CENTER, tech_center)
            .add_range_if(Fields.FILING_DATE, filing_date_from, filing_date_to)
            .build())

        # Handle custom fields vs predefined field set
        if fields:
            # User specified custom fields - validate and use those
            fields = validate_custom_fields(fields)
            field_list = fields
            field_set_name = "custom"
        else:
            # No custom fields - use predefined tier
            field_list = field_manager.get_fields("trials_minimal")
            field_set_name = "trials_minimal"

        # Make API call
        raw_response = await api_client.search_trials(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Filter response (custom fields vs predefined set)
        if fields:
            # Custom fields - use filter_response_custom()
            filtered_response = field_manager.filter_response_custom(
                raw_response,
                fields
            )
        else:
            # Predefined tier - use standard filtering
            filtered_response = field_manager.filter_response(
                raw_response,
                field_set_name
            )

        # Format for output
        formatted = format_trial_response(
            trials=filtered_response.get("patentTrialProceedingDataBag", []),
            query_info=create_query_info(
                filters=filters,
                range_filters=range_filters,
                pagination={"offset": 0, "limit": limit}
            ),
            field_set=field_set_name,
            context_info=filtered_response.get("context_info"),
            count=filtered_response.get("count", 0)
        )

        return formatted

    except ValueError as e:
        # Validation error
        return format_error_response(str(e), "VALIDATION_ERROR")
    except Exception as e:
        # Unexpected error
        logger.error(f"Error in search_trials_minimal: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


@mcp.tool()
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
    examiner_name: Optional[str] = None,
    art_unit: Optional[str] = None,
    assignee_name: Optional[str] = None,
    petitioner_counsel: Optional[str] = None,
    patent_owner_counsel: Optional[str] = None,
    decision_outcome: Optional[str] = None,
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
        examiner_name: Examiner name
        art_unit: Art unit number
        assignee_name: Assignee name
        petitioner_counsel: Petitioner counsel name
        patent_owner_counsel: Patent owner counsel name
        decision_outcome: Decision outcome
        fields: Optional custom field list (overrides predefined balanced set).
                Use dot notation for nested fields.
                Examples: ["trialNumber", "trialMetaData.trialStatusCategory"]
                If not provided, uses predefined "trials_balanced" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 20, max 100)

    Returns:
        JSON string with comprehensive trial data (balanced or custom field set)
    """
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for trial search")
            api_client = get_api_client()

        # Validate inputs
        if trial_number:
            trial_number = validate_trial_number(trial_number)

        if patent_number:
            patent_number = validate_patent_number(patent_number)

        if petitioner_name:
            petitioner_name = validate_party_name(petitioner_name)

        if patent_owner_name:
            patent_owner_name = validate_party_name(patent_owner_name)

        if assignee_name:
            assignee_name = validate_party_name(assignee_name)

        if filing_date_from or filing_date_to:
            filing_date_from, filing_date_to = validate_date_range(filing_date_from, filing_date_to)

        if institution_date_from or institution_date_to:
            institution_date_from, institution_date_to = validate_date_range(
                institution_date_from, institution_date_to
            )

        if final_decision_date_from or final_decision_date_to:
            final_decision_date_from, final_decision_date_to = validate_date_range(
                final_decision_date_from, final_decision_date_to
            )

        if trial_type:
            trial_type = validate_trial_type(trial_type)

        limit = validate_limit(limit, max_limit=100)

        # Build filters using FilterBuilder pattern
        from .util.filter_builder import FilterBuilder
        from .config.filter_field_mapping import TrialFilterFields as Fields

        filters, range_filters = (FilterBuilder()
            .add_if(Fields.TRIAL_NUMBER, trial_number)
            .add_if(Fields.PATENT_NUMBER, patent_number)
            .add_if(Fields.PETITIONER_NAME, petitioner_name)
            .add_if(Fields.PATENT_OWNER_NAME, patent_owner_name)
            .add_if(Fields.TRIAL_TYPE, trial_type)
            .add_if(Fields.TRIAL_STATUS, trial_status)
            .add_if(Fields.TECH_CENTER, tech_center)
            .add_if(Fields.EXAMINER_NAME, examiner_name)
            .add_if(Fields.ART_UNIT, art_unit)
            .add_if(Fields.ASSIGNEE_NAME, assignee_name)
            .add_if(Fields.PETITIONER_COUNSEL, petitioner_counsel)
            .add_if(Fields.PATENT_OWNER_COUNSEL, patent_owner_counsel)
            .add_if(Fields.DECISION_OUTCOME, decision_outcome)
            .add_range_if(Fields.FILING_DATE, filing_date_from, filing_date_to)
            .add_range_if(Fields.INSTITUTION_DATE, institution_date_from, institution_date_to)
            .add_range_if(Fields.FINAL_DECISION_DATE, final_decision_date_from, final_decision_date_to)
            .build())

        # Handle custom fields vs predefined field set
        if fields:
            # User specified custom fields - validate and use those
            fields = validate_custom_fields(fields)
            field_list = fields
            field_set_name = "custom"
        else:
            # No custom fields - use predefined tier
            field_list = field_manager.get_fields("trials_balanced")
            field_set_name = "trials_balanced"

        # Make API call
        raw_response = await api_client.search_trials(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Filter response (custom fields vs predefined set)
        if fields:
            # Custom fields - use filter_response_custom()
            filtered_response = field_manager.filter_response_custom(
                raw_response,
                fields
            )
        else:
            # Predefined tier - use standard filtering
            filtered_response = field_manager.filter_response(
                raw_response,
                field_set_name
            )

        # Format output
        formatted = format_trial_response(
            trials=filtered_response.get("patentTrialProceedingDataBag", []),
            query_info=create_query_info(
                filters=filters,
                range_filters=range_filters,
                pagination={"offset": 0, "limit": limit}
            ),
            field_set=field_set_name,
            context_info=filtered_response.get("context_info"),
            count=filtered_response.get("count", 0)
        )

        return formatted

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except Exception as e:
        logger.error(f"Error in search_trials_balanced: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


@mcp.tool()
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
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for trial search")
            api_client = get_api_client()

        # Validate inputs (same as minimal)
        if trial_number:
            trial_number = validate_trial_number(trial_number)

        if patent_number:
            patent_number = validate_patent_number(patent_number)

        if petitioner_name:
            petitioner_name = validate_party_name(petitioner_name)

        if patent_owner_name:
            patent_owner_name = validate_party_name(patent_owner_name)

        if filing_date_from or filing_date_to:
            filing_date_from, filing_date_to = validate_date_range(filing_date_from, filing_date_to)

        if trial_type:
            trial_type = validate_trial_type(trial_type)

        limit = validate_limit(limit, max_limit=50)  # Lower limit for complete data

        # Build filters using FilterBuilder pattern
        from .util.filter_builder import FilterBuilder
        from .config.filter_field_mapping import TrialFilterFields as Fields

        filters, range_filters = (FilterBuilder()
            .add_if(Fields.TRIAL_NUMBER, trial_number)
            .add_if(Fields.PATENT_NUMBER, patent_number)
            .add_if(Fields.PETITIONER_NAME, petitioner_name)
            .add_if(Fields.PATENT_OWNER_NAME, patent_owner_name)
            .add_if(Fields.TRIAL_TYPE, trial_type)
            .add_if(Fields.TRIAL_STATUS, trial_status)
            .add_range_if(Fields.FILING_DATE, filing_date_from, filing_date_to)
            .build())

        # Handle custom fields vs predefined field set
        if fields:
            # User specified custom fields - validate and use those
            fields = validate_custom_fields(fields)
            field_list = fields
            field_set_name = "custom"
        else:
            # No custom fields - use predefined tier
            field_list = field_manager.get_fields("trials_complete")
            field_set_name = "trials_complete"

        # Make API call
        raw_response = await api_client.search_trials(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Filter response (custom fields vs predefined set)
        if fields:
            # Custom fields - use filter_response_custom()
            filtered_response = field_manager.filter_response_custom(
                raw_response,
                fields
            )
        else:
            # Predefined tier - use standard filtering
            filtered_response = field_manager.filter_response(
                raw_response,
                field_set_name
            )

        # Format output
        formatted = format_trial_response(
            trials=filtered_response.get("patentTrialProceedingDataBag", []),
            query_info=create_query_info(
                filters=filters,
                range_filters=range_filters,
                pagination={"offset": 0, "limit": limit}
            ),
            field_set=field_set_name,
            context_info=filtered_response.get("context_info"),
            count=filtered_response.get("count", 0)
        )

        return formatted

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except Exception as e:
        logger.error(f"Error in search_trials_complete: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


# ==========================================
# SHARED DOCUMENT TOOLS (3 tools - work for all identifier types)
# ==========================================

@mcp.tool()
async def ptab_get_documents(
    identifier: str,
    identifier_type: str = "trial",
    limit: int = 50,
    offset: int = 0,
    sort_order: str = "desc",
    document_title: Optional[str] = None,
    document_category: Optional[str] = None,
    filing_party: Optional[str] = None,
    outcome_category: Optional[str] = None
) -> str:
    """Get list of documents for trial, appeal, or interference with SELECTIVE FILTERING.

    ⚠️ CRITICAL: For proceedings with 50+ documents, ALWAYS use filtering parameters.
    Requesting all documents without filters can cause massive token usage.

    PREREQUISITE: Must have valid trial/appeal/interference identifier from search results.

    📋 FILTERING PARAMETERS:

    **limit** - Max documents to return (default: 50, max: 200). Applied AFTER filtering.

    **offset** - Skip the first N documents after sorting (default: 0, client-side).
      Applied after sort_order so results are consistent.
      Example: sort_order='asc', offset=5, limit=10 → documents 6-15 oldest-first.

    **sort_order** - Sort direction applied client-side to the API response (default: "desc"):
      - "desc": Newest first (default — same as previous behavior)
      - "asc": Oldest first — surfaces the Petition, POPR, Institution Decision,
               and early exhibits which the API returns last in default order.
      NOTE: The USPTO documents endpoint does not support server-side sort/pagination
      query params. sort_order and offset operate on whatever the API returns (~25 docs).

    RETRIEVING EARLY DOCUMENTS (Petition, POPR, Institution Decision):
      # Oldest documents first — Petition, POPR, early exhibits
      ptab_get_documents(identifier='IPR2024-01353', sort_order='asc', limit=25)
      # Skip first 5 oldest, get next 10
      ptab_get_documents(identifier='IPR2024-01353', sort_order='asc', offset=5, limit=10)

    **document_title** - Case-insensitive substring filter on documentTypeDescriptionText.
      The API returns a plain-text description for each document (e.g. "Final Written Decision",
      "Institution Decision on Petition", "Petition for Inter Partes Review"). This filter
      matches any document whose description contains the supplied string.
      More precise than document_category — use it to target a single document type.
      Examples:
        ptab_get_documents(identifier='IPR2024-01353', document_title='Final Written Decision')
        ptab_get_documents(identifier='IPR2024-01353', document_title='Institution Decision')
        ptab_get_documents(identifier='IPR2024-01353', document_title='Petition for Inter Partes')
        ptab_get_documents(identifier='IPR2024-01353', document_title='Patent Owner Response')
        ptab_get_documents(identifier='IPR2024-01353', document_title='Oral Hearing')
      Tip: use a short substring (e.g. 'Institution', 'Oral') to cast a wider net;
           use a longer phrase to target exactly one document.

    📄 PAGINATION (trials only): Uses server-side pagination via POST search endpoint.
    Returns the true total_documents count and a next_offset hint when more pages exist.
    Full docket access example for a 40-paper proceeding:
      # Page 1 — Papers 1-25 oldest first (Petition, POPR, Institution Decision...)
      ptab_get_documents(identifier='IPR2024-01353', sort_order='asc', offset=0, limit=25)
      # Page 2 — Papers 26-40
      ptab_get_documents(identifier='IPR2024-01353', sort_order='asc', offset=25, limit=25)
    Appeals/Interferences still use a GET endpoint with no server-side pagination.

    **document_category** - Coarser filter for trials by document category (case-insensitive).
      Use document_title for precision; use document_category when browsing by broad type.
      Key Categories:
        - PETITION: Petition documents
        - RESPONSE: Patent owner responses
        - ORDER: Board orders
        - DECISION: Board decisions (Institution, Final Written Decision)
        - MOTION: Motions and exhibits

    **filing_party** - Filter trials by filing party (case-insensitive):
      Key Parties:
        - BOARD: Board documents (orders, decisions)
        - PETITIONER: Petitioner submissions
        - PATENT OWNER: Patent owner submissions

    **outcome_category** - Filter appeals/interferences by outcome (case-insensitive):
      Appeals: "Affirmed", "Reversed", "Rehearing Decision Denied"
      Interferences: "Final Decision", "Judgment", etc.

    📌 EXAMPLES (always use filtering for large proceedings):

    # Final Written Decision only
    ptab_get_documents(identifier='IPR2024-00123', document_category='DECISION', limit=5)

    # All Board orders
    ptab_get_documents(identifier='IPR2024-00123', filing_party='BOARD', limit=20)

    # Patent owner responses
    ptab_get_documents(identifier='IPR2024-00123', filing_party='PATENT OWNER')

    # Appeals with specific outcome
    ptab_get_documents(identifier='2025000943', identifier_type='appeal',
                       outcome_category='Affirmed', limit=10)

    ⚠️ AVOID: ptab_get_documents(identifier='...', limit=200) without filters
    ✅ DO: Always filter by document_category, filing_party, or outcome_category

    BASIC USAGE:
    - Core Purpose: Retrieve complete document list for any PTAB proceeding
    - Returns: Documents with filtering applied
    - Supports: Trials (IPR/PGR/CBM), Appeals, Interferences (via identifier_type parameter)
    - Typical Volume: 10-100+ documents depending on proceeding complexity

    WHEN TO USE THIS TOOL:
    - Document Discovery: After selecting trial/appeal/interference from search results
    - Selective Download Planning: Review documents before downloading (avoid unnecessary OCR costs)
    - Multi-Document Workflows: Get all document IDs for batch processing
    - Progressive Disclosure Stage 3: After minimal search → balanced analysis → document operations

    DOCUMENT WORKFLOW:
    1. Use search_trials_minimal/balanced to find proceeding - Get trial number
    2. Use ptab_get_documents (this tool) with filters - Get specific document types
    3. User/LLM selects priority documents based on use case
    4. Use ptab_get_document_download - Get browser-accessible download links
    5. OR use ptab_get_document_content - Extract text for LLM analysis (OCR costs apply)

    PRIORITY DOCUMENTS BY USE CASE:

    IPR Response Strategy:
      ptab_get_documents(identifier='...', document_category='DECISION')
      - Final Written Decision (outcome analysis)
      - Institution Decision (claims instituted)

    Prior Art Research:
      ptab_get_documents(identifier='...', filing_party='PETITIONER')
      - Petition documents (petitioner's case)
      - Petitioner exhibits (cited references)

    Litigation Preparation:
      ptab_get_documents(identifier='...', filing_party='BOARD', limit=20)
      - All decisions and orders (procedural history)
      - Estoppel analysis documents

    RELATED TOOLS:
    - Next Step: ptab_get_document_download (browser access) or ptab_get_document_content (LLM analysis)
    - Previous Step: search_trials_minimal/balanced (find trials first)
    - Cross-MCP: pfw_get_application_documents (prosecution history documents)

    GUIDANCE REFERENCES:
    - For document selection strategies: ptab_get_guidance(section='documents')
    - For multi-document workflows: ptab_get_guidance(section='documents')
    - For cost optimization (avoid unnecessary OCR): ptab_get_guidance(section='cost')

    Args:
        identifier: Trial number (IPR2024-00123), appeal number (2024-001234), or interference number
        identifier_type: Type of proceeding - "trial" (default), "appeal", or "interference"
        limit: Max documents to return (default: 50, max: 200)
        offset: Skip first N documents after sorting (client-side, default: 0).
        sort_order: Client-side sort direction - "desc" (newest first, default) or "asc" (oldest first).
                    Use "asc" to surface the Petition and earliest filings first.
        document_title: Case-insensitive substring match on documentTypeDescriptionText.
                        Use to target specific document types, e.g. 'Final Written Decision',
                        'Institution Decision', 'Petition for Inter Partes', 'Patent Owner Response'.
        document_category: Coarser filter for trials by document category (PETITION, RESPONSE, ORDER, DECISION, MOTION)
        filing_party: Filter trials by filing party (BOARD, PETITIONER, PATENT OWNER)
        outcome_category: Filter appeals/interferences by outcome

    Returns:
        JSON string with filtered document list

    Example:
        {"identifier": "IPR2024-00123",
         "identifier_type": "trial",
         "total_documents": 45,
         "filtered_count": 5,
         "filter_applied": {"document_category": "DECISION"},
         "documents": [
             {"documentIdentifier": "171141394",
              "documentTitleText": "Final Written Decision",
              "documentFilingDate": "2024-05-15",
              "documentSizeQuantity": 97699}
         ]}
    """
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for document operations")
            api_client = get_api_client()

        # Validate limit
        if limit < 1 or limit > 200:
            raise ValueError("Limit must be between 1 and 200")

        # Validate offset
        if offset < 0:
            raise ValueError("Offset must be >= 0")

        # Validate sort_order
        sort_order = sort_order.lower()
        if sort_order not in ("asc", "desc"):
            raise ValueError("sort_order must be 'asc' or 'desc'")

        # Validate identifier type
        identifier_type = validate_identifier_type(identifier_type)

        # Validate identifier based on type
        if identifier_type == "trial":
            identifier = validate_trial_number(identifier)
        elif identifier_type == "appeal":
            identifier = validate_appeal_number(identifier)
        elif identifier_type == "interference":
            identifier = validate_interference_number(identifier)

        # Route to correct API method
        # Trials: use POST search endpoint for server-side pagination/sort
        # Appeals/Interferences: use GET convenience endpoints (no search endpoint available)
        if identifier_type == "trial":
            raw_response = await api_client.search_trial_documents(
                identifier,
                offset=offset,
                limit=limit,
                sort_order=sort_order
            )
        elif identifier_type == "appeal":
            raw_response = await api_client.get_appeal_decisions(identifier)
        elif identifier_type == "interference":
            raw_response = await api_client.get_interference_decisions(identifier)
        else:
            raise ValueError(f"Unsupported identifier type: {identifier_type}")

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Extract documents from response (API-specific key names)
        if identifier_type == "trial":
            # Trial documents are nested inside patentTrialDocumentDataBag
            trial_bag = raw_response.get("patentTrialDocumentDataBag", [])
            documents = []
            for trial_doc in trial_bag:
                doc_data = trial_doc.get("documentData")
                if doc_data:
                    flattened_doc = {
                        **doc_data,  # Document fields (includes documentIdentifier)
                        "trialNumber": trial_doc.get("trialNumber"),
                        "lastModifiedDateTime": trial_doc.get("lastModifiedDateTime")
                    }
                    documents.append(flattened_doc)
        elif identifier_type == "appeal":
            # Appeal documents are nested inside patentAppealDataBag
            appeal_bag = raw_response.get("patentAppealDataBag", [])
            documents = []
            for appeal in appeal_bag:
                doc_data = appeal.get("documentData")
                if doc_data:
                    # Flatten structure: add document data directly to list
                    # Include appeal metadata for context
                    flattened_doc = {
                        **doc_data,  # Document fields
                        "appealNumber": appeal.get("appealNumber"),
                        "appealOutcomeCategory": appeal.get("decisionData", {}).get("appealOutcomeCategory"),
                        "decisionIssueDate": appeal.get("decisionData", {}).get("decisionIssueDate")
                    }
                    documents.append(flattened_doc)
        elif identifier_type == "interference":
            # Interference documents are nested inside patentInterferenceDataBag
            interference_bag = raw_response.get("patentInterferenceDataBag", [])
            documents = []
            for interference in interference_bag:
                doc_data = interference.get("documentData")
                if doc_data:
                    # Flatten structure: add document data directly to list
                    # Include interference metadata for context
                    flattened_doc = {
                        **doc_data,  # Document fields
                        "interferenceNumber": interference.get("interferenceNumber"),
                        "interferenceStyleName": interference.get("interferenceMetaData", {}).get("interferenceStyleName"),
                        "declarationDate": interference.get("interferenceMetaData", {}).get("declarationDate")
                    }
                    documents.append(flattened_doc)
        else:
            documents = []

        # For trials: API returns the true total count (server-side pagination)
        # For appeals/interferences: count what we got (no pagination support)
        api_total_count = raw_response.get("count")
        total_documents = api_total_count if (identifier_type == "trial" and api_total_count is not None) else len(documents)

        # Apply filtering
        filtered_documents = documents
        filters_applied = {}

        # Filter by document_title substring (case-insensitive) — applies to all identifier types
        # Matches against documentTypeDescriptionText (e.g. "Final Written Decision")
        if document_title:
            document_title_lower = document_title.lower()
            filtered_documents = [
                doc for doc in filtered_documents
                if document_title_lower in doc.get("documentTypeDescriptionText", "").lower()
                or document_title_lower in doc.get("documentTitleText", "").lower()
            ]
            filters_applied["document_title"] = document_title

        if identifier_type == "trial":
            # Filter by document_category (case-insensitive)
            if document_category:
                document_category_upper = document_category.upper()
                filtered_documents = [
                    doc for doc in filtered_documents
                    if doc.get("documentCategory", "").upper() == document_category_upper
                ]
                filters_applied["document_category"] = document_category

            # Filter by filing_party (case-insensitive)
            if filing_party:
                filing_party_upper = filing_party.upper()
                filtered_documents = [
                    doc for doc in filtered_documents
                    if doc.get("filingPartyCategory", "").upper() == filing_party_upper
                ]
                filters_applied["filing_party"] = filing_party

        elif identifier_type in ["appeal", "interference"]:
            # Filter by outcome_category (case-insensitive)
            if outcome_category:
                outcome_category_upper = outcome_category.upper()
                if identifier_type == "appeal":
                    filtered_documents = [
                        doc for doc in filtered_documents
                        if doc.get("appealOutcomeCategory", "").upper() == outcome_category_upper
                    ]
                else:  # interference
                    filtered_documents = [
                        doc for doc in filtered_documents
                        if doc.get("interferenceOutcomeCategory", "").upper() == outcome_category_upper
                    ]
                filters_applied["outcome_category"] = outcome_category

        # Sort client-side (server-side sort omitted until field name is confirmed).
        # For trials: offset/limit are server-side; sort is client-side on returned page.
        # For appeals/interferences: offset/limit/sort are all client-side.
        def _sort_key(doc):
            return doc.get("documentFilingDate") or doc.get("lastModifiedDateTime") or ""
        filtered_documents.sort(key=_sort_key, reverse=(sort_order == "desc"))

        if identifier_type != "trial":
            # offset/limit already sent to API for trials; only apply client-side for others
            if offset:
                filtered_documents = filtered_documents[offset:]
            if limit and limit < len(filtered_documents):
                filtered_documents = filtered_documents[:limit]

        # Format output with filtering metadata
        formatted = format_document_list(
            documents=filtered_documents,
            identifier=identifier,
            identifier_type=identifier_type,
            count=len(filtered_documents)
        )

        # Parse formatted JSON to add filtering metadata
        formatted_dict = json.loads(formatted)
        formatted_dict["total_documents"] = total_documents
        formatted_dict["returned_count"] = len(filtered_documents)
        if filters_applied:
            formatted_dict["filters_applied"] = filters_applied
        formatted_dict["offset"] = offset
        formatted_dict["limit"] = limit
        formatted_dict["sort_order"] = sort_order
        if identifier_type == "trial" and total_documents and total_documents > offset + len(filtered_documents):
            formatted_dict["next_offset"] = offset + len(filtered_documents)

        return json.dumps(formatted_dict, indent=2)

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except RuntimeError as e:
        # Catch async lifecycle errors specifically
        error_msg = str(e)
        if "cannot schedule new futures" in error_msg or "interpreter shutdown" in error_msg:
            logger.error(f"Async lifecycle error in ptab_get_documents: {error_msg}")
            return json.dumps({
                "error": True,
                "message": "Operation failed due to async runtime issue. Try restarting the MCP server.",
                "technical_details": error_msg
            }, indent=2)
        else:
            raise  # Re-raise other RuntimeErrors
    except Exception as e:
        logger.error(f"Error in ptab_get_documents: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


@mcp.tool()
async def ptab_get_document_download(
    document_id: str,
    identifier: str,
    identifier_type: str = "trial"
) -> str:
    """Generate secure browser-accessible download URLs for PTAB documents (PDFs).

    PREREQUISITE: First use ptab_get_documents to get document_identifier from document list.

    BASIC USAGE:
    - Core Purpose: Create clickable proxy links for browser downloads (handles API authentication)
    - Proxy Integration: Centralized PFW proxy (port 8080) with automatic fallback to local (port 8083)
    - Link Validity: 7-day persistent links (remain valid after proxy restart)
    - Security: Keeps API credentials secure while enabling direct browser access

    WHEN TO USE THIS TOOL:
    - User Download: When user will review document themselves in browser
    - Multi-Document Packages: Generate download links for complete docket
    - Legal Review Workflows: Provide attorneys with browser-accessible PDFs
    - Cost Avoidance: Use download (free) instead of content extraction (OCR costs $)

    DOWNLOAD VS EXTRACT DECISION TREE:

    User needs document → User will read it themselves?
      YES → ptab_get_document_download (this tool) - FREE
            Returns browser-accessible link
            User downloads and reviews directly

      NO → LLM needs to analyze content?
           YES → ptab_get_document_content - PAID
                 Hybrid extraction (PyPDF2 + Mistral OCR)
                 Cost: ~$0.15 per 1M tokens (Mistral OCR)
                 Limit to 1-3 critical documents

    CRITICAL RESPONSE FORMAT - Always format with BOTH clickable link and raw URL:

    Format: **[Download {DocumentType} ({PageCount} pages)]({proxy_url})** | Raw URL: `{proxy_url}`

    Why both formats?
    - Clickable links work in Claude Desktop and most clients
    - Raw URLs enable copy/paste in Msty and other clients where links aren't clickable
    - Ensures maximum compatibility across different MCP clients

    Example:
      **[Download Final Written Decision (45 pages)](http://localhost:8080/download/...)** | Raw URL: `http://localhost:8080/download/...`

    MULTI-DOCUMENT WORKFLOW:

    Step 1: Get document list
      docs = ptab_get_documents(identifier='IPR2024-00123', identifier_type='trial')

    Step 2: Filter to priority documents (e.g., Final Written Decisions)
      fwd_docs = [d for d in docs['documents']
                  if 'Final Written Decision' in d.get('description', '')]

    Step 3: Generate download links for all (up to 5-10)
      for doc in fwd_docs[:5]:
          download = ptab_get_document_download(
              identifier='IPR2024-00123',
              identifier_type='trial',
              document_id=doc['documentIdentifier']
          )

    Step 4: Format with BOTH clickable and raw URL
      link = f"**[Download {doc['description']} ({doc['pageCount']} pages)]({download['proxy_url']})** | Raw URL: `{download['proxy_url']}`"

    PROXY BEHAVIOR:
    - Always-on mode: Set ENABLE_ALWAYS_ON_PROXY=true for immediate access
    - Persistent links: Enabled by default - 7-day encrypted links
    - Centralized proxy detection: Automatic fallback if PFW proxy unavailable
    - Download links work immediately and remain valid for 7 days

    EXPECTED FILENAME FORMATS:
    Pattern: PTAB-{date}_{trial}_{patent}_{description}.pdf

    Examples:
      - PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf
      - PTAB-2024-03-20_PGR2025-00045_PAT-9876543_INSTITUTION_DECISION.pdf
      - PTAB-2024-01-10_IPR2024-00123_PAT-8524787_PATENT_OWNER_RESPONSE.pdf

    RELATED TOOLS:
    - Previous Step: ptab_get_documents (get document list and IDs first)
    - Alternative: ptab_get_document_content (LLM analysis instead of user download)
    - Cross-MCP: pfw_get_document_download (prosecution history documents)

    GUIDANCE REFERENCES:
    - For download link formatting: ptab_get_guidance(section='documents')
    - For multi-document workflows: ptab_get_guidance(section='documents')
    - For cost optimization: ptab_get_guidance(section='cost')
    - For cross-MCP integration: ptab_get_guidance(section='workflows_pfw')

    Args:
        document_id: Document identifier from ptab_get_documents()
        identifier: Trial/appeal/interference number
        identifier_type: Type of proceeding - "trial" (default), "appeal", or "interference"

    Returns:
        JSON string with download URL, proxy info, and llm_response_guidance

    Example Response:
        {
            "document_id": "171141394",
            "identifier": "IPR2024-00123",
            "proxy_url": "http://localhost:8080/download/IPR2024-00123/171141394",
            "document_description": "Final Written Decision",
            "page_count": 45,
            "enhanced_filename": "PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf",
            "llm_response_guidance": {
                "format": "**[Download Final Written Decision (45 pages)](http://localhost:8080/download/...)** | Raw URL: `http://localhost:8080/download/...`",
                "critical": "Provide clickable markdown link for browser access AND raw URL for clients like Msty where links aren't clickable",
                "example": "**[Download Final Written Decision (45 pages)](http://localhost:8080/download/IPR2024-00123/171141394)** | Raw URL: `http://localhost:8080/download/IPR2024-00123/171141394`"
            }
        }
    """
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for document download")
            api_client = get_api_client()

        # Validate inputs
        identifier_type = validate_identifier_type(identifier_type)

        if identifier_type == "trial":
            identifier = validate_trial_number(identifier)
        elif identifier_type == "appeal":
            identifier = validate_appeal_number(identifier)
        elif identifier_type == "interference":
            identifier = validate_interference_number(identifier)

        if not document_id:
            raise ValueError("Document ID is required")

        # First, fetch full proceeding data to get patent_number, application_number, filing_date
        proceeding_patent_number = None
        proceeding_application_number = None
        proceeding_filing_date = None

        if identifier_type == "trial":
            # Fetch full trial proceeding data
            trial_response = await api_client.search_trials(
                filters=[{"name": "trialNumber", "value": [identifier]}],
                pagination={"offset": 0, "limit": 1}
            )
            trial_data = trial_response.get("patentTrialProceedingDataBag", [])
            if trial_data:
                trial = trial_data[0]
                # Extract patent number from respondentData
                respondent_data = trial.get("respondentData", {})
                proceeding_patent_number = respondent_data.get("patentNumber")
                proceeding_application_number = respondent_data.get("applicationNumber")
                # Extract filing date from trialMetaData
                trial_meta = trial.get("trialMetaData", {})
                proceeding_filing_date = trial_meta.get("accordedFilingDate")
        elif identifier_type == "appeal":
            # Fetch full appeal data
            appeal_response = await api_client.search_appeals(
                filters=[{"name": "appealNumber", "value": [identifier]}],
                pagination={"offset": 0, "limit": 1}
            )
            appeal_data = appeal_response.get("patentAppealDataBag", [])
            if appeal_data:
                appeal = appeal_data[0]
                # Extract patent number and filing date from decision metadata
                decision_meta = appeal.get("decisionMetaData", {})
                proceeding_patent_number = decision_meta.get("patentNumber")
                proceeding_application_number = decision_meta.get("applicationNumber")
                decision_data = appeal.get("decisionData", {})
                proceeding_filing_date = decision_data.get("decisionIssueDate")
        elif identifier_type == "interference":
            # Fetch full interference data
            interference_response = await api_client.search_interferences(
                filters=[{"name": "interferenceNumber", "value": [identifier]}],
                pagination={"offset": 0, "limit": 1}
            )
            interference_data = interference_response.get("patentInterferenceDataBag", [])
            if interference_data:
                interference = interference_data[0]
                # Extract patent number and filing date from metadata
                interference_meta = interference.get("interferenceMetaData", {})
                proceeding_patent_number = interference_meta.get("patentNumber")
                proceeding_application_number = interference_meta.get("applicationNumber")
                proceeding_filing_date = interference_meta.get("declarationDate")

        # Get document metadata to extract fileDownloadURI
        if identifier_type == "trial":
            docs_response = await api_client.get_trial_documents(identifier)
        elif identifier_type == "appeal":
            docs_response = await api_client.get_appeal_decisions(identifier)
        elif identifier_type == "interference":
            docs_response = await api_client.get_interference_decisions(identifier)
        else:
            raise ValueError(f"Unsupported identifier type: {identifier_type}")

        # Extract documents from response (API-specific key names)
        # Preserve parent item data for enhanced filename generation
        if identifier_type == "trial":
            # Trial documents are nested inside patentTrialDocumentDataBag
            trial_bag = docs_response.get("patentTrialDocumentDataBag", [])
            documents = []
            for trial_doc in trial_bag:
                doc_data = trial_doc.get("documentData")
                if doc_data:
                    flattened_doc = {
                        **doc_data,  # Document fields (includes documentIdentifier)
                        "trialNumber": trial_doc.get("trialNumber"),
                        "lastModifiedDateTime": trial_doc.get("lastModifiedDateTime"),
                        # Preserve parent data for enhanced filename
                        "trialDocumentCategory": trial_doc.get("trialDocumentCategory"),
                        "_patentOwnerData": trial_doc.get("patentOwnerData", {})
                    }
                    documents.append(flattened_doc)
        elif identifier_type == "appeal":
            # Appeal documents are nested inside patentAppealDataBag
            appeal_bag = docs_response.get("patentAppealDataBag", [])
            documents = []
            for appeal in appeal_bag:
                doc_data = appeal.get("documentData")
                if doc_data:
                    flattened_doc = {
                        **doc_data,
                        "appealNumber": appeal.get("appealNumber"),
                        "appealOutcomeCategory": appeal.get("decisionData", {}).get("appealOutcomeCategory"),
                        "decisionIssueDate": appeal.get("decisionData", {}).get("decisionIssueDate"),
                        # Preserve parent data for enhanced filename
                        "appealDocumentCategory": appeal.get("appealDocumentCategory"),
                        "_appellantData": appeal.get("appellantData", {})
                    }
                    documents.append(flattened_doc)
        elif identifier_type == "interference":
            # Interference documents are nested inside patentInterferenceDataBag
            interference_bag = docs_response.get("patentInterferenceDataBag", [])
            documents = []
            for interference in interference_bag:
                doc_data = interference.get("documentData")
                if doc_data:
                    flattened_doc = {
                        **doc_data,
                        "interferenceNumber": interference.get("interferenceNumber"),
                        "interferenceStyleName": interference.get("interferenceMetaData", {}).get("interferenceStyleName"),
                        "declarationDate": interference.get("interferenceMetaData", {}).get("declarationDate")
                    }
                    documents.append(flattened_doc)
        else:
            documents = []

        # Find document by ID
        matching_doc = None

        for doc in documents:
            if doc.get("documentIdentifier") == document_id:
                matching_doc = doc
                break

        if not matching_doc:
            raise ValueError(f"Document ID '{document_id}' not found in {identifier}")

        # Extract download URL
        download_url = matching_doc.get("fileDownloadURI")

        if not download_url:
            raise ValueError(f"No download URI found for document {document_id}")

        # Extract document metadata using correct field names (matching proxy logic)
        # Priority: documentTitleText > category fields > generic type
        doc_description = (
            matching_doc.get("documentTitleText") or  # Trials (most specific)
            matching_doc.get("appealDocumentCategory") or  # Appeals: "Decision"
            matching_doc.get("trialDocumentCategory") or  # Trials: "PETITION", etc.
            matching_doc.get("documentCategory") or
            matching_doc.get("documentTypeDescriptionText") or  # Fallback: "Paper"
            "Document"
        )
        # Use documentName as final fallback
        if doc_description == "Document" and matching_doc.get("documentName"):
            doc_name = matching_doc.get("documentName", "")
            if doc_name.endswith(".pdf"):
                doc_name = doc_name[:-4]
            doc_description = doc_name.split("_")[0] if "_" in doc_name else doc_name

        page_count = matching_doc.get("pageCount", "Unknown")
        document_code = matching_doc.get("documentCategory")

        # Get filing date from document (more accurate) or fallback to proceeding
        filing_date = matching_doc.get("documentFilingDate") or proceeding_filing_date or ""

        # Get patent number from preserved parent data or fallback to proceeding
        if identifier_type == "trial":
            patent_number = matching_doc.get("_patentOwnerData", {}).get("patentNumber") or proceeding_patent_number
        elif identifier_type == "appeal":
            patent_number = matching_doc.get("_appellantData", {}).get("patentNumber") or proceeding_patent_number
        else:
            patent_number = proceeding_patent_number
        application_number = proceeding_application_number

        # Generate enhanced filename
        enhanced_filename = generate_enhanced_filename(
            identifier=identifier,
            identifier_type=identifier_type,
            document_description=doc_description,
            document_code=document_code,
            filing_date=filing_date,
            patent_number=patent_number
        )

        # Attempt centralized proxy registration
        centralized_url = await register_with_centralized_proxy(
            identifier=identifier,
            identifier_type=identifier_type,
            document_id=document_id,
            download_url=download_url,
            api_key=settings.uspto_api_key,
            patent_number=patent_number,
            application_number=application_number,
            enhanced_filename=enhanced_filename,
            internal_auth_secret=settings.internal_auth_secret
        )

        if centralized_url:
            # Success - use centralized proxy
            final_url = centralized_url
            proxy_mode = "centralized"
            proxy_note = "Unified download through PFW centralized proxy (persistent links, enhanced rate limiting, cross-MCP sharing)"
            logger.info(f"✅ Using centralized proxy: {centralized_url}")
        else:
            # Failback - use local PTAB proxy
            local_port = get_local_proxy_port()

            # Ensure local proxy is running (on-demand startup if ENABLE_ALWAYS_ON_PROXY=false)
            proxy_started = await _ensure_local_proxy_running(local_port)
            if not proxy_started:
                logger.warning("Local proxy failed to start - download URL may not work")

            final_url = f"http://localhost:{local_port}/download/{identifier_type}/{identifier}/{document_id}"
            proxy_mode = "local"
            proxy_note = f"Local PTAB proxy on port {local_port} (automatic failback from centralized proxy)"
            logger.info(f"ℹ️  Using local PTAB proxy: {final_url}")

        response = {
            "document_id": document_id,
            "identifier": identifier,
            "identifier_type": identifier_type,
            "download_url": final_url,
            "document_description": doc_description,
            "page_count": page_count,
            "filing_date": filing_date,
            "patent_number": patent_number,
            "enhanced_filename": enhanced_filename,
            "proxy_info": {
                "mode": proxy_mode,
                "note": proxy_note,
                "centralized_available": centralized_url is not None
            },
            "llm_response_guidance": {
                "format": f"**[Download {doc_description} ({page_count} pages)]({final_url})** | Raw URL: `{final_url}`",
                "critical": "Provide clickable markdown link for browser access AND raw URL for clients like Msty where links aren't clickable",
                "example": f"**[Download {doc_description} ({page_count} pages)]({final_url})** | Raw URL: `{final_url}`"
            }
        }

        return json.dumps(response, indent=2)

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except RuntimeError as e:
        # Catch async lifecycle errors specifically
        error_msg = str(e)
        if "cannot schedule new futures" in error_msg or "interpreter shutdown" in error_msg:
            logger.error(f"Async lifecycle error in ptab_get_document_download: {error_msg}")
            return json.dumps({
                "error": True,
                "message": "Operation failed due to async runtime issue. Try restarting the MCP server.",
                "technical_details": error_msg
            }, indent=2)
        else:
            raise  # Re-raise other RuntimeErrors
    except Exception as e:
        logger.error(f"Error in ptab_get_document_download: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


@mcp.tool()
async def ptab_get_document_content(
    document_id: str,
    identifier: str,
    identifier_type: str = "trial",
    use_ocr: bool = False
) -> str:
    """Extract text content from PTAB documents for LLM analysis (hybrid PyPDF2 + Mistral OCR).

    PREREQUISITE: First use ptab_get_documents to get document_identifier.

    BASIC USAGE:
    - Core Purpose: Extract text from PDFs for LLM analysis and question answering
    - Extraction Strategy: Try PyPDF2 first (free), use Mistral OCR if needed (costs $)
    - Cost Management: PyPDF2 always attempted first to avoid OCR charges
    - Typical Use: Answer questions about Board decisions, analyze reasoning

    WHEN TO USE THIS TOOL:
    - LLM Analysis: When LLM needs to answer questions about document content
    - Text Extraction: For semantic search, RAG, or text mining workflows
    - Decision Analysis: Understanding Board's claim construction or reasoning
    - Selective Extraction: Only for 1-3 critical documents (avoid cost explosion)

    HYBRID EXTRACTION STRATEGY:

    Step 1: Download PDF from USPTO
    Step 2: Try PyPDF2 text extraction (fast, free)
    Step 3: If < 100 chars, use Mistral OCR (slower, costs $)
    Step 4: Return extracted text with metadata

    Cost Calculation:
    - PyPDF2 extraction: FREE (always tried first)
    - Mistral OCR: ~$0.15 per 1M input tokens
      - Final Written Decision (45 pages): ~$0.01-0.02
      - Petition (100 pages): ~$0.02-0.04
      - Complete docket (500 pages): ~$0.10-0.15

    COST OPTIMIZATION WORKFLOW:

    User needs document → LLM will analyze?
      YES → How many documents?
            - 1-3 documents: ptab_get_document_content (acceptable cost)
            - 5+ documents: Use ptab_get_document_download instead
                            → User reviews and selects 1-3 for extraction

      NO → ptab_get_document_download (user downloads, FREE)

    RELATED TOOLS:
    - Alternative: ptab_get_document_download (user download, no OCR costs)
    - Previous Step: ptab_get_documents (get document list first)
    - Cross-MCP: pfw_get_document_content (prosecution history text extraction)

    GUIDANCE REFERENCES:
    - For cost optimization strategies: ptab_get_guidance(section='cost')
    - For download vs extract decision tree: ptab_get_guidance(section='documents')
    - For OCR cost calculations: ptab_get_guidance(section='cost')

    Args:
        document_id: Document identifier from ptab_get_documents()
        identifier: Trial/appeal/interference number
        identifier_type: Type of proceeding - "trial" (default), "appeal", or "interference"
        use_ocr: Force Mistral OCR even if PyPDF2 succeeds (for better quality)

    Returns:
        JSON string with extracted text, method used, cost estimate

    Example Response:
        {
            "text": "UNITED STATES PATENT AND TRADEMARK OFFICE...",
            "extraction_method": "pypdf2",
            "character_count": 25000,
            "page_count": 45,
            "ocr_cost_usd": 0.00,
            "note": "PyPDF2 extraction successful (no OCR charges)"
        }

    Example Response (OCR used):
        {
            "text": "UNITED STATES PATENT AND TRADEMARK OFFICE...",
            "extraction_method": "mistral_ocr",
            "character_count": 25000,
            "page_count": 45,
            "ocr_cost_usd": 0.015,
            "note": "Mistral OCR used (PyPDF2 failed for scanned PDF)"
        }
    """
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for document content extraction")
            api_client = get_api_client()

        # Validate inputs
        identifier_type = validate_identifier_type(identifier_type)

        if identifier_type == "trial":
            identifier = validate_trial_number(identifier)
        elif identifier_type == "appeal":
            identifier = validate_appeal_number(identifier)
        elif identifier_type == "interference":
            identifier = validate_interference_number(identifier)

        if not document_id:
            raise ValueError("Document ID is required")

        # Get document metadata
        if identifier_type == "trial":
            docs_response = await api_client.get_trial_documents(identifier)
        elif identifier_type == "appeal":
            docs_response = await api_client.get_appeal_decisions(identifier)
        elif identifier_type == "interference":
            docs_response = await api_client.get_interference_decisions(identifier)
        else:
            raise ValueError(f"Unsupported identifier type: {identifier_type}")

        # Extract documents from response (API-specific key names)
        if identifier_type == "trial":
            # Trial documents are nested inside patentTrialDocumentDataBag
            trial_bag = docs_response.get("patentTrialDocumentDataBag", [])
            documents = []
            for trial_doc in trial_bag:
                doc_data = trial_doc.get("documentData")
                if doc_data:
                    flattened_doc = {
                        **doc_data,  # Document fields (includes documentIdentifier)
                        "trialNumber": trial_doc.get("trialNumber"),
                        "lastModifiedDateTime": trial_doc.get("lastModifiedDateTime")
                    }
                    documents.append(flattened_doc)
        elif identifier_type == "appeal":
            # Appeal documents are nested inside patentAppealDataBag
            appeal_bag = docs_response.get("patentAppealDataBag", [])
            documents = []
            for appeal in appeal_bag:
                doc_data = appeal.get("documentData")
                if doc_data:
                    flattened_doc = {
                        **doc_data,
                        "appealNumber": appeal.get("appealNumber"),
                        "appealOutcomeCategory": appeal.get("decisionData", {}).get("appealOutcomeCategory"),
                        "decisionIssueDate": appeal.get("decisionData", {}).get("decisionIssueDate")
                    }
                    documents.append(flattened_doc)
        elif identifier_type == "interference":
            # Interference documents are nested inside patentInterferenceDataBag
            interference_bag = docs_response.get("patentInterferenceDataBag", [])
            documents = []
            for interference in interference_bag:
                doc_data = interference.get("documentData")
                if doc_data:
                    flattened_doc = {
                        **doc_data,
                        "interferenceNumber": interference.get("interferenceNumber"),
                        "interferenceStyleName": interference.get("interferenceMetaData", {}).get("interferenceStyleName"),
                        "declarationDate": interference.get("interferenceMetaData", {}).get("declarationDate")
                    }
                    documents.append(flattened_doc)
        else:
            documents = []

        # Find document by ID
        matching_doc = None

        for doc in documents:
            if doc.get("documentIdentifier") == document_id:
                matching_doc = doc
                break

        if not matching_doc:
            raise ValueError(f"Document ID '{document_id}' not found in {identifier}")

        # Extract download URL
        download_url = matching_doc.get("fileDownloadURI")

        if not download_url:
            raise ValueError(f"No download URI found for document {document_id}")

        # Download PDF
        if identifier_type == "trial":
            pdf_bytes = await api_client.download_trial_document(download_url)
        elif identifier_type == "appeal":
            pdf_bytes = await api_client.download_appeal_document(download_url)
        elif identifier_type == "interference":
            pdf_bytes = await api_client.download_interference_document(download_url)
        else:
            raise ValueError(f"Unsupported identifier type: {identifier_type}")

        # Try PyPDF2 extraction first
        extracted_text = ""
        extraction_method = "pypdf2"
        ocr_cost_usd = 0.00

        if not use_ocr:
            try:
                import io
                import PyPDF2

                pdf_file = io.BytesIO(pdf_bytes)
                pdf_reader = PyPDF2.PdfReader(pdf_file)

                text_parts = []
                for page in pdf_reader.pages:
                    text_parts.append(page.extract_text())

                extracted_text = "\n".join(text_parts)

                # If extraction succeeded with good amount of text, use it
                if len(extracted_text.strip()) >= 100:
                    logger.info(f"PyPDF2 extraction successful: {len(extracted_text)} chars")
                else:
                    logger.warning(f"PyPDF2 extraction yielded only {len(extracted_text)} chars")
                    extracted_text = ""  # Will trigger OCR

            except Exception as e:
                logger.warning(f"PyPDF2 extraction failed: {str(e)}")
                extracted_text = ""

        # If PyPDF2 failed or use_ocr=True, try Mistral OCR
        if not extracted_text or use_ocr:
            extraction_method = "mistral_ocr"

            # Get page count for cost estimation
            page_count = matching_doc.get("pageCount", 50)  # Default to 50 if not available
            if isinstance(page_count, str):
                try:
                    page_count = int(page_count)
                except ValueError:
                    page_count = 50

            # Use OCR service
            ocr_result = await ocr_service.extract_document_content(
                pdf_content=pdf_bytes,
                page_count=page_count,
                identifier=identifier,
                document_id=document_id
            )

            if ocr_result.get("success"):
                extracted_text = ocr_result.get("extracted_content", "")
                ocr_cost_usd = ocr_result.get("processing_cost_usd", 0.0)
                logger.info(f"Mistral OCR extraction successful: {len(extracted_text)} chars, "
                           f"${ocr_cost_usd:.4f} cost")
            else:
                # OCR failed - return error information
                error_msg = ocr_result.get("message", "Unknown OCR error")
                logger.error(f"Mistral OCR extraction failed: {error_msg}")

                # Return enhanced error with LLM guidance when both extraction methods fail
                if not extracted_text:
                    return json.dumps({
                        "document_id": document_id,
                        "identifier": identifier,
                        "text": "",
                        "extraction_method": "PyPDF2 (insufficient)",
                        "error": "Document appears to be scanned/image-based. PyPDF2 could not extract meaningful text.",
                        "mistral_api_key_missing": not ocr_service.mistral_api_key,
                        "llm_guidance": {
                            "explain_to_user": "Many USPTO PTAB documents are scanned images rather than text-based PDFs. "
                                              "PyPDF2 can only extract text from text-based PDFs - it cannot read scanned images.",
                            "recommended_solution": "Configure Mistral API for OCR capability (~$0.001/page, with free tier available)",
                            "free_tier_info": "Mistral offers a generous free tier - sign up at https://console.mistral.ai/",
                            "setup_instructions": "Set MISTRAL_API_KEY environment variable after obtaining key from Mistral console"
                        }
                    }, indent=2)
                ocr_cost_usd = 0.00

        # Return result
        response = {
            "document_id": document_id,
            "identifier": identifier,
            "identifier_type": identifier_type,
            "text": extracted_text,
            "extraction_method": extraction_method,
            "character_count": len(extracted_text),
            "ocr_cost_usd": ocr_cost_usd,
            "document_description": matching_doc.get("documentDescription", ""),
            "filing_date": matching_doc.get("filingDate", "")
        }

        return json.dumps(response, indent=2)

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except RuntimeError as e:
        # Catch async lifecycle errors specifically
        error_msg = str(e)
        if "cannot schedule new futures" in error_msg or "interpreter shutdown" in error_msg:
            logger.error(f"Async lifecycle error in ptab_get_document_content: {error_msg}")
            return json.dumps({
                "error": True,
                "message": "Operation failed due to async runtime issue. Try restarting the MCP server.",
                "technical_details": error_msg
            }, indent=2)
        else:
            raise  # Re-raise other RuntimeErrors
    except Exception as e:
        logger.error(f"Error in ptab_get_document_content: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


# ==========================================
# APPEALS SEARCH TOOLS (3 tools)
# ==========================================

@mcp.tool()
async def search_appeals_minimal(
    appeal_number: Optional[str] = None,
    application_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    appellant_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    examiner_name: Optional[str] = None,
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
          examiner_name='Smith',
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
        patent_number: Patent number (8524787, US8524787, etc.)
        appellant_name: Appellant/applicant name
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        examiner_name: Examiner name
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
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for appeal search")
            api_client = get_api_client()

        # Validate inputs
        if appeal_number:
            appeal_number = validate_appeal_number(appeal_number)

        if patent_number:
            patent_number = validate_patent_number(patent_number)

        if decision_date_from or decision_date_to:
            decision_date_from, decision_date_to = validate_date_range(
                decision_date_from, decision_date_to
            )

        if appellant_name:
            appellant_name = validate_party_name(appellant_name)

        limit = validate_limit(limit, max_limit=100)

        # Build filters using FilterBuilder pattern
        from .util.filter_builder import FilterBuilder
        from .config.filter_field_mapping import AppealFilterFields as Fields

        filters, range_filters = (FilterBuilder()
            .add_if(Fields.APPEAL_NUMBER, appeal_number)
            .add_if(Fields.APPLICATION_NUMBER, application_number)
            # Note: patent_number removed - appeals are for applications, not granted patents
            .add_if(Fields.APPELLANT_NAME, appellant_name)
            # Note: examiner_name removed - not available in appeals data structure
            .add_if(Fields.ART_UNIT, art_unit)
            .add_range_if(Fields.DECISION_DATE, decision_date_from, decision_date_to)
            .build())

        # Handle custom fields vs predefined field set
        if fields:
            # User specified custom fields - validate and use those
            fields = validate_custom_fields(fields)
            field_list = fields
            field_set_name = "custom"
        else:
            # No custom fields - use predefined tier
            field_list = field_manager.get_fields("appeals_minimal")
            field_set_name = "appeals_minimal"

        # Make API call
        raw_response = await api_client.search_appeals(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Filter response (custom fields vs predefined set)
        from .util.response_formatter import format_appeal_response
        if fields:
            # Custom fields - use filter_response_custom()
            filtered_response = field_manager.filter_response_custom(
                raw_response,
                fields
            )
        else:
            # Predefined tier - use standard filtering
            filtered_response = field_manager.filter_response(
                raw_response,
                field_set_name
            )

        # Format for output
        formatted = format_appeal_response(
            appeals=filtered_response.get("patentAppealDataBag", []),
            query_info=create_query_info(
                filters=filters,
                range_filters=range_filters,
                pagination={"offset": 0, "limit": limit}
            ),
            field_set=field_set_name,
            context_info=filtered_response.get("context_info"),
            count=filtered_response.get("count", 0)
        )

        return formatted

    except ValueError as e:
        # Validation error
        return format_error_response(str(e), "VALIDATION_ERROR")
    except Exception as e:
        # Unexpected error
        logger.error(f"Error in search_appeals_minimal: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


@mcp.tool()
async def search_appeals_balanced(
    appeal_number: Optional[str] = None,
    application_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    appellant_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    examiner_name: Optional[str] = None,
    art_unit: Optional[str] = None,
    technology_center: Optional[str] = None,
    decision_type: Optional[str] = None,
    decision_outcome: Optional[str] = None,
    claims_rejected: Optional[str] = None,
    claims_affirmed: Optional[str] = None,
    panel_members: Optional[str] = None,
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
        patent_number: Patent number (8524787)
        appellant_name: Appellant party name
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        examiner_name: Examiner name
        art_unit: Art unit number
        technology_center: Technology center number
        decision_type: Decision type
        decision_outcome: Decision outcome (Affirmed, Reversed, etc.)
        claims_rejected: Claims rejected
        claims_affirmed: Claims affirmed
        panel_members: Panel member names
        fields: Optional custom field list (overrides predefined balanced set).
                Use dot notation for nested fields.
                Examples: ["appealNumber", "decisionDate"]
                If not provided, uses predefined "appeals_balanced" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 20, max 100)

    Returns:
        JSON string with comprehensive appeal data (balanced or custom field set)
    """
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for appeal search")
            api_client = get_api_client()

        # Validate inputs
        if appeal_number:
            appeal_number = validate_appeal_number(appeal_number)

        if patent_number:
            patent_number = validate_patent_number(patent_number)

        if appellant_name:
            appellant_name = validate_party_name(appellant_name)

        if decision_date_from or decision_date_to:
            decision_date_from, decision_date_to = validate_date_range(
                decision_date_from, decision_date_to
            )

        limit = validate_limit(limit, max_limit=100)

        # Build filters using FilterBuilder pattern
        from .util.filter_builder import FilterBuilder
        from .config.filter_field_mapping import AppealFilterFields as Fields

        filters, range_filters = (FilterBuilder()
            .add_if(Fields.APPEAL_NUMBER, appeal_number)
            .add_if(Fields.APPLICATION_NUMBER, application_number)
            # Note: patent_number removed - appeals are for applications, not granted patents
            .add_if(Fields.APPELLANT_NAME, appellant_name)
            # Note: examiner_name removed - not available in appeals data structure
            .add_if(Fields.ART_UNIT, art_unit)
            .add_if(Fields.TECH_CENTER, technology_center)
            .add_if(Fields.DECISION_TYPE, decision_type)
            .add_if(Fields.DECISION_OUTCOME, decision_outcome)
            # Note: Claims fields may not exist in all appeals - testing needed
            # .add_if(Fields.CLAIMS_REJECTED, claims_rejected)
            # .add_if(Fields.CLAIMS_AFFIRMED, claims_affirmed)
            # .add_if(Fields.PANEL_MEMBERS, panel_members)
            .add_range_if(Fields.DECISION_DATE, decision_date_from, decision_date_to)
            .build())

        # Handle custom fields vs predefined field set
        if fields:
            # User specified custom fields - validate and use those
            fields = validate_custom_fields(fields)
            field_list = fields
            field_set_name = "custom"
        else:
            # No custom fields - use predefined tier
            field_list = field_manager.get_fields("appeals_balanced")
            field_set_name = "appeals_balanced"

        # Make API call
        raw_response = await api_client.search_appeals(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Filter response (custom fields vs predefined set)
        from .util.response_formatter import format_appeal_response
        if fields:
            # Custom fields - use filter_response_custom()
            filtered_response = field_manager.filter_response_custom(
                raw_response,
                fields
            )
        else:
            # Predefined tier - use standard filtering
            filtered_response = field_manager.filter_response(
                raw_response,
                field_set_name
            )

        # Format for output
        formatted = format_appeal_response(
            appeals=filtered_response.get("patentAppealDataBag", []),
            query_info=create_query_info(
                filters=filters,
                range_filters=range_filters,
                pagination={"offset": 0, "limit": limit}
            ),
            field_set=field_set_name,
            context_info=filtered_response.get("context_info"),
            count=filtered_response.get("count", 0)
        )

        return formatted

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except Exception as e:
        logger.error(f"Error in search_appeals_balanced: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


@mcp.tool()
async def search_appeals_complete(
    appeal_number: Optional[str] = None,
    application_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    appellant_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    examiner_name: Optional[str] = None,
    art_unit: Optional[str] = None,
    technology_center: Optional[str] = None,
    decision_type: Optional[str] = None,
    decision_outcome: Optional[str] = None,
    claims_rejected: Optional[str] = None,
    claims_affirmed: Optional[str] = None,
    panel_members: Optional[str] = None,
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
        patent_number: Patent number (8524787)
        appellant_name: Appellant party name
        decision_date_from: Decision date start (YYYY-MM-DD)
        decision_date_to: Decision date end (YYYY-MM-DD)
        examiner_name: Examiner name
        art_unit: Art unit number
        technology_center: Technology center number
        decision_type: Decision type
        decision_outcome: Decision outcome (Affirmed, Reversed, etc.)
        claims_rejected: Claims rejected
        claims_affirmed: Claims affirmed
        panel_members: Panel member names
        fields: Optional custom field list (overrides predefined complete set).
                Use dot notation for nested fields.
                Examples: ["appealNumber", "decisionDate"]
                If not provided, uses predefined "appeals_complete" field set.
                NOTE: documentBag fields are forbidden (use ptab_get_documents instead)
        limit: Maximum results (default 10, max 50)

    Returns:
        JSON string with complete appeal data (all fields or custom field set)
    """
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for appeal search")
            api_client = get_api_client()

        # Validate inputs
        if appeal_number:
            appeal_number = validate_appeal_number(appeal_number)

        if patent_number:
            patent_number = validate_patent_number(patent_number)

        if appellant_name:
            appellant_name = validate_party_name(appellant_name)

        if decision_date_from or decision_date_to:
            decision_date_from, decision_date_to = validate_date_range(
                decision_date_from, decision_date_to
            )

        limit = validate_limit(limit, max_limit=100)

        # Build filters using FilterBuilder pattern
        from .util.filter_builder import FilterBuilder
        from .config.filter_field_mapping import AppealFilterFields as Fields

        filters, range_filters = (FilterBuilder()
            .add_if(Fields.APPEAL_NUMBER, appeal_number)
            .add_if(Fields.APPLICATION_NUMBER, application_number)
            # Note: patent_number removed - appeals are for applications, not granted patents
            .add_if(Fields.APPELLANT_NAME, appellant_name)
            # Note: examiner_name removed - not available in appeals data structure
            .add_if(Fields.ART_UNIT, art_unit)
            .add_if(Fields.TECH_CENTER, technology_center)
            .add_if(Fields.DECISION_TYPE, decision_type)
            .add_if(Fields.DECISION_OUTCOME, decision_outcome)
            # Note: Claims fields may not exist in all appeals - testing needed
            # .add_if(Fields.CLAIMS_REJECTED, claims_rejected)
            # .add_if(Fields.CLAIMS_AFFIRMED, claims_affirmed)
            # .add_if(Fields.PANEL_MEMBERS, panel_members)
            .add_range_if(Fields.DECISION_DATE, decision_date_from, decision_date_to)
            .build())

        # Handle custom fields vs predefined field set
        if fields:
            # User specified custom fields - validate and use those
            fields = validate_custom_fields(fields)
            field_list = fields
            field_set_name = "custom"
        else:
            # No custom fields - use predefined tier
            field_list = field_manager.get_fields("appeals_complete")
            field_set_name = "appeals_complete"

        # Make API call
        raw_response = await api_client.search_appeals(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Filter response (custom fields vs predefined set)
        from .util.response_formatter import format_appeal_response
        if fields:
            # Custom fields - use filter_response_custom()
            filtered_response = field_manager.filter_response_custom(
                raw_response,
                fields
            )
        else:
            # Predefined tier - use standard filtering
            filtered_response = field_manager.filter_response(
                raw_response,
                field_set_name
            )

        formatted = format_appeal_response(
            appeals=filtered_response.get("patentAppealDataBag", []),
            query_info=create_query_info(
                filters=filters,
                range_filters=range_filters,
                pagination={"offset": 0, "limit": limit}
            ),
            field_set=field_set_name,
            context_info=filtered_response.get("context_info"),
            count=filtered_response.get("count", 0)
        )

        return formatted

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except Exception as e:
        logger.error(f"Error in search_appeals_complete: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


# ==========================================
# INTERFERENCES SEARCH TOOLS (3 tools)
# ==========================================

@mcp.tool()
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
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for interference search")
            api_client = get_api_client()

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
        from .util.filter_builder import FilterBuilder
        from .config.filter_field_mapping import InterferenceFilterFields as Fields

        filters, range_filters = (FilterBuilder()
            .add_if(Fields.INTERFERENCE_NUMBER, interference_number)
            # Note: Interferences have separate senior/junior fields
            # Searching senior party by default (can add junior search if needed)
            .add_if(Fields.SENIOR_PATENT_NUMBER, patent_number)
            .add_if(Fields.SENIOR_PARTY_NAME, party_name)
            # Note: Interferences use DECLARATION_DATE instead of DECISION_DATE
            .add_range_if(Fields.DECLARATION_DATE, decision_date_from, decision_date_to)
            .build())

        # Handle custom fields vs predefined field set
        if fields:
            # User specified custom fields - validate and use those
            fields = validate_custom_fields(fields)
            field_list = fields
            field_set_name = "custom"
        else:
            # No custom fields - use predefined tier
            field_list = field_manager.get_fields("interferences_minimal")
            field_set_name = "interferences_minimal"

        # Make API call
        raw_response = await api_client.search_interferences(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Filter response (custom fields vs predefined set)
        from .util.response_formatter import format_interference_response
        if fields:
            # Custom fields - use filter_response_custom()
            filtered_response = field_manager.filter_response_custom(
                raw_response,
                fields
            )
        else:
            # Predefined tier - use standard filtering
            filtered_response = field_manager.filter_response(
                raw_response,
                field_set_name
            )

        # Format for output
        formatted = format_interference_response(
            interferences=filtered_response.get("patentInterferenceDataBag", []),
            query_info=create_query_info(
                filters=filters,
                range_filters=range_filters,
                pagination={"offset": 0, "limit": limit}
            ),
            field_set=field_set_name,
            context_info=filtered_response.get("context_info"),
            count=filtered_response.get("count", 0)
        )

        return formatted

    except ValueError as e:
        # Validation error
        return format_error_response(str(e), "VALIDATION_ERROR")
    except Exception as e:
        # Unexpected error
        logger.error(f"Error in search_interferences_minimal: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


@mcp.tool()
async def search_interferences_balanced(
    interference_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    party_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    technology_center: Optional[str] = None,
    decision_type: Optional[str] = None,
    decision_outcome: Optional[str] = None,
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
        decision_type: Decision type
        decision_outcome: Decision outcome
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
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for interference search")
            api_client = get_api_client()

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
        from .util.filter_builder import FilterBuilder
        from .config.filter_field_mapping import InterferenceFilterFields as Fields

        filters, range_filters = (FilterBuilder()
            .add_if(Fields.INTERFERENCE_NUMBER, interference_number)
            # Note: Interferences have separate senior/junior patent fields
            .add_if(Fields.SENIOR_PATENT_NUMBER, patent_number)
            # Note: Using SENIOR_PARTY_NAME (not PARTY_NAME which doesn't exist)
            .add_if(Fields.SENIOR_PARTY_NAME, party_name)
            # Note: Using SENIOR_TECH_CENTER (interferences have separate senior/junior tech centers)
            .add_if(Fields.SENIOR_TECH_CENTER, technology_center)
            # Note: DECISION_TYPE and DECISION_OUTCOME don't exist for interferences
            # (interferences don't have decision data like appeals/trials)
            # .add_if(Fields.DECISION_TYPE, decision_type)  # REMOVED - field doesn't exist
            # .add_if(Fields.DECISION_OUTCOME, decision_outcome)  # REMOVED - field doesn't exist
            .add_if(Fields.SENIOR_PARTY_NAME, senior_party)
            .add_if(Fields.JUNIOR_PARTY_NAME, junior_party)
            # Note: Interferences use DECLARATION_DATE instead of DECISION_DATE
            .add_range_if(Fields.DECLARATION_DATE, decision_date_from, decision_date_to)
            .build())

        # Handle custom fields vs predefined field set
        if fields:
            # User specified custom fields - validate and use those
            fields = validate_custom_fields(fields)
            field_list = fields
            field_set_name = "custom"
        else:
            # No custom fields - use predefined tier
            field_list = field_manager.get_fields("interferences_balanced")
            field_set_name = "interferences_balanced"

        # Make API call
        raw_response = await api_client.search_interferences(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Filter response (custom fields vs predefined set)
        from .util.response_formatter import format_interference_response
        if fields:
            # Custom fields - use filter_response_custom()
            filtered_response = field_manager.filter_response_custom(
                raw_response,
                fields
            )
        else:
            # Predefined tier - use standard filtering
            filtered_response = field_manager.filter_response(
                raw_response,
                field_set_name
            )

        # Format for output
        formatted = format_interference_response(
            interferences=filtered_response.get("patentInterferenceDataBag", []),
            query_info=create_query_info(
                filters=filters,
                range_filters=range_filters,
                pagination={"offset": 0, "limit": limit}
            ),
            field_set=field_set_name,
            context_info=filtered_response.get("context_info"),
            count=filtered_response.get("count", 0)
        )

        return formatted

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except Exception as e:
        logger.error(f"Error in search_interferences_balanced: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


@mcp.tool()
async def search_interferences_complete(
    interference_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    party_name: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    technology_center: Optional[str] = None,
    decision_type: Optional[str] = None,
    decision_outcome: Optional[str] = None,
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
        decision_type: Decision type
        decision_outcome: Decision outcome
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
    try:
        # Ensure API client is initialized (critical fix for async lifecycle issues)
        global api_client
        if api_client is None:
            logger.info("Initializing API client for interference search")
            api_client = get_api_client()

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
        from .util.filter_builder import FilterBuilder
        from .config.filter_field_mapping import InterferenceFilterFields as Fields

        filters, range_filters = (FilterBuilder()
            .add_if(Fields.INTERFERENCE_NUMBER, interference_number)
            # Note: Interferences have separate senior/junior patent fields
            .add_if(Fields.SENIOR_PATENT_NUMBER, patent_number)
            # Note: Using SENIOR_PARTY_NAME (not PARTY_NAME which doesn't exist)
            .add_if(Fields.SENIOR_PARTY_NAME, party_name)
            # Note: Using SENIOR_TECH_CENTER (interferences have separate senior/junior tech centers)
            .add_if(Fields.SENIOR_TECH_CENTER, technology_center)
            # Note: DECISION_TYPE and DECISION_OUTCOME don't exist for interferences
            # (interferences don't have decision data like appeals/trials)
            # .add_if(Fields.DECISION_TYPE, decision_type)  # REMOVED - field doesn't exist
            # .add_if(Fields.DECISION_OUTCOME, decision_outcome)  # REMOVED - field doesn't exist
            .add_if(Fields.SENIOR_PARTY_NAME, senior_party)
            .add_if(Fields.JUNIOR_PARTY_NAME, junior_party)
            # Note: Interferences use DECLARATION_DATE instead of DECISION_DATE
            .add_range_if(Fields.DECLARATION_DATE, decision_date_from, decision_date_to)
            .build())

        # Handle custom fields vs predefined field set
        if fields:
            # User specified custom fields - validate and use those
            fields = validate_custom_fields(fields)
            field_list = fields
            field_set_name = "custom"
        else:
            # No custom fields - use predefined tier
            field_list = field_manager.get_fields("interferences_complete")
            field_set_name = "interferences_complete"

        # Make API call
        raw_response = await api_client.search_interferences(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Filter response (custom fields vs predefined set)
        from .util.response_formatter import format_interference_response
        if fields:
            # Custom fields - use filter_response_custom()
            filtered_response = field_manager.filter_response_custom(
                raw_response,
                fields
            )
        else:
            # Predefined tier - use standard filtering
            filtered_response = field_manager.filter_response(
                raw_response,
                field_set_name
            )

        formatted = format_interference_response(
            interferences=filtered_response.get("patentInterferenceDataBag", []),
            query_info=create_query_info(
                filters=filters,
                range_filters=range_filters,
                pagination={"offset": 0, "limit": limit}
            ),
            field_set=field_set_name,
            context_info=filtered_response.get("context_info"),
            count=filtered_response.get("count", 0)
        )

        return formatted

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except Exception as e:
        logger.error(f"Error in search_interferences_complete: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


# ==========================================
# UTILITY TOOLS (2 tools)
# ==========================================

@mcp.tool()
async def ptab_get_guidance(section: str) -> str:
    """
    Get selective PTAB MCP guidance for context-efficient access.

    This tool provides targeted guidance sections (1-15KB each) instead of dumping
    all documentation at once (~70KB+). Request only the section you need.

    Context Reduction: 90-95% reduction per section vs complete guidance.

    Available Sections:
        - overview: Available sections and quick reference chart
        - fields: Field configuration and customization (YAML editing)
        - documents: Document operations and download link formatting
        - workflows_pfw: Cross-MCP integration with Patent File Wrapper
        - workflows_fpd: Cross-MCP integration with Filing & Petition Data
        - workflows_citations: Cross-MCP integration with Enriched Citations
        - workflows_pinecone: Cross-MCP integration with Pinecone RAG
        - workflows_complete: Complete prosecution lifecycle tracking (all MCPs)
        - tools: Tool usage and progressive disclosure decision tree
        - errors: Common error patterns and troubleshooting
        - cost: Cost optimization strategies (token reduction, OCR costs)

    Quick Reference Chart:
        - "Find IPR/PGR/CBM proceedings" → section='tools'
        - "Document download formatting" → section='documents'
        - "PFW integration workflows" → section='workflows_pfw'
        - "Field customization" → section='fields'
        - "Error troubleshooting" → section='errors'
        - "Reduce token costs" → section='cost'

    Args:
        section: Guidance section name (see Available Sections above)

    Returns:
        Markdown-formatted guidance for requested section only

    Example:
        ptab_get_guidance(section='workflows_pfw')
        ptab_get_guidance(section='documents')
        ptab_get_guidance(section='overview')
    """
    try:
        # Get guidance section (returns clean markdown, NOT dict)
        guidance_markdown = get_guidance_section(section)
        return guidance_markdown

    except Exception as e:
        logger.error(f"Error in ptab_get_guidance: {str(e)}")
        return format_error_response(str(e), "GUIDANCE_ERROR")


@mcp.tool()
async def ptab_get_field_configs() -> str:
    """
    View current field configuration from YAML.

    Shows predefined field sets for trials, appeals, and interferences.
    Useful for understanding available fields and customizing configurations.

    Returns:
        JSON string with field configuration details

    Example Response:
        {
            "config_file": "field_configs.yaml",
            "predefined_sets": {
                "trials_minimal": {
                    "description": "Ultra-minimal trial discovery",
                    "fields": ["trialNumber", "trialMetaData.accordedFilingDate", ...],
                    "field_count": 12
                },
                "trials_balanced": {...},
                "trials_complete": {...}
            }
        }
    """
    try:
        # Get all predefined sets
        config_info = {
            "config_file": "field_configs.yaml",
            "config_location": str(config_path),
            "predefined_sets": {}
        }

        # Get field sets for each data type
        for data_type in ["trials", "appeals", "interferences"]:
            for tier in ["minimal", "balanced", "complete"]:
                set_name = f"{data_type}_{tier}"
                try:
                    fields = field_manager.get_fields(set_name)
                    config_info["predefined_sets"][set_name] = {
                        "description": f"{tier.title()} {data_type} field set",
                        "fields": fields,
                        "field_count": len(fields)
                    }
                except Exception as e:
                    logger.warning(f"Field set {set_name} not found: {e}")

        return json.dumps(config_info, indent=2)

    except Exception as e:
        logger.error(f"Error in ptab_get_field_configs: {str(e)}")
        return format_error_response(str(e), "CONFIG_ERROR")


# ==========================================
# PROXY SERVER MANAGEMENT
# ==========================================

async def _run_proxy_server(port: int = 8083):
    """
    Run the FastAPI proxy server.

    Uses API key from Settings (which may come from secure storage or environment variables).
    """
    try:
        import uvicorn
        from .proxy.server import create_proxy_app

        # Pass API key and port from Settings to proxy server
        # This allows proxy to work with secure storage (Windows DPAPI)
        app = create_proxy_app(api_key=settings.uspto_api_key, port=port)
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            access_log=False  # Reduce noise in logs
        )
        server = uvicorn.Server(config)
        logger.info(f"HTTP proxy server starting on http://127.0.0.1:{port}")
        await server.serve()

    except Exception as e:
        global _proxy_server_running
        _proxy_server_running = False
        logger.error(f"Proxy server failed: {e}")
        raise


async def _ensure_local_proxy_running(port: int = None) -> bool:
    """
    Ensure the local proxy server is running (on-demand startup).

    This function is called when:
    - ENABLE_ALWAYS_ON_PROXY=false (on-demand mode)
    - Centralized proxy is unavailable
    - A document download is requested

    Thread-safe: Uses asyncio.Lock to prevent concurrent startup attempts.

    Args:
        port: Port number for proxy server (default: from get_local_proxy_port())

    Returns:
        True if proxy is running (already running or successfully started)
    """
    global _proxy_server_running, _proxy_server_task

    # Fast path: already running
    if _proxy_server_running:
        return True

    # Use lock to prevent concurrent startup attempts
    async with _proxy_startup_lock:
        # Double-check after acquiring lock (another task may have started it)
        if _proxy_server_running:
            return True

        # Determine port
        if port is None:
            port = get_local_proxy_port()

        try:
            logger.info(f"📦 On-demand proxy startup: Starting local proxy on port {port}")
            _proxy_server_task = asyncio.create_task(_run_proxy_server(port))
            _proxy_server_running = True

            # Brief wait to ensure server starts cleanly
            await asyncio.sleep(0.5)

            # Verify proxy is responding
            import requests
            try:
                response = requests.get(f"http://localhost:{port}/", timeout=1.0)
                if response.status_code == 200:
                    logger.info(f"✅ On-demand proxy started successfully on port {port}")
                    return True
            except Exception as e:
                logger.warning(f"Proxy started but health check failed: {e}")
                # Continue anyway - the server task is running
                return True

        except Exception as e:
            logger.error(f"❌ Failed to start on-demand proxy: {e}")
            _proxy_server_running = False
            return False

    return _proxy_server_running


def _detect_pfw_proxy() -> Optional[int]:
    """
    Detect if USPTO PFW MCP proxy is available for centralized document downloads.

    Uses environment variable CENTRALIZED_PROXY_PORT for instant detection:
    - Not set or "none": Skip HTTP checks entirely (instant startup)
    - Set to valid port: Use that port directly
    - Fallback: HTTP probe with retry logic for race conditions

    Returns:
        Port number if PFW proxy is available, None otherwise
    """
    logger.info("🔍 Checking for centralized USPTO PFW MCP proxy...")

    # INSTANT DETECTION: Check environment variable first
    centralized_port_env = os.getenv("CENTRALIZED_PROXY_PORT", "none").lower()

    if centralized_port_env == "none":
        # PFW explicitly not installed - skip all HTTP checks (instant startup)
        logger.info("ℹ️  Standalone mode: Using local PTAB proxy (always-on)")
        logger.info("   💡 Install USPTO PFW MCP for enhanced features:")
        logger.info("      - Persistent download links (7-day encrypted URLs)")
        logger.info("      - Centralized proxy (unified rate limiting)")
        logger.info("      - Cross-MCP document sharing and caching")
        logger.info("   📦 Get it at: https://github.com/johnwalkoe/patent_filewrapper_mcp")
        return None

    # If port is explicitly set, try it first
    if centralized_port_env.isdigit():
        explicit_port = int(centralized_port_env)
        try:
            response = requests.get(f"http://localhost:{explicit_port}/", timeout=0.3)
            if response.status_code == 200:
                logger.info("🎯 SUCCESS: Using centralized USPTO proxy ecosystem")
                logger.info(f"   ✅ Detected PFW proxy on port {explicit_port}")
                logger.info("   ✅ Persistent links available")
                logger.info("   ✅ Enhanced rate limiting")
                logger.info("   ✅ Cross-MCP document sharing")
                return explicit_port
        except Exception:
            logger.warning(f"   ⚠️  CENTRALIZED_PROXY_PORT={explicit_port} set but proxy not responding")

    # Optimized retry configuration for fast startup
    max_retries = 3
    retry_delay = 1.0  # seconds
    timeout = 1.0  # seconds

    for attempt in range(max_retries):
        if attempt > 0:
            logger.info(f"   Retry {attempt}/{max_retries-1} (waiting for PFW proxy to start)...")
            time.sleep(retry_delay)

        # Check if PFW proxy is running on port 8080 (primary port)
        try:
            pfw_port = 8080
            response = requests.get(f"http://localhost:{pfw_port}/", timeout=timeout)
            if response.status_code == 200:
                data = response.json()
                if "Patent File Wrapper Proxy" in data.get("service", ""):
                    logger.info("🎯 SUCCESS: Detected PFW centralized proxy on port 8080")
                    logger.info("   ✅ Persistent links available")
                    logger.info("   ✅ Enhanced rate limiting")
                    logger.info("   ✅ Cross-MCP document sharing")
                    os.environ['CENTRALIZED_PROXY_PORT'] = '8080'
                    return pfw_port
        except Exception:
            pass

    # PFW not detected - use standalone mode
    logger.info("ℹ️  Standalone mode: Using local PTAB proxy (always-on)")
    logger.info("   💡 Install USPTO PFW MCP for enhanced features")
    return None


async def run_hybrid_server(enable_always_on: bool = True, proxy_port: int = 8083):
    """
    Run both MCP server and HTTP proxy server concurrently.

    Args:
        enable_always_on: If True, start proxy immediately (default)
        proxy_port: Port for the HTTP proxy server (default: 8083)
    """
    try:
        global _proxy_server_running, _proxy_server_task

        # Detect PFW proxy with retry logic
        pfw_proxy_port = _detect_pfw_proxy()

        # Start both servers concurrently
        logger.info("Starting hybrid PTAB MCP + HTTP proxy server")

        # Run MCP server in a separate task
        mcp_task = asyncio.create_task(
            asyncio.to_thread(lambda: mcp.run(transport='stdio'))
        )

        # Start proxy server immediately if always-on mode is enabled
        if enable_always_on:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                port_free = s.connect_ex(("127.0.0.1", proxy_port)) != 0

            if not port_free:
                logger.info(
                    "Port %d already in use — skipping proxy server startup "
                    "(another instance is running; MCP tools are still fully available)",
                    proxy_port,
                )
                _proxy_server_running = True  # treat as running so tools work
            else:
                logger.info(f"Always-on mode: Starting HTTP proxy server on port {proxy_port}")
                _proxy_server_task = asyncio.create_task(_run_proxy_server(proxy_port))
                _proxy_server_running = True
                # Brief wait to ensure server starts cleanly
                await asyncio.sleep(0.5)
                logger.info(f"Proxy server started successfully on port {proxy_port}")
        else:
            logger.info(f"On-demand mode: Proxy will start on first document request")

        # Wait for MCP server to complete (it runs indefinitely)
        await mcp_task

    except KeyboardInterrupt:
        logger.info("Shutting down servers...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


# ==========================================
# SERVER ENTRY POINT
# ==========================================

def run_server():
    """
    Entry point for the ptab-mcp command.
    Called by: uv run ptab-mcp
    """
    # Check if always-on proxy should be enabled (default: true)
    enable_always_on = os.getenv("ENABLE_ALWAYS_ON_PROXY", "true").lower() == "true"

    # Get local proxy port
    default_port = get_local_proxy_port()

    # Run hybrid server with proxy
    asyncio.run(run_hybrid_server(enable_always_on=enable_always_on, proxy_port=default_port))


if __name__ == "__main__":
    run_server()
