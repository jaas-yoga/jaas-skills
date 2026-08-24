# personal-notes

An example skill package (design.md §4.1 canonical layout) demonstrating a
**private, user-owned** skill — visible only to the account that owns it
(the "My Skills" filter in `/skills`), unlike `git-fundamentals` and
`github-workflow-assistant`, which are public.

Automatically seeded at API startup by
`index/demo_seed.py` (skipped if it's already been published once — see
that module's docstring), owned by the `owner@jaas.local` dev-login
account (README.md's "Skipping Google: local dev login" section in the
sibling `jaas_ui` repo). Sign in as that account to see it under
**My Skills**.

## Files

Same canonical layout as the other example skills — see
`../git-fundamentals/README.md` for what each file is for.

## Publishing manually (or re-publishing after an edit)

```bash
uv run jaasctl publish examples/skills/personal-notes --owner-user usr_owner --visibility private
```

`jaasctl publish` doesn't currently expose `--owner-user`/`--visibility`
flags (it always publishes public/unowned) — `demo_seed.py` calls
`artifact.publish.publish_skill()` directly instead, which does accept
them. To bump the seeded version, edit `manifest.yaml`'s `version` and
restart the API — `demo_seed.py` re-publishes whenever the id it's
seeding isn't already in the index.
