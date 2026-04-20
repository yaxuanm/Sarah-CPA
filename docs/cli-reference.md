# DueDateHQ CLI Reference

This document is the code-aligned reference for the current DueDateHQ CLI.
Source of truth: `src/duedatehq/cli.py`.

## Global

Entry point:

```bash
duedatehq [--db DB_PATH] <command> ...
```

Global options:

- `--db DB_PATH`
  - Optional
  - Accepts either:
    - a SQLite file path
    - a PostgreSQL DSN such as `postgresql://user:pass@host:5432/duedatehq`

Output conventions:

- Most commands return JSON.
- `chat` returns a text reply plus render blocks, not JSON.

## tenant

### tenant add

```bash
duedatehq tenant add <name>
```

Arguments:

- `name`
  - Required
  - Tenant display name

Returns:

```json
{
  "tenant_id": "..."
}
```

## client

### client add

```bash
duedatehq client add <tenant_id> <name> --entity <entity_type> --states <csv> --tax-year <year> [--client-type <individual|business>] [--legal-name <name>] [--home-jurisdiction <state>] [--contact-name <name>] [--contact-email <email>] [--contact-phone <phone>] [--preferred-channel <email|sms|slack>] [--responsible-cpa <name>] [--entity-election <value>] [--intake-status <draft|in_progress|ready|needs_followup>] [--profile-source <manual|import|inferred>] [--first-year-filing | --no-first-year-filing] [--final-year-filing | --no-final-year-filing] [--extension-requested | --no-extension-requested] [--extension-filed | --no-extension-filed] [--estimated-tax-required | --no-estimated-tax-required] [--payroll-present | --no-payroll-present] [--contractor-reporting-required | --no-contractor-reporting-required] [--notice-received | --no-notice-received]
```

Arguments:

- `tenant_id`
  - Required
- `name`
  - Required
- `--entity`
  - Required
  - Example: `s-corp`, `llc`, `partnership`
- `--states`
  - Required
  - Comma-separated state codes such as `TX,CA,DE`
- `--tax-year`
  - Required
  - Integer
- `--client-type`
  - Optional
  - Defaults to `business`
- `--legal-name`
  - Optional
- `--home-jurisdiction`
  - Optional
  - Resident or home jurisdiction for the client
- `--contact-name`, `--contact-email`, `--contact-phone`
  - Optional
  - Seeds the primary client contact record
- `--preferred-channel`
  - Optional
  - Preferred channel for the primary contact
- `--responsible-cpa`
  - Optional
- `--entity-election`
  - Optional
- `--intake-status`
  - Optional
  - Defaults to `draft`
- `--profile-source`
  - Optional
  - Defaults to `manual`
- Annual filing flags
  - Optional boolean flags stored on the annual tax profile:
  - `--first-year-filing`
  - `--final-year-filing`
  - `--extension-requested`
  - `--extension-filed`
  - `--estimated-tax-required`
  - `--payroll-present`
  - `--contractor-reporting-required`
  - `--notice-received`

Behavior:

- Creates a client.
- Stores stable profile fields on `clients`.
- Seeds an annual `client_tax_profiles` row for the provided tax year.
- Seeds resident and operating jurisdictions in `client_jurisdictions`.
- Creates a primary contact in `client_contacts` when contact details are provided.
- Automatically generates deadlines from active rules.

Returns:

```json
{
  "client_id": "...",
  "tenant_id": "..."
}
```

### client update-states

```bash
duedatehq client update-states <tenant_id> <client_id> --states <csv>
```

Arguments:

- `tenant_id`
- `client_id`
- `--states`
  - Required

Behavior:

- Updates a client's registered states.
- Recomputes matching deadlines.

### client list

```bash
duedatehq client list <tenant_id>
```

Returns:

- JSON array of clients for the tenant

## rule

### rule ingest-text

