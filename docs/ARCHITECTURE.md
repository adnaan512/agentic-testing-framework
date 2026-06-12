# Architecture

## Design Philosophy

This project implements the **MAPE-K** (Monitor-Analyze-Plan-Execute-Knowledge) reference architecture from autonomic computing. The core insight: instead of one monolithic LLM prompt that "does everything", each stage of the testing loop is a distinct, independently testable, independently swappable component.

## Why MAPE-K?

Traditional test automation is scripted: a human writes steps, assertions, and maintenance burden scales linearly with application complexity. An *autonomous* testing agent needs to:

1. **Observe** the application state without a pre-written script
2. **Decide** whether the observed state is interesting (novel) or broken (anomalous)
3. **Choose** what to do next to maximize coverage of untested behavior
4. **Execute** that choice against a live browser
5. **Remember** what it has seen so it converges instead of looping forever

MAPE-K maps directly onto these needs and, critically, keeps the "how do I interact with a browser" concern completely separate from the "how do I decide what to test" concern. This separation is what lets you swap the LLM provider, change the exploration strategy, or replace Playwright with Selenium without touching more than one module.

## Component Details

### Monitor (`PlaywrightDriver.observe()`)

Produces a `PageState` snapshot: URL, title, DOM hash, interactive elements, console errors, network errors, and an optional screenshot. The DOM hash + element count → `fingerprint` is the key signal the KnowledgeBase uses for visited-state tracking.

**Design choice**: We extract at most 25 interactive elements per page. Dumping the entire DOM into an LLM context is the fastest way to burn tokens and degrade decision quality.

### Analyzer (`HeuristicLLMAnalyzer`)

Two responsibilities, deliberately kept separate:

1. **Novelty detection** (`is_novel`): Pure fingerprint lookup, no LLM. This is what stops infinite loops.
2. **Anomaly detection** (`detect_anomalies`): Layered approach:
   - Deterministic checks first (console errors, network failures, missing titles, dead-end pages)
   - LLM judgment second, only for ambiguous observations (confusing UI, layout issues)

Running cheap checks first means the LLM is only invoked when there's genuine ambiguity — cheaper and more reliable.

### Planner (`LLMPlanner`)

- `next_action()`: LLM ranks candidate elements; falls back to first-untried on failure
- `synthesize_test_case()`: Converts an exploration path into a replayable `TestCase`

The action-selection strategy is deliberately simple. The interesting engineering is in failure handling (CircuitBreaker, retry), not in having a maximally clever planning algorithm.

### Executor (`PlaywrightDriver.execute()`)

Maps `Action` objects to Playwright API calls. Wrapped in `retry_with_backoff` so transient failures (slow loads, flaky selectors) don't immediately kill the run.

### Knowledge (`JsonKnowledgeBase`)

Thread-safe, JSON-backed store for:
- Visited state fingerprints (convergence guarantee)
- Anomaly log (the "bug report")  
- Generated test cases (the deliverable)

Atomic writes (write-to-temp + rename) prevent checkpoint corruption on crashes.

### Supervisor

The self-adaptive control layer above the four MAPE stages. Responsible for:
- Running the loop up to `max_exploration_steps`
- Depth-based backtracking (reset to start URL when `max_depth` reached)
- Checkpointing after every step
- Catching per-step exceptions (one bad step ≠ a crashed run)
- Aborting after 3 consecutive failures
- Periodic test case synthesis every 5 steps

## Resilience Patterns

Each pattern addresses a distinct failure mode in LLM-in-the-loop systems:

| Pattern | Failure Mode | Mechanism |
|---------|-------------|-----------|
| `retry_with_backoff` | Transient (network, slow page) | Exponential delay, configurable exception filter |
| `CircuitBreaker` | Persistent (always-broken element) | Per-key failure budget, cooldown, half-open recovery |
| `CheckpointManager` | Process crash | Atomic JSON write, resume from last good state |
| `Bulkhead` | Resource exhaustion | Semaphore-based concurrency limit |

## Data Flow

```
start_url
    │
    ▼
┌──────────┐     PageState     ┌──────────┐    Anomaly[]    ┌──────────────┐
│ Monitor  │ ──────────────→   │ Analyzer │ ──────────────→ │ KnowledgeBase│
│(observe) │                   │(detect)  │                 │ (record)     │
└──────────┘                   └──────────┘                 └──────────────┘
                                    │                             │
                               is_novel?                     has_visited?
                                    │                             │
                                    ▼                             │
                               ┌──────────┐                      │
                               │ Planner  │ ◄────────────────────┘
                               │(next_act)│
                               └────┬─────┘
                                    │ Action
                                    ▼
                               ┌──────────┐
                               │ Executor │
                               │(execute) │
                               └──────────┘
                                    │
                                    ▼
                              next iteration
```
