# Alembic Merge Playbook — Fork Edition

> **Who this is for:** anyone merging upstream `open-webui/open-webui` changes into this fork, or writing a new fork-local migration, or recovering a database whose schema has drifted from its `alembic_version` marker.
>
> **Why it exists:** between 2026-01 and 2026-04 this fork accumulated six "repair" migrations after upstream merges went wrong. Every one of them manipulated `alembic_version` or re-linked the chain by hand, and every one of them eventually caused a production incident because real DDL got skipped. That era is over. This document is the contract.

---

## TL;DR — the six rules

1. **Every new fork migration's `down_revision` is the current `alembic heads` at commit time — never an ID from the middle of the chain.**
2. **After `git merge upstream/<branch>`, if `alembic heads` returns two IDs, generate a merge revision with `alembic merge -m "merge upstream <version>" <fork_head> <upstream_head>`. Commit the merge file. Do not rewrite `down_revision` on any existing migration.**
3. **Never write a "repair" migration whose job is to get around a broken chain.** A migration may create or alter schema; it may not paper over a bookkeeping bug. If you are tempted, stop and recover per Section 7.
4. **Never `alembic stamp` a production database to skip forward.** Stamping is for initialising a fresh database that already has the expected schema from another source — it is not a conflict resolution tool.
5. **Every `op.create_table` / `op.add_column` in a fork migration runs behind an idempotent `IF NOT EXISTS` guard** (helper in Section 9). Upstream migrations stay untouched.
6. **`alembic current` and `alembic heads` are snapshotted into commit messages for every merge commit and every deploy commit.** If a deploy later misbehaves, those markers tell us exactly what changed.

If you remember nothing else, remember: **Alembic solves the merge problem correctly. Our job is to use its solution, not invent our own.**

---

## Table of contents

