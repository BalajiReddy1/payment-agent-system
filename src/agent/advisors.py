"""
Advisors: the slow lane of the two-lane brain.

The deterministic lane has already detected the incident, scored the
alternatives and decided what to do. An advisor is asked a narrower question:
*what should a human understand about this?* It writes the assessment that
appears on the incident, using the evidence, the hypotheses, and what
measurably worked on similar incidents before.

Two deliberate constraints.

**Advisors get no tools.** The tool-calling path exists separately and runs
through the authorization tiers and the approval queue. Handing the advisor
those tools would create a second decision path that bypasses the ranking, the
guardrails and the holdout measurement - an unaudited way to change payment
routing, arrived at by a component whose job was to write a sentence.

**The model is optional.** The import is lazy and every failure is contained,
so a missing package, an absent API key or a provider outage degrades the
narrative and never the mitigation. build_advisor() returns None when the
model cannot be reached, and the agent simply runs without commentary.
"""

import logging
import os
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are assisting a payment operations team.

An autonomous agent has already detected an incident and decided how to respond.
You are NOT deciding what to do - you are explaining the situation to the
on-call engineer who has to trust, question, or override that decision.

Write 2-3 sentences covering:
1. What appears to be happening, in operational terms.
2. Which hypothesis the evidence most supports, and what would distinguish it
   from the alternatives.
3. What you would watch to know whether the response is working.

Be concrete and quantitative. If the evidence is thin, say so rather than
inventing confidence. Do not recommend actions the agent has not proposed."""


def format_incident_brief(context: Dict[str, Any]) -> str:
    """
    Turn an incident context into the prompt an advisor sees.

    Kept pure and separate from any client so the prompt can be inspected and
    tested without a model call.
    """
    lines = [
        f"INCIDENT {context.get('incident_id', 'unknown')}",
        f"Pattern: {context.get('pattern_type')} affecting {context.get('target')}",
        f"Severity: {context.get('severity', 0):.2f}  "
        f"Confidence: {context.get('confidence', 0):.0%}",
        "",
        "EVIDENCE",
    ]
    lines += [f"  - {item}" for item in context.get('evidence', [])] or ["  (none recorded)"]

    hypotheses = context.get('hypotheses') or []
    if hypotheses:
        lines += ["", "HYPOTHESES (agent's priors)"]
        lines += [
            f"  - {h['root_cause']}: {h['probability']:.0%}"
            for h in sorted(hypotheses, key=lambda h: -h.get('probability', 0))[:5]
        ]

    similar = context.get('similar_incidents') or []
    if similar:
        lines += ["", "SIMILAR PAST INCIDENTS"]
        lines += [f"  - {item}" for item in similar[:5]]

    worked = context.get('what_worked_before') or {}
    if worked:
        lines += ["", "MEASURED OUTCOMES ON COMPARABLE INCIDENTS"]
        lines += [
            f"  - {action}: {stats['expected_lift']:+.1%} across "
            f"{stats['samples']} measured incidents"
            for action, stats in worked.items()
        ]
    else:
        lines += ["", "No comparable incident has a measured outcome yet."]

    return "\n".join(lines)


def build_advisor(
    model: str = "gemini-2.5-flash",
    temperature: float = 0.2,
    client_factory: Optional[Callable[[], Any]] = None,
    max_chars: int = 600,
) -> Optional[Callable[[Dict[str, Any]], str]]:
    """
    Build the advisor callable the agent invokes once per incident.

    Args:
        model: Model identifier.
        temperature: Low by default; this is an explanation, not a brainstorm.
        client_factory: Supplies the client. Injected in tests so the prompt
            and the response handling can be exercised without a network call.
        max_chars: Assessments are shown inline on an incident card, so an
            essay is worse than a sentence.

    Returns:
        A callable(context) -> str, or None when no model is reachable. The
        caller treats None as "run without commentary" rather than an error.
    """
    if client_factory is None:
        client_factory = _default_client_factory()
        if client_factory is None:
            return None

    def advise(context: Dict[str, Any]) -> str:
        client = client_factory()
        prompt = format_incident_brief(context)
        text = _generate(client, model, temperature, prompt)
        text = " ".join(text.split())
        return text[:max_chars] if len(text) > max_chars else text

    return advise


def _default_client_factory() -> Optional[Callable[[], Any]]:
    """
    Resolve a Gemini client, or None if one is not available.

    The import is deliberately inside the function: the LLM is an optional
    capability, and a missing package must not stop the agent - or anything
    that imports it - from starting.
    """
    if not (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')):
        logger.info("No GEMINI_API_KEY/GOOGLE_API_KEY set; running without an advisor")
        return None

    try:
        from google import genai  # noqa: F401
    except ImportError:
        logger.info("google-genai not installed; running without an advisor")
        return None

    def factory():
        from google import genai
        return genai.Client()

    return factory


def _generate(client: Any, model: str, temperature: float, prompt: str) -> str:
    """
    Call the model, tolerating differences in SDK surface.

    Advisors are the one place a provider SDK touches the agent, so the
    coupling is kept to this function.
    """
    try:
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=temperature,
        )
    except ImportError:
        config = None

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        **({'config': config} if config is not None else {}),
    )
    return getattr(response, 'text', '') or ''
