# Benchmarking a pipeline change

How to measure whether a change to the pipeline makes a run cheaper or faster without making it worse. Every change of the cost and speed roadmap is measured this way, before and after, on the same tickets.

**Rule.** A change is accepted when it lowers cost or time beyond the variation between two runs of the same version, and no quality indicator gets worse.

## Fixed setup

Keep everything constant except the change under test.

| Element | Value |
|---|---|
| Project | The room reservation demo (`AI4IT/roomreservation`), on the `main` commit the ticket was written against |
| Tickets | **M**: AI4IT-35 (four-hour limit on single reservations: backend rule, form validation, contracts, tests). S and L tickets are to be added |
| Models | The roles the client will use, mapped as below |
| Version under test | The released marketplace (`claude plugin list`), or a branch with `--plugin-dir` |
| Metrics | `.enabler/metrics/` in the project, with a price table for the models in use (see "Behind an LLM gateway" in [the metrics plugin README](../plugins/ai-enabler-metrics/README.md#behind-an-llm-gateway)) |

Model mapping while the benchmark runs through Azure OpenAI instead of Claude:

| Role | Claude (client) | Benchmark | Price ratio |
|---|---|---|---|
| Main session and Opus agents (refiner, planner, reviewers) | Opus | `gpt-6.1-sol` | 1/2 |
| Sonnet agents (analyst, scouts, implementer, test engineer) | Sonnet | `gpt-6.1-terra` | 1/2 (cache reads 1/4) |
| Background tasks (Haiku) | Haiku | `gpt-5.6-terra` | — |

Reasoning stays on (no `MAX_THINKING_TOKENS=0`). The two tiers and their price ratio are kept, so before and after comparisons are valid; absolute figures do not transfer to Claude (different tokenizer, verbosity and caching rules).

## Running one case

1. Start from a clean `main`. Move the ticket's previous run directory (`.enabler/runs/<KEY>`) and the event files (`.enabler/metrics/events/`) to an archive folder outside both, and keep the previous run's code on a branch of its own: the new run creates the same feature branch.
2. Start Claude Code in the project and run `/ai-enabler:delivery-run <KEY>`.
3. Act the same way every time:
   - plan gate: `approve`, unless the plan is wrong; note any `adjust` and why;
   - ship gate: `fix: <one sentence>` for each open finding, then `hold`;
   - `/exit` at the end, so the session's last events are written.
4. Do not ask for the usage report inside the session: it would be measured with the run.

## Producing the inputs

Run the report from outside Claude Code, once at the provider's prices and, for an estimate of what the client would pay, once with Claude prices for the same tokens:

```bash
python plugins/ai-enabler-metrics/scripts/usage_report.py --metrics-dir <project>/.enabler/metrics --out-dir bench/run-1 --quiet
python plugins/ai-enabler-metrics/scripts/usage_report.py --metrics-dir <project>/.enabler/metrics --out-dir bench/run-1-claude --quiet --pricing claude-equivalent.json
```

`claude-equivalent.json` prices each benchmark model as the Claude model of its role (list prices per million tokens; update them with the bundled `pricing.json`):

```json
{
  "providers": {
    "gateway": {
      "models": {
        "gpt-6.1-sol":   { "input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write_5m": 5.0,  "cache_write_1h": 8.0 },
        "gpt-6.1-terra": { "input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write_5m": 2.5,  "cache_write_1h": 4.0 },
        "gpt-5.6-terra": { "input": 1.0, "output": 5.0,  "cache_read": 0.10, "cache_write_5m": 1.25, "cache_write_1h": 2.0 }
      }
    }
  }
}
```

## Comparing

```bash
python tools/bench.py --case "1.8.1 run 1" bench/run-1/usage.json <archive>/run-1/run \
                      --case "1.8.1 run 2" bench/run-2/usage.json <project>/.enabler/runs/AI4IT-35
```

The table has one column per case and, from two cases on, the change of the last against the first: cost in total and per agent, tokens, AI and human time, wall clock, interactions, tool calls and subagent runs; and, from the run directory, acceptance criteria met, rounds at each gate and the human interventions.

Read the rest of the quality side from the run directory and put it next to the table: tests passed and failed, coverage of the changed code, mutation score (`test-report.md`), and review findings by severity, open and fixed (`review.md`).

## Reading and recording the result

- Two runs of the same version give the variation to expect from the models themselves. A difference smaller than that is noise.
- A change that saves cost but adds a finding, lowers coverage or the mutation score, or needs more rounds at a gate is not accepted as it is.
- Post the table, the quality indicators and the conclusion as a comment on the change's issue.