```bash
duedatehq rule ingest-text --source-url <url> --text-file <file> [--fetched-at <iso_ts>]
```

Arguments:

- `--source-url`
  - Required
- `--text-file`
  - Required
- `--fetched-at`
  - Optional ISO timestamp

Behavior:

- Reads raw rule text from a file.
- Parses it into a rule.
- Low-confidence results go to the review queue.

Returns:

- A `RuleRecord` JSON object on success
- A `RuleReviewItem` JSON object on low confidence

### rule add

```bash
duedatehq rule add --tax-type <type> --jurisdiction <jurisdiction> --entity-types <csv> --deadline-date <yyyy-mm-dd> --effective-from <yyyy-mm-dd> --source-url <url> [--confidence <float>]
```

Arguments:

- `--tax-type`
  - Required
- `--jurisdiction`
  - Required
  - Example: `FEDERAL`, `CA`
- `--entity-types`
  - Required
  - Comma-separated values
- `--deadline-date`
  - Required
- `--effective-from`
  - Required
- `--source-url`
  - Required
- `--confidence`
  - Optional
  - Defaults to `0.99`

Behavior:

- Creates a rule directly.
- Supersedes the prior active version for the same jurisdiction and tax type.
- Refreshes affected deadlines.

### rule list

```bash
duedatehq rule list
```

Returns:

- JSON array of all rules

### rule review-queue

```bash
duedatehq rule review-queue
```

Returns:

- JSON array of low-confidence review items

## fetch

### fetch

```bash
duedatehq fetch (--source <source> | --state <state> | --all) [--text-file <file>] [--source-url <url>] [--fetched-at <iso_ts>] [--list-sources]
```

Mutually exclusive selectors:

- `--source`
- `--state`
- `--all`

Arguments:

- `--text-file`
- `--source-url`
- `--fetched-at`
- `--list-sources`

Behavior:

- `--list-sources`: returns the source registry
- `--all`: currently returns the source registry, not a true bulk fetch
- ingest mode requires both:
  - `--text-file`
  - `--source-url`

Returns:

- source list for `--list-sources` or `--all`
- otherwise:

```json
{
  "fetch_run": {...},
  "result": {...}
}
```

## deadline

### deadline list

```bash
duedatehq deadline list <tenant_id> [--client <client_id>] [--within-days <int>] [--status <pending|completed|snoozed|waived|overridden>] [--jurisdiction <state>] [--limit <int>] [--offset <int>] [--show-reminders]
```

Arguments:

- `tenant_id`
- `--client`
  - Optional
- `--within-days`
  - Optional
- `--status`
  - Optional
- `--jurisdiction`
  - Optional
- `--limit`
  - Optional
- `--offset`
  - Optional
- `--show-reminders`
  - Optional flag

Behavior:

- Lists deadlines for the tenant.
- When `--client` is set, filters to that client.
- When `--within-days` is set, filters to deadlines due between today and the next N days.
- When `--status` is set, filters by the current deadline status.
- When `--jurisdiction` is set, filters by jurisdiction code.
- When `--limit` and `--offset` are set, paginates the ordered result set.
- When `--show-reminders` is set, embeds reminders per deadline.

### deadline action

```bash
duedatehq deadline action <tenant_id> <deadline_id> <action> [--until <iso_ts>] [--new-date <yyyy-mm-dd>] [--actor <name>]
```

Arguments:

- `tenant_id`
- `deadline_id`
- `action`
  - Allowed values:
    - `complete`
    - `snooze`
    - `waive`
    - `reopen`
    - `override`
- `--until`
  - Used with `snooze`
- `--new-date`
  - Used with `override`
- `--actor`
  - Optional
  - Defaults to `cli`

Behavior:

- Executes a state-machine transition.
- Invalid transitions raise an error.

### deadline trigger-reminders

```bash
duedatehq deadline trigger-reminders --tenant-id <tenant_id> [--at <iso_ts>]
```

