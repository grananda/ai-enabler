---
name: metrics-stale-assets
description: Lists every installed skill and agent with its owner, version, last use and number of uses, and marks the ones gone stale — unused for 90 days — or without an owner, for the quarterly pruning of shared AI assets. Reads the events recorded by the ai-enabler-metrics usage hooks; computes everything with a bundled script. Use when the user says "which skills are unused", "stale skills", "prune the skills", "skill usage report", "which agents does nobody use", "quarterly pruning", or "skills without an owner".
argument-hint: "[--stale-days 90] [--assets-dir <dir> ...] [--metrics-dir <dir> ...]"
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.0"
---

# ai-enabler-metrics:metrics-stale-assets — skills and agents nobody uses

Shared assets rot when nobody prunes them: the author moves on, nobody dares delete, nobody trusts the folder. This skill gives the list for the quarterly review.

## Flow

1. **Run the script**, passing through the flags in `$ARGUMENTS`:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assets.py" [flags]
   ```

   It looks at the project's `.claude/skills` and `.claude/agents`, and at the plugins of this marketplace; `--assets-dir` adds another plugin or folder that holds `skills/` and `agents/`. It writes `assets.html` and `assets.json` to `.enabler/metrics/reports/<date>/` and prints the path.
2. **If it says no metrics directory was found**, usage capture was never switched on, so there is nothing to judge use by: point to `/ai-enabler-metrics:metrics-usage-init`.
3. **Read `assets.json`** and tell the person:
   - how many days of sessions the recording covers. Below 90, nothing can be called stale yet and the report says "not seen yet"; say so plainly instead of listing those as unused;
   - the **stale** assets — last used 90 days ago or more, or never in 90 days of recording — each with its owner;
   - the assets **without an owner**;
   - the path of `assets.html`.

## Which folder

Paths in this skill say `.enabler/metrics/`. A project set up before 1.0.0 may still keep its data in `.enabler/kpi/`; the scripts use whichever exists and print the paths they write. In such a project read and write under `.enabler/kpi/` — never create `.enabler/metrics/` beside it, which would split the data.

## Rules

- This skill reports. It never archives, moves or deletes an asset; that is the owner's decision at the review.
- "Unused" means unused in the sessions that were recorded: projects with capture on, on this machine unless event files are shared. Say that limit whenever you name an asset as stale, and recommend checking with its owner.
- The number of skills, and how often each is used, are context, never targets. Do not rank owners or teams by them.
