# Working in this repository

Rules for anyone changing this marketplace, human or agent. They are few, and each exists because the thing it prevents has happened.

## Versions travel with the change

Whoever makes a change also bumps the versions it affects and writes the changelog entry, in the same commit. Nobody does it afterwards. There are three levels, and they move independently:

| Level | Where | Bumps when |
|---|---|---|
| Marketplace | `VERSION` at the repository root | **Always.** Any change to the repository; see below for how much. |
| Plugin | `version` in `plugins/<plugin>/.claude-plugin/plugin.json` | Something in that plugin changed: a skill, an agent, a hook, a script, a reference, the manifest. |
| Skill or agent | `metadata.version` in its `SKILL.md` or agent file | That skill or agent changed: its file, or anything in the skill's `scripts/` or `references/`. |

Only what changed is bumped. Touching one skill bumps that skill, its plugin and `VERSION`; the other skills and the other plugin stay where they are. A change that only touches a README bumps `VERSION` and nothing else, because it does not change what a skill does.

How much to bump follows the kind of change:

- **patch** — a fix, a clarification, a correction that does not change what the asset promises;
- **minor** — new behaviour, a new option, a new stage, a new output, all compatible with existing use;
- **major** — anything that breaks someone who was using it: a renamed or removed skill, agent, command or flag, a changed file format in `.enabler/`, a changed default that alters results. Say what breaks in the plugin README.

The marketplace version is a release counter for the collection, and it moves more gently than the plugins do:

- **patch** when the release holds only fixes;
- **minor** for anything else — new behaviour, and also a breaking release of a plugin. What breaks is carried by that plugin's own major version and by the **Breaking** group of the changelog entry;
- **major** is reserved for a change to the marketplace itself (how it is installed, what it is), and is the owner's call. Do not bump it on your own.

The versions do not have to agree with each other: a skill at `1.2.0` in a plugin at `1.5.0` in a marketplace at `1.9.0` is the normal state.

Check before committing:

```
python3 tools/check_versions.py        # compares the working tree with origin/main
```

It fails when a changed skill, agent or plugin did not raise its version, or when `VERSION` did not go up: a version that is deleted, malformed, merely re-quoted or lowered does not count as a bump. A renamed or moved skill is a removal plus a new asset, so every plugin involved needs its bump. If the base reference does not exist the script says so and exits with 2 rather than passing.

## The changelog is part of the change

`CHANGELOG.md` records what each marketplace version brought. Every change adds to it in the same commit, under the version `VERSION` was bumped to:

- one section per marketplace version, newest first: `## [x.y.z] — YYYY-MM-DD`, followed by a line with the version each plugin reached;
- entries grouped as **Breaking**, **Added**, **Changed**, **Fixed**, each starting with the plugin it concerns (`**ai-enabler:**`, `**ai-enabler-metrics:**`, or `**Marketplace:**`);
- written for someone who uses the plugins: what is different for them, not which file was edited. A breaking change says what breaks and what to do instead.

Several changes made before a version is pushed go into the same section; once a version is on `main`, the next change opens a new one. `check_versions.py` fails when `VERSION` moved and the changelog has no section for it.

## Naming, ownership and metadata

The convention comes from Standard 2 of the AI4IT SWAT framework manual, kept in [docs/reference/](docs/reference/README.md): shared AI assets have a name, an owner and a version, so they outlive their author.

Every skill and agent has:

- a **name** that starts with its area and then says what it does (`delivery-plan`, `delivery-code-reviewer`): lowercase letters, numbers and hyphens, equal to its folder or file name;
- an **owner**, one person, as `metadata.owner: "Name <email>"`;
- a **version**, as `metadata.version: "x.y.z"`, quoted.

```
python3 tools/check_conventions.py
```

Both plugins follow it. A new skill or agent arrives with its name, owner and version, or the check fails.

## Documentation follows behaviour

`SKILL.md` and agent files are what the model reads; the READMEs are what people read. When a change alters what a skill does or promises, the plugin README changes in the same commit, and so does the root README or `docs/` if they describe it. Everything in the repository is written in English.

## Before committing

```
python3 tools/check_versions.py
python3 tools/check_conventions.py
python3 plugins/ai-enabler/tests/test_remote_guard.py
python3 plugins/ai-enabler-metrics/tests/test_usage.py
python3 plugins/ai-enabler-metrics/tests/test_delivery.py
claude plugin validate .
```

## What never goes into a commit

The repository is public. Client material, reports with people's names, tokens and local notes stay out of it. Stage files by path or review `git status` before `git add -A`; local-only files belong in `.git/info/exclude`.
