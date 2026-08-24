# Coding Standards and API Conventions

Phase 0 deliverable per implementation-plan.md. Applies to all modules under `src/jaas_registry`.

## Module boundaries

- `common` — shared models, error codes, config. No dependency on any other module below.
- `validation` — schema/SemVer/dependency-graph validation. Depends on `common` only.
- `artifact` — packaging, digest, signing, immutable writes. Depends on `common`, `storage`.
- `storage` — object-store adapter (local filesystem now; S3/OCI later behind the same interface).
- `index` — in-memory index, query planner, SemVer resolver, and the event
  stream abstraction/consumer for index sync (`index/events.py`,
  `index/consumer.py`). Depends on `common`, `validation`.
- `authz` — JWT validation, policy/scope matching. Depends on `common`.
- `api` — FastAPI routes only; no business logic — delegates to the modules above.

Rule: a module never imports from `api`. This keeps the core registry logic usable from `jaasctl` (CLI) without booting the web server.

## Error model

All rejected operations raise a `JaasError` (see `common/errors.py`) with a stable, documented `code`. Codes are never reused for a different meaning once shipped. HTTP mapping lives only in `api/errors.py`.

## Testing bar (Definition of Done)

- New logic in `validation`, `index`, `authz`, `artifact` requires unit tests before merge.
- Endpoints require at least one contract test asserting request/response shape.
- A change is not done until `ruff check .` and `pytest` both pass.
- Target >= 90% branch coverage for `validation` (per design.md acceptance criteria).

## API conventions

- Routes are versioned under `/api/v1`.
- List endpoints are always paginated (`page`, `pageSize`) and return `total` + `nextPageToken`.
- Errors return `{ "code": str, "message": str }` with the HTTP status implied by the code family.
