# App name:
Jaas skills - jaas run / jaasctl validate	Ancient symbols that perform actions (like prompts/skills).
# Skill Registry Technical Design

Version: 2.0.0  
Date: 2026-08-01  
Status: Proposed for Engineering Execution

## 1. Purpose and Scope

This document defines the technical architecture for a stateless, GitOps-driven Skill Registry that distributes immutable AI-agent skill packages. The design supports multiple agent frameworks, avoids an operational database, and provides deterministic publication, indexing, discovery, and retrieval behavior.

### 1.1 Goals

1. Provide secure, searchable, immutable skill distribution.
2. Support framework-agnostic execution contracts.
3. Enable horizontal scaling without shared mutable state.
4. Enforce dependency safety, runtime compatibility, and permission boundaries.
5. Keep operational complexity low by relying on object storage or OCI registries as the authoritative persistence layer.

### 1.2 Non-Goals

1. Runtime orchestration of skill execution inside the registry service.
2. Stateful workflow management for downstream agents.
3. Enterprise identity provider implementation details (integration points are defined, not provider-specific setup).

## 2. High-Level Architecture

```text
+-----------------------------------------------------------------------------------+
|                                 ANY AI FRAMEWORK                                  |
|      LangGraph | CrewAI | AutoGen | Claude Code | OpenAI | Internal Engines      |
+-----------------------------------------+-----------------------------------------+
                                          |
                                     REST / gRPC
                                          |
+-----------------------------------------v-----------------------------------------+
|                            REGISTRY API GATEWAY                                   |
+------------------------------+------------------------------+----------------------+
                               |                              |
                    +----------v----------+          +--------v--------+
                    |  INDEX SERVICE      |          | AUTHZ SERVICE   |
                    |  - In-memory index  |          | JWT claim check |
                    |  - SemVer resolver  |          | Scope mapping   |
                    |  - Runtime filter   |          +--------+--------+
                    +----------+----------+                   |
                               |                              |
                      +--------v------------------------------v---------+
                      |        ARTIFACT ACCESS AND VERIFICATION         |
                      | S3/MinIO or OCI references, digest, signature   |
                      +----------------------+---------------------------+
                                             |
                              +--------------v--------------+
                              | Object Storage / OCI Source |
                              | Immutable artifacts + meta  |
                              +-----------------------------+
```

### 2.1 Core Design Principles

1. Immutable Artifacts: Artifacts are content-addressed by digest and never overwritten.
2. Stateless Compute: API instances can be replaced without data loss.
3. Deterministic Resolution: Same query + constraints yields the same result.
4. Policy-First Security: Access is denied by default unless claims satisfy policy.
5. Verifiable Supply Chain: Every artifact must pass digest and signature verification.

## 3. Component Design

### 3.1 API Gateway

Responsibilities:
1. Expose search, metadata, and retrieval endpoints.
2. Validate request shape and required query params.
3. Perform authn/authz handoff.
4. Return deterministic paginated results.

Key interfaces:
1. REST for broad compatibility.
2. Optional gRPC for low-latency internal clients.

### 3.2 Index Service

Responsibilities:
1. Build an in-memory inverted index from manifest metadata.
2. Execute free-text and structured filter queries.
3. Resolve semantic versions and aliases.
4. Apply runtime and permission filter hooks.

Design notes:
1. Cold start index build reads from storage manifest prefixes.
2. Event-driven updates patch index entries incrementally.
3. Query ranking supports weighted fields: name, tags, description, owner, category.
4. Every stateless replica subscribes to the same event stream (single shared topic/queue, not per-pod) and applies updates independently, so index state converges across replicas rather than diverging. Reconciliation (see 8.2.2) bounds any transient divergence.
5. "Shards" refer to in-process memory partitioning of the index within a single replica to bound heap size, not distribution of the index across replicas — each replica still holds the full index.
6. Event transport is pluggable (for example Kafka, SQS, or Pub/Sub) and must be fixed per deployment environment; consumer group semantics must guarantee at-least-once delivery to every replica.

### 3.3 Artifact Access Layer

Responsibilities:
1. Resolve immutable artifact references.
2. Return short-lived presigned URLs or OCI pull references.
3. Verify digest and signature before exposing final artifact metadata.

