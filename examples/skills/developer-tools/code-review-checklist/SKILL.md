---
name: code-review-checklist
description: Structured review of a diff or pull request for correctness, security, test coverage, and scope - flags real defects and unjustified scope creep rather than nitpicking style. Use when asked to review a diff, review a PR, or check code before merge.
---

# Code Review Checklist

You review a given `diff` (or PR reference) for defects worth blocking on,
not style preferences a linter already enforces. Given a `diff` or `prUrl`:

1. **Understand the stated intent first.** Read the PR description/commit
   message before the diff itself - you're checking whether the change
   does what it claims, not just whether it's "good code" in the abstract.
2. **Correctness.** Trace each changed function's new behavior against its
   callers. Look for: off-by-one errors, unhandled null/empty cases, race
   conditions in concurrent code, and mismatched types across a changed
   function signature's call sites.
3. **Security.** Flag unsanitized input reaching a shell command, SQL
   string, or HTML output; secrets or credentials committed in plaintext;
   and any newly-added dependency with a known CVE.
4. **Test coverage.** A behavior change with no corresponding test change
   is a finding, not an assumption you let slide - say so explicitly
   rather than silently approving.
5. **Scope.** Flag changes unrelated to the stated intent (a "fix login
   bug" PR that also reformats an unrelated file) - call it out as scope
   creep, don't silently accept it as a freebie.
6. **Readability, last.** Only raise naming/structure feedback after
   correctness/security/test findings are exhausted - never let a style
   nit crowd out an actual defect in your output.
7. **Report a verdict**, not just a list: approve, approve-with-comments,
   or request-changes, with each finding tied to a specific file/line.

Never approve a diff you have not actually traced end-to-end - "looks fine
at a glance" is not a review.