Arguments:

- `--tenant-id`
  - Required
- `--at`
  - Optional

Behavior:

- Triggers due reminders for that tenant at the given timestamp or now.

Returns:

```json
{
  "triggered": 8,
  "reminders": [...]
}
```

### deadline transitions

```bash
duedatehq deadline transitions <tenant_id> <deadline_id>
```

Returns:

- JSON array of transition history for the deadline

### deadline available-actions

```bash
duedatehq deadline available-actions <tenant_id> <deadline_id>
```

Returns:

```json
{
  "deadline_id": "dl-001",
  "current_status": "pending",
  "available_actions": ["complete", "snooze", "waive", "override"]
}
```

## log

### log

```bash
duedatehq log [--tenant-id <tenant_id>] [--object-id <object_id>]
```

Arguments:

- `--tenant-id`
  - Optional
- `--object-id`
  - Optional

Behavior:

- Queries audit logs.

Returns:

- JSON array of audit records

## export

### export

```bash
duedatehq export <tenant_id> [--client <client_id>] [--actor <name>]
```

Arguments:

- `tenant_id`
- `--client`
  - Optional
- `--actor`
  - Optional
  - Defaults to `cli`

Behavior:

- Exports the tenant's deadlines.
- When `--client` is set, filters the export to one client.
- Writes an audit record.

Returns:

- JSON array of exported deadlines

## today

### today

```bash
duedatehq today <tenant_id> [--limit <int>] [--enrich]
```

Arguments:

- `tenant_id`
- `--limit`
  - Optional
  - Defaults to `5`
- `--enrich`
  - Optional flag
  - Adds `client_name` and `days_remaining` to each row

Behavior:

- Returns high-priority deadlines for the tenant's today view.
- With `--enrich`, joins client names and computes remaining days for frontend-oriented rendering.

## chat

### chat

```bash
duedatehq chat [--tenant-id <tenant_id>] [--mode <text|voice>] [--prompt <text>] [--transcript-file <file>]
```

Arguments:

- `--tenant-id`
  - Optional
- `--mode`
  - Optional
  - `text` or `voice`
  - Defaults to `text`
- `--prompt`
  - Optional
- `--transcript-file`
  - Optional

Behavior:

- If `--prompt` or `--transcript-file` is provided, runs a one-shot interaction.
- If neither is provided, starts an interactive loop.
- Current `voice` mode is transcript-driven, not real audio capture.

Output shape:

- one short language reply
- one or more rendered blocks

Example:

```bash
duedatehq chat --tenant-id <tenant_id> --prompt "show me today"
duedatehq chat --tenant-id <tenant_id>
duedatehq chat --tenant-id <tenant_id> --mode voice --transcript-file sample.txt
```

## notify

### notify config add

```bash
duedatehq notify config add <tenant_id> --channel <email|sms|slack> --destination <target>
```

Arguments:

- `tenant_id`
- `--channel`
  - Required
  - `email`, `sms`, or `slack`
- `--destination`
  - Required

Behavior:

- Creates a notification route.

### notify config list

```bash
duedatehq notify config list <tenant_id>
```

Returns:

- JSON array of notification routes

### notify preview

```bash
duedatehq notify preview <tenant_id> [--within-days <int>]
```

Arguments:

- `tenant_id`
- `--within-days`
  - Optional
  - Defaults to `7`

Returns:

- JSON array of upcoming reminders

### notify history

```bash
duedatehq notify history <tenant_id>
```

Returns:

- JSON array of reminder history

### notify send-pending

```bash
duedatehq notify send-pending <tenant_id> [--smtp-host <host>] [--smtp-port <int>] [--smtp-sender <email>] [--sms-webhook <url>] [--slack-webhook <url>]
```

Arguments:

- `tenant_id`
- `--smtp-host`
- `--smtp-port`
  - Optional
  - Defaults to `25`
