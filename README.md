# Sarah-CPA

DueDateHQ first-phase infrastructure, validated without any frontend.

## What Works

- Rule ingestion into an append-preserving rule table with supersession tracking
- Low-confidence rule routing into a manual review queue
- Client-to-rule mapping into concrete deadlines
- Reminder queue generation and rebuild on deadline changes
- Tenant-scoped reminder triggering for PostgreSQL RLS compatibility
- Deadline state machine with transition history
- Append-only audit log enforced by database triggers
- Official-source fetchers for HTML, RSS, and PDF inputs
- Notification delivery routing for email, SMS, and Slack
- Celery dispatch hooks for fetch, reminder scheduling, and notification delivery
- Interactive chat mode with text-first realtime view rendering and a voice-ready input mode
- Structured plan execution pipeline: executor, response generator, and interaction backend
- CLI commands for create/list/update/export/worker flows

## Database

By default the CLI writes to `.duedatehq/duedatehq.sqlite3` in the repo root.

You can also set `DUEDATEHQ_DATABASE_URL` instead of passing `--db`.

Use another database file with:

```bash
python -m duedatehq.cli --db C:\path\to\test.sqlite3 ...
```

For a PostgreSQL-backed app, pass a DSN instead:

```bash
python -m duedatehq.cli --db postgresql://user:pass@localhost:5432/duedatehq tenant add "Acme Tenant"
python -m duedatehq.cli --db postgresql://user:pass@localhost:5432/duedatehq db init
python -m duedatehq.cli --db postgresql://user:pass@localhost:5432/duedatehq db status
python -m duedatehq.cli --db postgresql://user:pass@localhost:5432/duedatehq db rls-check
```

The PostgreSQL schema and RLS policies live in:

```bash
db/postgres_schema.sql
```

That schema includes:

- tenant-scoped tables with `tenant_id`
- row-level security policies for tenant-bound tables
- append-only audit log triggers
- helper SQL functions to require `app.tenant_id`

## CLI

```bash
python -m duedatehq.cli tenant add "Acme Tenant"
python -m duedatehq.cli fetch --list-sources --all
python -m duedatehq.cli fetch --source irs --text-file notice.txt --source-url https://irs.gov/example
python -m duedatehq.cli worker fetch --source irs --text-file notice.txt --source-url https://irs.gov/example
python -m duedatehq.cli worker fetch --source irs --url https://irs.gov/newsroom/example --format html
python -m duedatehq.cli worker fetch --source irs --url https://irs.gov/pub/irs-drop/n-26-01.pdf --format pdf
python -m duedatehq.cli worker fetch --source federal_register --rss-url https://example.com/feed.xml --entry-title-contains deadline
python -m duedatehq.cli rule add --tax-type franchise_tax --jurisdiction CA --entity-types s-corp --deadline-date 2026-04-20 --effective-from 2026-01-01 --source-url https://ftb.ca.gov/rule
python -m duedatehq.cli client add <tenant_id> "Acme LLC" --entity s-corp --states TX,CA,DE --tax-year 2026
python -m duedatehq.cli deadline list <tenant_id> --client <client_id> --show-reminders
python -m duedatehq.cli deadline action <tenant_id> <deadline_id> complete --actor user-1
python -m duedatehq.cli deadline trigger-reminders --tenant-id <tenant_id> --at 2026-04-19T09:00:00+00:00
python -m duedatehq.cli today <tenant_id>
python -m duedatehq.cli chat --tenant-id <tenant_id> --prompt "show me today"
python -m duedatehq.cli chat --tenant-id <tenant_id> --mode voice --transcript-file sample_transcript.txt
python -m duedatehq.cli notify config add <tenant_id> --channel email --destination owner@example.com
python -m duedatehq.cli notify config add <tenant_id> --channel slack --destination https://hooks.slack.com/services/...
python -m duedatehq.cli notify preview <tenant_id> --within-days 14
python -m duedatehq.cli notify history <tenant_id>
python -m duedatehq.cli notify send-pending <tenant_id> --smtp-host localhost --smtp-sender noreply@example.com
python -m duedatehq.cli worker schedule-reminders <tenant_id> --hours 24
python -m duedatehq.cli worker jobs --tenant-id <tenant_id>
python -m duedatehq.cli celery ping
python -m duedatehq.cli celery dispatch-fetch --source irs
python -m duedatehq.cli celery dispatch-reminders <tenant_id>
python -m duedatehq.cli celery dispatch-notifications <tenant_id>
python -m duedatehq.cli log --tenant-id <tenant_id>
```

