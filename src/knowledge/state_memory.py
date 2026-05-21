"""
Concrete KnowledgeBase: the 'K' in MAPE-K. Tracks visited page-state fingerprints
(so the agent converges instead of looping forever), the running list of anomalies
found, and every synthesized test case. Backed by a simple JSON file so a run's
findings survive process restarts and can be diffed across runs over time --
useful for tracking whether the same defects keep reappearing across builds
(directly relevant to regression analysis, not just one-off bug hunting).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path

from src.models import Anomaly, PageState, TestCase
from src.patterns.mape_k import KnowledgeBase

logger = logging.getLogger("agentic_testing.knowledge")


class JsonKnowledgeBase(KnowledgeBase):
    def __init__(self, output_dir: str):
        self._lock = threading.Lock()
        self._visited: set[str] = set()
        self._anomalies: list[Anomaly] = []
        self._test_cases: list[TestCase] = []
        self._path = Path(output_dir) / "knowledge.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def has_visited(self, state: PageState) -> bool:
        with self._lock:
            return state.fingerprint in self._visited

    def record_visit(self, state: PageState) -> None:
        with self._lock:
            self._visited.add(state.fingerprint)
        self._flush()

    def record_anomaly(self, anomaly: Anomaly) -> None:
        with self._lock:
            self._anomalies.append(anomaly)
        logger.info("Anomaly recorded [%s/%s]: %s", anomaly.severity, anomaly.category, anomaly.description)
        self._flush()

    def record_test_case(self, test_case: TestCase) -> None:
        with self._lock:
            self._test_cases.append(test_case)
        self._flush()

    def visited_count(self) -> int:
        with self._lock:
            return len(self._visited)

    @property
    def anomalies(self) -> list[Anomaly]:
        with self._lock:
            return list(self._anomalies)

    @property
    def test_cases(self) -> list[TestCase]:
        with self._lock:
            return list(self._test_cases)

    def _flush(self) -> None:
        with self._lock:
            payload = {
                "visited_fingerprints": list(self._visited),
                "anomalies": [self._anomaly_dict(a) for a in self._anomalies],
                "test_cases": [self._test_case_dict(t) for t in self._test_cases],
            }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        tmp.replace(self._path)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._visited = set(data.get("visited_fingerprints", []))
            logger.info("Resumed knowledge base: %d states already visited.", len(self._visited))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load existing knowledge base, starting fresh: %s", exc)

    @staticmethod
    def _anomaly_dict(a: Anomaly) -> dict:
        d = asdict(a)
        d["severity"] = a.severity.value
        return d

    @staticmethod
    def _test_case_dict(t: TestCase) -> dict:
        d = asdict(t)
        for step in d["steps"]:
            action_type = step["action"]["action_type"]
            step["action"]["action_type"] = (
                action_type.value if hasattr(action_type, "value") else action_type
            )
        return d
