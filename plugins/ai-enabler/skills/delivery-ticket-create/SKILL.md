---
name: delivery-ticket-create
description: Turns a few sentences typed to Claude Code into a complete ticket, written as a local Markdown file - context, requirements, testable acceptance criteria, edge cases, scope, assumptions and open questions. Works like the refiner, starting from a short brief instead of an existing ticket. The file is the source for a plan or a delivery. Stays local; a Jira issue is created only if the user asks for it at the end. Use when the user says "create a ticket for...", "write a story for...", "I need a ticket that...", "turn this into a ticket", or describes a piece of work in a line or two and wants it defined properly.
argument-hint: <what is needed, in a few sentences> [--out <path>]
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.0"
---

# ai-enabler:delivery-ticket-create — a few sentences into a ticket

Takes a short description of a piece of work and produces a ticket a coding agent can implement from: a Markdown file on this machine. Nothing is changed in the codebase or in git, and nothing goes to Jira unless the person asks for it at the end.

Read `${CLAUDE_PLUGIN_ROOT}/references/ticket-readiness.md` first: it defines when a ticket is ready, how gaps are closed, and the format of the file.

## Flow

1. **Preflight.** Check, in this order:
   - `$ARGUMENTS` holds a brief. With none, ask what is needed. If it names a Jira key or an existing file instead of describing work, that is a ticket to refine: point to `/ai-enabler:delivery-ticket-refine`.
   - The brief says **what** should change and **for whom or why**. If either is missing, ask — in one go, three questions at most, each about something that changes the feature (who uses it, what the result is, what is explicitly not wanted). Do not interview: everything else is the refiner's work, and what nobody knows yet becomes an assumption or an open question in the ticket.
   - Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo_profile.py" check`. Take `root` from it: the output goes under `<root>/.enabler/tickets/`, a folder the script keeps out of git. If the status is `missing`, say in one line that the ticket will be written without knowledge of the repository; do not build the profile now.
   - The output path: `--out` if given, otherwise `<root>/.enabler/tickets/<slug>.md`, where the slug is two to five words from the brief, lowercase with hyphens. Never overwrite a file that is there: add `-2`, `-3`.
2. **Write the ticket.** Launch `ai-enabler:delivery-ticket-refiner` with `mode: document`, the `brief` exactly as the person wrote it, their answers to your questions, and the absolute output path.
3. **Present.** From its report and the file, show compactly:

   ```
   TICKET — <title>
   Requirements : <n> (<n> from you · <n> added)
   Criteria     : <n> (<n> from you · <n> added) · <sufficient|scarce|missing>
   Ready        : <ready|ready with assumptions|blocked>
   Added        : <each addition in one line, with its reason>
   Assumptions  : <each in one line, or "none">
   Questions    : <each in one line, blocking ones first, or "none">
   File         : <path>
   ```

4. **Questions, once.** If the refiner left questions, ask them now with their options and the suggested one, blocking questions first, at most four at a time. With the answers, relaunch the refiner with the file it wrote as the source, the answers, and the same output path; present the result again. Questions the person cannot answer now stay in the file.
5. **Where it goes.** Ask where they want the ticket:
   - **Keep it here** — the default, and the first option. Nothing else happens.
   - **Another place on this machine** — copy the file to the path they give.
   - **Jira** — offer it only when a connected MCP server exposes a tool that creates an issue **and** the project is not in local-only mode (`.enabler/local-only` exists or `git.local_only` is true; then do not mention Jira at all). If they choose it, follow "Creating the issue" below.

   When the person already said where they want it, do that and do not ask.
6. **Close.** Say where the file is, that it is theirs to edit, and name the next step: `/ai-enabler:delivery-plan <path>` to see the plan, or `/ai-enabler:delivery-run <path>` to deliver it.

## Creating the issue

Only on the person's explicit choice in step 5, or when they asked for it in so many words. Creating an issue is seen by other people and cannot be taken back quietly, so:

1. Ask for the project key and the issue type if they did not give them. Do not guess a project.
2. Show exactly what will be created — project, type, summary, and that the description is the file's content from "Context" to "Open questions", without the frontmatter and without the table "What refinement added" — and wait for a yes.
3. Create one issue. Do not assign it, link it, add it to a sprint or an epic, set a priority, or transition it. Nothing beyond the create call.
4. Report the key and the URL, and add `jira: <KEY>` to the file's frontmatter.
5. If the create call fails or is refused by the local-only guard, say so and leave it there: the file is the ticket. Do not look for another way.

A ticket with blocking questions can still be created in Jira if the person wants it there; say that it is not ready and that the questions are in its description.

## Rules

- **Local by default.** Without the person's choice of Jira in this run, nothing leaves the machine. An approval given in an earlier run does not carry over.
- **Nothing is written outside `.enabler/`** unless `--out` or the person's answer in step 5 says so. No code, no branch, no commit.
- Do not write the ticket in your own context: the refiner subagent does it, you present it.
- What the person said is unmarked; everything supplied by refinement is marked as added, an assumption or a question. Never present an invented business rule as theirs.
- A run delivered from the file has the file as its source: nothing is read from or written to Jira in that run, even if an issue was created from it.
