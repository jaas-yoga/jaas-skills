# Skill Registry Detailed Implementation Plan

Version: 1.0.0  
Date: 2026-08-01  
Linked Design: design.md

## 1. Plan Overview

This plan converts the technical design into executable engineering phases with measurable outcomes, delivery gates, and rollback-safe milestones.

### 1.1 Delivery Objectives

1. Build a stateless registry service with in-memory search and immutable artifact retrieval.
2. Deliver deterministic publish validation including schema, dependency, digest, and signature checks.
3. Ship production-grade observability, security controls, and scaling behavior.
4. Enable phased adoption from S3/MinIO to OCI-first workflows without service interruption.

### 1.2 Team Roles

1. Platform Team: infrastructure, deployment, observability.
2. Backend Team: API, indexing, policy enforcement.
3. Security Team: signature trust, authz policy, audit controls.
4. QA Team: integration, performance, and resilience validation.

## 2. Work Breakdown Structure

## Phase 0: Foundations and Standards (Week 1)

### Deliverables

1. Repository structure finalized.
2. Coding standards and API conventions documented.
3. Definition of Done and test quality bars approved.

### Tasks

1. Create module boundaries:
- api-gateway
- index-engine
- artifact-provider
- authz
- common contracts
2. Define configuration model:
- environment variables
- policy files
- feature flags
3. Set up CI baseline:
- lint
- unit tests
- dependency scanning

### Exit Criteria

1. CI passes on baseline branches.
2. Standards documents are approved.

## Phase 1: Skill Package Contracts and Validation Engine (Weeks 2-3)

### Deliverables

1. Finalized schemas for manifest and contract files.
2. Validation library consumable by CLI and backend.

### Tasks

1. Define JSON Schemas:
- manifest.yaml schema
- schema.json validation
- permissions.yaml schema
- dependencies.yaml schema
2. Implement validation rules:
- required fields
- SemVer validation
- id namespace regex
- runtime format validation
- dependency constraint parsing
3. Build graph validator:
- dependency graph construction
- cycle detection (SCC)
4. Create shared error model with stable error codes.

### Exit Criteria

1. Invalid package fixtures fail with deterministic error codes.
2. All validation unit tests pass with >= 90% branch coverage for validators.

## Phase 2: Publish Pipeline and Artifact Integrity (Weeks 3-4)

Note: Phase 2 overlaps Phase 1 by one week. Only packaging/signing groundwork (tasks 1-2) may start in week 3, run in parallel with Phase 1 hardening. Ingest verification (task 3) consumes the Phase 1 validation library and cannot start until Phase 1 exit criteria are met.

### Deliverables

1. Skill packaging and signing workflow.
2. Ingest pipeline for artifact metadata and verification.

### Tasks

1. Implement packaging command flow:
- collect package files
- generate normalized archive
- compute sha256 digest
2. Integrate Cosign/Sigstore signing in CI.
3. Implement ingest verification:
- digest comparison
- signature verification
- policy trust-chain check
4. Enforce immutable writes:
- S3 conditional write or OCI immutable tag strategy

### Exit Criteria

1. Tampered packages are rejected.
2. Duplicate publishes return 409 conflict.
3. Publish audit event is emitted with actor + digest.

## Phase 3: API Gateway and Search Service (Weeks 5-6)

### Deliverables

1. Public REST API for search, metadata, and artifact token retrieval.
2. In-memory index engine with filtered query support.

### Tasks

1. Implement endpoints:
- GET /api/v1/skills
- GET /api/v1/skills/{id}/versions/{version}
- POST /api/v1/skills/{id}/versions/{version}/artifact-token
2. Implement query planner:
- text query parsing
- structured tag/category filters
- pagination and deterministic sort
3. Implement SemVer resolver:
- exact
- ranges
- alias channels
4. Implement runtime compatibility filtering.

### Exit Criteria

1. Endpoint contracts pass API conformance tests.
2. Search p95 under target for expected corpus size.

## Phase 4: Authorization and Policy Enforcement (Week 7)

### Deliverables

1. JWT validation middleware.
2. Permission resolution engine against skill policy metadata.

### Tasks

1. Implement token verification:
- issuer
- audience
- signature
- expiry checks
2. Implement scope mapping logic.
3. Apply deny-by-default authorization policy.
4. Add tenant-boundary optional checks.

### Exit Criteria

1. Unauthorized retrieval attempts return 403.
2. Permission matrix tests pass for all major scope permutations.

## Phase 5: Index Build, Event Sync, and Recovery (Weeks 8-9)

### Deliverables

1. Cold-start index builder from storage manifests.
2. Event-driven incremental index updater.
3. Reconciliation scanner for drift repair.

### Tasks

1. Implement bootstrap harvester:
- list manifest prefixes
- parse and validate
- build index documents
2. Implement event consumer:
- publish event ingestion
- idempotent apply
- retry and dead-letter handling
3. Add reconciliation job:
- periodic scan
- compare index checksum
- repair divergence

### Exit Criteria

1. Cold start meets rebuild SLO.
2. Event lag is observable and within threshold.
3. Reconciliation resolves synthetic drift scenarios.

## Phase 6: Observability and Operations (Week 10)

### Deliverables

1. Production telemetry package.
2. Alerting, dashboards, and runbooks.

### Tasks

