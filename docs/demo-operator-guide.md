# DueDateHQ Demo Operator Guide

This is the short guide for running the current DueDateHQ demo from the CLI, API, and frontend.

## Demo user stories

1. Import a client portfolio.
   Upload or preview a CSV, confirm column mappings, review rows, then approve the generated work plan.

2. Weekly triage.
   Open the Work queue, inspect Work now / Blocked / Needs review / Archive, open an item, edit it, file or revoke an extension, archive it, or draft a client follow-up.

3. Official rule-change review.
   Review monitored tax-source updates, inspect source/diff/affected clients, then apply or dismiss the change.

## Frontend

Run the redesign demo:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5182/
```

The top bar includes:

- `Work`: weekly triage board.
- `Clients`: client directory and import wizard.
- `Review`: official source changes and affected-client review.
- `Settings`: workspace defaults and CPA reminder connections.
- `Ask`: separate chat workspace.
- `Docs`: this quick reference in the app UI.

## Backend API

Start the FastAPI app from the repo root:

```bash
uv run --with fastapi --with uvicorn uvicorn duedatehq.http_api:create_fastapi_app --factory --reload
```

Useful demo endpoints:

```text
POST /import/preview
GET  /review/impact/{tenant_id}
POST /review/interpret/{tenant_id}
POST /clients/{tenant_id}/{client_id}/email/draft
POST /clients/{tenant_id}/{client_id}/email
GET  /settings/{tenant_id}
PATCH /settings/{tenant_id}/notification-routes/{route_id}
```

## CLI

Show CLI help:

```bash
uv run python -m duedatehq.cli --help
```

Preview the demo import file:

```bash
uv run python -m duedatehq.cli import preview demo-data/due-datehq-demo-import.csv
```

Configure a CPA reminder route:

```bash
uv run python -m duedatehq.cli notify config add <tenant_id> --channel email --destination ops@example.com
uv run python -m duedatehq.cli notify config add <tenant_id> --channel wechat --destination wechat://johnson-cpa
```

## AI Assist

AI assist is exposed through backend services for:

- Import mapping and normalized client preview.
- Policy/rule interpretation with source metadata and affected clients.
- Client follow-up email drafts anchored to a deadline or task.

If `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` is configured, the backend uses Anthropic. Without a key, it returns deterministic fallback output through the same API path so the demo remains stable.

## Demo data

Primary demo CSV:

```text
demo-data/due-datehq-demo-import.csv
```

Handoff files:

```text
handoff/redesign-v2-handoff.md
handoff/duedatehq-mock.html
handoff/DueDateHQ — 用户故事与价值主张画布.html
handoff/DueDateHQ — 商业计划书.html
```
