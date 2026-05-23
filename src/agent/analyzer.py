"""Analyzer: the A in MAPE-K. Novelty + anomaly detection."""

from __future__ import annotations
import logging
from src.llm.client import LLMClient
from src.models import Anomaly, PageState, Severity
from src.patterns.mape_k import Analyzer, KnowledgeBase

logger = logging.getLogger("agentic_testing.agent.analyzer")


class HeuristicLLMAnalyzer(Analyzer):
    def __init__(self, llm_client, use_llm_judgment=True):
        self._llm = llm_client
        self._use_llm_judgment = use_llm_judgment

    def is_novel(self, state, knowledge): return not knowledge.has_visited(state)

    def detect_anomalies(self, state):
        return self._deterministic_checks(state)

    def _deterministic_checks(self, state):
        found = []
        for err in state.console_errors:
            found.append(Anomaly(severity=Severity.HIGH, category="console_error",
                description=f"JS error on '{state.url}': {err}", page_url=state.url,
                evidence={"raw_error": err}, screenshot_path=state.screenshot_path))
        for err in state.network_errors:
            found.append(Anomaly(severity=Severity.MEDIUM, category="network_error",
                description=f"Network fail on '{state.url}': {err}", page_url=state.url,
                evidence={"raw_error": err}, screenshot_path=state.screenshot_path))
        return found

    # --- extra heuristics added ---
    def _title_and_dead_end_checks(self, state):
        found = []
        if not state.title or state.title.strip().lower() in {"", "untitled", "error"}:
            found.append(Anomaly(severity=Severity.LOW, category="missing_page_title",
                description=f"Missing title at '{state.url}'", page_url=state.url))
        if not state.interactive_elements and state.url:
            found.append(Anomaly(severity=Severity.MEDIUM, category="dead_end_page",
                description=f"No interactive elements at '{state.url}'", page_url=state.url))
        return found
