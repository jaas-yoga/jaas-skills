# JAAS Skills: Complete Guide

## Overview

The JAAS Skills registry contains 4 core example skills (documented in
full below and in [EXAMPLE_SKILLS.md](EXAMPLE_SKILLS.md)) plus a growing
category-organized catalog under `examples/skills/<category>/` — see
"Example Skills" in the reference list further down for the running total.
Each skill requires a specific set of files with defined structures.

---

## 🎯 Quick Reference: All Example Skills

| Skill | Purpose | Category | Complexity | Key Features |
|-------|---------|----------|-----------|--------------|
| **Git Fundamentals** | Local version control operations | developer-tools | ⭐⭐ | Branching, commits, merges, rebases, stashing, cherry-picking, tagging, recovery |
| **GitHub Workflow Assistant** | GitHub hosted platform operations | developer-tools | ⭐⭐⭐ | PRs, issues, CI status via `gh` CLI |
| **Personal Notes** | Freeform scratchpad notes | productivity | ⭐ | Store/retrieve notes by topic |
| **Team Runbook** | On-call incident management | operations | ⭐⭐ | Incident acknowledgment, severity assessment, mitigation, postmortem |

Plus 8 more `developer-tools` skills under `examples/skills/developer-tools/`:
code-review-checklist, dependency-upgrade-assistant, debugging-methodology,
api-client-generator, database-migration-safety, monorepo-navigation,
ci-failure-triage (depends on GitHub Workflow Assistant), and
refactoring-safety-net.

---

## 📁 Skill Package Structure

Every skill **must have**:

```
my-skill/
├── manifest.yaml          # ✅ REQUIRED - metadata & identity
├── SKILL.md              # ✅ REQUIRED - entrypoint (prompt/instructions)
├── schema.json           # ✅ REQUIRED - input/output contract
├── permissions.yaml      # ⚠️  Optional (defaults to empty list [])
├── dependencies.yaml     # ⚠️  Optional (defaults to empty list [])
├── README.md             # 📖 Optional - human-readable docs
├── examples/             # 📂 Optional - usage examples
└── tests/                # 📂 Optional - test cases
```

---

## 📋 Required Fields by File

### 1. **manifest.yaml** (REQUIRED)

The skill's identity card. Must contain:

```yaml
apiVersion: v1                          # Always "v1"
id: jaas.devtools.git-fundamentals      # Unique ID: vendor.domain.capability
name: Git Fundamentals                  # Human-readable name
version: 1.2.0                          # Semantic versioning (MAJOR.MINOR.PATCH)
description: >-                         # 1-2 sentence summary
  Core version-control operations...
owner:
  team: jaas-registry-examples          # ✅ REQUIRED
  contact: examples@jaas-registry.local # ⚠️  Optional but recommended
entrypoint: SKILL.md                    # Path to main instructions
category: developer-tools               # Free-form category string
tags:                                   # ⚠️  Optional list of searchable tags
  - git
  - version-control
  - developer-tools
runtime:                                # ✅ REQUIRED - compatibility declarations
  - family: prompt                      # Runtime family (e.g., "prompt")
    versionRange: ">=1.0.0,<2.0.0"      # SemVer constraint
```

**Required fields**: `apiVersion`, `id`, `name`, `version`, `description`, `owner`, `entrypoint`, `category`, `runtime`

**ID Format Rules**:
- Pattern: `vendor.domain.capability` (e.g., `jaas.devtools.git-fundamentals`)
- No spaces, lowercase preferred
- Must be globally unique in the registry

**Version Format**: Strict SemVer (`MAJOR.MINOR.PATCH`)
- `1.0.0` ✅
- `v1.0.0` ❌ (no 'v' prefix)
- `1.0` ❌ (missing patch)

---

### 2. **SKILL.md** (REQUIRED - named in `entrypoint`)

The skill's executable instructions. Must include:

```yaml
---
name: git-fundamentals                                    # Must match manifest
description: Core version-control operations...          # Concise 1-liner
---

# Git Fundamentals

## Instructions
1. Look before acting...
2. Branching...
[... detailed numbered instructions ...]

## Key Rules & Guardrails
- Never force-push without confirmation
- Always verify git status first
- Report back what was done
```

