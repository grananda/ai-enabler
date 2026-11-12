# Work items and the board

How work on this repository is tracked in GitLab, for people and coding assistants. [AGENTS.md](../AGENTS.md) holds the rules; this page is the operational reference. The board tracks work; the `.changes` fragment, the merge request and the release tooling remain the authority for what is released and how it is versioned ([release policy](release-policy.md)).

## Where

| What | Where |
|---|---|
| Project | `AI4IT/ai-transformation-framework` (GitLab project id `57456`), <https://umane.emeal.nttdata.com/git/AI4IT/ai-transformation-framework> |
| Issues | <https://umane.emeal.nttdata.com/git/AI4IT/ai-transformation-framework/-/issues> |
| Board | "Development" (board id `950`), <https://umane.emeal.nttdata.com/git/AI4IT/ai-transformation-framework/-/boards/950> |

The instance runs GitLab Community Edition: there are no scoped labels, epics or iterations, and issue links are `relates_to` only. Labels therefore use `/` rather than `::`, and nothing stops an issue from carrying two `workflow/` labels: keep exactly one.

## One issue per change

Every change that will reach `main` has an issue. Its title is `<KEY> — <one-line summary>`, where `<KEY>` is the team's ticket key (for example `ENABLER-2`); work that has no ticket of its own keeps the summary alone, without inventing a key. The GitLab number (`#2`) is what merge requests and commits reference. The description holds the ticket as written, and a **Status** section appended to it once work has started: the branch, what changed, any deviation from the ticket and why, the fragment, the checks run with their real outcome (including platform failures), and what is still pending. Keep it current; it is the summary someone opening the issue reads first.

## Comments: the record of the work

The comments are the history of the issue: what was done, what was concluded, and why. **Every piece of work on an issue ends with a comment**, written when it ends, not batched at the close:

| When | The comment says |
|---|---|
| Analysis done | Whether the change makes sense; what was checked, in the code and in external documentation (with a link); a verdict per requirement; the expected component, category and bump. When the ticket contradicts the current policy — tickets written before the fragment policy still ask for version bumps — say so; [AGENTS.md](../AGENTS.md) wins |
| Scope decided | What the person decided, and what was left out |
| A working session ends (implementation, a fix, a review round) | What was done, the commits, any deviation from the ticket and why, the checks run with their real outcome, and what is pending |
| A finding along the way | Something learned that changes the plan: a wrong assumption in the ticket, a limitation of a tool, a pre-existing failure |
| MR opened, merged | The MR, and anything the review changed |
| Released or rejected | The marketplace version that carries it, or why it is not done |

Write them for someone who was not there: facts and conclusions, with commands, paths and links as evidence, not a narration of the session. Keep them short — the diff, the MR and the Status section hold the details. Write in English, like the rest of the repository, and nothing that must not be in a shared tracker: no credentials, client material or reports naming people.

## Columns

The board's lists are labels. Dragging a card replaces its `workflow/` label; doing it by hand, remove the previous one.

| Column | Label | Enter when | Leave when |
|---|---|---|---|
| Open | none | The issue is created | Analysis starts |
| Analysis | `workflow/analysis` | Someone examines whether and how to do it | The person responsible agrees a scope (or rejects it) |
| Ready | `workflow/ready` | Scope agreed, `bump/` label set | A branch is created |
| In progress | `workflow/in progress` | Work started on a `feat/`, `fix/`, `docs/`, `chore/` or `refactor/` branch | The merge request is opened |
| In review | `workflow/in review` | MR open, with its fragment; checks and human review | The MR is merged into `main` |
| Awaiting release | `workflow/awaiting release` | Merged into `main`; its fragment is pending | A release MR consumed the fragment and the release tags exist |
| Closed | — | Released and tagged, or rejected | — |

A merged change is not released until a `release/<marketplace-version>` MR consumes its fragment; that is why "Awaiting release" exists. The release maintainer closes those issues once the tags exist, with a comment naming the marketplace version. An issue rejected in analysis is closed with a comment saying why.

## Labels

The labels mirror the fragment, so that the board shows what a release will contain. When the fragment and the labels disagree, the fragment is right: update the labels.

| Group | Labels | Matches |
|---|---|---|
| `component/` | `ai-enabler`, `ai-enabler-metrics`, `marketplace` | The fragment's `components`. One per plugin touched; `component/marketplace` only for root-only changes (tools, release tooling, root docs), since every fragment covers the marketplace anyway |
| `type/` | `feature`, `fix`, `change`, `breaking`, `docs`, `chore` | The fragment's `category` (`Added`, `Fixed`, `Changed`, `Breaking`) and the Conventional Commit type (`feat`, `fix`, `docs`, `chore`/`refactor`) |
| `bump/` | `patch`, `minor`, `major` | The expected bump. Set when the scope is agreed, not before. A marketplace major needs the owner's explicit approval |

## Branches, commits and merge requests

- Name the branch after the key in lowercase: `feat/enabler-1-agent-attribution-in-events`, `fix/enabler-2-bounded-scout-commands`.
- Reference the issue with `Refs #<n>` in the MR description (the "Issue" line of the template) and, if wanted, in the commit body. **Never `Closes #<n>` or `Fixes #<n>`**: GitLab would close the issue at merge, before it is released.
- One issue, one MR, one fragment, as a rule. A change split into several MRs keeps one issue and lists every MR in its Status and in a comment.

## Milestones

Optional. When a release is planned, the release maintainer may create a milestone named after the planned marketplace version (`1.8.0`) and assign the issues in "Awaiting release" to it. The version comes from `python tools/release.py plan`, never from a guess.

## Coding assistants

- **Reading is free; most writing is not.** An assistant may read issues, comments and the board at any time. Creating or closing an issue, changing labels, moving a card or linking issues is a write to a shared system, like a push: do it only when the person asked for it or confirmed it. One confirmation covers the board updates of the task at hand; say each update in the reply.
- **Commenting the work is part of the work.** When the person asks an assistant to work on an issue, the comments listed under "Comments: the record of the work" and the Status section are part of the request: post them without asking again, and say in the reply that you did. If the assistant has no GitLab access, it writes the comment in its reply for the person to post, and says so.
- **At each transition**, update the board when authorized, or tell the person which move is due.
- **Credentials.** Use the GitLab API with a token from the environment (`GITLAB_TOKEN`) or from a file outside the repository, or `glab` if it is installed and authenticated. Never print a token, never ask for it in the chat, never write it into the repository or a command shown to the person. A project access token makes the bot user the author of what is written.
- **Content.** Issues are private, but the repository is public. Do not copy client material, credentials or reports naming people from an issue into a commit, a fragment or a document.
