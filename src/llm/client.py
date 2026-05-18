"""LLM client — provider-agnostic Protocol and JSON extraction."""

from __future__ import annotations
import json, logging, random
from typing import Any, Protocol

logger = logging.getLogger("agentic_testing.llm")


class LLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"): text = text.strip("`"); text = text[4:] if text.startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1: raise ValueError("No JSON found")
    return json.loads(text[start:end+1])


class MockClient:
    """Deterministic stand-in for an LLM — no API key needed."""

    def __init__(self, seed=7):
        self._rng = random.Random(seed)

    def complete_json(self, system_prompt, user_prompt):
        if "plan_next_action" in user_prompt or "plan_next_action" in system_prompt:
            return {"chosen_index": 0, "action_type": "click", "value": None,
                    "reasoning": "[mock] selecting first untried element"}
        if "detect_anomalies" in system_prompt:
            return {"anomalies": []}
        if "synthesize_test_case" in system_prompt:
            return {"title": "[mock] Exploratory regression path", "tags": ["smoke"]}
        return {}
