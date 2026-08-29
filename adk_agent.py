"""
ADK Agent — the tool-calling path.

Uses Gemini 2.5 Flash via the google-genai SDK with native Python function-calling.
No MCP subprocess, no asyncio — fully synchronous and Cloud Run compatible.

The SDK import is deliberately deferred into analyze_and_act(). This module is
imported by an application surface, whose job — showing what the agent
detected and did — needs no LLM at all. Importing google.genai at module scope
meant a missing optional package took the entire UI down with a
ModuleNotFoundError, for a capability that page never used.
"""

import os
import json
import logging
from typing import Dict, Any

from payment_tools import ALL_TOOLS

logger = logging.getLogger(__name__)

# ── System prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an autonomous Payment Operations Agent.
You receive real-time payment metrics and alerts.
You MUST use your provided tools to mitigate payment failures based on these metrics.

Rules:
1. Always explain your reasoning BEFORE calling a tool.
2. Choose the most appropriate tool for the situation.
3. If the situation is critical, act immediately with circuit breakers or method suppression.
4. For moderate issues, adjust retry strategies or routing first.
5. Always alert the ops team for visibility on any action you take.
"""


def analyze_and_act(metrics_summary: str) -> Dict[str, Any]:
    """
    Send a metrics summary to Gemini, let it reason and call tools directly.
    Fully synchronous — safe to call from a server-side application surface.

    Args:
        metrics_summary: A plain-text description of the current payment situation.

    Returns:
        Dict with keys: agent_reasoning, tool_called, tool_result

    Raises:
        RuntimeError: if the google-genai SDK is not installed. Callers that
            treat the LLM as optional should catch this; nothing else in the
            system depends on it.
    """

    # 1. Initialize Gemini client. Imported here, not at module scope, so the
    #    application can start without the SDK present.
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed; the tool-calling path is "
            "unavailable. Install it with `pip install google-genai`."
        ) from exc

    client = genai.Client()

    # 2. Create chat with tools wired in natively
    chat = client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=ALL_TOOLS,       # plain Python functions — SDK handles schema
            temperature=0.2,
        ),
    )

    logger.info("Sending metrics to Gemini: %s", metrics_summary)

    # 3. Send the user message — the SDK handles tool dispatch automatically
    response = chat.send_message(metrics_summary)

    # 4. Build result dict
    result: Dict[str, Any] = {
        "agent_reasoning": response.text or "",
        "tool_called": None,
        "tool_result": None,
    }

    # The google-genai SDK with automatic_function_calling (default) will
    # execute the function on our behalf and include the result in the
    # response text. We can also inspect the history for explicit tool info.
    for content in chat.get_history():
        for part in content.parts:
            if hasattr(part, "function_call") and part.function_call:
                result["tool_called"] = part.function_call.name
            if hasattr(part, "function_response") and part.function_response:
                result["tool_result"] = str(part.function_response.response)

    return result


# ── CLI test harness ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    test_metrics = (
        "ALERT: Issuer HDFC Bank is showing a 15% drop in success rate "
        "in the last 10 minutes. Latency has spiked to 800ms. "
        "Immediate action is required."
    )

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY or GOOGLE_API_KEY before running.")
    else:
        output = analyze_and_act(test_metrics)
        print("\n--- FINAL OUTPUT ---")
        print(json.dumps(output, indent=2))