Design notes:
1. Signature verification runs at ingest and can be rechecked at retrieval for high-assurance mode.
2. URL TTL is configurable by policy (for example, 60 to 300 seconds).

### 3.4 Authorization Layer

Responsibilities:
1. Validate JWT signatures and issuer.
2. Map claims to policy scopes.
3. Enforce permission requirements declared per skill.

Design notes:
1. Policy model supports deny overrides.
2. Permission matching allows exact and hierarchical scope patterns.

## 4. Canonical Skill Package Specification

### 4.1 Package Layout

```text
skill.id/
  manifest.yaml
  schema.json
  permissions.yaml
  dependencies.yaml
  prompt.md
  executor.py | executor.js | module.wasm
  README.md
  changelog.md
  tests/
  examples/
```

Implementation note: at publish time, only `manifest.yaml` must actually be
present on disk — id/name/version/owner are the skill's own identity and
have no sensible default. `schema.json`, `permissions.yaml`, and
`dependencies.yaml` each have an unambiguous empty default (an open/untyped
I/O contract, no permissions requested, no dependencies) and are filled in
automatically when absent, so a minimal skill isn't forced to carry
placeholder files just to say "none of this applies." The entrypoint file
`manifest.yaml` names (`prompt.md`/`SKILL.md`/`executor.py`/etc.) is
likewise optional to have on disk, but is packaged alongside the four
documents whenever it does exist (see `artifact/publish.py`'s
`load_source_documents`) — it's just never *validated* as a structured
document the way the other four are, since its format is entirely runtime-
family-dependent. Any other canonical-layout file (`README.md`,
`changelog.md`, `tests/`, `examples/`) is still never packaged by the
current implementation (see `artifact/packaging.py`).

### 4.2 manifest.yaml Required Fields

1. apiVersion
2. id
3. name
4. version
5. description
6. owner
7. entrypoint
8. inputs and outputs schema references
9. permissions list
10. dependencies list
11. digest
12. signature
13. tags (list, optional)
14. category
15. runtime compatibility declarations (runtime family and version range)

### 4.3 ID and Version Policy

1. ID format: vendor.domain.capability or org.category.name.
2. Version format: strict SemVer.
3. Duplicate id + version publish attempts must return 409 Conflict.

### 4.4 Dependency Policy

1. Every dependency must include id and version constraint.
2. All dependencies must be resolvable at publish time.
3. Circular dependencies are rejected by strongly connected component detection.

### 4.5 Publish-Time Guardrails

Structural validation (§4.2-§4.4) confirms a package is well-formed. It
says nothing about *content* risk — secrets, dangerous code, prompt
injection, license/supply-chain exposure. Guardrails are a second,
independent gate that runs immediately after structural validation
succeeds and before any archive is written, using the same "reject before
persisting anything" posture as the existing duplicate-publish and
dependency-cycle checks (§4.4.3, §8.1).

