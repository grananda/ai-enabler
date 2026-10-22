# Input files for jira_cycle.py --input

The directory holds one `sprints.json` and any number of other `.json` files with issues.

## sprints.json

A list of the sprints to analyse (closed sprints only), in any order:

```json
[
  { "name": "Sprint 137", "startDate": "2026-08-13T08:00:00.000+0000", "endDate": "2026-09-03T16:00:00.000+0000" }
]
```

`start`/`end` are accepted in place of `startDate`/`endDate`.

## Issue files

Each file is a list of issues, an object with an `issues` list, or a single issue. Two shapes are accepted, and may be mixed.

**Jira's own shape** — an issue as returned with `expand=changelog`. Only these parts are read:

```json
{
  "key": "TB-5120",
  "fields": {
    "issuetype": { "name": "Story" },
    "assignee": { "displayName": "Ana Diaz" },
    "status": { "name": "Done" },
    "created": "2026-08-01T09:00:00.000+0000",
    "resolutiondate": "2026-08-27T14:10:00.000+0000",
    "summary": "..."
  },
  "changelog": { "histories": [
    { "created": "2026-08-14T08:02:11.000+0000",
      "items": [ { "field": "status", "fromString": "To Do", "toString": "In Progress" } ] }
  ] }
}
```

**Compact shape** — the same information, already reduced to status transitions:

```json
{
  "key": "TB-5120", "type": "Story", "assignee": "Ana Diaz", "status": "Done",
  "created": "2026-08-01T09:00:00.000+0000", "resolved": "2026-08-27T14:10:00.000+0000",
  "transitions": [
    { "at": "2026-08-14T08:02:11.000+0000", "from": "To Do", "to": "In Progress" }
  ]
}
```

Rules that matter for correctness:

- Include **every** status transition of the ticket's whole life, not only those inside the sprints. The script decides which ones count.
- Timestamps keep their full precision and their offset, exactly as Jira gives them.
- `resolved` is empty or absent for an unresolved ticket.
- Include every ticket that was in any of the sprints, also the unresolved ones: blocked time is reported for them.
