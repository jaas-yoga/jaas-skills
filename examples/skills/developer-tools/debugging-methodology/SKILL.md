---
name: debugging-methodology
description: Systematic root-cause debugging for a reported bug - reproduces it first, bisects to the smallest failing case, forms and tests one hypothesis at a time, and fixes the root cause rather than the symptom. Use when asked to debug, investigate, or find the root cause of a bug or error.
---

# Debugging Methodology

Given a bug `report` (symptom, error message, or failing test):

1. **Reproduce before theorizing.** Get the exact failing case running
   locally first - a fix for a bug you haven't reproduced is a guess, not
   a fix.
2. **Read the actual error**, not just its headline. Full stack trace,
   exact error message, and the input that triggered it - a truncated
   read of "NullPointerException" without the trace wastes every step
   after this one.
3. **Bisect to the smallest failing case.** Strip the reproduction down
   (smaller input, fewer steps, `git bisect` across commits if the
   regression is recent) until you have the minimal thing that still
   fails.
4. **One hypothesis at a time.** State what you think is wrong, predict
   what a specific check would show if you're right, then run that one
   check. Don't change three things at once and see if it "works now" -
   you won't know which change mattered.
5. **Distinguish symptom from root cause.** A null check that stops the
   crash is not the same as understanding why the value was null - keep
   asking "why" until you hit the actual originating condition, not just
   the first place it became visible.
6. **Check for the same root cause elsewhere.** Once found, grep for the
   same pattern (same unguarded call, same assumption) elsewhere in the
   codebase - a root cause that produced one visible bug often produced
   silent ones too.
7. **Fix the root cause**, add a regression test that would have caught
   it, and only then remove any temporary debug logging/prints you added
   along the way.
8. **Report the actual root cause in plain language**, not just "fixed
   it" - the next person hitting a similar symptom needs to know what to
   check.

Never report a bug fixed based on the symptom disappearing alone if you
haven't reproduced the original failure and watched your specific fix
resolve it.
