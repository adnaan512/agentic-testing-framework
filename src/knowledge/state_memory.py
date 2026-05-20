"""KnowledgeBase: the K in MAPE-K. Tracks visited states."""

from __future__ import annotations
import logging, threading
from pathlib import Path
from src.models import Anomaly, PageState, TestCase
from src.patterns.mape_k import KnowledgeBase

logger = logging.getLogger("agentic_testing.knowledge")


class JsonKnowledgeBase(KnowledgeBase):
    def __init__(self, output_dir):
        self._lock = threading.Lock()
        self._visited = set()
        self._anomalies = []
        self._test_cases = []
        self._path = Path(output_dir) / "knowledge.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def has_visited(self, state): return state.fingerprint in self._visited
    def record_visit(self, state): self._visited.add(state.fingerprint)
    def record_anomaly(self, a):
        self._anomalies.append(a)
        logger.info("Anomaly [%s/%s]: %s", a.severity, a.category, a.description)
    def record_test_case(self, tc): self._test_cases.append(tc)
    def visited_count(self): return len(self._visited)

    @property
    def anomalies(self): return list(self._anomalies)
    @property
    def test_cases(self): return list(self._test_cases)
