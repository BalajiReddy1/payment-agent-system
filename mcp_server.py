"""
MCP Server
Exposes the payment operations tools over the Model Context Protocol so any
MCP client (Claude Desktop, a custom agent, an IDE) can drive the agent's
control plane.

This module is deliberately a thin adapter. The tools themselves live in
payment_tools.py, which has no MCP or asyncio dependency; keeping a second
copy here is how the two surfaces previously drifted apart, with the MCP
variant missing fixes the other had.
"""

import sys
import os

from mcp.server.fastmcp import FastMCP

# Ensure we can import from the project root
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from payment_tools import ALL_TOOLS, approve_pending_action  # noqa: E402

# Initialize the FastMCP Server
mcp = FastMCP("PaymentAgentHands")

# Register every agent-facing tool. approve_pending_action is registered
# separately below because it represents a human acting, not the agent.
for _tool in ALL_TOOLS:
    mcp.tool()(_tool)


@mcp.tool()
def approve_action(approval_id: str, approver: str) -> str:
    """Approve an action that was held for human authorization.

    Intended for a human operator, not for an autonomous agent: approving one's
    own proposals would defeat the authorization tiers entirely.

    Args:
        approval_id: The approval id returned when the action was queued.
        approver: Identity of the human approving the action.
    """
    return approve_pending_action(approval_id, approver)


if __name__ == "__main__":
    # Start the FastMCP server via stdio by default
    mcp.run()
