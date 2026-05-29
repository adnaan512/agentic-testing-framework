"""
Supervisor: orchestrates the full Monitor -> Analyze -> Plan -> Execute loop,
writes checkpoints, and is the single place that decides "should we keep going,
back off, or stop". This is the self-adaptive control layer sitting above the
four MAPE stages -- it doesn't know *how* to observe a page or plan an action,
only how to keep the loop itself healthy.

Concretely it is responsible for:
  - Running exploration for up to `max_exploration_steps`, terminating early on
    convergence (Planner returns no action) or depth limit
  - Checkpointing the run after every step so a crash doesn't lose progress
  - Catching and logging any exception from a single loop iteration so one bad
    step doesn't take down the whole run (the agentic-system equivalent of a
    supervisor process restarting a worker rather than crashing the system)
  - Periodically synthesizing a TestCase from the current exploration path
"""

from __future__ import annotations

import logging
import time

from src.agent.analyzer import HeuristicLLMAnalyzer
from src.agent.planner import LLMPlanner
from src.browser.playwright_driver import PlaywrightDriver
from src.knowledge.state_memory import JsonKnowledgeBase
from src.models import Action, AgentConfig, PageState
from src.patterns.resilience import CheckpointManager, CircuitBreaker

logger = logging.getLogger("agentic_testing.agent.supervisor")

# Re-synthesize a test case every N successful steps so a long exploration run
# yields multiple, focused regression tests rather than one giant one.
_TEST_CASE_SYNTHESIS_INTERVAL = 5


class Supervisor:
    def __init__(
        self,
        config: AgentConfig,
        driver: PlaywrightDriver,
        analyzer: HeuristicLLMAnalyzer,
        planner: LLMPlanner,
        knowledge: JsonKnowledgeBase,
    ):
        self._config = config
        self._driver = driver
        self._analyzer = analyzer
        self._planner = planner
        self._knowledge = knowledge
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=config.circuit_breaker_failure_threshold,
            cooldown_seconds=config.circuit_breaker_cooldown_seconds,
        )
        self._checkpoint = CheckpointManager(config.output_dir)
        self._path_states: list[PageState] = []
        self._path_actions: list[Action] = []

    def run(self) -> None:
        logger.info("Starting exploration of %s (max_steps=%d)", self._config.target_url,
                    self._config.max_exploration_steps)
        self._driver.start(self._config.target_url)

        consecutive_failures = 0
        for step in range(1, self._config.max_exploration_steps + 1):
            try:
                continue_loop = self._run_one_step(step)
                consecutive_failures = 0
                if not continue_loop:
                    logger.info("Exploration converged at step %d (no further actions found).", step)
                    break
            except Exception as exc:  # noqa: BLE001 -- supervisor must survive a single bad step
                consecutive_failures += 1
                logger.error("Step %d raised an unhandled error: %s", step, exc)
                if consecutive_failures >= 3:
                    logger.error("3 consecutive step failures -- aborting run for safety.")
                    break
                time.sleep(1.0)  # brief backoff before next attempt, distinct from per-action retry

        self._finalize_test_case()
        self._checkpoint.save(self._run_summary())
        logger.info(
            "Run complete: %d unique states visited, %d anomalies found, %d test cases generated.",
            self._knowledge.visited_count(), len(self._knowledge.anomalies), len(self._knowledge.test_cases),
        )
        self._driver.stop()

    def _run_one_step(self, step: int) -> bool:
        # -- Monitor -- #
        state = self._driver.observe()

        # -- Analyze -- #
        for anomaly in self._analyzer.detect_anomalies(state):
            self._knowledge.record_anomaly(anomaly)

        is_novel = self._analyzer.is_novel(state, self._knowledge)
        self._knowledge.record_visit(state)
        logger.info(
            "[step %d] %s | novel=%s | elements=%d | visited_total=%d",
            step, state.url, is_novel, len(state.interactive_elements), self._knowledge.visited_count(),
        )

        # -- Plan -- #
        depth = len(self._path_actions)
        if depth >= self._config.max_depth:
            logger.info("Max depth %d reached, backtracking to start URL.", self._config.max_depth)
            self._finalize_test_case()
            self._driver.navigate(self._config.target_url)
            self._path_states.clear()
            self._path_actions.clear()
            return True

        action = self._planner.next_action(state, self._knowledge, depth)
        if action is None:
            return False

        # -- Execute (through the circuit breaker, keyed by action signature) -- #
        action_key = f"{action.action_type.value}:{action.selector or action.value}"
        self._circuit_breaker.call(action_key, self._driver.execute, action)

        self._path_states.append(state)
        self._path_actions.append(action)

        if len(self._path_actions) % _TEST_CASE_SYNTHESIS_INTERVAL == 0:
            self._finalize_test_case()

        self._checkpoint.save(self._run_summary())
        return True

    def _finalize_test_case(self) -> None:
        if not self._path_actions:
            return
        test_case = self._planner.synthesize_test_case(self._path_states, self._path_actions)
        self._knowledge.record_test_case(test_case)
        logger.info("Synthesized test case '%s' (%d steps).", test_case.title, len(test_case.steps))

    def _run_summary(self) -> dict:
        return {
            "target_url": self._config.target_url,
            "visited_count": self._knowledge.visited_count(),
            "anomalies_found": len(self._knowledge.anomalies),
            "test_cases_generated": len(self._knowledge.test_cases),
            "circuit_breaker_status": self._circuit_breaker.status(),
        }
