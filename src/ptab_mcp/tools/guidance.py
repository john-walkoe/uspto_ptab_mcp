"""Guidance + field-configuration utility tools."""

import json
import os

from ..config.tool_reflections import get_guidance_section
from ..runtime import config_path, field_manager
from ..shared.safe_logger import get_safe_logger
from ..util.response_formatter import format_error_response

logger = get_safe_logger(__name__)

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
        - cost: Context optimization strategies (token reduction, targeted extraction)
        - limits: Active response-size budgets (live values), the _bounds/_window
                  markers, page caps, and the paging blocks on searches/documents

    Quick Reference Chart:
        - "Find IPR/PGR/CBM proceedings" → section='tools'
        - "Document download formatting" → section='documents'
        - "PFW integration workflows" → section='workflows_pfw'
        - "Field customization" → section='fields'
        - "Error troubleshooting" → section='errors'
        - "Reduce token usage" → section='cost'
        - "Why was my response truncated / how do I page it?" → section='limits'

    Args:
        section: Guidance section name (see Available Sections above)

    Returns:
        Markdown-formatted guidance for requested section only

    Example:
        PTAB_get_guidance(section='workflows_pfw')
        PTAB_get_guidance(section='documents')
        PTAB_get_guidance(section='overview')
    """
    try:
        # Get guidance section (returns clean markdown, NOT dict)
        guidance_markdown = get_guidance_section(section)
        return guidance_markdown

    except Exception as e:
        logger.error(f"Error in PTAB_get_guidance: {str(e)}")
        return format_error_response(str(e), "GUIDANCE_ERROR")


async def ptab_get_field_configs() -> str:
    """
    View current field configuration from YAML.
    Fields, field sets, available fields, columns, what fields can I request, schema, configuration, customize.

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
        # Full filesystem path only in stdio mode (local user edits the file);
        # HTTP mode serves remote clients — don't disclose server paths.
        is_stdio = os.getenv("FASTMCP_TRANSPORT", "stdio").lower() == "stdio"
        config_info = {
            "config_file": "field_configs.yaml",
            "config_location": str(config_path) if is_stdio else "field_configs.yaml (server repo root)",
            "predefined_sets": {}
        }

        # A YAML load failure silently swaps the built-in emergency field sets
        # in behind identical field_set labels, so say which config is live.
        fallback_note = field_manager.fallback_note()
        config_info["field_set_fallback"] = bool(fallback_note)
        if fallback_note:
            config_info["field_set_fallback_note"] = fallback_note

        # Active response budgets and page caps, so the model can see what this
        # process is enforcing (same numbers as PTAB_get_guidance('limits')).
        from ..shared.response_bounds import bounds_config

        config_info["limits"] = bounds_config()

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
        logger.error(f"Error in PTAB_get_field_configs: {str(e)}")
        return format_error_response(str(e), "CONFIG_ERROR")


def register(mcp) -> None:
    """Register the guidance/utility tools (schemas unchanged; PTAB_ display names)."""
    mcp.tool(name="PTAB_get_guidance",
             annotations={"defer_loading": False, "readOnlyHint": True})(ptab_get_guidance)
    mcp.tool(name="PTAB_get_field_configs",
             annotations={"defer_loading": True, "readOnlyHint": True})(ptab_get_field_configs)
