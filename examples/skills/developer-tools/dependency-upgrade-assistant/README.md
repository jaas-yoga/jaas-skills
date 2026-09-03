# dependency-upgrade-assistant

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills - public, visible to every tenant, no sign-in required.

Plans and executes a dependency version bump safely - reads changelogs for
breaking changes, runs the test suite before and after, and stages the
upgrade as its own commit separate from unrelated changes. See `SKILL.md`
for the actual instructions the skill carries - written in Claude Code's own
skill format (YAML frontmatter + instructions), since that's what this
skill actually targets.

## Publishing (or re-publishing after an edit)

```bash
uv run jaasctl validate examples/skills/developer-tools/dependency-upgrade-assistant
uv run jaasctl publish examples/skills/developer-tools/dependency-upgrade-assistant
./run.sh restart   # the running API only re-scans storage at startup
```
