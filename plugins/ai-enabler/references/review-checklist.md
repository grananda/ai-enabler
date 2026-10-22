# Review checklist

Given to each `delivery-code-reviewer` instance alongside its lens. It is a list of places to look, not a list of findings to produce: report only what the changed code actually shows.

## All lenses

- Does the change do what the ticket asks, and only that? Flag out-of-scope edits.
- Does it affect code outside the diff — shared modules, public contracts, configuration, build or deployment?
- Is it backwards compatible for existing callers, stored data and API clients?
- Does it follow the hard rules listed in the repository profile and its deltas?

## Correctness

- Each acceptance criterion: met, partially met, or missing.
- Boundary, empty, null and unexpected-state handling.
- Error paths: are failures caught at the right level, reported correctly, and never swallowed?
- Concurrency: shared state, races, locking, idempotency of retried operations.
- Transactions: boundaries, partial failure, ordering of side effects.
- Resources: connections, streams, subscriptions and timers released.
- Regressions in existing behaviour.

## Security

- Every new entry point: authentication, authorisation, input validation.
- Injection: SQL, command, path, template, expression language.
- Sensitive data in logs, error messages, responses and URLs.
- Secrets and environment-specific values in code or config.
- Deserialisation, file upload, redirects, outbound requests built from input.
- New or upgraded dependencies.

## Quality

- Layering and separation of concerns as this codebase practises them.
- Duplication of something that already exists; reuse missed.
- Naming, readability, function size, cyclomatic complexity.
- Dead or unreachable code, leftover debugging, commented-out code.
- Observability consistent with the surrounding code.
- Performance evident from the code: N+1 queries, repeated I/O or serialisation in loops, unbounded result sets, missing pagination.

## Tests

- A failing-if-broken test for each acceptance criterion.
- Error and boundary cases, not just the happy path.
- Assertions that check behaviour, not that a mock was called.
- Determinism: no dependence on time, order, network or shared state.
- Existing tests weakened, skipped or deleted by the change — other than the removals an approved delta lists.

## By layer, when the change touches it

**Backend:** query efficiency and indexes, transaction and lock scope, timeouts and retries on external calls, DTO and model validation, domain versus infrastructure errors, migration safety and rollback.

**API:** contract compliance, HTTP status codes, response shape, safe error bodies, pagination, filtering and sorting, versioning, breaking changes for clients, documentation (OpenAPI) kept in step.

**Frontend:** state management, unnecessary re-renders, unreleased subscriptions, async and error handling, loading, empty and error states, form validation, accessibility, internationalisation, business logic inside components, XSS and sensitive data in the client.
