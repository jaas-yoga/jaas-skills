# api-client-generator

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills - public, visible to every tenant, no sign-in required.

Generates a typed client for a REST or GraphQL API from its OpenAPI/GraphQL
schema - matching the target codebase's existing HTTP client and
error-handling conventions rather than introducing a new pattern. See
`SKILL.md` for the actual instructions the skill carries - written in Claude
Code's own skill format (YAML frontmatter + instructions), since that's what
this skill actually targets.

## Publishing (or re-publishing after an edit)

```bash
uv run jaasctl validate examples/skills/developer-tools/api-client-generator
uv run jaasctl publish examples/skills/developer-tools/api-client-generator
./run.sh restart   # the running API only re-scans storage at startup
```
