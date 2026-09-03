# monorepo-navigation

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills - public, visible to every tenant, no sign-in required.

Finds the right package/app boundary in a monorepo before making a change -
traces the workspace/build graph to know which packages a change actually
affects and which build/test commands to scope to, instead of running
everything or guessing package ownership. See `SKILL.md` for the actual
instructions the skill carries - written in Claude Code's own skill format
(YAML frontmatter + instructions), since that's what this skill actually
targets.

## Publishing (or re-publishing after an edit)

```bash
uv run jaasctl validate examples/skills/developer-tools/monorepo-navigation
uv run jaasctl publish examples/skills/developer-tools/monorepo-navigation
./run.sh restart   # the running API only re-scans storage at startup
```
