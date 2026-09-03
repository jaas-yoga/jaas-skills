# ci-failure-triage

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills - public, visible to every tenant, no sign-in required.

Triages a failing CI run - distinguishes a real regression from flake/infra
noise by reading the actual failure output and re-run history before
deciding whether to fix, retry, or escalate. See `SKILL.md` for the actual
instructions the skill carries - written in Claude Code's own skill format
(YAML frontmatter + instructions), since that's what this skill actually
targets.

`github-workflow-assistant` (`examples/skills/github/github-workflow-assistant`)
is a real, resolvable dependency of this skill (design.md §4.4) - it's the
layer this skill uses to read CI status back from a PR/commit in the first
place.

## Publishing (or re-publishing after an edit)

```bash
uv run jaasctl validate examples/skills/developer-tools/ci-failure-triage
uv run jaasctl publish examples/skills/developer-tools/ci-failure-triage
./run.sh restart   # the running API only re-scans storage at startup
```
