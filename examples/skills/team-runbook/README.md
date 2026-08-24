# team-runbook

An example skill package (design.md §4.1 canonical layout) demonstrating a
**private, tenant-owned** skill — visible to anyone whose active tenant
matches the owning tenant (the "My Tenant" filter in `/skills`), regardless
of which specific user published it. Unlike `personal-notes` (owned by a
single user), this represents a skill an org/team owns collectively.

Automatically seeded at API startup by `index/demo_seed.py` (skipped if
it's already been published once), owned by the `owner@jaas.local`
dev-login account's personal tenant. Sign in as that account and check
**My Tenant** in `/skills` to see it; the `admin@jaas.local` account
won't, since it has a different (its own) personal tenant — that's the
visibility model working as intended, not a bug.

## Files

Same canonical layout as the other example skills — see
`../git-fundamentals/README.md` for what each file is for.

## Publishing manually (or re-publishing after an edit)

`jaasctl publish` always publishes public/unowned — it has no
`--owner-tenant`/`--visibility` flags. `demo_seed.py` calls
`artifact.publish.publish_skill()` directly instead, which does accept
them. To bump the seeded version, edit `manifest.yaml`'s `version` and
restart the API — `demo_seed.py` re-publishes whenever the id it's
seeding isn't already in the index.
