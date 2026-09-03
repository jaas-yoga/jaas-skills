# database-migration-safety

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills - public, visible to every tenant, no sign-in required.

Writes and reviews database schema migrations for backward compatibility and
safe rollout on a live table - additive-first changes, backfills that don't
lock, and a tested rollback path. See `SKILL.md` for the actual instructions
the skill carries - written in Claude Code's own skill format (YAML
frontmatter + instructions), since that's what this skill actually targets.

## Publishing (or re-publishing after an edit)

```bash
uv run jaasctl validate examples/skills/developer-tools/database-migration-safety
uv run jaasctl publish examples/skills/developer-tools/database-migration-safety
./run.sh restart   # the running API only re-scans storage at startup
```
