"""
TestCaseExecutor: replays a synthesized TestCase step-by-step against a fresh
browser session, independent of the exploration loop that created it. This is
the difference between "an agent that pokes at a website" and "an agent that
produces tests" -- the exploration (Monitor/Analyze/Plan) and the execution
(replaying a TestCase from scratch, with retries and circuit breaking) are
kept as separate concerns so a generated TestCase can be re-run in CI by
itself, with no LLM involved at all.
"""

from __future__ import annotations

import logging
import time

from src.browser.playwright_driver import PlaywrightDriver
from src.models import Anomaly, Severity, TestCase, TestResult
from src.patterns.resilience import CircuitBreaker, CircuitOpenError, retry_with_backoff

logger = logging.getLogger("agentic_testing.agent.executor")


class TestCaseExecutor:
    def __init__(self, circuit_breaker: CircuitBreaker, max_retries: int = 2):
        self._circuit_breaker = circuit_breaker
        self._max_retries = max_retries

    def run(self, test_case: TestCase, driver: PlaywrightDriver) -> TestResult:
        start = time.time()
        anomalies: list[Anomaly] = []

        try:
            driver.navigate(test_case.origin_url)
            for i, step in enumerate(test_case.steps):
                key = f"{test_case.id}:step{i}:{step.action.selector or step.action.value}"
                try:
                    self._circuit_breaker.call(key, self._execute_with_retry, driver, step.action)
                except CircuitOpenError as exc:
                    logger.warning("Step %d of test %s skipped: %s", i, test_case.id, exc)
                    anomalies.append(
                        Anomaly(
                            severity=Severity.MEDIUM,
                            category="circuit_open_skip",
                            description=f"Step skipped after repeated failures: {step.action.description}",
                            page_url=test_case.origin_url,
                        )
                    )
        except Exception as exc:  # noqa: BLE001 -- a failing test case is a *result*, not a crash
            duration = time.time() - start
            logger.error("Test case %s failed: %s", test_case.id, exc)
            return TestResult(
                test_case_id=test_case.id,
                passed=False,
                duration_seconds=duration,
                anomalies=anomalies,
                error=str(exc),
            )

        duration = time.time() - start
        return TestResult(
            test_case_id=test_case.id,
            passed=len(anomalies) == 0,
            duration_seconds=duration,
            anomalies=anomalies,
        )

    def _execute_with_retry(self, driver: PlaywrightDriver, action) -> None:
        @retry_with_backoff(max_retries=self._max_retries, base_delay=0.5)
        def _do() -> None:
            driver.execute(action)

        _do()
