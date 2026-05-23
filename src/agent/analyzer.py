"""
Analyzer: the 'A' in MAPE-K.

Two distinct responsibilities, kept separate on purpose:

1. Novelty detection (`is_novel`) -- cheap, deterministic, no LLM call. Just a
   fingerprint lookup against the KnowledgeBase. This is what stops the agent
   from re-exploring the same state forever.

2. Anomaly detection (`detect_anomalies`) -- this is software testing's classic
   "oracle problem": given an observed state, decide whether it represents a
   defect. We layer cheap deterministic checks (console errors, failed network
   requests, broken navigation) with an LLM pass for things that require
   judgment (confusing UI copy, a form that "succeeds" but shows no
   confirmation, a layout that looks broken). Running deterministic checks
   first means the LLM is only invoked when there's something ambiguous left
   to reason about -- cheaper and more reliable than asking an LLM to notice
   a literal JS console error.
"""

from __future__ import annotations

import logging

from src.llm.client import LLMClient
from src.models import Anomaly, PageState, Severity
from src.patterns.mape_k import Analyzer, KnowledgeBase

logger = logging.getLogger("agentic_testing.agent.analyzer")

_ANOMALY_SYSTEM_PROMPT = """\
You are a QA oracle for a web application testing agent (task: detect_anomalies).
You will be given a page title, URL, and a short list of visible interactive
elements. Decide if there is anything that looks like a usability or
functional defect (e.g., a button with no label, a broken-looking layout
implied by the element list, contradictory text). Only flag things you can
reasonably infer from the given data; do not invent issues.
Respond as JSON: {"anomalies": [{"severity": "low|medium|high|critical",
"category": "string", "description": "string"}]}. If nothing stands out,
return {"anomalies": []}.
"""


class HeuristicLLMAnalyzer(Analyzer):
    def __init__(self, llm_client: LLMClient, use_llm_judgment: bool = True):
        self._llm = llm_client
        self._use_llm_judgment = use_llm_judgment

    def is_novel(self, state: PageState, knowledge: KnowledgeBase) -> bool:
        return not knowledge.has_visited(state)

    def detect_anomalies(self, state: PageState) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        anomalies.extend(self._deterministic_checks(state))
        if self._use_llm_judgment:
            anomalies.extend(self._llm_judgment_check(state))
        return anomalies

    # -- deterministic, no LLM needed ---------------------------------------- #

    def _deterministic_checks(self, state: PageState) -> list[Anomaly]:
        found: list[Anomaly] = []

        for err in state.console_errors:
            found.append(
                Anomaly(
                    severity=Severity.HIGH,
                    category="console_error",
                    description=f"JavaScript console error on '{state.url}': {err}",
                    page_url=state.url,
                    evidence={"raw_error": err},
                    screenshot_path=state.screenshot_path,
                )
            )

        for err in state.network_errors:
            found.append(
                Anomaly(
                    severity=Severity.MEDIUM,
                    category="network_error",
                    description=f"Failed network request on '{state.url}': {err}",
                    page_url=state.url,
                    evidence={"raw_error": err},
                    screenshot_path=state.screenshot_path,
                )
            )

        if not state.title or state.title.strip().lower() in {"", "untitled", "error"}:
            found.append(
                Anomaly(
                    severity=Severity.LOW,
                    category="missing_page_title",
                    description=f"Page at '{state.url}' has a missing or generic title: '{state.title}'",
                    page_url=state.url,
                    screenshot_path=state.screenshot_path,
                )
            )

        if not state.interactive_elements and state.url:
            found.append(
                Anomaly(
                    severity=Severity.MEDIUM,
                    category="dead_end_page",
                    description=f"Page at '{state.url}' exposes no interactive elements -- possible dead end or render failure.",
                    page_url=state.url,
                    screenshot_path=state.screenshot_path,
                )
            )

        return found

    # -- LLM judgment for things deterministic checks can't catch -------------- #

    def _llm_judgment_check(self, state: PageState) -> list[Anomaly]:
        element_summary = "\n".join(
            f"- <{el.tag}> role={el.role} text={el.text!r}" for el in state.interactive_elements[:15]
        ) or "(no interactive elements detected)"
        user_prompt = (
            f"task: detect_anomalies\n"
            f"Page title: {state.title}\nURL: {state.url}\n"
            f"Interactive elements:\n{element_summary}"
        )
        try:
            response = self._llm.complete_json(_ANOMALY_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:  # noqa: BLE001 -- analyzer must never crash the loop
            logger.warning("LLM anomaly judgment failed, skipping: %s", exc)
            return []

        results: list[Anomaly] = []
        for raw in response.get("anomalies", []):
            try:
                results.append(
                    Anomaly(
                        severity=Severity(raw.get("severity", "low")),
                        category=raw.get("category", "llm_flagged"),
                        description=raw.get("description", "LLM flagged an issue without detail."),
                        page_url=state.url,
                        screenshot_path=state.screenshot_path,
                    )
                )
            except (ValueError, KeyError) as exc:
                logger.debug("Skipping malformed anomaly from LLM: %s (%s)", raw, exc)
        return results
