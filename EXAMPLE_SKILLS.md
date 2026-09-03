# Example Skills Templates for JAAS

This document walks through 4 core example skills in full detail (complete
file structure, manifest excerpts, schema) as templates for your own
skills. The registry's example catalog is growing beyond these 4 into a
full library organized by category under `examples/skills/<category>/`
(see [SKILLS_GUIDE.md](SKILLS_GUIDE.md) §"Example Skills" for the running
list) — new additions get a one-line entry in the relevant category table
below rather than a full walkthrough section, to keep this doc scannable.

---

## 📋 Quick Selection Guide

| Skill | Best For | Complexity | Files | Copy Command |
|-------|----------|-----------|-------|--------------|
| **Git Fundamentals** | Version control, branching, commits | ⭐⭐ Medium | 6 | `cp -r examples/skills/github/git-fundamentals examples/skills/my-git-skill` |
| **GitHub Workflow Assistant** | GitHub PRs, issues, CI status | ⭐⭐⭐ High | 6 | `cp -r examples/skills/github/github-workflow-assistant examples/skills/my-github-skill` |
| **Personal Notes** | Simple CRUD, stateless API | ⭐ Low | 5 | `cp -r examples/skills/personal-notes examples/skills/my-notes-skill` |
| **Team Runbook** | Checklists, structured workflows | ⭐⭐ Medium | 5 | `cp -r examples/skills/team-runbook examples/skills/my-runbook-skill` |

### Developer Tools (additional)

The rest of the `developer-tools` category — same 6-file layout as Git
Fundamentals above, no separate walkthrough section:

| Skill | Best For | Copy Command |
|-------|----------|--------------|
| **Code Review Checklist** | Reviewing a diff/PR for correctness, security, scope | `cp -r examples/skills/developer-tools/code-review-checklist examples/skills/my-skill` |
| **Dependency Upgrade Assistant** | Safely bumping a package version | `cp -r examples/skills/developer-tools/dependency-upgrade-assistant examples/skills/my-skill` |
| **Debugging Methodology** | Root-causing a reported bug | `cp -r examples/skills/developer-tools/debugging-methodology examples/skills/my-skill` |
| **API Client Generator** | Generating a typed client from OpenAPI/GraphQL | `cp -r examples/skills/developer-tools/api-client-generator examples/skills/my-skill` |
| **Database Migration Safety** | Writing/reviewing a safe schema migration | `cp -r examples/skills/developer-tools/database-migration-safety examples/skills/my-skill` |
| **Monorepo Navigation** | Scoping a change to the right package(s) | `cp -r examples/skills/developer-tools/monorepo-navigation examples/skills/my-skill` |
| **CI Failure Triage** | Regression vs. flake/infra triage (depends on GitHub Workflow Assistant) | `cp -r examples/skills/developer-tools/ci-failure-triage examples/skills/my-skill` |
| **Refactoring Safety Net** | Behavior-preserving refactors with a test baseline | `cp -r examples/skills/developer-tools/refactoring-safety-net examples/skills/my-skill` |

---

## 🎯 Skill #1: Git Fundamentals

**Best For**: Version control operations, teaching git concepts, CI/CD workflows

### Directory Structure
```
examples/skills/github/git-fundamentals/
├── manifest.yaml
├── SKILL.md
├── schema.json
├── permissions.yaml
├── dependencies.yaml
├── README.md
└── [optional: examples/, tests/]
```

### File Sizes & Complexity
- `manifest.yaml` — ~10 lines (simple)
- `SKILL.md` — ~50 lines (detailed instructions)
- `schema.json` — ~30 lines (single input field)
- `permissions.yaml` — 2 lines (minimal)
- `dependencies.yaml` — Empty array

### Key Characteristics
✅ **Good starter template because**:
- Minimal dependencies (none!)
- Simple input/output contract
- Clear, numbered instruction steps
- Real-world use case
- No complex async or stateful behavior

### manifest.yaml Excerpt
```yaml
apiVersion: v1
id: jaas.devtools.git-fundamentals
name: Git Fundamentals
version: 1.2.0
category: developer-tools
entrypoint: SKILL.md
owner:
  team: jaas-registry-examples
  contact: examples@jaas-registry.local
runtime:
  - family: prompt
    versionRange: ">=1.0.0,<2.0.0"
```

### schema.json (Inputs/Outputs)
```json
{
  "inputs": {
    "type": "object",
    "properties": {
      "task": {
        "type": "string",
        "description": "What to do in plain language"
      }
    },
    "required": ["task"]
  },
  "outputs": {
    "type": "object",
    "properties": {
      "summary": { "type": "string" },
      "commandsRun": { "type": "array", "items": { "type": "string" } },
      "warnings": { "type": "array", "items": { "type": "string" } }
    },
    "required": ["summary"]
  }
}
```

