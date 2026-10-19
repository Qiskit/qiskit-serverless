---
name: fix-migrations
description: Fix a Django migration conflict in the gateway (two migrations sharing the same parent) after main merged a migration first, renumbering the branch's own migration safely
---

# Fix conflicting gateway migrations

Use it when `tox -emigrations` (or the "Check migrations" CI step) fails with
`Conflicting migrations detected; multiple leaf nodes in the migration graph`, typically after another
PR merged a migration before yours.

It renumbers the migration **this branch** added so it comes after the latest migration on `main`. It is
safe only when the two sides are independent. Stop and ask the user when they are not (Step 3).

## Step 0 — Ground rules

- Work from the `gateway/` directory, with the gateway virtualenv (not the client one).
- Do not commit or push. Leave the changes in the working tree for the user to review.
- Never touch a migration that is already on `main`: those are applied in other environments.

## Step 1 — Bring in main and find the conflict

```bash
git fetch origin main
git merge origin/main        # or whatever the user already did; resolve non-migration conflicts first
cd gateway
DJANGO_SECRET_KEY=x ENVIRONMENT=test EVENT_STREAMS_MAIN_REGION=eu-de \
  python manage.py makemigrations --check --dry-run
```

The error names the leaf nodes, for example `(0074_jobevent_created_default, 0077_outbox_unrecoverable in api)`.
It needs no database.

## Step 2 — Tell which migration is the branch's own

The branch's own migrations are the ones missing from `main`:

```bash
git diff --name-status origin/main...HEAD -- gateway/api/migrations/
```

Only files with status `A` are the branch's. Everything else in the directory is `main`'s.

## Step 3 — Decide whether renumbering is enough

Read the branch's migration and the migrations it now conflicts with (the ones on `main` after its parent).

**Stop and ask the user** if any of these holds, because renumbering would hide a real problem:

- Both sides alter the same model, field, index or constraint.
- The branch's migration has `RunPython`/`RunSQL`, or depends on data the other side changes.
- The branch has more than one migration of its own whose order matters (renumber them together, in order, and say so).
- Squashed migrations or `replaces` are involved.

If both sides are independent (for example an `AlterField` on one model and a new model elsewhere),
continue.

## Step 4 — Renumber

1. Take the next free number after the latest migration on `main`:
   `git ls-tree --name-only origin/main gateway/api/migrations/ | tail`
2. Rename with `git mv` so the history is kept, keeping the descriptive part of the name.
3. Change its `dependencies` to the latest migration on `main`.
4. Look for other references to the old name and update them:
   `git grep -n "<old name>"`.

## Step 5 — Verify

```bash
DJANGO_SECRET_KEY=x ENVIRONMENT=test EVENT_STREAMS_MAIN_REGION=eu-de tox -emigrations
pytest tests/ -q
tox -elint
```

When the migration changes the schema, also apply the whole chain on a real PostgreSQL, since the test
database is SQLite and it rebuilds tables where PostgreSQL might not:

```bash
docker run -d --rm --name pg-migration-check -p 55432:5432 \
  -e POSTGRES_USER=serverlessuser -e POSTGRES_PASSWORD=serverlesspassword -e POSTGRES_DB=serverlessdb postgres:16
DATABASE_HOST=127.0.0.1 DATABASE_PORT=55432 python manage.py sqlmigrate api <number>
DATABASE_HOST=127.0.0.1 DATABASE_PORT=55432 python manage.py migrate
docker stop pg-migration-check
```

## Step 6 — Report

Tell the user, in a few lines: which migration was renamed and to what, what it now depends on, what was
verified, and that nothing was committed. If another PR may take the same number before this one is merged,
say that it may need renumbering again.