1. [Why this kept going wrong](#1-why-this-kept-going-wrong)
2. [Mental model — the two chains](#2-mental-model--the-two-chains)
3. [Golden rules expanded](#3-golden-rules-expanded)
4. [Upstream-merge playbook (step-by-step)](#4-upstream-merge-playbook-step-by-step)
5. [Writing a new fork-local migration](#5-writing-a-new-fork-local-migration)
6. [Divergence scenarios and the right response](#6-divergence-scenarios-and-the-right-response)
7. [Recovery — when the chain is already broken](#7-recovery--when-the-chain-is-already-broken)
7b. [Clean-break-point — retiring historical repair migrations](#7b-clean-break-point--retiring-historical-repair-migrations)
8. [Anti-patterns to kill on sight](#8-anti-patterns-to-kill-on-sight)
9. [Idempotency helpers for fork migrations](#9-idempotency-helpers-for-fork-migrations)
10. [Troubleshooting recipes](#10-troubleshooting-recipes)
11. [Glossary](#11-glossary)

---

## 1. Why this kept going wrong

Every post-merge incident in this fork followed the same shape:

1. We added a fork-only migration **in the middle of the upstream chain** — i.e. its `down_revision` pointed at an upstream revision that was expected to stay the head forever.
2. Upstream later added a new migration with the *same* `down_revision`.
3. At that point there were two parallel Alembic heads. `alembic upgrade head` refused to run.
4. Instead of generating a merge revision (`alembic merge heads`) we rewrote `down_revision` on either our migration or on a new "repair" migration so the chain looked linear again — **but the version numbers we asked Alembic to visit had already been stamped into production databases.** From Alembic's point of view those databases were "done" and it happily skipped the migrations we tried to sneak in.
5. The DDL never ran in production; the table never existed; the scheduler that needed the table crashed every few seconds in the logs; we noticed weeks later when a customer reported it.

Concrete example (incident 2026-04-23, Stadtbau):

- Upstream added `56359461a091_add_calendar_tables.py` (`down_revision = c1d2e3f4a5b6`).
- Fork previously wrote `a8f52d3c1e7b_add_processing_task_table.py` with `down_revision = 56359461a091` — so on paper the calendar migration was a mandatory stop.
- But after a rebase `c7d8e9f0a1b2_repair_custom_schema.py` was added with a docstring that admits: *"The DB may have been stamped at 665e242be94b without the actual DDL running (due to a lost migration file during upstream merge)."*
- Result on the Stadtbau DB: `alembic_version = d8e9f0a1b2c3` (head) but `calendar_event` table absent. The scheduler spammed `UndefinedTableError: relation "calendar_event" does not exist`.

The rest of this document exists so that never happens again.

---

## 2. Mental model — the two chains

Think of this fork as living on a **side branch** of an upstream chain:

```
upstream:  U1 ─ U2 ─ U3 ─ U4 ─ U5 (head-at-last-merge)
                        ╲
fork:                    F1 ─ F2 ─ F3 (fork head)
```

- `U5` is the last upstream revision we rebased onto. Our first fork migration (`F1`) has `down_revision = U5`.
- Every fork migration since then extends the fork tail.
- When upstream adds `U6`, they add it as `down_revision = U5` — exactly the same parent as our `F1`. **That is the divergence.** Both `U6` and `F1` now claim `U5` as parent, and Alembic sees two heads: `U6` and `F3`.

**The only correct response** is to tell Alembic about the divergence with a merge revision:

```
upstream:  U1 ─ U2 ─ U3 ─ U4 ─ U5 ─ U6 ─ U7 (new upstream head)
                        ╲             ╲
fork:                    F1 ─ F2 ─ F3 ─ M (merge revision)
                                       ╱
                         upstream ─── ┘
```

`M` has **two parents** (`F3` and `U7`). `alembic upgrade head` now has an unambiguous total order and runs each of `U6`, `U7`, `F1`, `F2`, `F3`, `M` exactly once per database, in a topologically-valid order.

This is a first-class Alembic feature. It is designed for forks. We must use it.

---

## 3. Golden rules expanded

### Rule 1 — `down_revision` is always the current head

**Before writing a new fork migration, run:**

```bash
cd backend/open_webui
alembic heads
```

Use that ID as `down_revision`. If `alembic heads` returns more than one revision, **stop** — resolve the divergence first (Section 4), then come back.

Never pick a revision from the middle of the chain because "the calendar one is downstream of where my feature lives logically." Alembic doesn't care about logical placement; it cares about the DAG.

### Rule 2 — merge, don't rewrite

After a git-merge that adds upstream revisions:

```bash
alembic heads
# If two IDs:
alembic merge -m "merge upstream v<X>.<Y>" <fork_head> <upstream_head>
```

This generates a new file in `migrations/versions/` whose only job is to record that both branches converge here. **Do not edit it further.** Do not add DDL to it. Do not add data migrations to it. It is a bookkeeping marker.

The merge file does **not** need to be run on fresh databases any differently than any other migration — Alembic handles traversal.

### Rule 3 — no repair migrations

A migration whose docstring says "the DB may have been stamped at X without DDL running" or "repairs missing tables after merge" is a red flag. The remedy to a broken chain is to **recover the chain** (Section 7) and, if a schema backfill is genuinely needed for already-deployed databases, write that backfill as a **normal forward-only migration** — one whose DDL is correct whether run on a fresh database or an existing one, not one that silently skips work.

### Rule 4 — no stamping production

`alembic stamp` sets the `alembic_version` row without running any migrations. It is appropriate when:

- You provisioned a database from a backup that already contains a later schema and need Alembic to know that.
- You are initialising a brand-new database and want to skip migrations that have already been subsumed by the current model definitions.

It is **not** appropriate for dragging a production database forward past migrations whose DDL hasn't run. If you find yourself writing `alembic stamp <newer>` against a live DB to "get past" a blocked upgrade, the right move is Section 7 recovery.

### Rule 5 — idempotent fork migrations

Fork migrations may run against databases that were provisioned before we wrote them. Make every structural change idempotent using the helpers in Section 9. This is not a replacement for Rule 3; it is a seatbelt for the case where a database got ahead of the chain through a prior incident.

Upstream migrations are not our problem to make idempotent — if upstream breaks, that is an upstream bug.

### Rule 6 — snapshot `alembic current` + `heads` in commit messages

Every merge commit and every deploy commit includes the output of:

```bash
alembic current
alembic heads
```

at the time of the commit. These four lines let a future operator reconstruct what `alembic_version` should look like on any database deployed from that commit. Without them, recovery is archaeology.

---

## 4. Upstream-merge playbook (step-by-step)

Run this whenever you merge `upstream/<branch>` into a fork branch.

### Pre-merge snapshot

```bash
cd backend/open_webui
alembic current > /tmp/alembic-before-current.txt
alembic heads   > /tmp/alembic-before-heads.txt
```

Expect a single head. If not, stop — resolve that first with the merge procedure below before touching upstream.

### Perform the merge

```bash
cd <repo root>
git fetch upstream
git checkout feature/<your-branch>
git merge upstream/<their-branch>
```

Resolve code conflicts as normal. **Do not touch any file under `backend/open_webui/migrations/versions/` during conflict resolution** — both sides of a migration conflict should be kept (each file is its own revision; neither is "wrong").

### Post-merge inspection

```bash
cd backend/open_webui
alembic heads
```

**Three possible outcomes:**

- **One head, equal to the previous one.** Upstream added no migrations; nothing to do. Continue with the code review.
- **One head, different from the previous one.** Upstream added migrations, but our fork had no open-ended tail at the same parent. This is rare and means our fork migrations were extending from an older point that now has descendants on one side only. Verify the DAG with `alembic history` and confirm every fork migration is still reachable from the new head; if yes, done.
- **Two heads.** The common case. One is the upstream head, one is the fork head. Continue below.

### Generate a merge revision

```bash
alembic merge -m "merge upstream <version>" <fork_head> <upstream_head>
```

- `<version>` is the upstream tag you merged — e.g. `v0.9.1`.
- Order of arguments does not matter semantically; prefer `<fork_head>` first for readability.
- Alembic writes a new file into `migrations/versions/` named `<hash>_merge_upstream_<version>.py`. The file's `down_revision` is a tuple of both heads.

**Do not edit the generated file.** Add nothing to `upgrade()` or `downgrade()`. The merge migration is pure bookkeeping.

### Local verification

```bash
# Against a fresh local SQLite database:
rm -f /tmp/fork-merge-check.db
DATABASE_URL="sqlite:////tmp/fork-merge-check.db" alembic upgrade head

# And against a disposable copy of a production-shaped database, if possible:
DATABASE_URL="postgresql://..." alembic upgrade head --sql | head -200
# Review the SQL — every new table/column from both branches should appear.
```

### Commit

```bash
git add backend/open_webui/migrations/versions/<new merge file>.py
# Plus any code-side conflict resolutions.
git commit -m "$(cat <<'EOF'
chore(alembic): merge upstream v<X>.<Y>

Merges upstream migration head into the fork chain. Upstream added
<list the upstream revisions by short ID>. Fork head before merge was
<fork_head>; new head is <merge_revision_hash>.

alembic current (pre-merge):
  <paste>
alembic heads (pre-merge):
  <paste>
alembic heads (post-merge):
  <paste>
EOF
)"
```

### Deploy

Follow the normal deploy path (bump image tag in `n8n-kubernetes-hosting` or `stadtbau-k8s`). The deployed pod will run `alembic upgrade head` on boot (see Section 10 for where this is wired); the merge revision guarantees all branches converge.

### Post-deploy verification

After the pod is Ready, connect to the database and confirm:

```sql
SELECT version_num FROM alembic_version;
-- Should equal the merge revision hash.

-- Spot-check at least one new table from each branch:
SELECT to_regclass('public.<new_upstream_table>') IS NOT NULL;
SELECT to_regclass('public.<new_fork_table>') IS NOT NULL;
```

If either `to_regclass` returns `false`: **stop, invoke Section 7 recovery, do not attempt a "repair migration".**

---

## 5. Writing a new fork-local migration

### Generate

```bash
cd backend/open_webui
alembic revision -m "add_<thing>_table"
```

Alembic pre-fills `down_revision = <current head>`. **Leave it alone.**

### Write idempotent DDL

Import the helpers from `backend/open_webui/migrations/_fork_helpers.py` (see Section 9) and wrap every structural change:

```python
from _fork_helpers import create_table_if_missing, add_column_if_missing

def upgrade() -> None:
    create_table_if_missing(
        "my_new_table",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=True),
    )
    add_column_if_missing("chat", "new_flag", sa.Column("new_flag", sa.Boolean(), default=False))
```

### Implement `downgrade()`

Required by Alembic. For fork migrations this is usually `op.drop_table(...)` or `op.drop_column(...)` with the same idempotency guards reversed.

### Test locally against both fresh and existing DBs

```bash
# Fresh:
rm -f /tmp/x.db
DATABASE_URL="sqlite:////tmp/x.db" alembic upgrade head

# Against a DB that is already at the previous head:
DATABASE_URL="<prior state>" alembic upgrade head

# And against a DB that already has the table (rare, but validates idempotency):
DATABASE_URL="<has table already>" alembic upgrade head
```

### Commit

Reference `alembic current` in the body of the commit message as in Section 4.

---

## 6. Divergence scenarios and the right response

| Scenario | What you see | Correct response | Forbidden response |
|---|---|---|---|
| Clean merge | `alembic heads` returns 1 ID | Continue as normal | — |
| Two heads after upstream merge | `alembic heads` returns 2 IDs | `alembic merge -m "..." <h1> <h2>` (Section 4) | Rewrite any `down_revision`; write a repair migration |
| Three+ heads (two upstream merges stacked without a merge revision between) | `alembic heads` returns 3+ IDs | Generate ONE merge revision naming all heads at once: `alembic merge -m "merge upstream v<X> + fork" <h1> <h2> <h3>` | Chained pairwise merges are allowed but messy; prefer one N-way merge |
| Fork migration file lost / deleted | `alembic history` shows a broken reference | Restore the file from git history (`git log --all --oneline -- <path>`), then re-run Section 4 | Delete the orphaned `alembic_version` row in production; stamp forward |
| DB `version_num` references a revision that no longer exists in `migrations/versions/` | `alembic upgrade head` errors with `Can't locate revision identified by '<id>'` | Section 7 recovery | Hand-edit `alembic_version` to a newer ID |
| Upstream squashes or renames a revision | A revision ID disappears between upstream releases | If production has the old ID stamped: Section 7; if not: re-run the merge procedure | — |

---

## 7. Recovery — when the chain is already broken

Use this when a database's `alembic_version` claims head but schema reality disagrees, OR when `alembic upgrade head` errors with a missing/unknown revision.

### Step 1 — Snapshot

```bash
# On the running pod or against the DB:
psql $DATABASE_URL -c "SELECT version_num FROM alembic_version;" > /tmp/recovery-version.txt
pg_dump --schema-only $DATABASE_URL > /tmp/recovery-schema.sql
```

Back up the full DB if possible (`pg_dump $DATABASE_URL > /tmp/recovery-full.sql`). This is non-negotiable before any recovery operation.

### Step 2 — Diagnose

From `recovery-schema.sql` enumerate which tables exist. From `alembic history` reconstruct which tables **should** exist at `version_num`. The diff is the problem surface.

### Step 3 — Pick a recovery strategy

There are three, in order of preference:

#### Strategy A — forward-only backfill migration (preferred)

If the only issue is missing tables or columns that should exist at head:

1. Write **one new forward migration** that creates the missing objects **idempotently** (Section 9).
2. This migration has `down_revision = <current head>` and becomes the new head.
3. Deploy. Every production database goes through the new migration. Ones with the missing tables get them created; ones that somehow already have them skip the creation via the `IF NOT EXISTS` guard.

Do **not** call this a "repair migration" in its docstring. Describe what it does: *"backfill calendar_event and calendar tables on databases where the upstream migration was bypassed"*, with a reference to the incident commit.

#### Strategy B — sideways re-stamp

If `version_num` points at a revision that no longer exists in `migrations/versions/`:

1. Find the current equivalent in the current chain (the revision that has the same effective schema meaning).
2. `UPDATE alembic_version SET version_num = '<current_equivalent>'` — via a Python Alembic migration that uses `op.execute`, not via manual SQL on the database.
3. The migration is a true migration with `down_revision = <previous head>` and its only job is the `UPDATE`.

This is the one time editing `alembic_version` is permitted, and it must still be done through a migration file so the change is reproducible on every database.

#### Strategy C — full reset (last resort)

If the divergence is too large to backfill and the data is recoverable from a canonical source:

1. `pg_dump --data-only` all user tables you must preserve.
2. Drop database; re-provision.
3. `alembic upgrade head` on the fresh database.
4. Re-import user data.

This is acceptable only for development environments or as a deliberate major-version reset. Never on production without written customer approval.

### Step 4 — Verify

After the recovery migration deploys, re-run the post-deploy verification (Section 4) against the DB you recovered. Confirm `version_num` equals the new head and that every table named in the forward-only backfill now exists.

### Step 5 — Post-mortem

Write a short incident note into `docs/incidents/` with: what broke, the `version_num` at recovery time, which tables were missing, what the backfill migration ID is, and the commit that triggered the original break. This is how we stop recurring.

---

## 7b. Clean-break-point — retiring historical repair migrations

A fork that has been running long enough accumulates scar tissue: old repair migrations, backfills for drift that no longer exists on any live database, files whose docstrings admit something went wrong. They are harmless (the revision IDs are stamped into production DBs and can't be removed without breaking those DBs), but they are *ugly* and they drag forward into every future merge.

The way to retire them safely is to wait for a natural consolidation opportunity and execute it deliberately. Do not attempt this outside the window described here.

### When a clean-break-point is allowed

All three of these must be true:

1. Every production and staging database is known to be at a `version_num` **at or later than** the newest historical repair migration. (I.e. every DB has already traversed the debt; none is pinned at an old stamp.)
2. We are about to do an upstream merge that will itself generate a merge revision anyway — so the chain is already about to be rewritten in a legitimate way.
3. A full DB backup of every environment exists from within the last 24 hours and a rollback path is documented.

If any is false, defer. The scars stay in for another cycle.

### The procedure

1. **Snapshot every DB's `version_num`**. Record into `docs/incidents/clean-break-<date>.md` the revision each cluster reports. If any cluster is behind the clean-break candidate, upgrade it first (normal deploy) and re-snapshot.
2. **Introduce a sentinel revision** — a normal fork migration with empty `upgrade()` / `downgrade()` whose job is to be the "line in the sand". Deploy it. Every cluster's `version_num` advances to the sentinel.
3. **Verify every cluster's `version_num` equals the sentinel**, from the actual DB, not from hope. Redo the snapshot in step 1.
4. **On a branch, rewrite the chain**. The sentinel's `down_revision` now points at a pre-existing revision that is strictly *after* the last repair migration in the historical order. Delete the repair migration files and any intermediate revisions between the repairs and the sentinel. The sentinel now sits directly after the clean tail of the pre-repair chain.
5. **Verify the rewritten chain** locally:
   - `alembic history --verbose` produces a linear walk with no missing parents.
   - `rm -f /tmp/x.db && DATABASE_URL=sqlite:///tmp/x.db alembic upgrade head` succeeds on a fresh DB.
   - `alembic upgrade head` also succeeds against a disposable copy of production **with the `alembic_version` already set to the sentinel**, which it should no-op through. If this second check errors (because Alembic can't find the stamped revision anywhere in the chain), the rewrite is wrong — the sentinel must remain reachable.
6. **Deploy the rewritten chain**. Because every live DB is already at the sentinel, and the sentinel is still in the chain, Alembic finds it and does nothing. The deleted repair migrations are now invisible to every live system.
7. **Document**: the incident note from step 1 gets a postscript listing the retired revision IDs. `git log` preserves the old files for anyone archaeologising a future incident.

### What makes this NOT a rule-2 violation

Rule 2 forbids *rewriting `down_revision` on an existing migration after it has shipped*. The clean-break-point does not edit any migration that a live DB still needs to traverse — it deletes migrations that every live DB has already walked past and whose revision IDs are no longer the last-known-good stamp on any cluster. The sentinel is the seam that makes this safe.

If you can't truthfully answer "every live database already has `version_num` ≥ sentinel", this becomes a rule-2 violation and you must stop.

### Anti-sequence — how this goes wrong

- **"Let's also delete the sentinel itself"** — no. The sentinel is the proof that the retired tail was once reachable. Keep it forever.
- **"One cluster is behind but we'll upgrade it as part of the same deploy"** — no. Two separate deploys. First upgrade the lagging cluster to the sentinel, verify, then ship the rewrite. Never combine.
- **"Let's do the clean-break-point without a merge revision nearby"** — you can, but you're introducing chain rewrite risk for cosmetic benefit. Prefer to piggyback on a real merge.

---

## 8. Anti-patterns to kill on sight

Every bullet below appeared in our fork between 2026-01 and 2026-04 and each one cost a production incident.

- **A migration whose docstring admits uncertainty**: "The DB *may* have been stamped at X without DDL running." If a migration needs to say this, the chain is broken and we are trying to hide it. Stop, recover per Section 7.
- **`op.execute("UPDATE alembic_version SET version_num = ...")` inside a migration.** Allowed exactly in Strategy B above and nowhere else. If you see it in a code review, block the PR.
- **Rewriting `down_revision` on an existing migration after it has shipped.** The migration's ID and parent are an immutable contract once any production database has run it. To reconnect the DAG use a merge revision or a new migration, never an edit.
- **Chain-rewrite commits described as "relink migrations after upstream merge"** — if you see this message in `git log`, the relink was done wrong. The correct action was `alembic merge heads`.
- **`alembic stamp` on production.** See Rule 4.
- **"Idempotent" migration whose idempotency check looks at `alembic_version` rather than the actual table.** Idempotency means *"is the target object already there?"* Bookkeeping is Alembic's job, not the migration's.
- **Migrations that skip themselves based on environment variables.** A migration runs on every DB it reaches in the chain. If you need conditional behaviour, branch on actual schema state, never on env.

---

## 9. Idempotency helpers for fork migrations

This section is authoritative — the helpers below live at `backend/open_webui/migrations/_fork_helpers.py` and every fork migration imports them.

```python
# backend/open_webui/migrations/_fork_helpers.py
"""
Idempotency guards for fork-local migrations.

DO NOT USE in upstream migrations. Upstream migrations must stay
byte-identical to the upstream repository so that our Alembic chain
remains rebase-friendly.
"""

from alembic import op
import sqlalchemy as sa


def _dialect(conn) -> str:
    return conn.dialect.name


def _table_exists(conn, table_name: str) -> bool:
    if _dialect(conn) == "postgresql":
        return conn.execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t)"
            ),
            {"t": table_name},
        ).scalar()
    # SQLite fallback (dev only)
    return conn.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name = :t)"
        ),
        {"t": table_name},
    ).scalar()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    if _dialect(conn) == "postgresql":
        return conn.execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = :t AND column_name = :c)"
            ),
            {"t": table_name, "c": column_name},
        ).scalar()
    rows = conn.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(r[1] == column_name for r in rows)


def create_table_if_missing(table_name: str, *columns, **kwargs) -> None:
    """Like op.create_table, but a no-op if the table already exists."""
    conn = op.get_bind()
    if _table_exists(conn, table_name):
        return
    op.create_table(table_name, *columns, **kwargs)


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    """Like op.add_column, but a no-op if the column already exists."""
    conn = op.get_bind()
    if _column_exists(conn, table_name, column.name):
        return
    op.add_column(table_name, column)


def drop_table_if_exists(table_name: str) -> None:
    conn = op.get_bind()
    if not _table_exists(conn, table_name):
        return
    op.drop_table(table_name)


def drop_column_if_exists(table_name: str, column_name: str) -> None:
    conn = op.get_bind()
    if not _column_exists(conn, table_name, column_name):
        return
    op.drop_column(table_name, column_name)
```

### When to use each helper

- **`create_table_if_missing`** — every fork table creation.
- **`add_column_if_missing`** — every fork column addition on an existing table (upstream or fork).
- **`drop_*_if_exists`** — in `downgrade()` only.
- For index/constraint creation, wrap in a local `try/except` for now and extend the helper module when a second fork migration needs the same guard.

These helpers are **not** a licence to write sloppy migrations. They are a seatbelt, not a steering wheel. A fork migration should still be designed as if it will run on a clean database first.

---

## 10. Troubleshooting recipes

### `alembic upgrade head` hangs or says "Can't locate revision"

```
FAILED: Can't locate revision identified by '<id>'
```

Cause: `alembic_version` in the DB references a revision that no longer exists in `migrations/versions/`.

Fix: Section 7 Strategy B — forward re-stamp migration.

### Pod boot health check OK but scheduler logs `UndefinedTable`

Cause: `alembic_version` claims head but DDL for the referenced table never ran. Exact incident from 2026-04-23.

Fix:

1. Run `alembic history | head -20` to find the migration that creates the missing table.
2. Confirm the DB's `version_num` is equal to or greater than that migration's revision.
3. If yes and the table still doesn't exist → Section 7 Strategy A — write a forward backfill migration that creates the table idempotently.

### After a rebase, the same migration file shows up twice with different IDs

Cause: `alembic revision` was run on two branches in parallel and both auto-generated against the same parent.

Fix: one of the two is the canonical version; delete the other before committing. If both have already shipped to different environments (dev vs prod), promote the one in prod and rename the dev one via a chain-rewrite **on dev only**, never on prod.

### `alembic heads` returns 2+ after pulling a fork branch

Not an error by itself — this is the expected state immediately after `git merge upstream/...` before you've generated the merge revision. Run Section 4.

### Can I run `alembic upgrade head --sql` to preview?

Yes, always. Copy the output into the PR description for any PR that changes migrations. Reviewers can spot missing DDL that way.

### Where does `alembic upgrade head` actually run at boot?

In this fork, database migrations run automatically at application startup via `open_webui.internal.db` initialisation when `ENABLE_DB_MIGRATIONS=true` (default). To disable for a debug run, set `ENABLE_DB_MIGRATIONS=false` and run `alembic upgrade head` manually.

---

## 11. Glossary

- **Revision** — a single Alembic migration, identified by a short SHA-like hash.
- **Head** — a revision with no child (no other migration lists it as `down_revision`). A healthy chain has exactly one head.
- **Branch** — a divergence in the revision DAG. Arises when two revisions share the same `down_revision`. Alembic's term, not git's.
- **Merge revision** — a special revision whose `down_revision` is a tuple of two or more parent revisions. Generated by `alembic merge`. Pure bookkeeping — no DDL.
- **`alembic_version`** — single-row table in the target database that records the ID the DB is currently at.
- **`alembic stamp`** — command that writes a revision ID to `alembic_version` without running any migrations. Narrow use cases (Rule 4).
- **Chain rewrite** — editing `down_revision` on existing migrations to make a divergent DAG look linear. Forbidden on shipped migrations (Section 8).
- **Repair migration** — historical term for migrations that exist to paper over a broken chain. Forbidden (Rule 3).
- **Fork-local migration** — a migration written in this fork that does not exist upstream. Must use idempotency helpers (Section 9).
- **Upstream migration** — a migration copied from `open-webui/open-webui`. Byte-identical to upstream. We don't modify these.

---

## Appendix A — minimal merge workflow cheat sheet

```bash
# Before merge
cd backend/open_webui && alembic heads && alembic current

# Merge
cd <repo root>
git fetch upstream && git merge upstream/<branch>

# Post-merge
cd backend/open_webui && alembic heads
# If two IDs:
alembic merge -m "merge upstream v<X>.<Y>" <fork_head> <upstream_head>

# Verify locally
rm -f /tmp/x.db && DATABASE_URL=sqlite:////tmp/x.db alembic upgrade head

# Commit (snapshot alembic state in body)
git add migrations/versions/ && git commit
```

Keep this pinned somewhere while you merge.
