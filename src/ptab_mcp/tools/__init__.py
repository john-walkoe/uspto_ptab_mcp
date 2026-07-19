"""Tool registration package (SD-1/SOLID-1 god-module split).

Each module defines its tools as plain (envelope-wrapped) async functions and
exposes register(mcp); register_all preserves the historical registration
order: admin -> trials -> documents -> appeals -> interferences -> guidance.
"""

from . import admin, appeals, documents, guidance, interferences, trials


def register_all(mcp, auth_provider=None) -> None:
    admin.register(mcp, auth_provider)
    trials.register(mcp)
    documents.register(mcp)
    appeals.register(mcp)
    interferences.register(mcp)
    guidance.register(mcp)
