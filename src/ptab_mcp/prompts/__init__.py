"""
PTAB MCP Prompt Templates

This module contains comprehensive prompt templates for USPTO PTAB analysis workflows.
Each prompt provides complete implementation guidance with working code, error handling,
and cross-MCP integration patterns (PFW, FPD, Citations).

All prompts follow the comprehensive implementation pattern:
- Complete working code with loops and data processing
- Error handling with try/except for cross-MCP calls
- Safety rails with explicit context limits
- Presentation formatting with markdown tables
- Result aggregation and scoring systems
- Cross-MCP integration workflows

Available Prompts:
- trial_precedent_research: Find similar PTAB precedents for strategy
- complete_trial_litigation_package: Download complete trial docket
- prior_art_board_decision_mining: Extract prior art from Board decisions
- trial_timeline_analysis: Timeline analysis of proceeding milestones
- ipr_challenge_defense_PFW: IPR defense strategy with prosecution history
- ipr_petitioner_portfolio_analysis_PFW: Portfolio IPR risk assessment
- portfolio_ptab_risk_assessment_PFW_FPD: Combined prosecution and PTAB risk
- technology_landscape_ptab_analysis_PFW: Technology area PTAB trends
- cross_mcp_patent_intelligence_PFW: Complete patent intelligence package
- ptab_prior_art_validation_PFW_CITATIONS: Validate prior art across MCPs
- complete_prosecution_lifecycle_PFW_FPD_CITATIONS: Full lifecycle tracking
"""

import os

# Global mcp object set by register_prompts()
mcp = None

# Registration gate for the workflow prompt templates (same pattern as the
# ptab_manage_users PTAB_ENABLE_USER_MANAGEMENT gate: filtered at registration
# time, so gated-off prompts never appear in prompts/list). Default OFF —
# deployments that want the prompts must set PTAB_ENABLE_PROMPTS=true.
PROMPTS_ENABLED = (
    os.getenv("PTAB_ENABLE_PROMPTS", "false").lower() == "true"
)


def register_prompts(mcp_server):
    """Register all prompt templates with the MCP server.

    This function must be called after the MCP server is initialized.
    It sets the global mcp object and imports all prompt modules,
    which then register their prompts using the @mcp.prompt() decorator.

    Registration-gated by PTAB_ENABLE_PROMPTS (default off): when the gate is
    off, no prompt modules are imported and nothing registers.

    Args:
        mcp_server: The initialized FastMCP server instance
    """
    global mcp
    mcp = mcp_server

    if not PROMPTS_ENABLED:
        return

    # Import all prompt modules to register them with the MCP server
    # These imports must happen AFTER mcp is set
    from . import trial_precedent_research  # noqa: F401 — registers via @mcp.prompt side effect
    from . import complete_trial_litigation_package  # noqa: F401 — registers via @mcp.prompt side effect
    from . import prior_art_board_decision_mining  # noqa: F401 — registers via @mcp.prompt side effect
    from . import trial_timeline_analysis  # noqa: F401 — registers via @mcp.prompt side effect
    from . import ipr_challenge_defense_PFW  # noqa: F401 — registers via @mcp.prompt side effect
    from . import ipr_petitioner_portfolio_analysis_PFW  # noqa: F401 — registers via @mcp.prompt side effect
    from . import portfolio_ptab_risk_assessment_PFW_FPD  # noqa: F401 — registers via @mcp.prompt side effect
    from . import technology_landscape_ptab_analysis_PFW  # noqa: F401 — registers via @mcp.prompt side effect
    from . import cross_mcp_patent_intelligence_PFW  # noqa: F401 — registers via @mcp.prompt side effect
    from . import ptab_prior_art_validation_PFW_CITATIONS  # noqa: F401 — registers via @mcp.prompt side effect
    from . import complete_prosecution_lifecycle_PFW_FPD_CITATIONS  # noqa: F401 — registers via @mcp.prompt side effect


__all__ = [
    'register_prompts',
    'PROMPTS_ENABLED',
    'trial_precedent_research',
    'complete_trial_litigation_package',
    'prior_art_board_decision_mining',
    'trial_timeline_analysis',
    'ipr_challenge_defense_PFW',
    'ipr_petitioner_portfolio_analysis_PFW',
    'portfolio_ptab_risk_assessment_PFW_FPD',
    'technology_landscape_ptab_analysis_PFW',
    'cross_mcp_patent_intelligence_PFW',
    'ptab_prior_art_validation_PFW_CITATIONS',
    'complete_prosecution_lifecycle_PFW_FPD_CITATIONS',
]
