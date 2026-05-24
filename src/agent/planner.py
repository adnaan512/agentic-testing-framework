"""Planner: the P in MAPE-K. Decides what to do next."""

from __future__ import annotations
import logging
from src.llm.client import LLMClient
from src.models import Action, ActionType, PageState
from src.patterns.mape_k import KnowledgeBase, Planner

logger = logging.getLogger("agentic_testing.agent.planner")


class LLMPlanner(Planner):
    def __init__(self, llm_client): self._llm = llm_client

    def next_action(self, state, knowledge, depth):
        candidates = [el for el in state.interactive_elements if el.is_visible]
        if not candidates: return None
        el = candidates[0]
        return Action(action_type=ActionType.CLICK, selector=el.selector,
                      description=f"click on <{el.tag}>")

    def synthesize_test_case(self, states, actions):
        raise NotImplementedError("Not yet implemented")
