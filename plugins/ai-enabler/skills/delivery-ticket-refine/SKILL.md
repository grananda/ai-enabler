---
name: delivery-ticket-refine
description: Refines an existing ticket into a more robust definition, written as a local Markdown file. Reads a Jira issue (read-only, through the Jira MCP server) or a requirements file, finds what the definition leaves unsaid - unhappy paths, limits, permissions, data, scope - and closes each gap as a marked addition, an assumption or a question, the way a product owner and a business analyst would. Never writes to Jira. Use when the user says "refine PROJ-123", "improve this ticket", "this story is too thin", "what is missing in this ticket", "make this ticket ready", or wants a better definition before planning.
argument-hint: <JIRA-KEY | ticket.md | ticket.txt> [--out <path>]
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.0"
---

# ai-enabler:delivery-ticket-refine — a thin ticket into a robust one

Takes a ticket as its author wrote it and produces an improved version as a Markdown file on this machine. Nothing is changed in Jira, in the codebase or in git. The file is what `/ai-enabler:delivery-plan` and `/ai-enabler:delivery-run` accept as a source.

The same refinement runs inside the delivery pipeline, right after intake. Use this skill when you want to see and edit the improved ticket first, or work on the definition without delivering anything yet.

Read `${CLAUDE_PLUGIN_ROOT}/references/ticket-readiness.md` first: it defines when a ticket is ready, how gaps are closed, and the format of the file.

## Flow

1. **Preflight.** Check, in this order, and stop at the first thing that fails with one clear sentence on how to fix it:
   - `$ARGUMENTS` names a source: a Jira key (`[A-Z][A-Z0-9]+-\d+`) or the path of a `.md`/`.txt` file. With neither, ask for one. A few sentences of free text are not a ticket to refine: point to `/ai-enabler:delivery-ticket-create`.
   - A file source exists and is not empty. If it already starts with the frontmatter line `ai-enabler: refined-ticket`, say that it was refined before and go on: the person may have edited it or answered its questions.
   - For a Jira key, a connected MCP server exposes a tool that reads an issue by key (`jira.server` in `.enabler/config.json` picks one when several are connected; otherwise ask once). With none, follow "When there is no Jira MCP server" in `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md`. Reading Jira is allowed in local-only mode.
   - Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo_profile.py" check`. Take `root` from it: the output goes under `<root>/.enabler/tickets/`, a folder the script keeps out of git. If the status is `missing`, say in one line that refinement can use what the pipeline knows about the repository once a plan or a delivery has run here; do not build the profile now.
   - The output path: `--out` if given, otherwise `<root>/.enabler/tickets/<KEY>-refined.md` (for a file, its name without extension in place of the key). Never overwrite a file that is there: add `-2`, `-3`.
2. **Refine.** Launch `ai-enabler:delivery-ticket-refiner` with `mode: document`, the source, the Jira MCP server when there is one, and the absolute output path.
3. **Present.** From its report and the file, show compactly:

   ```
   REFINED — <KEY or file>: <title>
   As received : criteria <sufficient|scarce|missing> · <ready|ready with assumptions|blocked>
   Now         : criteria <...> · <...>
   Added       : <n> requirements · <n> criteria (<n> sharpened) · <n> assumptions
   What        : <each addition in one line, with its reason>
   Assumptions : <each in one line, or "none">
   Questions   : <each in one line, blocking ones first, or "none">
   File        : <path>
   ```

4. **Questions, once.** If the refiner left questions, ask them now with their options and the suggested one, blocking questions first, at most four at a time. With the answers, relaunch the refiner with the file it wrote as the source, the answers, and the same output path, so the answers are folded into the same file; present the result again. A person who prefers to answer later, or to ask someone else, keeps the file as it is: the questions stay in it.
5. **Close.** Say where the file is, that it is a local file they can edit freely (remove an addition, change an assumption, answer a question in place), and name the next step: `/ai-enabler:delivery-plan <path>` to see the plan, or `/ai-enabler:delivery-run <path>` to deliver it.

## Rules

- **Nothing is written to Jira, ever.** Not the refined description, not a comment, not the questions. If the person wants the result in Jira, the file is theirs to paste.
- **Nothing is written outside `.enabler/`** unless `--out` says so. No code, no branch, no commit.
- Do not refine in your own context: the refiner subagent does it, you present it.
- Everything the source did not say is marked as added. If the refiner returned a file where that is not the case, send it back rather than present it.
- A run delivered from the refined file has the file as its source, not the Jira issue: nothing is read from or written to Jira in that run. Say so when the source was a Jira key.
