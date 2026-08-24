# git-fundamentals

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills — public, visible to every tenant, no sign-in required.

Covers core version-control operations independent of any hosting platform:
branching, commit hygiene, merge vs. rebase, stashing, cherry-picking,
tagging, and recovering from mistakes via `git reflog`. See `SKILL.md` for
the actual instructions the skill carries — written in Claude Code's own
skill format (YAML frontmatter + instructions), since that's what this
skill actually targets.

`github-workflow-assistant` (the companion example skill) depends on this
one — a real, resolvable dependency edge (design.md §4.4), not just two
unrelated examples sitting next to each other.

## Publishing (or re-publishing after an edit)

```bash
uv run jaasctl validate examples/skills/git-fundamentals
uv run jaasctl publish examples/skills/git-fundamentals
./run.sh restart   # the running API only re-scans storage at startup
```
