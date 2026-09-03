# code-review-checklist

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills - public, visible to every tenant, no sign-in required.

Structured review of a diff or pull request for correctness, security, test
coverage, and scope creep - flags real defects worth blocking on rather than
nitpicking style a linter already enforces. See `SKILL.md` for the actual
instructions the skill carries - written in Claude Code's own skill format
(YAML frontmatter + instructions), since that's what this skill actually
targets.

## Publishing (or re-publishing after an edit)

```bash
uv run jaasctl validate examples/skills/developer-tools/code-review-checklist
uv run jaasctl publish examples/skills/developer-tools/code-review-checklist
./run.sh restart   # the running API only re-scans storage at startup
```
