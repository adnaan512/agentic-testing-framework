"""Supervisor: orchestrates the MAPE-K exploration loop."""

from __future__ import annotations
import logging
from src.agent.analyzer import HeuristicLLMAnalyzer
from src.agent.planner import LLMPlanner
from src.browser.playwright_driver import PlaywrightDriver
from src.knowledge.state_memory import JsonKnowledgeBase
from src.models import Action, AgentConfig, PageState
from src.patterns.resilience import CircuitBreaker

logger = logging.getLogger("agentic_testing.agent.supervisor")


class Supervisor:
    def __init__(self, config, driver, analyzer, planner, knowledge):
        self._config = config
        self._driver = driver
        self._analyzer = analyzer
        self._planner = planner
        self._knowledge = knowledge
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=config.circuit_breaker_failure_threshold,
            cooldown_seconds=config.circuit_breaker_cooldown_seconds)
        self._path_states = []
        self._path_actions = []

    def run(self):
        self._driver.start(self._config.target_url)
        for step in range(1, self._config.max_exploration_steps + 1):
            try:
                if not self._run_one_step(step): break
            except Exception as exc:
                logger.error("Step %d error: %s", step, exc)
        self._finalize_test_case()
        self._driver.stop()

    def _finalize_test_case(self):
        if not self._path_actions: return
        tc = self._planner.synthesize_test_case(self._path_states, self._path_actions)
        self._knowledge.record_test_case(tc)


    def _run_one_step(self, step):
        state = self._driver.observe()
        for a in self._analyzer.detect_anomalies(state):
            self._knowledge.record_anomaly(a)
        self._knowledge.record_visit(state)
        action = self._planner.next_action(state, self._knowledge, len(self._path_actions))
        if action is None: return False
        key = f"{action.action_type.value}:{action.selector or action.value}"
        self._circuit_breaker.call(key, self._driver.execute, action)
        self._path_states.append(state)
        self._path_actions.append(action)
        return True