1. Add structured logs with correlation IDs.
2. Add metrics:
- latency histograms
- verification failures
- authz denials
- index lag
3. Add traces with OpenTelemetry spans.
4. Define alerts:
- error rate spikes
- index lag threshold breach
- signature verification anomaly

### Exit Criteria

1. Dashboards show real-time service health.
2. On-call runbooks validated by tabletop exercises.

Local-prototype note: tasks 1-4 are implemented as real, tested code
(`observability/logging.py`, `metrics.py`, `tracing.py`, `alerts.py`, wired
through `api/middleware.py` and the affected modules) and verified against a
live `runectl serve` process. Exit criteria 1-2 need a real dashboard (Grafana)
and an on-call rotation to validate against — outside what a local repo can
exercise; `evaluate_all()` in `alerts.py` is the evaluation logic those
dashboards/runbooks would consume, stopping short of the paging integration.

## Phase 7: Performance, Resilience, and Security Hardening (Weeks 11-12)

### Deliverables

1. Load test report and tuning changes.
2. Failure-injection and recovery validation.
3. Security test report.

### Tasks

1. Run load tests at expected and peak throughput.
2. Tune memory/index allocations.
3. Run chaos scenarios:
- node restart storms
- event delay
- storage transient failures
4. Execute security test suite:
- auth bypass attempts
- signature trust failures
- malformed manifest fuzzing

### Exit Criteria

1. SLOs satisfied under peak profile.
2. Recovery verified for all listed failure modes.
3. Security sign-off completed.

Local-prototype note: `tests/performance/`, `tests/resilience/`, and
`tests/security/` implement tasks 1, 3, and 4 as real, passing tests — not
simulated. The load test (task 1) is an in-process ASGI-transport smoke test,
not a substitute for k6/locust/vegeta against a live multi-worker deployment
under real network conditions (§9.2's 1,000 RPS peak assumes a horizontally
scaled fleet per §9.3.1, not one process). It nonetheless caught two real
issues, fixed as part of task 2's "tuning changes": `observability/tracing.py`
now defaults to `BatchSpanProcessor` instead of a request-thread-blocking
`SimpleSpanProcessor`, and `index/semver_resolver.py` now memoizes SemVer
parsing, which was being redone from scratch for every skill on every search.
Chaos scenarios (task 3) are exercised via a `FlakyStore` failure-injection
wrapper and repeated bootstrap cycles, not real node/pod restarts in a
cluster. The security suite (task 4) is real dynamic testing (JWT forgery
attempts, trust-policy bypass attempts, hypothesis-based manifest fuzzing) but
is not equivalent to third-party penetration testing; exit criterion 3
("security sign-off") implies a human/external reviewer this repo cannot
provide on its own.

## Phase 8: Production Rollout (Week 13)

### Deliverables

1. Controlled production launch.
2. Post-launch validation and stabilization report.

### Tasks

1. Deploy canary subset.
2. Compare baseline and canary KPIs.
3. Expand rollout gradually.
4. Execute rollback playbook dry run.

### Exit Criteria

1. No high-severity production incidents during rollout window.
2. Rollback readiness validated.

## 3. Milestones and Gates

1. M1: Contract and validator completion.
2. M2: Secure publish and ingest verification complete.
3. M3: API + index capabilities complete.
4. M4: Authz enforcement and policy matrix pass.
5. M5: Recovery and event sync readiness.
6. M6: Operational readiness complete.
7. M7: Performance and security sign-off.
8. M8: Production go-live.

## 4. Test Plan by Layer

1. Unit:
- SemVer resolver
- graph cycle detection
- policy matcher
- schema validators
2. Contract:
- endpoint request/response schema stability
3. Integration:
- storage and registry adapter behavior
- ingest and verification paths
4. End-to-end:
- publish to discover to retrieve flow
5. Non-functional:
- load
- chaos
- security

## 5. Risk Register and Mitigations

1. Risk: Startup rebuild grows with corpus size.  
Mitigation: parallel manifest scan, shardable index build, snapshot-assisted bootstrap.
2. Risk: Event bus lag causes stale search outcomes.  
Mitigation: reconciliation sweep and staleness budget monitoring.
3. Risk: Signature trust policy misconfiguration blocks valid artifacts.  
Mitigation: staged trust policy rollout with policy simulation mode.
4. Risk: Scope model drift across teams.  
Mitigation: central permission catalog and automated policy linting.

## 6. Operational Runbook Summary

1. Incident: Signature verification spike.
- Check trust root rotation state.
- Validate CI signing chain.
- Toggle high-assurance recheck mode.
2. Incident: Index lag threshold breach.
- Inspect event consumer backlog.
- Trigger reconciliation job.
- Scale consumers temporarily.
3. Incident: Elevated 403 responses.
- Verify JWT issuer/audience config.
- Inspect recent policy changes.
- Roll back policy bundle if needed.

## 7. RACI (Simplified)

1. Validator and contracts: Backend (R), Security (C), Platform (C), QA (A for test gate).
2. Ingest and signing: Backend (R), Security (A), Platform (C).
3. API and search: Backend (R/A), QA (C), Platform (C).
4. Deployment and telemetry: Platform (R/A), Backend (C), Security (C).
5. Production rollout: Platform (R), Backend (R), Security (C), QA (C), Product owner (A).

## 8. Final Readiness Checklist

1. All critical test suites green.
2. SLO dashboards and alerts active.
3. Security approval documented.
4. Rollback playbook validated.
5. On-call handoff complete.
6. Launch decision recorded with milestone evidence.