- `--smtp-sender`
- `--sms-webhook`
- `--slack-webhook`

Behavior:

- Sends all pending notification deliveries for the tenant.
- Uses console notifiers by default.
- SMTP or webhook options replace the default sender per channel.

Returns:

```json
{
  "sent": 8,
  "deliveries": [...]
}
```

## worker

### worker fetch

```bash
duedatehq worker fetch [--source <source>] [--state <state>] [--text-file <file> | --url <url> | --rss-url <url>] [--format <text|html|pdf>] [--source-url <url>] [--fetched-at <iso_ts>] [--entry-title-contains <text>]
```

Arguments:

- `--source`
- `--state`
- one optional mode:
  - `--text-file`
  - `--url`
  - `--rss-url`
- `--format`
  - Only used with `--url`
  - Defaults to `html`
  - Allowed values: `text`, `html`, `pdf`
- `--source-url`
  - Required when using `--text-file`
- `--fetched-at`
- `--entry-title-contains`
  - Optional RSS title filter

Behavior:

- `--text-file`: fetch from a local file
- `--url`: fetch text, HTML, or PDF
- `--rss-url`: fetch from RSS
- if no mode is given, use the default source fetcher for `--source` or `--state`

### worker schedule-reminders

```bash
duedatehq worker schedule-reminders <tenant_id> [--at <iso_ts>] [--hours <int>]
```

Arguments:

- `tenant_id`
- `--at`
  - Optional
- `--hours`
  - Optional
  - Defaults to `24`

Behavior:

- Enqueues reminder jobs in the requested window.
- Drains due jobs immediately.

Returns:

```json
{
  "jobs": [...],
  "dispatched": 0
}
```

### worker jobs

```bash
duedatehq worker jobs [--tenant-id <tenant_id>]
```

Returns:

- JSON array of queued, claimed, or completed jobs

## celery

### celery ping

```bash
duedatehq celery ping [--broker-url <url>]
```

Returns:

```json
{
  "broker_url": "redis://localhost:6379/0",
  "task_default_queue": "duedatehq"
}
```

### celery dispatch-fetch

```bash
duedatehq celery dispatch-fetch [--broker-url <url>] [--source <source>] [--state <state>]
```

Returns:

```json
{
  "task_id": "...",
  "task": "duedatehq.fetch_source"
}
```

### celery dispatch-reminders

```bash
duedatehq celery dispatch-reminders <tenant_id> [--broker-url <url>]
```

Returns:

```json
{
  "task_id": "...",
  "task": "duedatehq.schedule_reminders"
}
```

### celery dispatch-notifications

```bash
duedatehq celery dispatch-notifications <tenant_id> [--broker-url <url>]
```

Returns:

```json
{
  "task_id": "...",
  "task": "duedatehq.send_notifications"
}
```

## db

### db init

```bash
duedatehq db init
```

Behavior:

- SQLite: returns initialized
- PostgreSQL: initializes the schema

### db status

```bash
duedatehq db status
```

Returns:

- SQLite:

```json
{
  "database": "sqlite",
  "path": "C:\\..."
}
```

- PostgreSQL:

```json
{
  "database": "postgresql",
  "version": "...",
  "tenant_id": null
}
```

### db rls-check

```bash
duedatehq db rls-check
```

Constraints:

- Only works with a PostgreSQL DSN.
- Raises an error for SQLite.

Behavior:

- Runs the PostgreSQL RLS self-check.

## Known limits

These are real current limits in the CLI and should not be abstracted away in interaction-layer docs:

- `fetch --all` does not perform a true bulk fetch yet.
- `export <tenant_id>` is tenant-scoped and does not support `client_id` filtering.
- `deadline list` does not currently support:
  - `--state`
  - `--entity-type`
  - `--tax-type`
  - `--within-days`
  - `--sort`
  - `--quarter`
- `chat --mode voice` is transcript-based and not tied to live audio capture.
