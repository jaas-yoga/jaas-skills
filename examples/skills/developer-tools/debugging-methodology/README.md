# debugging-methodology

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills - public, visible to every tenant, no sign-in required.

Systematic root-cause debugging for a reported bug - reproduces it first,
bisects to the smallest failing case, forms and tests one hypothesis at a
time, and fixes the root cause rather than the symptom. See `SKILL.md` for
the actual instructions the skill carries - written in Claude Code's own
skill format (YAML frontmatter + instructions), since that's what this
skill actually targets.

## Publishing (or re-publishing after an edit)

```bash
uv run jaasctl validate examples/skills/developer-tools/debugging-methodology
uv run jaasctl publish examples/skills/developer-tools/debugging-methodology
./run.sh restart   # the running API only re-scans storage at startup
```