**Best Practices**:
- Start with a summary of the skill's purpose
- Use numbered steps for sequential actions
- Include safety guardrails and warnings
- Explain the "why" behind complex procedures
- Mention dependencies on other skills (e.g., "Builds on `git-fundamentals`")

---

### 3. **schema.json** (REQUIRED)

Defines the input/output contract using JSON Schema:

```json
{
  "inputs": {
    "type": "object",
    "properties": {
      "task": {
        "type": "string",
        "description": "What to do, in plain language, e.g. 'rebase this branch onto main'."
      }
    },
    "required": ["task"]                 # Fields the caller MUST provide
  },
  "outputs": {
    "type": "object",
    "properties": {
      "summary": {
        "type": "string",
        "description": "What the agent did, in one or two sentences."
      },
      "commandsRun": {
        "type": "array",
        "items": { "type": "string" },
        "description": "The exact commands executed, in order."
      },
      "warnings": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Anything risky that was flagged before acting."
      }
    },
    "required": ["summary"]              # Fields the agent MUST return
  }
}
```

**Schema Rules**:
- Must have both `inputs` and `outputs` objects
- Each must be a valid JSON Schema document
- `required` lists which fields are mandatory
- All properties should include `description`
- Supports nested objects and arrays

**Minimal Valid Schema**:
```json
{
  "inputs": { "type": "object", "properties": {} },
  "outputs": { "type": "object", "properties": {} }
}
```

---

### 4. **permissions.yaml** (OPTIONAL - defaults to `[]`)

A flat list of permission scopes the skill requests:

```yaml
- fs:read
- fs:write
```

Or if no permissions needed:
```yaml
[]
```

**Permission Categories** (examples from design):
- `fs:read` / `fs:write` — File system access
- `net:http` — HTTP/REST access
- `shell:exec` — Shell command execution
- `db:query` — Database queries
- Custom scopes per deployment

---

### 5. **dependencies.yaml** (OPTIONAL - defaults to `[]`)

List of other skills this skill depends on:

```yaml
[]  # No dependencies (most common)
```

Or with dependencies:
```yaml
- id: jaas.devtools.git-fundamentals
  versionConstraint: ">=1.0.0,<2.0.0"
```

**Dependency Rules**:
- Every dependency must be resolvable at publish time
- Circular dependencies are rejected
- Version constraints use SemVer syntax (`>=1.0.0,<2.0.0`)
- At publish time, the registry verifies all dependencies exist

---

## 🔄 Skill Lifecycles & Key Behaviors

### Publishing

When a skill is published, the registry:

1. **Validates manifest.yaml** structure
2. **Resolves all dependencies** (must exist in registry)
3. **Detects circular dependencies** (rejected)
4. **Validates schema.json** (JSON Schema compliance)
5. **Scans for content issues** via guardrails:
   - Level 1 (Baseline): Secrets, package size limits, sensitive filenames → **BLOCK if found**
   - Level 2 (Standard): Copyleft licenses, dangerous code patterns → **WARN** (can publish)
   - Level 3 (Advanced): Binary artifacts, typosquat heuristics → **WARN** (opt-in)
   - Level 4 (Regulatory): Excessive permissions, insecure URLs → **WARN** (opt-in)
6. **Computes digest** (SHA256 of artifact)
7. **Signs** (if signing key configured)
8. **Stores artifact** (immutable by content hash)

### Version Conflict

If you try to publish `jaas.devtools.git-fundamentals:1.2.0` twice:
- **First publish**: ✅ Succeeds
- **Second publish**: ❌ Returns `409 Conflict`

**Solution**: Increment patch version (`1.2.1`) or use a different skill ID.

---

## ⚠️ Corner Cases & Edge Cases

### 1. **Empty/Minimal Skill**

A skill can have only `manifest.yaml` + `SKILL.md`:

```
minimal-skill/
├── manifest.yaml          # ✅ Identity
└── SKILL.md              # ✅ Instructions
```

Registry will auto-generate:
- `schema.json` → `{ "inputs": {}, "outputs": {} }`
- `permissions.yaml` → `[]`
- `dependencies.yaml` → `[]`

