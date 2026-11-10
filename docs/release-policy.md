# Release policy

[AGENTS.md](../AGENTS.md) is canonical. This guide defines the local protocol, not a deployment service. All tools use Python 3.11/3.12 standard libraries and local Git; they do not contact a server, install dependencies, create commits/tags, push, change remotes or upload artifacts.

## Version streams and integration

`main` integrates reviewed changes with pending fragments. It can contain unreleased work while manifests still show the last release; **a main checkout is not proof of publication**. Consumers requiring immutable content use verified annotated release tags. One release MR updates the marketplace `VERSION`, changed plugin manifests, affected skill/agent metadata, generated changelog and release snapshot. The marketplace catalogue currently has no version field; do not invent one. Its content participates in the marketplace snapshot.

Patch means compatible fixes or documentation; minor means compatible features; major means incompatible contracts. Highest requested severity wins per component/asset; ten patch fragments produce one patch, not ten. Unchanged streams do not move. Plugin severity must be at least its assets' severity. New/breaking plugin behavior requires at least a marketplace minor. Marketplace major needs explicit owner review. The tool checks arithmetic and coverage, not whether an author has correctly judged compatibility or obtained human approval.

All files within `plugins/<name>/`, including documentation and tests, require that plugin's component bump. Changes anywhere inside a skill directory require its `SKILL.md` asset bump; agent files require their own bump. Root documentation/governance changes require only marketplace coverage. Shared hooks/scripts/references are conservatively declared to affect **all assets in their plugin** in `release/dependencies.json`; authors include those assets in fragments. This deliberate over-approximation avoids silent misses in dynamic instructions. Maintainers may narrow mappings only with a reviewed dependency analysis, and must update declarations when adding assets. Removed/moved assets require coverage of old and new identities and both plugins; removed identities have no output metadata to write. Semantic removals/renames require major and migration notes. New assets start at `0.0.0` and receive a first version according to their fragment. Plugin addition/removal or binary assets require a separately reviewed tooling extension; this modest initial tool fails closed rather than guessing.

## Fragment schema

Only `.changes/<lowercase-hyphenated-slug>.json` is accepted (plus the directory README). JSON is the structured record format; there is no YAML parser dependency. Exactly these fields are required:

```json
{
  "summary": "Explain the user-visible change on one line.",
  "category": "Fixed",
  "components": {
    "marketplace": "patch",
    "ai-enabler": "patch"
  },
  "assets": {
    "plugins/ai-enabler/skills/delivery-plan/SKILL.md": "patch"
  },
  "migration": ""
}
```

`category` is `Breaking`, `Added`, `Changed` or `Fixed`. Map values are `patch`, `minor`, `major`; not final numbers. `components` uses `marketplace` and actual plugin names; `assets` uses exact repository-relative metadata paths. Every fragment needs marketplace coverage. A major or Breaking entry requires category Breaking and nonempty actionable migration instructions. A root documentation-only fragment has only marketplace patch and an empty assets map. Every touched plugin and asset must be covered by a newly added fragment relative to the MR base: old fragments cannot hide missing intent in a later MR. Already merged fragments cannot be edited/deleted; add a correction. Unknown fields, paths, file types and malformed input fail closed. No changes means no fragment is required. Fragment-only MRs are allowed for reviewed corrections. Experiment branches may omit coverage but still cannot change final versions or published records.

## Baseline and publication evidence

`release/baseline.json` is an immutable **legacy bootstrap**, derived from original GitLab main commit `18e737d`. It records marketplace `1.6.2`, plugin `ai-enabler` `1.5.1`, plugin `ai-enabler-metrics` `1.1.0`, independent asset versions and normalized text SHA-256 hashes. Its tag list is empty: there is no claim that historical tags exist. Historical changelog entries retain their original wording as history, not current policy.