### When to Copy This
- ✅ Building CLT/tool-based skills
- ✅ Skills that guide users through sequences
- ✅ Low-state operations (read-only or file-based)
- ✅ First-time skill authors

---

## 🎯 Skill #2: GitHub Workflow Assistant

**Best For**: GitHub API integration, pull requests, issues, CI/CD pipelines

### Directory Structure
```
examples/skills/github/github-workflow-assistant/
├── manifest.yaml
├── SKILL.md
├── schema.json
├── permissions.yaml
├── dependencies.yaml
├── README.md
└── [optional: examples/, tests/]
```

### File Sizes & Complexity
- `manifest.yaml` — ~15 lines (references dependency)
- `SKILL.md` — ~60 lines (detailed GitHub workflow)
- `schema.json` — ~35 lines (task + optional repo)
- `permissions.yaml` — 2 lines (fs access)
- `dependencies.yaml` — 3 lines (git-fundamentals)

### Key Characteristics
✅ **Good template for**:
- External API integration (GitHub's `gh` CLI)
- Skill dependencies
- More complex workflows
- Multi-step procedures with verification
- Error handling & guard rails

### manifest.yaml Excerpt
```yaml
apiVersion: v1
id: jaas.devtools.github-assistant
name: GitHub Workflow Assistant
version: 1.3.0
category: developer-tools
entrypoint: SKILL.md
owner:
  team: jaas-registry-examples
  contact: examples@jaas-registry.local
runtime:
  - family: prompt
    versionRange: ">=1.0.0,<2.0.0"
```

### dependencies.yaml
```yaml
- id: jaas.devtools.git-fundamentals
  versionConstraint: ">=1.0.0,<2.0.0"
```

### schema.json (Inputs/Outputs)
```json
{
  "inputs": {
    "type": "object",
    "properties": {
      "task": {
        "type": "string",
        "description": "What to do, e.g. 'open a PR for this branch'"
      },
      "repo": {
        "type": "string",
        "description": "owner/repo slug (optional)"
      }
    },
    "required": ["task"]
  },
  "outputs": {
    "type": "object",
    "properties": {
      "summary": { "type": "string" },
      "actionsTaken": { "type": "array", "items": { "type": "string" } },
      "url": { "type": "string" }
    },
    "required": ["summary"]
  }
}
```

### When to Copy This
- ✅ External API integration (GitHub, GitLab, Slack, etc.)
- ✅ Skills that depend on other skills
- ✅ Complex multi-step workflows
- ✅ Verifying outcomes before reporting success

---

## 🎯 Skill #3: Personal Notes

**Best For**: Simple CRUD operations, stateless APIs, minimal complexity

### Directory Structure
```
examples/skills/personal-notes/
├── manifest.yaml
├── SKILL.md
├── schema.json
├── permissions.yaml
├── dependencies.yaml
└── README.md
```

### File Sizes & Complexity
- `manifest.yaml` — ~8 lines (simplest)
- `SKILL.md` — ~20 lines (concise instructions)
- `schema.json` — ~20 lines (simple contract)
- `permissions.yaml` — 0 lines (empty)
- `dependencies.yaml` — 0 lines (empty)

### Key Characteristics
✅ **Good template for**:
- Minimal skills (MVP approach)
- Stateless operations
- Lightweight contracts
- First-time learners
- Testing & prototyping

### manifest.yaml Excerpt
```yaml
apiVersion: v1
id: jaas.demo.personal-notes
name: Personal Notes
version: 1.0.0
category: productivity
entrypoint: SKILL.md
owner:
  team: jaas-registry-examples
  contact: examples@jaas-registry.local
runtime:
  - family: prompt
    versionRange: ">=1.0.0,<2.0.0"
```

### schema.json (Inputs/Outputs)
```json
{
  "inputs": {
    "type": "object",
    "properties": {
      "topic": { "type": "string", "description": "Topic name" },
      "note": { "type": "string", "description": "Note content" }
    },
    "required": ["topic"]
  },
  "outputs": {
    "type": "object",
    "properties": {
      "message": { "type": "string" },
      "noteCount": { "type": "integer" }
    },
    "required": ["message"]
  }
}
```

### When to Copy This
- ✅ Creating your first skill
- ✅ Rapid prototyping & MVPs
- ✅ Proof-of-concept skills
- ✅ Learning the structure
- ✅ Simple utilities (converters, formatters, etc.)

---

## 🎯 Skill #4: Team Runbook

**Best For**: Structured workflows, checklists, incident response, domain-specific processes

### Directory Structure
```
examples/skills/team-runbook/
├── manifest.yaml
├── SKILL.md
├── schema.json
├── permissions.yaml
├── dependencies.yaml
└── README.md
```

### File Sizes & Complexity
- `manifest.yaml` — ~10 lines (domain-specific)
- `SKILL.md` — ~40 lines (step-by-step checklist)
- `schema.json` — ~25 lines (structured inputs)
- `permissions.yaml` — 0 lines (empty)
- `dependencies.yaml` — 0 lines (empty)

### Key Characteristics
✅ **Good template for**:
- Checklists & structured workflows
- Domain-specific processes (incident response, onboarding, etc.)
- Procedural guidance
- Multi-step verification
- Business logic workflows

### manifest.yaml Excerpt
```yaml
apiVersion: v1
id: jaas.demo.team-runbook
name: Team Runbook
version: 1.0.0
category: operations
entrypoint: SKILL.md
owner:
  team: jaas-registry-examples
  contact: examples@jaas-registry.local
runtime:
  - family: prompt
    versionRange: ">=1.0.0,<2.0.0"
```

### schema.json (Inputs/Outputs)
```json
{
  "inputs": {
    "type": "object",
    "properties": {
      "incidentSummary": {
        "type": "string",
        "description": "Brief incident description"
      },
      "severity": {
        "type": "string",
        "enum": ["sev1", "sev2", "sev3"],
        "description": "Severity level (optional)"
      }
    },
    "required": ["incidentSummary"]
  },
  "outputs": {
    "type": "object",
    "properties": {
      "acknowledgment": { "type": "string" },
      "assessment": { "type": "string" },
      "postmortem": { "type": "string" }
    },
    "required": ["acknowledgment"]
  }
}
```

### When to Copy This
- ✅ Incident response workflows
- ✅ Onboarding processes
- ✅ Compliance checklists
- ✅ Team-specific procedures
- ✅ Multi-phase workflows with outputs at each stage

---

## 🚀 How to Get Started: Step-by-Step

### Step 1: Choose Your Template
```bash
# Pick based on your use case from the table above
# Examples:
# - Building a Slack integration? → Use github-workflow-assistant as template
# - Simple utility? → Use personal-notes as template
# - Complex workflow? → Use team-runbook as template
```

### Step 2: Copy the Template
```bash
cd /Users/balakrishnamaduru/Documents/projects/jaas-skills

# Copy example
cp -r examples/skills/github/git-fundamentals examples/skills/my-custom-skill
cd examples/skills/my-custom-skill
```

### Step 3: Edit the 5 Core Files

#### 3a. Update manifest.yaml
```yaml
apiVersion: v1
id: jaas.mycorp.my-custom-skill        # Change this!
name: My Custom Skill                  # Change this!
version: 1.0.0                         # Start at 1.0.0
description: >-                        # Your description
  What this skill does.
owner:
  team: my-team                        # Your team name
  contact: myemail@company.com         # Your email
entrypoint: SKILL.md
category: my-category                  # Pick a category
tags:
  - my-tag
  - another-tag
runtime:
  - family: prompt
    versionRange: ">=1.0.0,<2.0.0"
```

#### 3b. Write SKILL.md
```markdown
---
name: my-custom-skill
description: One-line description here
---

# My Custom Skill

## What This Does
Explain the purpose clearly.

## Instructions
1. First step...
2. Second step...
3. Third step...

## Safety Guardrails
- Rule 1
- Rule 2
```

#### 3c. Define schema.json
```json
{
  "inputs": {
    "type": "object",
    "properties": {
      "myInput": {
        "type": "string",
        "description": "What the user provides"
      }
    },
    "required": ["myInput"]
  },
  "outputs": {
    "type": "object",
    "properties": {
      "result": {
        "type": "string",
        "description": "What the skill returns"
      }
    },
    "required": ["result"]
  }
}
```

#### 3d. List permissions.yaml (if needed)
```yaml
- fs:read
- fs:write
- net:http
```

#### 3e. List dependencies.yaml (if needed)
```yaml
- id: jaas.devtools.git-fundamentals
  versionConstraint: ">=1.0.0,<2.0.0"
```

### Step 4: Validate Locally
```bash
cd examples/skills/my-custom-skill
uv run jaasctl validate .
```

### Step 5: Publish
```bash
# Via CLI
uv run jaasctl release examples/skills/my-custom-skill \
  --tag v1.0.0 \
  --api-url http://localhost:8027

# Or via web UI at http://localhost:3000
```

---

## 📊 Template Comparison Matrix

| Aspect | Git Fundamentals | GitHub Assistant | Personal Notes | Team Runbook |
|--------|------------------|------------------|----------------|--------------|
| **Lines of Code** | ~50 SKILL.md | ~60 SKILL.md | ~20 SKILL.md | ~40 SKILL.md |
| **Dependencies** | 0 | 1 | 0 | 0 |
| **Permissions** | 2 | 2 | 0 | 0 |
| **Input Fields** | 1 (task) | 2 (task, repo) | 2 (topic, note) | 2 (incident, severity) |
| **Output Fields** | 3 | 3 | 2 | 3 |
| **Schema Complexity** | Simple | Medium | Simple | Medium |
| **External APIs** | ❌ | ✅ (GitHub/gh CLI) | ❌ | ❌ |
| **Guard Rails** | ✅✅✅ (many) | ✅✅ (some) | ❌ (none) | ✅ (procedural) |
| **State Management** | File-based | File-based | Deployment-specific | None |
| **Best For Beginners** | ✅ (No deps) | ⚠️ (Has deps) | ✅✅ (Simplest) | ✅ (Clear steps) |

---

## 🎓 Learning Path

### Path 1: Minimal Learner
1. Start with **Personal Notes** (5 files, ~10 lines each)
2. Add outputs to **Git Fundamentals** (understand commands)
3. Add dependencies to **GitHub Assistant** (understand composition)

### Path 2: Real-World Builder
1. Start with **GitHub Assistant** (learn from real example)
2. Adapt for **Slack / Discord / Jira** (change the API, keep structure)
3. Add multiple skill dependencies (understand versioning)

### Path 3: Domain-Specific
1. Start with **Team Runbook** (learn structured workflows)
2. Customize for your domain (incident response → security audit → compliance)
3. Add custom input validation in schema.json

---

## 🔍 Where to Find Example Files

All example skills are located at:
```
/Users/balakrishnamaduru/Documents/projects/jaas-skills/examples/skills/
```

Individual files:
```
examples/skills/
├── github/
│   ├── git-fundamentals/
│   │   ├── manifest.yaml
│   │   ├── SKILL.md
│   │   ├── schema.json
│   │   ├── permissions.yaml
│   │   ├── dependencies.yaml
│   │   └── README.md
│   └── github-workflow-assistant/
│       ├── manifest.yaml
│       ├── SKILL.md
│       ├── schema.json
│       ├── permissions.yaml
│       ├── dependencies.yaml
│       └── README.md
├── developer-tools/          # 8 skills, each 6 files (same layout as github/ above)
│   ├── code-review-checklist/
│   ├── dependency-upgrade-assistant/
│   ├── debugging-methodology/
│   ├── api-client-generator/
│   ├── database-migration-safety/
│   ├── monorepo-navigation/
│   ├── ci-failure-triage/       # depends on github/github-workflow-assistant
│   └── refactoring-safety-net/
├── personal-notes/
│   ├── manifest.yaml
│   ├── SKILL.md
│   ├── schema.json
│   ├── permissions.yaml
│   ├── dependencies.yaml
│   └── README.md
└── team-runbook/
    ├── manifest.yaml
    ├── SKILL.md
    ├── schema.json
    ├── permissions.yaml
    ├── dependencies.yaml
    └── README.md
```

---

## ✅ Checklist Before Publishing Your New Skill

- [ ] Copied template skill
- [ ] Updated all IDs from template to your skill IDs
- [ ] Wrote clear SKILL.md instructions (10+ steps)
- [ ] Defined inputs & outputs in schema.json
- [ ] Listed all permissions needed
- [ ] Listed all dependencies (if any)
- [ ] Ran `uv run jaasctl validate .` successfully
- [ ] No hardcoded secrets (API keys, tokens, passwords)
- [ ] No GPL/AGPL licenses (unless acceptable)
- [ ] Archive size < 50MB
- [ ] Tested locally (if applicable)
- [ ] Ready to publish!

---

## 🎯 Next Steps

1. **Pick a template** from the 4 examples above
2. **Copy it**: `cp -r examples/skills/TEMPLATE examples/skills/my-skill`
3. **Customize** the 5 files (manifest.yaml, SKILL.md, schema.json, etc.)
4. **Validate**: `uv run jaasctl validate examples/skills/my-skill`
5. **Publish**: `uv run jaasctl release examples/skills/my-skill --tag v1.0.0 --api-url http://localhost:8027`

See **SKILLS_GUIDE.md** for comprehensive field documentation and corner cases.

---

**Last Updated**: 2026-09-03  
**Version**: 1.0.0
