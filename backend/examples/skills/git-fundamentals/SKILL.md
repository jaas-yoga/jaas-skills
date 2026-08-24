---
name: git-fundamentals
description: Core version-control operations independent of any hosting platform - branching, commit hygiene, merge vs. rebase, stashing, cherry-picking, tagging, and recovering from mistakes via git reflog. Use when asked to branch, commit, merge, rebase, stash, cherry-pick, tag, or recover lost git work.
---

# Git Fundamentals

You help a developer with local version-control operations, independent of
any hosting platform (no `gh`/GitHub/GitLab specifics here — see the
`github-workflow-assistant` skill for that layer). Given a plain-language
`task`, do the following:

1. **Look before acting.** `git status`, `git log --oneline -10`, and
   `git branch -vv` first. Never assume the working tree is clean or which
   branch is checked out.
2. **Branching.** Create branches from an up-to-date base
   (`git fetch && git checkout -b <name> origin/main`). Use descriptive
   names (`fix/`, `feat/`, `chore/` prefixes if the repo already uses that
   convention — check recent branch names first, don't impose one).
3. **Committing.** Stage specific files, not `git add -A`/`.`, unless the
   user explicitly wants everything — an unreviewed broad add can catch
   secrets or generated files. Write the message via a heredoc.
4. **Merge vs. rebase.** Rebase a private, not-yet-shared branch to keep
   history linear. Never rebase a branch other people are already working
   from — merge instead, and say why you chose one over the other.
5. **Stash.** `git stash push -u -m "<description>"` (the `-u` includes
   untracked files, and always a message — an unlabeled stash is easy to
   lose track of). Confirm before `git stash drop`; a dropped stash is not
   trivially recoverable.
6. **Cherry-pick.** Verify the target branch first with `git log` so you
   don't duplicate a commit that's already there; use `-x` to record the
   original commit hash in the new message for traceability.
7. **Tagging.** Annotated tags (`git tag -a vX.Y.Z -m "..."`) for anything
   release-related, not lightweight tags — they carry a message and
   tagger identity.
8. **Recovering from mistakes.** `git reflog` before assuming anything is
   permanently lost — a `reset --hard`, an accidental branch delete, or an
   amend can almost always be recovered from it within the reflog's
   retention window. Never reach for `git reflog expire` or `git gc
   --prune=now` when trying to *recover* something; those are exactly the
   operations that would foreclose recovery.
9. **Conflicts.** Read both sides of a conflict marker before resolving —
   don't default to "keep mine" or "keep theirs" without understanding what
   each side actually changed and why.
10. **Never** force-push, `reset --hard`, or delete a branch without the
    user confirming first — treat these the same as any other destructive,
    hard-to-reverse action.

Report back: what you did, the exact commands run in order, and anything
risky you flagged before proceeding (a force-push, a dropped stash, a
rewritten history) rather than doing it silently.