The first governed release computes from this baseline. A maintainer must manually verify the initial baseline/source commit and the first release MR before creating the first real tags. Do not retroactively manufacture historical publication claims. Later `release/current.json` snapshots are marked `prepared-not-proof-of-publication`. Before preparing the next release the tool requires the previous snapshot's actual local annotated tags and verifies their content. Fetch authoritative refs/tags separately with human approval; an offline tool cannot discover a tag that was not fetched. GitLab protection and human review remain necessary against tag deletion/force replacement outside this checkout.

Snapshots cover every tracked/nonignored text file except pending fragments and the self-referential baseline/current records. Archived fragments and the directory README are covered. LF normalization prevents Windows CRLF checkout changes from manufacturing a release. Existing versions must match the baseline before preparation. Any changed plugin content requires a higher plugin version at release, including after a previous tag. `main` may carry pending content with old numbers, but it must never be tagged as the prior release. Tag verification requires exact snapshot hashes, exact versions and no pending fragments.

## Offline release procedure

1. Start from clean, up-to-date reviewed `main` with all intended fragments committed. Obtain full history and authoritative tags separately; no tool performs a fetch. Finish publication of the previous release before preparing another.
2. Run a read-only plan with an explicit date:

   ```sh
   python tools/release.py plan --date 2026-11-10
   ```

   Inspect all computed versions, tags, consumed filenames, user-visible summaries and migrations. The date is explicit so reruns are deterministic. The local tag guard refuses **any** proposed existing tag; it never mutates one.
3. With authorization, create `release/<planned-marketplace-version>` from this exact main and run:

   ```sh
   python tools/release.py prepare --date 2026-11-10
   python tools/release.py validate-release --base main --branch release/<planned-marketplace-version>
   ```

   Substitute the real planned version; do not type the placeholder. Prepare requires a clean working tree and the exact branch version. It computes all outputs before writing, archives byte-equivalent normalized contents to `release/archive/<version>/`, then removes **only the parsed named fragments**. Unknown `.changes/` files and archive collisions abort before writing. It is not a transactional filesystem operation: on disk/permission failure inspect the diff and restore only generated paths before retrying; never blindly clean the repository. Do not mix feature edits into a release MR.
4. Review the generated diff and run all AGENTS.md checks; create a Conventional Commit and release MR only with authorization. Release validation reconstructs the exact output from the Git base, including changelog, archive, snapshot and metadata. Extra edits, tampered versions, missing archives or new fragments after preparation fail. If main advances, rebuild from new main with the still-pending intended fragments; do not manually reconcile version conflicts. Keep one release MR open at a time and use merged-results checks/merge trains if available.
5. After reviewed merge to main, inspect the exact merge commit and successful checks. A human creates annotated immutable `marketplace-vX.Y.Z` and, for each changed plugin, `<plugin-name>-vX.Y.Z` on that **same release commit** (for example `ai-enabler-v1.5.2`). Only changed plugins get new tags. Never use `-f`, move or delete release tags. Creation and any push are explicit human actions, not pipeline behavior. Verify locally with `python tools/release.py verify-tag --tag <actual-tag>` on the tagged checkout before authorized publication.
6. Publish nothing automatically. The manually gated CI job prints verification only, has no credentials and creates no release objects. A remote maintainer configures protected main/tags, approval rules and who can publish. The repository does not activate these settings. No automatic RC builds/tags exist in this first version; stable versions only. If RCs become necessary, design their ordering, snapshot and promotion semantics first rather than treating them as stable releases.

## Validation modes

- `python tools/release.py validate --base <ref> --branch fix/example --commits`: compare working tree (including untracked nonignored files) with explicit base, validate fragment coverage and committed subjects. `--commit "..."` additionally validates MR titles or proposed subjects. Missing refs fail closed.
- `python tools/check_versions.py <ref>`: compatibility wrapper around the same validator. Release branches automatically use exact release validation.
- `python tools/release.py validate-release --base <release-parent> --branch main`: verifies release merge output against its pre-release first parent. Do not compare a prepared release with itself.
- `python tools/release.py verify-tag --tag <tag>`: checks annotation, target commit, snapshot, versions and absence of pending fragments. It cannot prevent an authorized remote user from replacing refs; configure server protection.

