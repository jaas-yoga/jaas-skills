# refactoring-safety-net

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills - public, visible to every tenant, no sign-in required.

Makes a behavior-preserving refactor safely - establishes a passing test
baseline (writing characterization tests first if coverage is thin), changes
structure without changing behavior, and verifies the baseline still passes
at each step. See `SKILL.md` for the actual instructions the skill carries -
written in Claude Code's own skill format (YAML frontmatter + instructions),
since that's what this skill actually targets.

## Publishing (or re-publishing after an edit)

```bash
uv run jaasctl validate examples/skills/developer-tools/refactoring-safety-net
uv run jaasctl publish examples/skills/developer-tools/refactoring-safety-net
./run.sh restart   # the running API only re-scans storage at startup
```
