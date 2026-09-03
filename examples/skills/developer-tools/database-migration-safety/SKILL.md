---
name: database-migration-safety
description: Writes and reviews database schema migrations for backward compatibility and safe rollout on a live table - additive-first changes, backfills that don't lock, and a tested rollback path. Use when asked to write, review, or run a database migration.
---

# Database Migration Safety

Given a schema change `intent` against a named table:

1. **Check table size and traffic first.** A migration safe on an empty
   dev table can lock a production table with real row counts for the
   duration of the operation - ask or check before assuming it's cheap.
2. **Prefer additive, multi-step changes over a single destructive one.**
   Adding a NOT NULL column: add it nullable, backfill in batches, then
   add the constraint - not one migration that adds NOT NULL with a
   default and locks the whole table on some engines.
3. **Never drop a column or table in the same migration that stops
   writing to it.** Stop writing first (a deploy), confirm nothing reads
   it either, then drop it in a later, separate migration - this gives a
   rollback window if the "stop using it" assumption was wrong.
4. **Backfills run in batches**, not one giant `UPDATE`, to avoid
   long-held locks and huge transaction/WAL growth - check the engine's
   own guidance on batch size if the codebase doesn't already have a
   backfill helper.
5. **Write the down-migration / rollback path and actually consider
   running it** - a migration with no tested rollback is a one-way door;
   say so explicitly if a true rollback isn't possible (e.g., a
   destructive change) rather than writing a rollback script that
   silently doesn't work.
6. **Match the migration tool already in use** (Alembic, Rails, Prisma,
   raw SQL files, etc.) and its existing naming/versioning convention -
   don't introduce a second migration mechanism.
7. **Never edit an already-applied migration file** - a new migration
   corrects a mistake in an old one, the same way a new commit corrects
   an old one, so environments that already ran the original stay
   consistent.
8. **Report the rollout plan**: which step needs a deploy in between
   (e.g., "backfill, wait for deploy, then add constraint in a follow-up
   migration"), not just the SQL.
