"""
Planner: the 'P' in MAPE-K.

Decides what the agent should do next, and separately, turns a completed
exploration path into a TestCase that a human team can keep, re-run in CI, and
read without needing to understand the agent that generated it.

The action-selection strategy here is deliberately simple (LLM ranks untried
elements; falls back to first-untried if the LLM call fails or returns
nothing usable) -- the interesting engineering is in *how failure is handled*
(see fallback below and the CircuitBreaker around it in the Supervisor), not in
having a maximally clever planning algorithm. A more sophisticated planner
(e.g. UCB-style exploration weighting, or a learned value function over
PageState) can be dropped in behind this same Planner interface without
touching anything else.
"""

from __future__ import annotations

import logging
import uuid

from src.llm.client import LLMClient
from src.models import Action, ActionType, PageState, TestCase, TestStep
from src.patterns.mape_k import KnowledgeBase, Planner

logger = logging.getLogger("agentic_testing.agent.planner")

_PLAN_SYSTEM_PROMPT = """\
You are the planning module of an autonomous web-testing agent (task: plan_next_action).
Given the current page and a list of candidate interactive elements (each with
an index), choose the single most promising element to interact with next in
order to explore new application behavior (prefer elements that look like they
lead to new functionality: forms, nav links, tabs -- over elements likely to
repeat a state, like decorative icons).
Respond as JSON: {"chosen_index": <int>, "action_type": "click|fill|hover",
"value": "<string or null, only for fill>", "reasoning": "<short string>"}.
If none of the candidates look worth exploring, respond with {"chosen_index": -1}.
"""

_SYNTHESIZE_SYSTEM_PROMPT = """\
You are the test-authoring module of an autonomous web-testing agent
(task: synthesize_test_case). Given a sequence of pages visited and actions
taken, write a short, human-readable test case title and 1-3 relevant tags
(e.g. "navigation", "form", "regression", "smoke").
Respond as JSON: {"title": "<string>", "tags": ["<string>", ...]}.
"""


class LLMPlanner(Planner):
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    def next_action(self, state: PageState, knowledge: KnowledgeBase, depth: int) -> Action | None:
        candidates = [el for el in state.interactive_elements if el.is_visible]
        if not candidates:
            return None

        candidate_summary = "\n".join(
            f"[{i}] <{el.tag}> role={el.role} text={el.text!r} input_type={el.input_type}"
            for i, el in enumerate(candidates)
        )
        user_prompt = (
            f"task: plan_next_action\n"
            f"Current depth: {depth}\nPage title: {state.title}\nURL: {state.url}\n"
            f"Candidates:\n{candidate_summary}"
        )

        chosen_index = -1
        action_type = ActionType.CLICK
        value = None
        try:
            response = self._llm.complete_json(_PLAN_SYSTEM_PROMPT, user_prompt)
            chosen_index = int(response.get("chosen_index", -1))
            action_type = ActionType(response.get("action_type", "click"))
            value = response.get("value")
        except Exception as exc:  # noqa: BLE001 -- planner falls back rather than crash the loop
            logger.warning("Planner LLM call failed (%s); falling back to first candidate.", exc)
            chosen_index = 0

        if chosen_index < 0 or chosen_index >= len(candidates):
            if chosen_index == -1 and not value:
                # LLM explicitly found nothing worth exploring here.
                logger.debug("Planner found no promising candidates at depth %d.", depth)
                return None
            chosen_index = 0  # defensive fallback for an out-of-range index

        element = candidates[chosen_index]
        if action_type == ActionType.FILL and not value:
            value = "test_value_123"  # placeholder input for exploratory form-filling

        return Action(
            action_type=action_type,
            selector=element.selector,
            value=value,
            description=f"{action_type.value} on <{element.tag}> ({element.text or element.role or 'no label'})",
        )

    def synthesize_test_case(self, states: list[PageState], actions: list[Action]) -> TestCase:
        path_summary = "\n".join(
            f"{i+1}. on {s.url}: {a.description}" for i, (s, a) in enumerate(zip(states, actions))
        ) or "(no actions recorded)"
        title, tags = "Exploratory regression path", ["smoke"]
        try:
            response = self._llm.complete_json(
                _SYNTHESIZE_SYSTEM_PROMPT, f"task: synthesize_test_case\nPath:\n{path_summary}"
            )
            title = response.get("title", title)
            tags = response.get("tags", tags) or tags
        except Exception as exc:  # noqa: BLE001
            logger.warning("Test case synthesis LLM call failed (%s); using generic title.", exc)

        steps = [TestStep(action=a) for a in actions]
        origin = states[0].url if states else ""
        return TestCase(
            id=str(uuid.uuid4())[:8],
            title=title,
            origin_url=origin,
            steps=steps,
            tags=tags,
        )