### 2. **Entrypoint File Missing**

If `SKILL.md` doesn't exist but `manifest.yaml` lists it as entrypoint:

- ❌ **Validation fails** during publish
- **Fix**: Create the file or change `entrypoint` to an existing file

### 3. **Cyclic Dependencies**

If Skill A depends on B, B depends on C, C depends on A:

- ❌ **Publish rejected** with "circular dependency" error
- **Fix**: Restructure dependencies or merge skills

### 4. **Unresolvable Dependency**

If `dependencies.yaml` references `jaas.missing.skill:1.0.0` and it doesn't exist:

- ❌ **Publish rejected** at dependency resolution phase
- **Fix**: Create the dependency first, or remove it

### 5. **Version Constraint Mismatch**

Skill A depends on `git-fundamentals:>=1.0.0,<2.0.0`  
But you publish `git-fundamentals:2.0.0`:

- If A tries to resolve later: ❌ **Resolution fails** (no matching version)
- **Fix**: Update A's constraint to `>=1.0.0,<3.0.0` or publish a compatible version of A

### 6. **Schema Validation Issues**

Invalid `schema.json`:
```json
{ "invalid": "schema" }  // Missing required "inputs"/"outputs"
```

- ❌ **Publish fails** with schema validation error
- **Fix**: Ensure `inputs` and `outputs` are present as top-level keys

### 7. **Guardrail Violations**

**BLOCK scenarios** (prevent publish):
- Hardcoded AWS keys, private tokens (secret scanning)
- Skill > 50MB (size limit)
- Files named `.env`, `config.secrets.json` (sensitive patterns)

**WARN scenarios** (allow but flag):
- GPL/AGPL licensed dependencies (copyleft check)
- `eval()`, `exec()`, regex DoS patterns (code safety)
- Overly broad filesystem permissions (permission scope)

### 8. **Runtime Compatibility**

Skill declares:
```yaml
runtime:
  - family: prompt
    versionRange: ">=1.0.0,<2.0.0"
```

Caller (e.g., LangGraph SDK v3) requests skills for `prompt:3.0.0`:
- ❌ **Not returned** in search results (constraint mismatch)
- Caller must either:
  - Lower its runtime requirement, or
  - Skill maintainer must publish new version with updated runtime constraint

### 9. **Visibility & Permissions**

A skill is `visibility: private` (only visible to its owner tenant):

- Anonymous caller: ❌ **Cannot see it** in search results
- Owner tenant user: ✅ **Can see and use it**
- Another tenant: ❌ **Cannot access** (401 or 404)

### 10. **Duplicate Publication in Different Tenants**

Tenant A publishes `my.skill:1.0.0`  
Tenant B publishes `my.skill:1.0.0`

- Both are **allowed** (different tenants, different namespaces)
- But they have **different skill IDs in the search index**:
  - Tenant A's visible as `my.skill:1.0.0` (to members of A)
  - Tenant B's visible as `my.skill:1.0.0` (to members of B)
  - Search filters by visibility/ownership to avoid confusion

### 11. **ID vs. Name Mismatch**

`manifest.yaml`:
```yaml
id: jaas.devtools.git
name: "Git Fundamentals"
```

`SKILL.md`:
```yaml
---
name: git-fundamentals
---
```

- ⚠️  **Accepted but inconsistent**
  - Manifest `id`/`name` are the authoritative identity
  - SKILL.md `name` is just for documentation (can differ)
  - Recommendation: Keep them consistent to avoid confusion

### 12. **Permission Scope Typos**

`permissions.yaml`:
```yaml
- fs:read
- fs:writte  # Typo!
```

- ⚠️  **No validation error** (permissions are free-form)
- Registry accepts it as a custom permission string
- **Fix**: Correct the typo before publishing, or the runtime may not grant the intended permission

### 13. **Category Doesn't Exist**

`manifest.yaml`:
```yaml
category: "nonexistent-category"
```

- ✅ **Allowed** (categories are free-form, not validated against a fixed list)
- Shows up in search filters
- **Note**: It won't match searches for common categories like `developer-tools`