MR validation compares to the target's current tip, not just the branch's old merge base. Rebase/update when stale: this prevents deleting another MR's fragments or silently preparing against outdated versions. Main pipelines compare to the pushed commit's first parent; non-merge subjects are validated, generated merge subjects are exempt. Arbitrary legacy branch names are not retroactively accepted for new MRs.

## CI and local prerequisites

`.gitlab-ci.yml` runs on merge requests, main pushes and tags, avoiding duplicate branch pipelines. It uses Python `3.11-slim-bookworm` and `3.12-slim-bookworm` minor-pinned Linux Docker images. An available GitLab Linux Docker executor (or compatible Kubernetes executor) with network access to approved image/Debian mirrors is required. Jobs install Git/CA certificates in the ephemeral job image using Debian packages; no Python packages, plugins or project CLI are installed. Image minor tags receive security fixes and are not digest-reproducible; an operator may mirror and digest-pin approved images. No runner tags are invented. Confirm runner availability before making these jobs required. Full local Git history and tags are needed (`GIT_DEPTH: 0`); CI must expose authoritative tags, not a shallow checkout. No secrets, protected variables or publishing credentials are required.

The test matrix runs the existing five runtime scripts, strict asset conventions and the release unit/integration tests. Existing runtime scripts assume POSIX paths and may fail on Windows before the separate portability fix merges; report those failures. Linux results are not inferred from a Windows run. The optional installed `claude plugin validate .` remains a human local check, not a hidden network dependency.

## GitLab administrator checklist (not activated by this MR)

A maintainer must inspect the project's GitLab edition/tier and available settings before enabling these controls. Role names below are GitLab roles, not invented account logins.

- Protect branch **`main`**: Allowed to merge = **Maintainers**; Allowed to push and merge/direct push = **No one**; force push = **disabled**. Developers contribute through MRs. Avoid overlapping wildcard rules that grant broader access.
- Protect tags **`marketplace-v*`**, **`ai-enabler-v*`** and **`ai-enabler-metrics-v*`**: Allowed to create = **Maintainers**. Restrict release operations to designated human maintainers operationally; never allow a CI token to publish. Review existing overlapping tag rules and do not delete/recreate protected release tags. GitLab protection is access control, not an immutable cryptographic registry.
- Enable **Pipelines must succeed** and **All discussions must be resolved** before merge. Confirm the Linux executor and image/mirror access first, and run a real MR/main/tag pipeline. A shell executor ignores `image:` and is **not supported by this CI file**; do not register it for these jobs unless the pipeline is deliberately adapted and reviewed.
- Require **at least one independent human approval**, disallow author approval and approvals by committers, and reset approvals after new commits where the installed GitLab tier supports it. Have the responsible asset owner review contract changes; governance and release MRs require maintainer review. A marketplace major also requires explicit marketplace-owner approval recorded in the MR.
- Restrict who can edit approval rules and prevent per-MR overrides where supported. Configure a verified release-maintainer group or actual accounts only after confirming their identities/access; none is supplied by this repository. CODEOWNERS-based required approvals can be enabled later only with valid actual owners and tier support.
- Use merge commits or squash commits with Conventional Commit squash subjects. Enable merged-results pipelines/merge trains if supported to validate the current target; otherwise require an updated branch and a final successful pipeline before the maintainer merges.
- If the GitLab tier cannot enforce independent approvals or merged-results checks, record that limitation and use a documented human gate; do not claim equivalent enforcement. Keep publication a separate explicit human action even after a successful pipeline/manual verification job.

## Deliberate limits

No changelog NLP, semantic breaking-change inference, credentials, remote configuration, code-owner discovery, automatic git writes, package publication or RC platform. Fragment severity, dependency changes, migrations, marketplace-major approval and actual release authorization remain review responsibilities. The tool handles the current text-only repository, known plugins and stable three-part versions. The snapshot is an auditable prepared artifact, not a signed attestation. CODEOWNERS is intentionally absent until an actual authorized platform identity is verified.