For raw text ingestion:

```bash
python -m duedatehq.cli rule ingest-text --source-url https://irs.gov/example --text-file notice.txt
python -m duedatehq.cli rule review-queue
```

## Worker Boundaries

- `FetchWorker`: wraps a fetcher and pushes documents through rule ingestion
- `ReminderScheduler`: batches the next time window of reminder jobs into a queue
- `ReminderWorker`: drains queued reminder jobs and triggers reminders per tenant, which keeps PostgreSQL RLS intact
- `PersistentJobQueue`: stores worker jobs in the database instead of process memory

## Notifications

- `notify config add`: persist an enabled route for `email`, `sms`, or `slack`
- `notify send-pending`: deliver pending notifications using SMTP, JSON webhooks, or console notifiers
- notification deliveries are written to the database before send, then marked `sent` or `failed`

## Celery

Set `DUEDATEHQ_BROKER_URL` or pass `--broker-url` to the `celery` commands:

```bash
$env:DUEDATEHQ_BROKER_URL="redis://localhost:6379/0"
python -m duedatehq.cli celery ping
```

Reminder reads now default to the current active queue. Historical cancelled reminders remain in the database and surface through history-oriented views such as `notify history`.

## Conversational Mode

- `chat --prompt "...":` one-shot interaction that returns a language reply and one or more rendered blocks
- `chat` with no `--prompt`: interactive text loop
- `chat --mode voice`: voice-equivalent path for transcript input; this currently accepts transcript text and routes it through the same intent/render pipeline as typed input

The current render contract is:

- one short language conclusion
- one or more structured render blocks such as `Today`, `Deadlines`, `Rule Review Queue`, or `Pending Notifications`

## Structured Interaction Backend

The repo now includes deterministic interaction primitives for the v5 guide:

- `PlanExecutor`: executes `cli_call`, `resolve_entity`, `foreach`, and `post_filter` plan steps
- `ResponseGenerator`: turns executor output into frontend payloads such as `ListCard`, `ClientCard`, `ConfirmCard`, and `GuidanceCard`
- `InteractionBackend`: routes read plans, write plans, and confirmed actions through the executor/renderer pipeline

The programmatic entry points live in `duedatehq.api`:

- `process_plan(...)`
- `process_action(...)`
- `chat(...)`

These are intended for small-scale interaction and LLM smoke testing before a dedicated frontend or HTTP transport is added.

For the next-step interaction direction, see:

- `docs/interactive-rendering-vnext.md`

## Onboarding Prototype

A static onboarding intake prototype now lives at:

- `frontend/onboarding.html`

It aligns to the current intake-oriented schema split:

- stable client profile on `clients`
- annual filing profile on `client_tax_profiles`
- resident and operating jurisdictions on `client_jurisdictions`
- primary contact on `client_contacts`

The page is intentionally frontend-only for now. It generates a live JSON payload and a code-aligned CLI command so the intake flow can be reviewed before a dedicated HTTP transport is added.

## Small Demo Data

A minimal demo seed script is available for local testing:

```bash
C:\sarah-cpa\.tools\python\3.11.9\python.exe scripts\seed_small_demo.py
```

It creates one demo tenant with a few rules, three clients, several deadlines, a small amount of history, and one notification route. The script is idempotent for the demo tenant name.

## Verification

```bash
python -m pytest -q
```

For PostgreSQL integration verification:

```bash
$env:DUEDATEHQ_TEST_POSTGRES_DSN="postgresql://user:pass@localhost:5432/duedatehq_test"
python -m pytest -q tests/test_postgres_integration.py
```
