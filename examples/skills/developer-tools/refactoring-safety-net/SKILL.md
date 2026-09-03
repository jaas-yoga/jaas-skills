---
name: refactoring-safety-net
description: Makes a behavior-preserving refactor safely - establishes a passing test baseline (writing characterization tests first if coverage is thin), changes structure without changing behavior, and verifies the baseline still passes before and after each step. Use when asked to refactor, restructure, extract, or clean up code without changing behavior.
---

# Refactoring Safety Net

Given a refactor `intent` (extract a function, rename, restructure a
module, etc.):

1. **Establish a green baseline first.** Run the existing tests covering
   the code being refactored before touching anything - if they're
   already failing, that's a pre-existing issue to flag, not something
   your refactor should be blamed for later.
2. **If coverage is thin, write characterization tests before
   refactoring**, not after - tests that pin down current actual behavior
   (including quirks) so you have something to check the refactor
   against, even if that behavior isn't obviously "correct".
3. **Make one kind of change at a time.** A pure rename, a pure
   extraction, a pure reordering - never combine a structural refactor
   with a behavior change or bug fix in the same step; if you find a bug
   while refactoring, note it and fix it separately.
4. **Re-run the test suite after every discrete step**, not just at the
   end - catching a break immediately after a small step is far cheaper
   to diagnose than after ten combined changes.
5. **Preserve the public interface unless the refactor explicitly targets
   it** - changing a function's external signature is an API change, not
   a pure refactor; call that out separately if it's necessary.
6. **Diff the behavior, not just the tests.** Passing tests are necessary
   but not sufficient - for anything with untested edge cases, manually
   compare before/after output on a few real inputs if the stakes justify
   it.
7. **Leave the code more understandable than you found it**, but resist
   scope creep - don't restructure unrelated code nearby just because
   you're already in the file.
8. **Report exactly what changed structurally and confirm the full test
   suite is green** at the end, not just the tests that originally
   covered the changed area.
