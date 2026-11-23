# Input files for jira_cycle.py --input

Scrum uses `sprints.json` and issue files. Kanban uses `collection.json` and issue files, with no sprints required. An empty complete issue collection is valid. Both routes (REST and MCP/offline) describe the same scope; metadata is not an issue record. Use a clean directory when changing scope so old batches cannot be mixed in.

## collection.json

Required for Kanban. Legacy Scrum files without it remain readable, including existing `--board` commands, but board scope and freshness are explicitly unverified: the requested board is recorded separately, not asserted as the collection scope. They must not be reused as a scope-checked cache. If metadata is supplied, its scope is validated.

```json
{
  "collected_at": "2026-10-12T09:00:00+00:00",
  "issues_complete": true,
  "scope": {
    "mode": "kanban",
    "project": "TB",
    "board": "7",
    "filter": "99",
    "window": ["2026-09-28T00:00:00+00:00", "2026-10-12T00:00:00+00:00"],
    "group_by": "week",
    "timezone": "UTC",
    "boundary": "[start,end)",
    "selection": "saved-filter-membership-at-collection; lifetime-overlap"
  }
}
```

IDs are strings. For a filter-only scope, `board` is null. For Scrum use `mode`, `project`, `board`, `filter: null` and `sprint_ids` instead of the window/grouping fields. `collected_at` is when current fields were observed, not when an old file was copied. `issues_complete` means every page and candidate issue was retrieved, not that every history is complete. Incomplete histories are tracked separately per issue.

The script rejects a mismatching requested mode/project/board/filter/window/grouping. Supply the same flags/configuration used for collection; it does not infer a Kanban mode or silently adopt another window. Store normalized UTC timestamps as above. Output snapshots preserve sanitized `scope` and `collected_at`; arbitrary metadata and credentials are never copied.

### Named profile identity

With `--profile NAME`, metadata is required for **both** Scrum and Kanban. Add `scope.profile: "NAME"` and `scope.connection_url: "https://jira.example.test"` matching the profile's configured endpoint exactly (including a context path, without trailing slash). The MCP server must be verified against that endpoint; do not collect from a convenient different server. A named profile without connection configuration cannot accept Jira input because its origin cannot be verified. Missing/mismatched identity is an error. Unprofiled invocations reject profile-owned collections. The script reads the explicit `--input` location, never guesses profile from its files.

Profile snapshots preserve profile and sanitized endpoint identity, but never credential values or references. Collections and snapshots belong under `<metrics-dir>/profiles-data/NAME/delivery/`, reports under that profile's reports directory; explicit report output does not move snapshots. See the plugin README for profile schema, precedence, context reset and output-directory ownership rules.

### Kanban selection and semantics

Resolve the board's saved filter through board configuration, then search `filter = <ID> AND created < "<until date plus one day>" ORDER BY key`, paginating all candidates. Do not replace the filter with `project = ...` or add lower created/resolved bounds. The padded upper bound compensates for Jira account-timezone date literals; exact UTC overlap is applied locally. If board configuration is inaccessible, stop rather than widening scope. A saved filter itself may cover multiple projects: the project selects/displays the board, not an extra implicit intersection.

Keep all issues whose lifetime overlaps the window, including issues created long before it, still open, or resolved after it. The script discards creations at/after the exact end and old resolutions with no subsequent activity. Do not clip histories: first in-progress entry can precede the window by years. Final/latest recorded resolution assigns cycle time to exactly one `[start,end)` bucket. Weekly buckets start Monday, monthly buckets start on the first; edge buckets may be partial, and empty buckets remain visible. Historical blocking counts calendar-day interval intersections with the window, capped at collection time; `blocked_now` separately lists current blocked status among window candidates, including issues whose blocking began after the historical window. Period statistics cover resolved cohorts; the blocked list covers all retained candidates.

This is saved-filter membership **at collection**, not a historical reconstruction of board membership. A filter that excludes completed issues also excludes their cycle times; use a suitable saved filter. Deleted/inaccessible issues cannot be reconstructed. Current fields (including assignee and resolution) are observed at collection; reopened issues use the latest recorded resolution.

Snapshots use `mode: kanban`, `period_kind`, `periods`, `by_period`, `window`, `timezone`, `boundary`, and `period` on detail rows. Legacy Scrum `sprints`, `by_sprint`, inclusive sprint resolution endpoints, gap assignment and blocking semantics are unchanged. Dashboard consumers accept both. Statistics retain the same working-day math, fixed-seed bootstrap and Wilson intervals.

## sprints.json

A list of the sprints to analyse (closed sprints only), in any order:

```json
[
  { "name": "Sprint 12", "startDate": "2026-08-13T08:00:00.000+0000", "endDate": "2026-09-03T16:00:00.000+0000" }
]
```

`start`/`end` are accepted in place of `startDate`/`endDate`.

## Issue files

Each file is a list of issues, an object with an `issues` list, or a single issue. Two shapes are accepted, and may be mixed.

**Jira's own shape** — an issue as returned with `expand=changelog`. Only these parts are read:

```json
{
  "key": "PROJ-123",
  "fields": {
    "issuetype": { "name": "Story" },
    "assignee": { "displayName": "Jane Doe" },
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
  "key": "PROJ-123", "type": "Story", "assignee": "Jane Doe", "status": "Done",
  "created": "2026-08-01T09:00:00.000+0000", "resolved": "2026-08-27T14:10:00.000+0000",
  "transitions": [
    { "at": "2026-08-14T08:02:11.000+0000", "from": "To Do", "to": "In Progress" }
  ]
}
```

Rules that matter for correctness:

- Include **every** status transition of the ticket's whole life, not only those inside the sprints/window. The script decides which ones count. Paginate histories to their reported total/end; do not assume `expand=changelog` is complete. Raw records preserve `changelog.total` and `startAt`; compact records carry `history_complete: true` only when verified, otherwise false. Missing verification is reported in Kanban as `unverified_changelogs`, not silently treated as complete. REST attempts paged histories and flags unsupported/incomplete responses.
- Timestamps keep their full precision and their offset, exactly as Jira gives them.
- `resolved` is empty or absent for an unresolved ticket.
- Include every ticket that was in any of the sprints, also the unresolved ones: blocked time is reported for them.
