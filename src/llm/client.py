"""LLM client — provider-agnostic Protocol and JSON extraction."""

from __future__ import annotations
import json, logging
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