**A genuinely separate service, not a vendored library.** The rule
catalog *and* the engine that executes it live entirely in a standalone
codebase — [jaas-guardrails-catalog](https://github.com/balakrishna-maduru/jaas-guardrails-catalog)
— with its own repo, `pyproject.toml`, test suite, and deploy. This
service is reached exclusively over its own REST API
(`GET /catalog`, `POST /scan`, `GET /healthz`); this codebase contains
**no scanning logic and no copy of the rule catalog**. The only contact
point is `src/jaas_registry/guardrails/client.py`'s `GuardrailsClient` —
an HTTP client, not an import of the other repo's Python. Running both
locally means running two processes (`run.sh` manages this — see
ROLLOUT.md), same as this app and its web UI already are two processes.

**Why a service and not a submodule**: an earlier iteration vendored just
the *catalog* (data) as a pinned git submodule and executed it in-process
here. That still coupled the two codebases at the Python level — any
change to how a check runs required a coordinated change in this repo.
Moving the engine into the catalog's own repo, behind a versioned REST
API, means the guardrails service can add rule kinds, retune thresholds,
or scale independently, with its own release cadence, and this app never
needs a code change to consume a new catalog version — only a network
call to a possibly-newer service.

**Four levels**, modeled on CIS Benchmark's Level 1/Level 2/STIG tiering
and on GitHub's always-on-secret-scanning-vs-opt-in-custom-rules split
(full definitions live in the guardrails service's own README):

| Level | Posture | Enforcement |
|---|---|---|
| 1 — Baseline | Every tenant, every publish, no opt-out | BLOCK |
| 2 — Standard | On by default; a tenant admin may disable individual checks | WARN |
| 3 — Advanced | Off by default; opt-in | WARN |
| 4 — Regulatory | Off by default; opt-in; heavier, lower-confidence heuristics | WARN |

The 19-rule v1 catalog spans SECRET, SIZE, CODE_SAFETY, PROMPT_SAFETY,
PERMISSIONS, LICENSING, SUPPLY_CHAIN, PRIVACY, COMPLIANCE, and
CONTENT_SAFETY categories, each citing the industry source it derives
from: gitleaks/trufflehog secret-detector patterns and CWE-798, CWE-95/
CWE-78/CWE-502, OWASP Top 10 for LLM Applications 2025 LLM01/LLM06/LLM07,
OSSF Scorecard's Pinned-Dependencies and Binary-Artifacts checks, FOSSA/
SPDX license categories, and Microsoft Presidio's PII entity taxonomy.

**Division of responsibility**: the guardrails service owns *what checks
exist and how they run* — it enforces mandatory (Level 1) checks itself
regardless of what a caller's `/scan` request asks for, so this app can
never accidentally (or via a bug) disable one by omission. This app owns
*which configurable checks a tenant has opted into* —
`guardrails/policy.py`'s `GuardrailPolicy`/`GuardrailPolicyStore`,
file-backed at `<policy_dir>/guardrail_policies/<tenant_id>.json` (same
convention as `authn/tenants.py`'s membership store) — because that's a
tenant-administration concern tied to this app's own auth/RBAC model, not
something the content-scanning service should need to know about.

**Where this hooks in**: `artifact/publish.py`'s `publish_skill` calls
`GuardrailsClient.scan(...)` right after `validate_skill_package`
succeeds; a BLOCK finding raises `JaasError(GUARDRAIL_VIOLATION)` before
any archive/store write, mirroring the existing tamper/duplicate-publish
rejection path. WARN findings never block a publish; they are recorded on
the publish audit event (§7.3) and surfaced to the caller (CLI stdout, or
the `warnings` field on the `/drafts/{id}/validate` response consumed by
the web UI — see ui-design.md §10.7). `guardrails_client` is an opt-in
parameter (`| None = None`, same shape as `existing_dependency_graph`
above it) — real callers (`jaasctl`, the web API) always pass a real
client, so production publishes are always scanned; a caller that only
cares about unrelated behavior (signing, storage, index sync) can omit it
without needing a live guardrails service.

**Resilience**: the guardrails service being temporarily unreachable
never takes the rest of this app down. Its catalog is fetched on demand
per-request (`api/deps.py::get_guardrail_catalog`), not cached at startup,
so search/sharing/auth/etc. stay fully available; only the specific
routes that need it (draft validate/publish, the two tenant
guardrail-policy endpoints, `/api/v1/guardrails`) return
`503 GUARDRAILS_SERVICE_UNAVAILABLE` if it's down.

## 5. API Contract

### 5.1 Search Endpoint

Method: GET  
Path: /api/v1/skills

Query parameters:
1. query (string)
2. runtime (string, optional)
3. versionConstraint (string, optional)
4. tags (csv, optional)
5. category (string, optional)
6. page (int)
7. pageSize (int)

Response shape:
1. items[] with id, name, version, category, tags, runtime, digest, summary
   score, visibility, ownerUser, ownerTenant.
2. page metadata with total, nextPageToken.

Behavior:
1. Reachable without a bearer token (unchanged from before the visibility
   model existed); an absent, expired, or otherwise invalid token is treated
   as anonymous rather than rejected — this endpoint has no permission to
   deny, only a view to scope down.
2. Results are filtered per ui-implementation-plan.md Phase 2 / §7.2 item 4's
   visibility rule before scoring/pagination: an anonymous caller only ever
   sees `visibility: public` entries.

### 5.2 Skill Metadata Endpoint

Method: GET  
Path: /api/v1/skills/{id}/versions/{version}

Behavior:
1. Returns full manifest metadata and resolved dependencies, plus
   visibility, ownerUser, and ownerTenant.
2. Does not return executable payload.
3. Same visibility rule as 5.1; a caller who can't see the skill gets
   `SKILL_NOT_FOUND` (404), identical to a truly nonexistent id — existence
   of a private skill is never revealed to a caller without access.

### 5.5 Sharing Endpoints

Method: GET / POST / DELETE  
Path: /api/v1/skills/{id}/shares, /api/v1/skills/{id}/shares/{grantId}

Behavior:
1. List, create, or revoke a share grant (§7.2 item 4) on a skill.
2. Requires the `skills:share` scope AND (the skill's owning user OR an
   admin of its owning tenant) — the scope alone doesn't restrict which
   skill, so both checks apply together.
3. Revoking a grant takes effect on the very next request; no index rebuild
   or cache invalidation is needed, since grants are looked up per-request.

### 5.3 Artifact Access Endpoint

Method: POST  
Path: /api/v1/skills/{id}/versions/{version}/artifact-token

Behavior:
1. Validates caller authorization.
2. Returns short-lived artifact access details.

### 5.4 Artifact Retrieval Endpoint

Method: GET  
Path: /api/v1/artifacts/{token}

Behavior:
1. Redeems a token issued by 5.3; the token's possession within its TTL is the
   access control (no separate authorization check on this path), matching how
   a presigned URL works once minted.
2. Reusable until expiry, not single-use.
3. When `high_assurance_signature_recheck` is enabled (§3.3.1), re-verifies
   digest and signature against the trust policy before returning bytes;
   rejects with the same CORRUPT_PAYLOAD / INVALID_SIGNATURE codes as ingest.
4. Against a real S3/OCI backend this endpoint is unnecessary — the token
   response in 5.3 would instead be a directly-fetchable presigned URL. It
   exists only because the local-filesystem storage stand-in has no such
   mechanism of its own.

## 6. Data and Index Model

### 6.1 Indexed Fields

1. id
2. name
3. description
4. tags
5. category
6. owner.team
7. runtime
8. permissions
9. publishTimestamp
10. digest
11. signature (not searchable/filterable; carried so §5.4's high-assurance recheck doesn't need a second storage read)
12. visibility (public/private) — a property of the skill id, every version shares one value
13. ownerUser, ownerTenant — the identity a visibility/sharing check evaluates against (§7.2 item 4), distinct from the free-text owner.team label used for display/ranking

### 6.2 Derived Fields

1. latest stable version pointer.
2. compatibility flags per runtime family.
3. dependency depth score.

### 6.3 Ranking Model

Weighted scoring example:
1. Exact id match: 1.0
2. Name token match: 0.6
3. Owner match: 0.5
4. Tag match: 0.4
5. Category match: 0.3
6. Description match: 0.2

## 7. Security and Compliance Design

### 7.1 Trust Chain

1. Artifact generated in CI pipeline.
2. Digest computed from package payload.
3. Signature produced through Cosign/Sigstore.
4. Registry verifies signature against organizational trust policy.

### 7.2 Access Control

1. JWT validation at request boundary.
2. Scope checks against permissions manifest.
3. Optional tenant boundary enforcement through audience and tenant claims.
4. Visibility/sharing filter on search and metadata (§5.1-5.2): a `public`
   skill is visible to anyone; a `private` skill is visible only to its
   owning tenant or an explicit share grant (§5.5) naming the caller's user
   id or tenant id. Evaluated per-request against the caller's claims, never
   baked into the index — the same entry is visible or invisible depending
   on who's asking, and revoking a grant takes effect immediately.
5. Guardrail policy (§4.5) is readable by any tenant member, writable only
   by a tenant admin — the same `_require_membership`/`_require_admin` gate
   already used for member invites.

### 7.3 Auditability

1. Emit immutable publish events with actor, digest, and policy verdict.
2. Emit retrieval events with caller identity hash and skill reference.
3. Keep tamper-evident logs in centralized observability platform.
4. Publish events additionally record `guardrail_warning_ids` (§4.5) —
   which non-blocking checks fired, even though they didn't stop the
   publish — so a tenant can audit warning trends over time from the log
   alone, without a separate scan-result store.

## 8. Failure Modes and Recovery

### 8.1 Deterministic Corner Cases

1. Duplicate publish: reject with 409.
2. Missing dependency: reject at publish.
3. Circular dependency: reject at graph validation.
4. Corrupt payload: reject at digest verification.
5. Invalid signature: reject at trust check.
6. Runtime mismatch: exclude during search.
7. Unauthorized request: return 403.

### 8.2 Recovery Behavior

1. Instance crash: restart and rebuild index from storage metadata.
2. Event delay: periodic reconciliation scan repairs index drift.
3. Storage transient error: retry with exponential backoff and jitter.

## 9. Performance and Capacity Planning

### 9.1 Target SLOs

1. Search latency p95 <= 150 ms.
2. Metadata endpoint p95 <= 120 ms.
3. Token endpoint p95 <= 180 ms.
4. Cold start index rebuild <= 120 seconds for baseline corpus.
5. Availability target >= 99.9% monthly.

### 9.2 Capacity Assumptions

1. Skill packages: 50,000 in first 12 months.
2. Query throughput: 250 RPS average, 1,000 RPS peak.
3. Artifact token requests: 80 RPS average.

### 9.3 Scaling Strategy

1. Scale API pods horizontally.
2. Keep index memory footprint bounded with compact fields and configurable shards.
3. Use read-through local cache for frequently accessed metadata.

## 10. Observability

### 10.1 Metrics

1. request_count by endpoint and status.
2. latency histogram by endpoint.
3. index_build_duration.
4. index_event_apply_lag.
5. authz_denied_count.
6. signature_verification_failures.

Implementation note: exposed via `prometheus_client` at `GET /metrics` (Prometheus
exposition format) against a dedicated `CollectorRegistry`, not the process-wide
default, so multiple app instances in one process (as in tests) don't collide.

### 10.2 Logs

1. Structured JSON logs.
2. Correlation IDs propagated through all handlers.
3. Redaction of sensitive claims and tokens.

Implementation note: correlation IDs are carried on a `contextvars.ContextVar`
(read from an incoming `X-Correlation-Id` header, generated otherwise, echoed
back on the response). Redaction masks JWT-shaped substrings in any log
message as defense in depth, not as the only safeguard — error messages are
not expected to embed raw tokens in the first place.

### 10.3 Tracing

1. OpenTelemetry instrumentation for request path and storage calls.
2. Span annotations for validation and policy outcomes.

Implementation note: each app/CLI invocation builds its own `TracerProvider`
rather than installing one process-wide global — OTel only allows setting the
global provider once per process, which would make automated tests fight over
a shared exporter. `jaasctl serve` and `jaasctl publish` each open one
top-level span per operation so their nested storage-call spans share a trace
instead of each becoming an unrelated root. Validation and policy rejections
(schema/dependency/cycle checks, JWT/scope denials, signature/trust failures)
annotate whichever span is currently active via `annotate_current_span_error`,
which is a safe no-op when nothing is tracing.

### 10.4 Alerting

Alert conditions (error rate spike, index lag breach, signature verification
anomaly) are evaluated as a pure function over the metrics in §10.1 —
`observability/alerts.py` — returning which alerts currently fire and at what
severity. Wiring that result to a real paging channel (Slack, PagerDuty,
Alertmanager) is a production-deployment concern outside a local prototype's
reach; this is the evaluation logic those rules would run.

## 11. Deployment Architecture

### 11.1 Environments

1. Dev: fast iteration, relaxed quotas.
2. Staging: production-like policy and load tests.
3. Production: strict policy enforcement and high-availability configuration.

### 11.2 Runtime Platform

1. Kubernetes deployment with HPA.
2. Rolling updates with readiness checks.
3. Pod disruption budgets to preserve availability.

### 11.3 Configuration Management

1. GitOps-managed manifests.
2. Immutable container tags.
3. Environment-specific overlays for policy and endpoint settings.

## 12. Testing Strategy

1. Unit tests for SemVer resolution, graph validation, and policy checks.
2. Contract tests for all API endpoints.
3. Integration tests with S3/MinIO and OCI registry mocks.
4. Security tests for JWT and signature verification paths.
5. Load tests for search and token endpoints.

## 13. Acceptance Criteria

1. Publish requests fail deterministically for invalid schema, failed tests, unresolved dependencies, cycles, digest mismatch, or invalid signature.
2. Registry can recover full query capability from storage metadata without a database.
3. Query results are runtime-compatible and permission-filtered.
4. Artifact access is short-lived and auditable.
5. Horizontal scaling introduces no consistency regressions beyond defined event lag tolerance.
