# DueDateHQ

DueDateHQ is a deadline-intelligence workspace for CPA firms that manage
recurring tax and compliance work across many clients and jurisdictions.

It is not a tax-preparation product and it is not a client portal. The product
focuses on the layer before execution: keeping client profiles, deadlines,
blockers, extensions, reminders, and official rule changes organized enough for
the CPA to decide what should happen next.

## Product Scope

DueDateHQ helps a CPA answer three daily questions:

- What should I work on first?
- Which clients are blocked because I am missing information?
- Which official rule or deadline changes need my review before they affect the
  client portfolio?

The product combines a structured dashboard with an Ask interface. The dashboard
is the primary operating surface. Ask is used when a CPA has a natural-language
question and needs the system to render the right work surface.

## Core Workflows

1. Import clients from an existing spreadsheet or competitor export.
2. Review mapped fields and confirm which rows create or update clients.
3. Generate deadline work from client profile, state footprint, tax type, and
   extension status.
4. Triage work across active, blocked, review, overdue, extended, and archived
   states.
5. Review official rule changes, inspect source evidence, and apply or dismiss
   the downstream impact.
6. Draft client follow-ups when a work item needs missing information.

## Implementation Progress

### Client intake and profile binding

Implemented:
- CSV import with upload, column mapping, row review, new-client creation, and
  existing-client update paths.
- Client profile fields for entity type, jurisdictions, tax types, contacts,
  notes, blockers, and derived deadlines.
- Editable client detail surface.

In progress:
- AI parsing for less-structured client documents beyond clean CSV exports.
- Wider database write-through for profile updates, derived work, and import
  audit logs.

### Deadline generation and work board

Implemented:
- Deadline work generated from client profile, jurisdiction footprint, tax type,
  and extension status.
- Work board with Work now, Blocked, Needs review, Archive, Overdue, and
  Extension states.
- Work detail with source, reminders, blocker state, extension state, edit task,
  actions, and client follow-up.

In progress:
- Full API-backed board payloads and persistent state transitions across every
  front-end interaction.
- More complete filter, archive, and audit-history workflows.

### Official-source review and impact analysis

Implemented:
- Source-linked rule review surface with before/after diff and affected-client
  summary.
- Backend models for rules, notices, deadlines, review state, and audit events.
- CA/TX/NY source configuration and rule-change scenarios.

In progress:
- Repeatable source-specific fetch/parse jobs for CA, TX, and NY.
- Broader official-source coverage and production scheduling for 24-hour update
  monitoring.

### Reminder, notification, and client follow-up

Implemented:
- Reminder timeline tied to deadline urgency.
- Client follow-up draft generation from the selected work item and blocker.
- Notification settings entry points for email and Slack-style reminders.

In progress:
- Email and Slack delivery queue, preview, send history, and connection
  settings.
- Configurable reminder cadence.

### Extension, archive, and export

Implemented:
- File extension and revoke extension actions.
- Extended due date and extension status shown in Work and Client surfaces.
- Archive path for handled work.
- Export entry points and CSV-oriented data structures for client/deadline
  reporting.
- Backend export commands for tenant-scoped deadline data.

In progress:
- Extension application records, revocation audit trail, and original-vs-extended
  due date history.
- Client-facing PDF report template and view-level export packages.

### Ask, API, and CLI

Implemented:
- Ask streams through the backend and can return structured work surfaces.
- HTTP API exposes bootstrap, action, chat streaming, session, and flywheel
  endpoints for the demo runtime.
- CLI supports tenant, client, import, task, blocker, notice, deadline, export,
  notify, worker, celery, and log flows.

In progress:
- Turning source sync and notification delivery into stable API and CLI flows
  that can be used interchangeably.
- More complete backend action coverage for dashboard interactions.

## AI Boundaries

AI is used where CPA workflows are messy:

- mapping inconsistent import fields;
- interpreting official-source language;
- summarizing affected clients;
- drafting client follow-up messages;
- rendering a useful work surface from natural-language questions.

AI does not silently change tax records or perform professional filing work.
Material changes are routed through CPA review and source-visible actions.

## Running Locally

### Backend

```bash
uv sync --extra api
uv run python scripts/seed_small_demo.py
uv run uvicorn duedatehq.http_api:app --host 127.0.0.1 --port 8000
```

API smoke checks:

```bash
curl -X POST http://127.0.0.1:8000/bootstrap/today \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"2403c5e1-85ac-4593-86cc-02f8d97a8d92","today":"2026-04-26"}'

curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"2403c5e1-85ac-4593-86cc-02f8d97a8d92","session_id":"demo","message":"show California rule changes"}'
```

### Frontend

```bash
cd frontend
npm install
VITE_DUEDATEHQ_API_BASE=http://127.0.0.1:8000 npm run dev
```

Frontend checks:

```bash
cd frontend
npm run build
npm run test:render-spec
```

Backend checks:

```bash
uv run --extra api --with pytest --with httpx pytest tests/test_http_api.py -q
```

## Deployment

```bash
./scripts/deploy_frontend_ec2.sh
./scripts/deploy_backend_ec2.sh
```

Current hosted paths:

- Frontend: https://naeu-demo.dify.dev/duedatehq/
- API base: https://naeu-demo.dify.dev/demo-api/duedatehq/
- Compact deck: https://naeu-demo.dify.dev/duedatehq/due-datehq-ten-minute-story-compact.html

## Repository Map

- `frontend/`: React/Vite product UI.
- `src/duedatehq/`: domain engine, API, interaction backend, source monitoring,
  notification, and workflow infrastructure.
- `scripts/`: seed data, simulation, and deployment scripts.
- `docs/`: PRD, design notes, CLI reference, and operator guide.
- `due-datehq-ten-minute-story-compact.html`: compact product story deck.
