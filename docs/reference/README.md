# Reference

Source material this marketplace is built to.

| Document | What it is |
|---|---|
| [AI4IT_ai_transformation_SWAT_bible.html](AI4IT_ai_transformation_SWAT_bible.html) | *Working with AI, as a team* — the AI4IT SWAT framework manual for team leads. Open it in a browser; it is a self-contained slide document (← → to navigate, `O` for the contents). |

## How the marketplace follows it

The manual defines six standards that hold for every team. These are the ones the plugins implement directly:

| Standard in the manual | Where it lives here |
|---|---|
| Skills, agents and plugins have a name, an owner and a version (area-first names, `metadata.owner`, `metadata.version`, pruning of unused assets) | The naming and metadata convention of both plugins, `tools/check_conventions.py`, and the versioning rules in [AGENTS.md](../../AGENTS.md) |
| AI-assisted output passes a defined review gate, with a human accountable for it | The two gates of the delivery pipeline, the independent read-only reviewers, and "never merge, never approve" in the safety rules |
| Tests are the contract: derived from testable acceptance criteria, never from generated code | Acceptance tests written before the code, by a different agent from the one that writes it, which may not edit them |
| AI's place in the delivery flow is written down | The pipeline stages and the diagram in the root README |
| A four-number baseline: cycle time, review waiting time, pull request size, rework | The delivery-flow metrics of `ai-enabler-metrics` |
| Usage figures are context, never targets ("lines of AI-generated code", "assistant usage", "number of skills") | `ai-enabler-metrics` calls them usage metrics and refuses a target on any of them. Only the four delivery metrics can be given one, and only then is a metric called a KPI |
| Prune quarterly: unused for 90 days means archived; no owner means deleted at the next review | `/ai-enabler-metrics:metrics-stale-assets` lists every skill and agent with its owner, last use and whether it is stale |

One thing goes beyond the manual: the usage report breaks its figures down per developer, because the team asked for it. They stay what the manual says they are — a sign that adoption is happening, not a measure of delivery — and the report says so on the page.
