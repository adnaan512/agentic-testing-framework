# Agentic Testing Framework

An autonomous agent that explores a web application, discovers interactive elements, generates test cases, and reports defects — powered by a MAPE-K self-adaptive architecture with LLM-based decision making.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# 2. Run with mock LLM (no API key needed)
python main.py --url https://example.com --provider mock --max-steps 15

# 3. (Optional) Run with a real LLM for smarter exploration
export ANTHROPIC_API_KEY="sk-..."
python main.py --url https://your-app.com --provider anthropic --max-steps 40
```

## Architecture

The framework implements the **MAPE-K** (Monitor-Analyze-Plan-Execute-Knowledge) reference architecture for self-adaptive systems:

```
┌─────────────────────────────────────────────────────┐
│                    Supervisor                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Monitor  │→ │ Analyzer │→ │ Planner  │          │
│  │(Browser) │  │(Heuristic│  │ (LLM)    │          │
│  │          │  │  + LLM)  │  │          │          │
│  └──────────┘  └──────────┘  └────┬─────┘          │
│       ↑                          ↓                 │
│  ┌──────────┐              ┌──────────┐            │
│  │ Executor │← ← ← ← ← ← │  Action  │            │
│  │(Browser) │              │          │            │
│  └──────────┘              └──────────┘            │
│                 ┌──────────────┐                   │
│                 │ KnowledgeBase│ (visited states,   │
│                 │   (JSON)     │  anomalies, tests) │
│                 └──────────────┘                   │
└─────────────────────────────────────────────────────┘
```

### Key Components

| Component | Interface | Implementation | Purpose |
|-----------|-----------|---------------|---------|
| Monitor | `Monitor` | `PlaywrightDriver` | Observe the live page: DOM hash, interactive elements, errors |
| Analyzer | `Analyzer` | `HeuristicLLMAnalyzer` | Novelty detection + anomaly oracle (deterministic + LLM) |
| Planner | `Planner` | `LLMPlanner` | Choose next action; synthesize test cases from paths |
| Executor | `Executor` | `PlaywrightDriver` | Execute actions against the browser |
| Knowledge | `KnowledgeBase` | `JsonKnowledgeBase` | Visited-state tracking, anomaly log, test case store |

### Resilience Patterns

| Pattern | Purpose |
|---------|---------|
| `retry_with_backoff` | Handles transient failures (flaky selectors, network blips) |
| `CircuitBreaker` | Per-action failure budget — stops hammering a broken element |
| `CheckpointManager` | Crash recovery — resume from last good state |
| `Bulkhead` | Isolates concurrent sessions so one crash doesn't kill the run |

## Project Structure

```
agentic-testing-framework/
├── main.py                          # CLI entry point
├── src/
│   ├── models.py                    # Core dataclasses (PageState, Action, TestCase, etc.)
│   ├── patterns/
│   │   ├── mape_k.py                # Abstract MAPE-K interfaces
│   │   └── resilience.py            # Retry, CircuitBreaker, Checkpoint, Bulkhead
│   ├── browser/
│   │   └── playwright_driver.py     # Playwright wrapper (Monitor + Executor)
│   ├── llm/
│   │   └── client.py                # LLM providers (Anthropic, OpenAI, Mock)
│   ├── knowledge/
│   │   └── state_memory.py          # JSON-backed KnowledgeBase
│   ├── agent/
│   │   ├── analyzer.py              # Heuristic + LLM anomaly detection
│   │   ├── planner.py               # LLM-guided action selection + test synthesis
│   │   ├── executor.py              # TestCase replay with retries
│   │   └── supervisor.py            # MAPE-K loop orchestrator
│   └── reporting/
│       └── report_generator.py      # Self-contained HTML report
├── tests/
│   ├── test_resilience_patterns.py  # Unit tests for resilience primitives
│   └── fixtures/                    # Static HTML pages for local testing
├── examples/
│   └── run_demo.py                  # Quick demo script
└── docs/
    └── ARCHITECTURE.md              # Detailed design rationale
```

## Example Output

Here is what the generated HTML defect report looks like after a run:

![Agentic HTML Report Example](docs/assets/testing_screenshot.PNG)

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## CLI Options

```
python main.py --help
  --url URL              Target URL to explore
  --provider {anthropic,openai,mock}
  --model MODEL          Model name (default: claude-sonnet-4-6)
  --max-steps N          Max exploration steps (default: 30)
  --max-depth N          Max depth before backtracking (default: 6)
  --output-dir DIR       Output directory (default: ./run_output)
  --no-headless          Show the browser window
  --verbose              Debug logging
```

## License

MIT — see [LICENSE](LICENSE).
