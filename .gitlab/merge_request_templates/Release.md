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

After merge, the maintainer: creates and verifies the annotated tags on the release merge commit and pushes them; runs the manual `verify-release-manually` job of the marketplace tag pipeline; creates the GitLab release `Marketplace <version>` on the marketplace tag (sections Components, Changes, Requirements and update, Validation; see [the release procedure](../../docs/release-policy.md#offline-release-procedure)); closes the released issues naming the version.
