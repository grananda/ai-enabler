# Working in this repository

Canonical common instructions for humans and coding assistants. Tool-specific instruction files point here; they must not copy or override this policy.

## Changes first, versions at release

Feature and maintenance merge requests add a unique structured `.changes/*.json` record. Do **not** bump `VERSION`, plugin manifests or existing skill/agent `metadata.version`, and do not edit published changelog sections. This deliberately replaces the former "bump every MR" rule. The release maintainer collects reviewed fragments in one release MR; deterministic local tooling computes final versions, generates the changelog and archives exactly the consumed fragments.

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/release-policy.md](docs/release-policy.md) for the schema and commands. `tools/check_versions.py` is a compatibility entry point for the same policy, not a second versioning mechanism.

- Marketplace, plugins and individual skills/agents have independent versions. Every releasable repository change needs a marketplace bump; every touched plugin needs component coverage, including its documentation and tests. Root-only documentation needs no plugin bump.
- Use **patch** for fixes, corrections and documentation; **minor** for compatible new behavior, options, stages or outputs; **major** for incompatible contracts. Changed assets need explicit fragment coverage; their metadata bumps are applied automatically at release. Shared dependencies are declared in `release/dependencies.json`.
- A removed or renamed skill, agent, command or flag, changed persisted format, or default that alters results can break consumers. Record a major bump, a **Breaking** entry and actionable migration instructions. In `.enabler/`, this includes `config.json`, `state.json` keys, recorded events/snapshots and anything that prevents an in-progress run resuming. Agent-to-agent handoff content may change in a minor only if old runs still resume.
- Marketplace **patch** covers fixes/docs; **minor** covers new behavior and breaking plugin releases. A marketplace **major** changes installation or the collection's own contract and requires the owner's explicit approval. Never choose it autonomously. Plugin and asset majors carry their own breaking changes.
- Published versions and annotated tags are immutable. Never move/delete a release tag or replace content under the same published version. No command in the release tooling commits, tags, pushes or uploads.

## Branches and review

`main` is the stable integration branch and is intended to be protected: merge requests, successful checks and human review, with no direct or force pushes. A GitLab maintainer must configure this separately; repository files do not activate protection.

Use `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>` or `refactor/<slug>`, optionally a lowercase ticket prefix such as `fix/abc-123-path-handling`. Use `experiment/<slug>` for nonrelease work; promote reviewed changes to a governed branch before targeting `main`. Only release maintainers use `release/<marketplace-version>`.

Commit subjects and MR titles use Conventional Commits, for example `fix(runtime): normalize local paths`. See the release policy for accepted types and squash/merge rules. Do not commit or push without the person's authorization; branch before authorized commits on `main`. Do not alter other worktrees, client projects or remote configuration as part of an unrelated change.

## Work items and the board

Work is tracked as GitLab issues on the project's "Development" board; [docs/work-items.md](docs/work-items.md) is the reference for columns, labels and access.

- Every change that reaches `main` has an issue titled `<KEY> — <summary>` (the summary alone when there is no ticket key; never invent one). Name the branch after the key (`feat/enabler-2-...`). The MR description says `Refs #<n>`, never `Closes` or `Fixes`: a merged change is not released until a release MR consumes its fragment.
- The board's columns are `workflow/` labels: analysis → ready → in progress → in review → awaiting release, then closed once the release is tagged. Keep exactly one `workflow/` label; GitLab here does not enforce it.
- `component/`, `type/` and `bump/` labels mirror the fragment. The fragment is the authority; when they differ, fix the labels.
- Analyse before implementing, and record the work on the issue: every piece of work ends with a comment saying what was done and what was concluded — the analysis, the scope decided, each working session with its commits, findings, the MR, the release — following "Comments: the record of the work" in [docs/work-items.md](docs/work-items.md). Keep a Status section current in the description. Report checks honestly, including platform failures.
- Reading issues and the board is always allowed. Commenting the work on an issue you were asked to work on, and keeping its Status current, needs no further confirmation. Creating, labelling, moving or closing issues is a remote write: only with the person's request or confirmation, as for a push. Never print, request in chat or commit a GitLab token.

## Naming, ownership and metadata

The convention comes from Standard 2 of the AI4IT SWAT framework manual in [docs/reference/](docs/reference/README.md): shared AI assets have a name, an owner and a version so they outlive their author.

Every skill and agent has:

- a **name** starting with its area, then what it does (`delivery-plan`, `delivery-code-reviewer`): lowercase letters, numbers and hyphens, matching its folder/file name;
- an **owner**, one person, as `metadata.owner: "Name <email>"`;
- a quoted **version**, as `metadata.version: "x.y.z"`. New unreleased assets start at `"0.0.0"`; a fragment selects their first released version. Existing assets retain their baseline until release.

Both plugins follow this. Never invent an owner identity, email or platform login. There is no CODEOWNERS file until a maintainer verifies an actual GitLab owner/group with repository access. Metadata owners are not automatically GitLab approval identities.

## Documentation follows behavior

`SKILL.md` and agent files are what the model reads; READMEs are what people read. When behavior or promises change, update the plugin README in the same MR, and the root README or `docs/` if they describe it. Write repository documentation in English. Changelog entries are user-facing and grouped as **Breaking**, **Added**, **Changed**, **Fixed**; breaking entries explain the replacement or migration.

## Before requesting review

Run from the repository root with Python 3.11 or 3.12 (standard library only):

```sh
python tools/check_versions.py origin/main
python tools/check_conventions.py --strict
python -m unittest discover -s tools/tests -v
python plugins/ai-enabler/tests/test_remote_guard.py
python plugins/ai-enabler/tests/test_repo_profile.py
python plugins/ai-enabler/tests/test_sources.py
python plugins/ai-enabler-metrics/tests/test_usage.py
python plugins/ai-enabler-metrics/tests/test_delivery.py
git diff --check
```

Pass an explicit available base instead of `origin/main` for offline review. Missing refs fail closed. If already installed, also run `claude plugin validate .`; do not install a CLI or authenticate merely to run checks without approval. Linux CI is authoritative for existing POSIX-oriented runtime tests; record Windows failures honestly rather than bypassing them.

## What never goes into a commit

The repository is public. Client material, reports with people's names, tokens and local notes stay out. Stage files by path or review `git status` before `git add -A`; local-only files belong in `.git/info/exclude`. Preserve the plugins' human approval gates and Git/Jira/source safety rules. Release automation must not introduce credentials, publishing tokens, automatic push, remote configuration changes or public artifact upload.
