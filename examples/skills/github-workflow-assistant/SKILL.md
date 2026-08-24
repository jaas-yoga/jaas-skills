---
name: github-workflow-assistant
description: Helps an AI agent follow a repo's git/GitHub conventions - drafting commit messages, opening pull requests and issues via the gh CLI, and reading CI status back before reporting success. Use when asked to commit, open a PR, open an issue, or check CI status in a git repo.
---

# GitHub Workflow Assistant

Builds on `git-fundamentals` (this skill's dependency) for local branch/
commit hygiene; this layer covers the hosted-platform-specific parts on top
of it — PRs, issues, and CI status — via the `gh` CLI.

You help a developer work with git and GitHub through the `gh` CLI. Given a
plain-language `task` (and optionally a `repo` slug), do the following:

1. **Check state before acting.** Run `git status`, `git remote -v`, and (if
   a PR/issue number is involved) `gh pr view`/`gh issue view` before making
   any change. Never assume a remote, branch, or open PR exists — confirm it.
2. **Commits.** Write commit messages via a heredoc to avoid quoting issues.
   Keep the summary line imperative and under ~70 characters; put the *why*,
   not the *what*, in the body. Never `--amend` or force-push unless the user
   explicitly asked for it.
3. **Pull requests.** Use `gh pr create --title "..." --body "..."` with a
   body structured as `## Summary` (a few bullets) and `## Test plan` (a
   checklist). Keep the title under 70 characters. Before declaring success,
   check the PR's own CI status (`gh pr checks`) rather than assuming it
   passed — report what's actually green, not what should be.
4. **Issues.** Use `gh issue create`/`gh issue comment` for anything that
   isn't itself a code change (bugs to track, follow-up work, questions for
   a maintainer). Don't open an issue for something you can just fix.
5. **Never** skip git hooks, force-push a shared branch, or delete a branch
   without the user confirming first — these are the same guardrails any
   careful collaborator would apply by hand.

Report back: what you did, the exact commands run, and a link to anything
you created (PR/issue URL). If something couldn't be verified (e.g. CI is
still running), say so explicitly rather than guessing at the outcome.
