## Release proposal

Use title `chore(release): prepare <marketplace-version>` and branch `release/<marketplace-version>`.

- Exact main base commit:
- Explicit release date:
- Planned marketplace/plugin/asset versions:
- Proposed immutable annotated tags:
- Consumed fragments:
- Issues released (in "awaiting release"; close them after the tags exist):

## Verification

- [ ] One release MR only; prepared from clean reviewed main
- [ ] Baseline or previous actual annotated tags verified
- [ ] Exact deterministic validation against current target passes
- [ ] Changelog and migration instructions reviewed
- [ ] Archived fragment contents are preserved; no unknown files removed
- [ ] Runtime tests, release tests and strict conventions pass
- [ ] No feature edits mixed into generated release changes
- [ ] Marketplace major has explicit owner approval, if applicable
- [ ] Maintainer will verify the final main commit before manually creating tags

## Publication gate

This MR does not authorize an automatic push, tag or upload. Record who will perform the human verification and separately authorized publication. Never force-replace a tag. Repository configuration does not itself protect main or tags.
