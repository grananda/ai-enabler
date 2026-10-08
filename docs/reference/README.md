# Reference

Source material this marketplace is built to.

| Document | What it is |
|---|---|
| [AI4IT_ai_transformation_SWAT_bible.html](AI4IT_ai_transformation_SWAT_bible.html) | *Working with AI, as a team* — the AI4IT SWAT framework manual for team leads. Open it in a browser; it is a self-contained slide document (← → to navigate, `O` for the contents). |

## How the marketplace follows it

The manual defines six standards that hold for every team. These are the ones the plugins implement directly:

| Standard in the manual | Where it lives here |
|---|---|
| Skills, agents and plugins have a name, an owner and a version (area-first names, `metadata.owner`, `metadata.version`, pruning of unused assets) | The naming and metadata convention of `ai-enabler`, `tools/check_conventions.py`, and the versioning rules in [AGENTS.md](../../AGENTS.md) |
| AI-assisted output passes a defined review gate, with a human accountable for it | The two gates of the delivery pipeline, the independent read-only reviewers, and "never merge, never approve" in the safety rules |
| Tests are the contract: derived from testable acceptance criteria, never from generated code | Acceptance tests written before the code, by a different agent from the one that writes it, which may not edit them |
| AI's place in the delivery flow is written down | The pipeline stages and the diagram in the root README |
| A four-number baseline: cycle time, review waiting time, pull request size, rework | The delivery-flow metrics of `ai-enabler-kpi` |

Where the two differ, on purpose: the manual lists assistant usage and lines of AI-generated code as context, never as targets. The usage report of `ai-enabler-kpi` shows those figures, per developer too, because the team asked for them; read them as the manual says — as a sign that adoption is happening, not as a measure of delivery.
