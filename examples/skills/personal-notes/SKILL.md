---
name: personal-notes
description: Records a short freeform note under a topic, and can list what's already been noted under that topic. Use when asked to jot something down, remember a note for later, or recall previous notes on a topic.
---

# Personal Notes

A small scratchpad skill. Given a `topic` and a `note`:

1. Append the note under that topic (in whatever notes store this
   deployment wires up — this example skill only defines the contract,
   not a specific backend).
2. Report back how many notes now exist under that topic, so the caller
   knows whether this is the first note or one of several.
3. If asked to recall notes for a topic instead of adding one, list them
   in the order they were recorded, most recent last.

Keep entries terse — this is a scratchpad, not a document. Don't
editorialize or summarize the note text; store it as given.
