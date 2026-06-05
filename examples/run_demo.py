"""
Quick demo: run the agent against a local HTML fixture with the mock LLM.
No API keys, no network access needed.

Usage:
    python examples/run_demo.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path so imports work when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.analyzer import HeuristicLLMAnalyzer
from src.agent.planner import LLMPlanner
from src.agent.supervisor import Supervisor
from src.browser.playwright_driver import PlaywrightDriver
from src.knowledge.state_memory import JsonKnowledgeBase
from src.llm.client import MockClient
from src.models import AgentConfig
from src.reporting.report_generator import generate_html_report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    fixture = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "index.html"
    if not fixture.exists():
        print(f"Fixture not found at {fixture}. Run from the project root.")
        sys.exit(1)

    start_url = fixture.as_uri()
    config = AgentConfig(
        target_url=start_url,
        max_exploration_steps=10,
        max_depth=4,
        headless=True,
        model_provider="mock",
        output_dir="./run_output",
    )

    llm = MockClient()
    driver = PlaywrightDriver(headless=True, screenshot_dir=f"{config.output_dir}/screenshots")
    analyzer = HeuristicLLMAnalyzer(llm_client=llm, use_llm_judgment=False)
    planner = LLMPlanner(llm_client=llm)
    knowledge = JsonKnowledgeBase(output_dir=config.output_dir)

    supervisor = Supervisor(config=config, driver=driver, analyzer=analyzer, planner=planner, knowledge=knowledge)
    supervisor.run()

    report = generate_html_report(
        target_url=config.target_url,
        anomalies=knowledge.anomalies,
        test_cases=knowledge.test_cases,
        visited_count=knowledge.visited_count(),
        output_path=f"{config.output_dir}/report.html",
    )
    print(f"\nReport: {report}")


if __name__ == "__main__":
    main()
