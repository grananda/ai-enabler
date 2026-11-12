# Contributing

Read [AGENTS.md](AGENTS.md) first. It is the canonical policy for people and assistants. [Release policy](docs/release-policy.md) is the operational reference.

## Start from reviewed main

Start from the change's issue on the project board, or create one; [work items and the board](docs/work-items.md) explains the columns and labels. Use a separate worktree when another task is in progress. Choose a branch such as `feat/abc-123-source-report`, `fix/runtime-paths`, `docs/install-guide`, `chore/release-governance` or `refactor/parser`. Ticket prefixes are optional and lowercase. Do not modify another worktree or a client checkout. `experiment/<slug>` is nonrelease and cannot target `main`; move selected changes to a regular branch and add fragments before review.

## Describe the change, not a guessed release number

1. Change code and relevant documentation together. Preserve ownership metadata and safety gates.
2. Add a unique `.changes/<slug>.json` with a user-facing summary, category, marketplace/component/asset bumps and migration text. See the schema in the release policy. Two independent MRs must not share one fragment filename.
3. Leave released versions and `CHANGELOG.md` unchanged. A new skill or agent starts with quoted metadata version `0.0.0` and needs a fragment.
4. Run the checks in AGENTS.md. `python tools/release.py validate --base <available-base> --branch <branch> --commit "fix(runtime): normalize paths"` validates a prospective subject before a commit exists. Add `--commits` to validate the non-merge commits already in the branch.
5. Open an MR with a Conventional Commit title, fill the template — including `Refs #<n>` for its issue, never `Closes` — and request the responsible human's review. Move the issue to "in review" and comment on it with the MR and what it contains. Never check a box without evidence. Do not include client data, credentials, private reports or local notes.

Accepted subject types are `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci`, `perf`, `style`, `revert`. An optional lowercase scope and `!` are supported: `feat(config)!: replace the state format`. A breaking subject still needs explicit fragment migration instructions; automation cannot infer semantic compatibility. Generated merge commit subjects are exempt, but MR titles and all non-merge commits are checked. Use a Conventional Commit title for the squash commit. Historical main commits before the chosen base are not relinted.

## Review responsibilities

Authors supply scope, evidence and migration notes. Asset owners review changed contracts; maintainers review shared dependencies and governance changes. Release maintainers approve the combined release plan, and the marketplace owner explicitly approves any marketplace major. The repo's named metadata owner is not evidence of a GitLab login or group. Do not invent CODEOWNERS entries. Configure enforceable approvals only after a maintainer verifies accounts and access.

## Migrating branches that used the previous policy

Do not rewrite or reset another person's branch. Coordinate a rebase onto governed `main`, inspect conflicts, restore only version fields (`VERSION`, existing plugin versions and existing asset metadata versions) to the new main baseline, and remove only that branch's not-yet-published changelog addition. Preserve actual behavior changes and all published changelog sections. Add a unique fragment describing the net change, including shared dependency assets and migration notes. Rerun runtime tests and `tools/release.py validate` before merge. This applies to the separate Python portability fix branch, which already contains old-policy bumps; this governance work does not modify it.

## Release work

Only a release MR changes final versions. See [the offline release procedure](docs/release-policy.md#offline-release-procedure). Preparation never commits, pushes, tags or uploads. A human reviews, merges, verifies and explicitly authorizes publication actions separately. Once the tags exist, close the issues whose fragments the release consumed, naming the marketplace version.
