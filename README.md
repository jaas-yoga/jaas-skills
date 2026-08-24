# JaaS Skills

A stateless, GitOps-driven registry that distributes immutable AI-agent skill packages.
See [design.md](design.md) for architecture and [implementation-plan.md](implementation-plan.md)
for the phased delivery plan this codebase follows.

This implementation targets a **local-first prototype**: a filesystem-backed object store
stands in for S3/OCI, and an in-process event queue stands in for a real message bus, both
behind the same interfaces described in the design so a production backend can be swapped in
later without touching calling code.

This repo is the backend only. The web UI (Google sign-in, visibility/
sharing, an authoring workspace, tenant management) lives in a separate,
sibling repo — **[jaas_ui](../jaas_ui)** — with no shared code, only
HTTP. See [ui-design.md](ui-design.md) and
[ui-implementation-plan.md](ui-implementation-plan.md) for the UI's design
and phased plan; those cross-cutting docs stay here because they also
describe the backend changes (`authn/`, `sharing/`, `drafts/`) built to
support it. A third sibling repo,
[jaas-guardrails-catalog](https://github.com/balakrishna-maduru/jaas-guardrails-catalog),
provides the publish-time content-safety scanning service (design.md §4.5)
— also reached only over HTTP, never imported.

## Running everything

```bash
./run.sh          # starts the API (http://127.0.0.1:8027) and, if a sibling
                   # ../jaas_guardrail checkout exists, the guardrails
                   # service (http://127.0.0.1:8028)
./run.sh status
./run.sh stop
```

For the full stack including the web UI, run `../jaas_ui/run.sh` instead
— it starts this api, guardrails, and its own web process together (see
that repo's README).

To validate a real Google sign-in flow against this API standalone (no web
UI), start it with `JAAS_GOOGLE_CLIENT_ID` set to the OAuth client the
caller uses.

## Development

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
```

## CLI

```bash
uv run jaasctl --help
```

### Git-native release (CI)

A skill can also live in its own git repo and release via CI on a tag
push, instead of (or alongside) the web UI's drafts workflow — see
[examples/ci/github-actions-release.yml](examples/ci/github-actions-release.yml)
for a full reference workflow. `jaasctl validate` (used in a PR check)
is unchanged; two new commands are CI-facing HTTP clients of this API,
not local/direct like the rest of the CLI:

```bash
# Requires a tenant admin to have registered this skill id + repo first —
# POST /api/v1/tenants/{tenantId}/repo-links.
uv run jaasctl release . --tag v1.2.3 \
  --oidc-token "$OIDC_TOKEN" --api-url https://registry.example.com
  # or: --token "$JAAS_PAT" --repo-url https://github.com/acme/my-skill --release-branch main

# Sync local rule YAML files to a tenant's custom guardrail rule library.
uv run jaasctl guardrails push ./rules --tenant-id tnt_acme --token "$JAAS_PAT"

# Dry-run validate one rule file against the guardrails service directly
# (no tenant/auth needed).
uv run jaasctl guardrails validate ./rules/no-todo.yaml
```

A repo link can optionally restrict which branches may release
(`releaseBranches`, set when registering the link or via
`PUT /api/v1/tenants/{tenantId}/repo-links/{skillId}`). Empty (the
default) means no restriction. Once set, the OIDC path proves the branch
via the workflow job's `environment:` claim (see the `release-staging`
job in the reference workflow) — a git tag isn't reliably "on" one
branch, so this is checked against GitHub's own environment deployment
policy rather than something this platform tries to derive itself. The
PAT path instead takes `--release-branch`/`releaseBranch` at face value,
a weaker, unverified guarantee consistent with PAT being the fallback
auth path throughout.
