# Repository profile

Shared by the `ai-enabler` skills and agents; split out of `run-and-config.md`, which is read at the start of every skill, because most runs never need it.

A repository is learned once, not once per ticket. What the pipeline knows about it lives outside the runs, in `.enabler/repo-profile/`, and stays on this machine:

| File | Content |
|---|---|
| `profile.md` | What the repository is: stack, the commands that work here, structure, conventions, hard rules, git conventions. Written once by the scout, about 150 lines at most, and not rewritten by the pipeline afterwards |
| `deltas/delta-NNN-<slug>.md` | One small complement each: what changed, or what was learned. About 30 lines at most. A later delta overrides an earlier one and the profile |
| `profile.json`, `pending.json` | Fingerprints of the files the profile was derived from. Written by the script, never by an agent |

The profile grows by complements, never by rewriting: a document that is extended on every run becomes too long to read, and then it is skimmed and trusted less. The base says what the repository is; each delta says what is different now.

Every abbreviated `repo_profile.py ...` or `sources.py ...` command in this reference and the delivery skills means `/bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/<script>.py" ...`. Keep script paths and path arguments quoted; on Windows use native paths such as `C:/work/project` for path arguments. Use this launcher, not an ad hoc interpreter fallback. If it fails, report the failure and stop the dependent step.

At the scout stage, ask the script whether the profile still holds — it compares a hash of each build manifest, CI and lint configuration file, the root README and the rules files (`CLAUDE.md`, `AGENTS.md`, contribution guides, ADRs) with what it recorded; lock files and source code are not watched:

```
/bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/repo_profile.py" check
```

It prints JSON. `root` is the folder whose `.enabler/` is in use, and `profile` the absolute path of `profile.md`; the run directories belong under the same `root`. Pass the scout the absolute paths the script prints, never a relative one.

| `status` | Meaning | Scout `tasks` | Then |
|---|---|---|---|
| `missing` | The repository has not been learned yet | `profile`, `ticket` | `record --expect <profile path>` |
| `unrecorded` | There is a `profile.md` but no usable fingerprints: written or restored by hand | `ticket` | `record`. Never overwrite that profile |
| `fresh` | Nothing the profile was derived from has changed | `ticket` | — |
| `stale` | Some watched files changed, appeared or disappeared (the script lists them, and summarises them under `summary`) | `delta`, `ticket` | see below |

**The profile describes the base branch, not the work in progress.** When the project is a git repository, `check` and `record` compare the watched files at the merge-base of `HEAD` and the base branch — the first that exists of `--base`, `git.base_branch` in `.enabler/config.json`, the default branch of `origin`, `main` or `master` — so the edits a run makes on its own feature branch, committed or not, leave the profile fresh; they are seen once they are merged. Both commands print what they compared under `against`. Without git, the working tree is used. Deltas learned during a run (`record --keep`) note the branch they were learned on; while that branch is not merged into the base branch, or no longer exists, `check` lists them under `provisional`. They are unconfirmed: they may describe a rule that never reaches the base branch. They are never deleted or rewritten; the scout names them in `repo-context.md` so that no later stage relies on them.

**When the profile is stale.** Get the delta's path with `repo_profile.py next-delta "<a few words on what changed>"` (they only become a file name: two or three nouns such as `"test runner"`, not a sentence and not the name of a command) and pass it to the scout with the `summary` lines of the check. `summary` names every file when a dozen or fewer changed; beyond that it gives one line per kind of file (`rules`, `ci`, `build`, `lint`, `docs`) and top-level folder, with counts, file names and two examples, and still names each file at the root of the project. Never pass the full `changed`, `added` and `removed` lists: after a large merge they run to hundreds of paths, and the scout would open them one by one. The scout answers one of two things:

- it wrote the delta — run `repo_profile.py record --expect <delta path>`. The script refuses if that file is not there, so a change is never marked as seen with nothing describing it;
- nothing the profile or its deltas say is affected (a dependency bump, a reformat) and it wrote no file — run `repo_profile.py record`. No empty delta is kept.

`record` stores the files as they were when `check` saw them, so a watched file edited in the meantime is found by the next check instead of being swallowed.

**When something was learned.** (The same holds for an external source: a note that starts with `source <name>: ` becomes a delta of that source; see `external-sources.md`.) A later stage may report that the profile was wrong or incomplete: a command that does not work here, a convention the code does not follow, a rule nobody had written down. Append it at once to `profile_notes` in `state.json`, one line each, so it survives a resume. A note states what is true of the repository as it is on the base branch — a command, a convention, a rule that already exists — never the behaviour this run is adding: that belongs to the change, and becomes true of the repository only when it is merged. At the next pause — a gate, or the end of the run, never the middle of a stage — and for each note: `next-delta`, launch the scout with the task `delta` and the note as its `learned` reason, `record --expect <delta path> --keep`, and remove the note from `state.json`. `--keep` leaves the fingerprints alone: a learned delta says nothing about which files changed.

**Starting again: `--relearn`.** Run `repo_profile.py reset` and treat the profile as `missing`: the repository is studied from scratch and every delta is dropped, learned ones included, so the scout reads the old profile and deltas *before* the reset and carries over what still holds. Never do it unasked. Suggest it, once, when `suggest_relearn` in the check is not empty (the profile has outgrown its size, there are more than ten deltas, or deltas run long), or when the scout says the profile and its deltas no longer fit together. `--refresh` does not touch the profile: it re-runs the stages of one ticket.

The person may correct `profile.md` or add a delta by hand; the pipeline itself never edits what is written. Nothing in `.enabler/repo-profile/` is committed, and none of it is copied into `CLAUDE.md`, `AGENTS.md` or any other project file.

**A run started before the profile existed** has a `repo-context.md` that holds everything, written by an earlier version. On resume, run `check` like any other run (Step 2), but do not ask for the `ticket` task: keep that file as it is. Agents read the profile, the deltas and it together.
