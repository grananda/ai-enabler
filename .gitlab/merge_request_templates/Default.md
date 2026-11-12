## Summary

User-visible change and reason. Use a Conventional Commit MR title.

## Scope and release intent

- Issue (`Refs #<n>`, never `Closes`; the issue moves to "awaiting release" at merge):
- Branch type and optional ticket:
- New `.changes/*.json` files:
- Component and asset bump intent (no final version edits):
- Shared dependency coverage:
- Breaking changes and migration (or not applicable):

## Evidence

List commands, outcomes and any platform limitations. Do not claim checks not run.

- [ ] Fragment policy and Conventional Commit checks pass
- [ ] Strict metadata conventions pass
- [ ] Release-tool tests and relevant runtime tests pass
- [ ] Behavior documentation is updated
- [ ] Existing final versions and published changelog entries are unchanged
- [ ] No client material, credentials, reports naming people or local notes are included
- [ ] Human review requested from the responsible asset owner/maintainer

## Review notes

Known limitations, rollout considerations and explicit decisions needed. Experiments cannot target main directly; promote to a governed branch first.