### 14. **Tag with Spaces or Special Chars**

`manifest.yaml`:
```yaml
tags:
  - "best practices"  # Space
  - "c++"             # Plus sign
```

- ✅ **Allowed** (tags are free-form strings)
- Searchable by exact match
- Recommendation: Use kebab-case (`best-practices`, `cpp`) for consistency

### 15. **Very Large Payload**

A skill's archive (manifest + schema + permissions + entrypoint file) > 50MB:

- ❌ **Guardrail blocks** with "package-size-limit" violation
- Common causes:
  - Large example files in `/examples/`
  - Embedded PDFs, images, or test fixtures
- **Fix**: Move large assets outside the skill package, or reduce archive size

---

## 📊 Example Skills Comparison Matrix

| Aspect | Git Fundamentals | GitHub Workflow | Personal Notes | Team Runbook |
|--------|------------------|-----------------|----------------|--------------|
| **Inputs Required** | task (string) | task, repo (optional) | topic, note | incidentSummary, severity (optional) |
| **Outputs Required** | summary | summary | message | acknowledgment, assessment |
| **Dependencies** | None | `git-fundamentals` | None | None |
| **Permissions** | `fs:read`, `fs:write` | `fs:read`, `fs:write` (+ git/gh CLIs) | Deployment-specific | None (documentation) |
| **Complexity** | Medium | High | Low | Medium |
| **State** | File system | File system + GitHub | External store | None |
| **Safety Guardrails** | Require confirmation for destructive ops | Check CI status before declaring success | None | Structured checklist |

---

## ✅ Checklist Before Publishing

- [ ] `manifest.yaml` has all required fields (apiVersion, id, name, version, description, owner, entrypoint, category, runtime)
- [ ] `id` follows vendor.domain.capability pattern and is globally unique
- [ ] `version` is valid SemVer (e.g., `1.2.3`)
- [ ] `entrypoint` file exists (e.g., `SKILL.md`)
- [ ] `SKILL.md` front matter `name` matches manifest (or at least makes sense)
- [ ] `schema.json` has `inputs` and `outputs` top-level keys
- [ ] All dependency IDs exist in the registry
- [ ] No circular dependencies
- [ ] No hardcoded secrets (API keys, tokens, passwords)
- [ ] Archive size < 50MB
- [ ] No GPL/AGPL licenses (unless acceptable for your use case)
- [ ] No dangerous patterns (`eval`, `exec`, overly permissive regex)
- [ ] Permission scopes are typo-free and meaningful
- [ ] `SKILL.md` includes clear instructions and guardrails
- [ ] Dependency versions use valid SemVer constraints

---

## 🔗 Cross-References

- **Full Manifest Schema**: `schemas/manifest.schema.json`
- **Full Schema.json Schema**: `schemas/schema.schema.json`
- **Full Permissions Schema**: `schemas/permissions.schema.json`
- **Design Document**: `design.md` (sections 4.1–4.5 cover publishing, guardrails, and edge cases)
- **CLI Validation**: `uv run jaasctl validate <skill-dir>`
- **Example Skills**: `examples/skills/{github/git-fundamentals,github/github-workflow-assistant,personal-notes,team-runbook}/` plus `examples/skills/developer-tools/{code-review-checklist,dependency-upgrade-assistant,debugging-methodology,api-client-generator,database-migration-safety,monorepo-navigation,ci-failure-triage,refactoring-safety-net}/`

---

## 🚀 Next Steps

To create a new skill:

1. **Copy an example**:
   ```bash
   cp -r examples/skills/github/git-fundamentals examples/skills/my-new-skill
   ```

2. **Edit the 5 files**:
   - `manifest.yaml` — Update id, name, version, description, owner
   - `SKILL.md` — Write your instructions
   - `schema.json` — Define inputs/outputs
   - `permissions.yaml` — List any scopes needed
   - `dependencies.yaml` — Link dependencies (if any)

3. **Validate locally**:
   ```bash
   uv run jaasctl validate examples/skills/my-new-skill
   ```

4. **Publish** (via CLI or web UI)

---

**Last Updated**: 2026-09-03  
**Version**: 1.0.0
