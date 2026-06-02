#!/usr/bin/env python3
"""
CLI entry point for the agentic testing framework.

Example:
    python main.py --url https://example.com --provider mock --max-steps 15
    python main.py --url https://example.com --provider anthropic --max-steps 40 --no-headless
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.agent.analyzer import HeuristicLLMAnalyzer
from src.agent.planner import LLMPlanner
from src.agent.supervisor import Supervisor
from src.browser.playwright_driver import PlaywrightDriver
from src.knowledge.state_memory import JsonKnowledgeBase
from src.llm.client import build_llm_client
from src.models import AgentConfig
from src.reporting.report_generator import generate_html_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous agentic web testing framework.")
    parser.add_argument("--url", required=True, help="Target URL to explore and test.")
    parser.add_argument("--provider", default="mock", choices=["anthropic", "openai", "mock"],
                         help="LLM provider. Use 'mock' to run with no API key.")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Model name for the chosen provider.")
    parser.add_argument("--max-steps", type=int, default=30, help="Max exploration steps.")
    parser.add_argument("--max-depth", type=int, default=6, help="Max actions per exploration path before backtracking.")
    parser.add_argument("--output-dir", default="./run_output", help="Directory for reports, screenshots, checkpoints.")
    parser.add_argument("--no-headless", action="store_true", help="Run the browser with a visible window.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = AgentConfig(
        target_url=args.url,
        max_exploration_steps=args.max_steps,
        max_depth=args.max_depth,
        headless=not args.no_headless,
        model_provider=args.provider,
        model_name=args.model,
        output_dir=args.output_dir,
    )

    llm_client = build_llm_client(config.model_provider, config.model_name)
    driver = PlaywrightDriver(
        headless=config.headless,
        screenshot_dir=f"{config.output_dir}/screenshots",
        timeout_seconds=config.request_timeout_seconds,
    )
    analyzer = HeuristicLLMAnalyzer(llm_client=llm_client, use_llm_judgment=config.model_provider != "mock")
    planner = LLMPlanner(llm_client=llm_client)
    knowledge = JsonKnowledgeBase(output_dir=config.output_dir)

    supervisor = Supervisor(config=config, driver=driver, analyzer=analyzer, planner=planner, knowledge=knowledge)
    supervisor.run()

    report_path = generate_html_report(
        target_url=config.target_url,
        anomalies=knowledge.anomalies,
        test_cases=knowledge.test_cases,
        visited_count=knowledge.visited_count(),
        output_path=f"{config.output_dir}/report.html",
    )
    print(f"\nReport written to: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
