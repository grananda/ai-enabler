---
name: delivery-sources
description: "Manages the external sources of context the ai-enabler pipeline reads besides the project itself - other repositories by URL, repositories already cloned in folders next to the project, other folders, and documents (Markdown, text, PDF, HTML, Word). Adds, lists, refreshes and removes them, and learns a new one straight away. Sources are read-only: nothing in the pipeline ever writes to them. Use when the user says \"add the contracts repo as context\", \"the pipeline should also read ../design-system\", \"use this document as reference\", \"which sources does ai-enabler use\", \"refresh the sources\", or \"remove that source\"."
argument-hint: "[add <url|path> [--name N] [--about TEXT] [--paths GLOB,GLOB] [--ref REF] | list | refresh [NAME] | relearn NAME | remove NAME]"
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.1.0"
---

# ai-enabler:delivery-sources — what else the pipeline should read

The project being changed is rarely the whole story: the API contracts are in another repository, the components in a design system, the business rules in a Word document. A source tells the pipeline where to look. It is learned once, like the project, and the planner, implementer, test engineer and reviewers get what matters from it for each ticket.

Read "External sources" in `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md` first. Every command below goes through `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sources.py"`, called `sources.py` here.

## Flow

**No argument, or `list`.** Run `sources.py check` and show one line per source: name, kind, what it is for, where it is read, and its status (`missing` — not learned yet, `fresh`, `stale` — changed since it was learned, `unreachable`). If there are none, say so and run the question in "Adding" below.

**`add <url|path>`**, or the person describes a source in their own words:

1. Work out the location. A URL; a path to a folder or a document; or a name the person uses for a repository they have cloned — `sources.py siblings` lists the git repositories next to the project, with their remotes, so "the contracts repo" can be matched to `../contracts`.
2. Ask, once and together, only for what is missing and matters: what the source is for (`--about`, one sentence: it is how the scout decides whether the source matters for a ticket), and, for a large repository, which part matters (`--paths`, for example `openapi/**`). Do not ask for a name; the script derives one.
3. `sources.py add <location> --about "..." [--paths ...] [--ref ...]`. For a URL whose clone is already next to the project, the script uses that folder and says so. A document must be `.md`, `.txt`, `.pdf`, `.html`, `.docx`, `.rst` or `.adoc`.
4. Offer to learn it now, so the next delivery does not wait for it. On a yes: `sources.py fetch <name>` when it is a URL source, then `ai-enabler:delivery-source-scout` with the task `profile` and the fields `sources.py check <name>` prints, then `sources.py record <name> --expect <profile path>`.

**`refresh [NAME]`.** `sources.py check [NAME]`. For each `unrecorded` source: `sources.py record <name>`. For each `stale` source: `sources.py fetch` when it needs it, `sources.py next-delta <name> "<what changed>"`, the scout with the task `delta` and the `recorded_commit` the check prints, then `record --expect <delta>` — or plain `record` when the scout wrote no delta. For each `missing` one, learn it as in `add`. Report what changed.

**`relearn NAME`.** `sources.py reset <name>`, then learn it again as in `add`. For a source whose deltas pile up or whose profile no longer fits.

**`remove NAME`.** Confirm, then `sources.py remove <name>`. It forgets what was learned and deletes the pipeline's own copy of a URL source; the person's own folders and documents are never touched.

## A project already under way

Sources can be added at any time; nothing has to start again.

- **Later runs** use the source from their first stage.
- **Runs in progress.** After adding, removing or refreshing a source, look for runs that are not finished (`.enabler/runs/*/state.json` with `stage` other than `done` and `status` other than `stopped`) and tell the person what will happen to each:
  - before its plan was approved: when it is resumed (`/ai-enabler:delivery-run <KEY>` or `/ai-enabler:delivery-plan <KEY>`), the source is learned, `external-context.md` is rewritten, and the plan is made — or revised — with it;
  - after its plan was approved: when it is resumed, `external-context.md` is rewritten before the next stage; if the source imposes something the approved plan does not do, that is shown to the person and, if it changes behaviour, handled as a delta at the plan gate. Nothing already written is changed silently;
  - held at the ship gate: the same, before the delivery report is written again.
- Offer to learn the new source now, so that resuming does not wait for it.

## Adding

When the person is asked whether a project needs sources (here, or by the preflight of `delivery-run` and `delivery-plan`), ask it as one question, offering what can be detected:

> Besides this repository, does the work depend on anything else — another repository, a folder, a document? I can see these repositories next to this one: `contracts` (git.example.com/team/contracts), `design-system`. Name any that apply, give a URL or a path, or say none.

An answer of "none" is remembered (`sources.py none`), and the question is not asked again; sources can still be added later with this skill or with `--context` on a run.

## Rules

- Sources are read-only. Nothing in the pipeline writes to them, and the plugin's source guard refuses any attempt. If a ticket needs a change in a source, that is out of scope for this project's pipeline: say so.
- Credentials are the ones git already has on this machine. Never ask for a token or a password, and never write one anywhere. If a URL cannot be reached, say so and suggest cloning it next to the project by hand, then adding that folder.
- Everything is kept in `.enabler/sources/`, a local folder kept out of git like the rest of `.enabler/`.
