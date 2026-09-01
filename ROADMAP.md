# JaaS Skills Roadmap

Prepared September 2026. Covers all three repos: `jaas-ui`, `jaas-skills` (the
`jaas-registry` backend), and `jaas-guardrails`.

A skill-registry market that barely existed a year ago now has an open
interoperability standard, a governance wave forming behind it, and a quality
crisis in its biggest public catalogs. This document lays out what that means
for JaaS Skills specifically, and what to build first — grounded in a direct
audit of all three repos, not guesses.

## Contents

1. [Where the ground is moving](#1-where-the-ground-is-moving) — industry context
2. [Where JaaS Skills stands today](#2-where-jaas-skills-stands-today) — audit findings
3. [The roadmap](#3-the-roadmap) — four phases
4. [Sources](#4-sources)

---

## 1. Where the ground is moving

Five things changed in the agent-skills space in the last nine months that
matter directly to this product's roadmap — not general AI news, specifically
the forces bearing on a skill registry.

### Agent Skills became a real open standard, fast

Anthropic published the Agent Skills format as an open standard at
[agentskills.io](https://github.com/agentskills/agentskills) in December
2025. A skill is a folder with a `SKILL.md` file plus bundled
scripts/resources, using progressive disclosure so only ~30–50 tokens load
until a skill actually triggers. Within 48 hours, OpenAI and Microsoft had
integrated support; by mid-2026 roughly 40 tools — Claude Code, Cursor,
GitHub Copilot, VS Code, Gemini CLI, OpenAI Codex among them — read the same
unmodified files.

### The big public catalogs have a quality crisis

SkillsBench scored 47,150 public skills scraped mostly from GitHub at an
average of 6.2 out of 12 on a quality rubric. Curated skills, by contrast,
raised agent task pass rates by 16.2 percentage points over uncurated ones —
a large, measured effect, not a vague claim.

### Unsigned skills are now an active attack surface

Most public skill registries carry no cryptographic signing and little
vetting — anyone with a GitHub account can publish, and agents execute
whatever's inside. Researchers have already documented "payload-less" skill
attacks, and in May 2026 attackers compromised 84 malicious package versions
across 42 npm packages in a six-minute window — including, in one case, a
package that carried valid-looking SLSA provenance. The industry is
converging on treating skill integrity the way package registries treat
build provenance: keyless signing bound to an OIDC identity (Sigstore), not
a private key sitting in a repo.

### Compliance obligations arrive on a real clock

OWASP published a first formal Top 10 for Agentic Applications in December
2025. The EU AI Act's high-risk obligations take effect in August 2026;
Colorado's AI Act becomes enforceable in June 2026. The Cloud Security
Alliance's Agentic Trust Framework (public draft, April 2026) asks for
identity, behavior, data governance, segmentation, and incident-response
controls — and specifically recommends a registry record per agent identity:
owning team, business purpose, systems accessed, privilege scope, review
date.

### Distribution is consolidating around a few marketplaces

Five marketplaces now matter for reach: Anthropic's own curated directory,
Vercel's `skills.sh`, OpenAI Codex plugins, Cline, and the MCP-server
ecosystem (Smithery, LobeHub). MCP itself — a different layer, for
tool/server access rather than packaged behavior — passed 100,000 indexed
servers across registries and was donated to the Linux Foundation's Agentic
AI Foundation in December 2025, making it vendor-neutral. Registry
fragmentation and trust are the two problems every writeup names as
unsolved.

---

## 2. Where JaaS Skills stands today

The backend (`jaas-registry`) is the mature core: 628 test functions, a real
4-level/19-rule guardrails engine, git-native publishing. The gaps below are
specific, pulled from a direct audit of all three repos.

### Built and real

- **Guardrails engine** — 19 offline, deterministic rules across 4 levels
  (baseline block → opt-in regulatory), RE2-based to block ReDoS, per-tenant
  custom rules, point-in-time publish certification.
- **Git-native publishing** — OAuth App per tenant, branch/PR/tag
  automation, CI release via OIDC or PAT, commit-gated saves to avoid noisy
  history.
- **Sharing & visibility** — public/private plus user- or tenant-scoped
  grants, 404-not-403 to avoid leaking existence of private skills, full
  permission-matrix test coverage.

### Designed but only a stand-in today

- **Artifact signing** — signs with an in-process RSA keypair generated at
  runtime. The design doc always specified Cosign/Sigstore; the code's own
  docstring calls this a placeholder.
- **Object storage** — local filesystem only, behind a backend-swappable
  interface built for S3/MinIO that nothing implements yet.

### Missing outright

- **Frontend test coverage** — no component tests, no E2E suite, no `"test"`
  script at all. The Monaco-based authoring workspace — the core of the
  product — has no automated safety net.
- **SKILL.md compatibility** — no import or export path to the open
  standard. Every skill published here today is portable to none of the
  ~40 tools that already read that format.
- **Consumption CLI** — `jaasctl` can publish and validate but has no
  `search`, `pull`, or `install` — every framework integration today is
  hand-rolled REST calls.

---

## 3. The roadmap

Four horizons. Each item names what it addresses and why it's sequenced
where it is — mostly a mix of "closes a real security gap," "the code
already half-exists," and "the market just made this table stakes."

### Phase 1 — Harden the foundation (0–4 weeks)

*Close the risks that exist today before adding anything new on top of them.*

**1.1 Frontend test suite (Playwright + component tests)** · `jaas-ui` · risk: highest
The draft/publish workspace is the product's core interaction and today has
**zero** automated coverage — a regression currently ships silently unless
someone catches it by hand.

**1.2 Real Sigstore/Cosign signing** · `jaas-registry` · security
Replaces the in-process RSA dev stand-in with keyless, OIDC-bound signing —
exactly what the design doc always specified, and directly answers the
industry's most active current attack pattern on unsigned skill packages.

**1.3 Version deprecation / "yank" mechanism** · `jaas-registry` · security
Publish is immutable by design, which is correct — but nothing today lets a
maintainer flag a version as insecure after the fact. Certification is
point-in-time only; this closes the loop guardrails opens.

### Phase 2 — Interoperate with the standard (1–3 months)

*Stop being an island. This is the single highest-leverage horizon.*

**2.1 SKILL.md / agentskills.io import & export** · `jaas-registry` + `jaas-ui` · highest leverage
The open standard now runs across ~40 tools nine months after publication.
Supporting it turns every skill in this registry from "usable in one place"
into "usable in Claude Code, Cursor, Copilot, VS Code, Gemini CLI, and
Codex" with no extra authoring work for publishers.

**2.2 `jaasctl search / pull / install`** · `jaas-registry` CLI
`jaasctl` only publishes today. A registry a framework can't consume from
the command line isn't yet shaped like a package manager.

**2.3 Object storage backend (S3/MinIO)** · `jaas-registry` infra
The interface was already built swappable; only the local-filesystem
implementation exists. This is the item standing between "prototype" and
"deployable at real scale."

**2.4 Wire up the existing event-bus index sync** · `jaas-registry` · quick win
The multi-replica sync machinery is already written — it's simply never
called from `create_app()`. Cheapest item on this entire roadmap.

### Phase 3 — Compete on trust (3–6 months)

*The public catalogs won on volume; win on curation and governance instead.*

**3.1 Usage-based discovery ranking** · `jaas-registry` · differentiation
Search ranking today is static token-matching with no usage signal at all.
Meanwhile curated results measurably beat uncurated ones by 16.2 points in
agent task success — surface that curation signal instead of leaving
ranking blind to it.

**3.2 Grant-lookup caching for sharing at scale** · `jaas-registry` · scale
Already flagged in the UI plan's own risk register as unmitigated. Fine at
prototype scale; a real risk the moment tenant/grant counts grow.

**3.3 Governance surface: audit export, identity fields, EU AI Act mapping** · `jaas-registry` · enterprise
EU AI Act high-risk obligations take effect August 2026. Enterprise buyers
are already being asked by regulators for exactly what the Agentic Trust
Framework specifies — owning team, business purpose, systems accessed,
review date, per registry entry. This is a sales-enablement item as much as
an engineering one.

**3.4 Ship the missing UI surfaces** · `jaas-ui` · debt
The backend already supports a published-file viewer, a cross-tenant
sharing audit page, and share/validation notifications — none have
frontend. Pure debt-paydown, no new backend work required.

### Phase 4 — Scale the ecosystem (6–12 months)

*Grow past a single registry, a single integration path, and a free tier.*

**4.1 Framework SDKs (LangGraph, CrewAI, AutoGen)** · new · ecosystem
The original design already draws these frameworks as consumers; today
integrating with any of them means hand-writing REST calls against the
registry API.

**4.2 Billing, plans, and quota model** · `jaas-registry` · commercial
No rate limiting or billing code exists anywhere in the codebase today —
reasonable for a prototype, a hard requirement the moment this needs to be
a commercial product with tiers.

**4.3 Multi-registry federation** · `jaas-registry` · scale
Every current design doc assumes exactly one registry instance. Mirroring a
public upstream, or resolving a dependency that lives in a different
registry, doesn't exist as a concept yet.

**4.4 Load-test to the stated 50,000-package target** · `jaas-registry` · validation
The design doc states a 50,000-package/12-month capacity target explicitly;
current performance tests only validate a 2,000-skill corpus.

**4.5 Abuse workflow & re-certification sweep** · `jaas-registry` · trust
Certification is point-in-time by design — a version certified clean under
an older, laxer guardrails catalog is never retroactively re-flagged when
the catalog gains new rules. Needs a deliberate re-scan path, plus a
report/takedown flow for public skills that has no equivalent today.

---

## 4. Sources

- [Agentman — The Agent Skills Ecosystem in 2026](https://agentman.ai/blog/agent-skills-ecosystem-report-2026)
- [agentskills/agentskills — spec repo](https://github.com/agentskills/agentskills)
- [Nimble — Top Anthropic Claude Agent Skills 2026](https://www.nimbleway.com/blog/anthropic-claude-agent-skills)
- [The Agent Skills Open Standard — portable SKILL.md files](https://codex.danielvaughan.com/2026/05/05/agent-skills-open-standard-portable-skills-codex-cli-cross-agent/)
- [MCP Institute — State of MCP 2026](https://mcp.institute/research/state-of-mcp-2026)
- [WorkOS — Everything your team needs to know about MCP in 2026](https://workos.com/blog/everything-your-team-needs-to-know-about-mcp-in-2026)
- [HiddenLayer — Malicious Skills in Agentic AI](https://www.hiddenlayer.com/research/the-next-ai-supply-chain-risk-malicious-skills-in-agentic-ai)
- [Red Hat — Supply-chain provenance for AI agent identity](https://next.redhat.com/2026/08/07/supply-chain-provenance-for-ai-agent-identity/)
- [Cloudsmith — 2026 Guide to Software Supply Chain Security](https://cloudsmith.com/blog/the-2026-guide-to-software-supply-chain-security-from-static-sboms-to-agentic-governance)
- [FutureAGI — AI Agent Compliance and Governance in 2026](https://futureagi.com/blog/ai-agent-compliance-governance-2026)
- [awesome-ai-agent-governance](https://github.com/systempromptio/awesome-ai-agent-governance)
- [Microsoft — Agent Governance Toolkit](https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit/)
- [Totalum — Agent Skills Marketplace Comparison 2026](https://www.totalum.app/blog/agent-skills-marketplaces-2026)
- [Agensi — AI Agent Marketplace Landscape 2026](https://www.agensi.io/learn/ai-agent-marketplace-landscape-2026)

---

*Also published as an [artifact](https://claude.ai/code/artifact/51fcbef3-d732-48ad-b00a-0fc1077cbdd5) with visual formatting.*
