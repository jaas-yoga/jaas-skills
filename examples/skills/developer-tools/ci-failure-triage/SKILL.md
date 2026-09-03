---
name: ci-failure-triage
description: Triages a failing CI run - distinguishes a real regression from flake/infra noise by reading the actual failure output and re-run history before deciding whether to fix, retry, or escalate. Use when asked to investigate, triage, or fix a failing CI run or build.
---

# CI Failure Triage

Builds on `github-workflow-assistant` for reading CI status back from a
PR/commit. Given a failing `runUrl` or `commitSha`:

1. **Read the actual failure output**, not just the red X - the specific
   failing step, its exact error/assertion message, and enough
   surrounding log context to see what ran right before the failure.
2. **Check re-run history before calling it flake.** A failure that also
   failed on a previous, unrelated commit/PR is likely infra or a
   pre-existing flaky test - a failure that only started on this PR's
   commits is very likely a real regression from this change.
3. **Correlate the failure with the actual diff.** If the failing
   test/module has no relationship to anything in the diff, treat that as
   evidence toward flake/infra, not proof - still verify with a re-run
   before concluding.
4. **Never blind-retry a failure that reproduces deterministically.**
   Re-running is only appropriate once you have some signal (unrelated
   diff, known-flaky test tag, an infra error like a timeout/network
   blip in the log) suggesting non-determinism - a real regression will
   just fail again and waste a CI slot.
5. **If it's a real regression, fix the root cause in the diff**, not the
   CI config - don't skip/quarantine a newly-broken test to make CI green
   unless a human explicitly asks for that as a stopgap, and say so
   explicitly if you do.
6. **If it's confirmed flake, say so and either re-run or flag the
   specific test for someone to fix** - a flaky test that gets silently
   re-run forever without being flagged never gets fixed.
7. **Report the verdict** (regression / flake / infra) with the evidence
   that led to it, not just "fixed" or "retried".
