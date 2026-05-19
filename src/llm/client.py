"""
LLM client used by the Analyzer and Planner. Kept deliberately provider-agnostic
and minimal -- this project is about the agent *architecture*, not about being
tied to one vendor's SDK.

Includes a `mock` provider that returns deterministic, rule-based responses with
no network calls. This matters for a project meant to be cloned and run by a
reviewer who may not have an API key on hand: `python main.py --provider mock`
demonstrates the full MAPE-K loop, resilience patterns, and report generation
end-to-end with zero external dependencies beyond Playwright.
"""

from __future__ import annotations

import json
import logging
import os
import random
from typing import Any, Optional, Protocol

from src.patterns.resilience import retry_with_backoff

logger = logging.getLogger("agentic_testing.llm")


class LLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


def _extract_json(text: str) -> dict[str, Any]:
    """LLMs occasionally wrap JSON in prose or code fences despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
    return json.loads(text[start : end + 1])


class AnthropicClient:
    def __init__(self, model: str = "claude-sonnet-4-6"):
        import anthropic  # local import: optional dependency unless this provider is used

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system_prompt + "\nRespond with ONLY a valid JSON object, no prose, no markdown fences.",
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return _extract_json(text)


class OpenAIClient:
    def __init__(self, model: str = "gpt-4o-mini"):
        from openai import OpenAI  # local import: optional dependency unless this provider is used

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        self._client = OpenAI(api_key=api_key)
        self._model = model

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return json.loads(response.choices[0].message.content)


class MockClient:
    """
    Deterministic, network-free stand-in for an LLM. Picks the first not-yet-tried
    interactive element it sees and always returns a benign anomaly assessment.
    Exists purely so the framework is runnable/demoable without API credentials --
    swap in AnthropicClient or OpenAIClient for real exploration.
    """

    def __init__(self, seed: int = 7):
        self._rng = random.Random(seed)

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if "plan_next_action" in user_prompt or "plan_next_action" in system_prompt:
            # Always pick the first candidate -- the planner has already verified
            # at least one exists before calling the LLM. This is what lets the
            # framework be demoed end-to-end with zero API keys.
            return {
                "chosen_index": 0,
                "action_type": "click",
                "value": None,
                "reasoning": "[mock] selecting first untried interactive element",
            }
        if "detect_anomalies" in system_prompt or "detect_anomalies" in user_prompt:
            return {"anomalies": []}
        if "synthesize_test_case" in system_prompt or "synthesize_test_case" in user_prompt:
            return {"title": "[mock] Exploratory regression path", "tags": ["smoke"]}
        return {}


def build_llm_client(provider: str, model: str) -> LLMClient:
    provider = provider.lower()
    if provider == "anthropic":
        return AnthropicClient(model=model)
    if provider == "openai":
        return OpenAIClient(model=model)
    if provider == "mock":
        return MockClient()
    raise ValueError(f"Unknown provider '{provider}'. Use 'anthropic', 'openai', or 'mock'.")
