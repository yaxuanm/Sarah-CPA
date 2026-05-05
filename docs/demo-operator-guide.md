# DueDateHQ Demo Operator Guide

This guide explains the current DueDateHQ MVP demo, the product boundaries, the main user journeys, and the backend surfaces that support the frontend.

## Product Boundary

DueDateHQ is a CPA practice-management dashboard for tax deadlines. It is not a tax filing system, document portal, or return-preparation product.

The product helps a CPA firm:

- Import a client portfolio from CSV.
- Bind clients to entity type, jurisdictions, tax types, contacts, and deadline rules.
- Generate deadline-backed work items.
- Triage weekly work across active, blocked, review, extension, overdue, and archived states.
- Monitor official tax-rule changes and understand which clients are affected.
- Draft client follow-up messages from the selected work context.
- Keep an audit-friendly record of source, reminders, blockers, extensions, and activity.

## Core Demo Story

The current 5-minute demo should follow three user journeys.

### 1. Import a Client Portfolio

Start in Clients, then open Import.

Show:

- CSV upload and drag-and-drop entry.
- Column mapping review.
- Manual mapping edits.
- AI-assisted mapping correction.
- Row review before write.
- Final result showing new clients and updated existing clients.
- Client directory reflecting the imported or updated records.

What this proves:

- A CPA does not need to manually enter a portfolio for a week.
- Existing clients are updated in place.
- New clients become cards in the directory.
- Imported profile fields drive derived deadline work.

### 2. Weekly Triage on the Work Board

Start in Work.

Show:

- Work now: items the CPA can act on today.
- Blocked: items waiting on client documents, confirmation, or profile details.
- Needs review: items produced by official-rule changes that still require a CPA decision.
- Archive: handled items that are no longer active work.
- Overdue labels when due dates have passed.
- Work detail with source, reminders, blocker status, extension state, edit task, action menu, and client follow-up.

What this proves:

- The product is organized around what the CPA should do next.
- Deadline urgency and workflow state are separate but both visible.
- The CPA can manually edit work, file or revoke extensions, mark blocked, archive, and request client follow-up.

### 3. Respond to an Official Rule Change

Start in Review.

Show:

- Official change queue.
- Source link.
- Before and after rule diff.
- Affected clients.
- Review detail showing exactly what each client changes to.
- Apply or dismiss decision.
- Applied changes surfacing in related client detail, calendar/work surfaces, and activity.

What this proves:

- DueDateHQ watches official sources.
- The system interprets a rule change into portfolio impact.
- The CPA remains the final decision-maker for ambiguous or material changes.

## Core Object Model

The smallest user-visible operational unit is a work item.

A work item should include:

- Client.
- Tax type.
- Jurisdiction.
- Due date.
- Status.
- Assignee.
- Source.
- Reminder plan.
- Blocker reason.
- Extension state.
- Activity history.

The frontend may show different layouts for Work, Clients, Review, and Settings, but the user should feel that every actionable row is one work item moving through a clear lifecycle.

## Work Statuses

- Active: the CPA can work on the item now.
- Blocked: the item cannot move because information is missing.
- Needs review: the item is waiting for a CPA decision about a rule or notice.
- Extension requested or approved: an extension action has changed the expected due date.
- Overdue: the due date has passed and the item is not archived.
- Archived: the item has been handled and removed from active triage.

## AI Features

AI should be shown only where it transforms messy input into structured work.

Current AI moments:

- Import mapping: infer CSV field mappings and help fix incorrect mappings.
- Import row interpretation: identify new versus existing clients and explain row issues.
- Policy interpretation: extract rule-change details and affected clients from official source text.
- Client follow-up: draft an email from the selected work item, blocker, due date, assignee, and contact.

UI principle:

- Do not place AI badges everywhere.
- Use lightweight indicators near the transformation action.
- Do not prefill generated content before the user clicks Generate or AI draft.

Backend principle:

- Use provider-backed AI when credentials are configured.
- Use deterministic fallback through the same API path when credentials are missing, so demos remain stable.

## Reminder And Email Logic

Reminder rows represent planned outreach or internal alerts derived from a work item and its due date.

For the demo:

- The system may queue or simulate email delivery.
- The UI should make clear that client follow-up is attached to a work item, not a standalone inbox.
- Sending a follow-up can move the item to Blocked, because the CPA is now waiting on client response.

Settings should support:

- Email reminder channel.
- WeChat or SMS-style CPA reminder channel.
- Editable defaults for reminder cadence and firm settings.

## Backend Routes

Useful API routes for the current demo:

```text
POST /bootstrap/today
POST /import/preview
POST /review/interpret/<tenant_id>
GET /review/impact/<tenant_id>
GET /settings/<tenant_id>
PATCH /settings/<tenant_id>/notification-routes/<route_id>
POST /clients/<tenant_id>/<client_id>/email/draft
POST /clients/<tenant_id>/<client_id>/email
```

## Local Commands

Run the backend API:

```bash
uv run --with fastapi --with uvicorn uvicorn duedatehq.http_api:create_fastapi_app --factory --reload --port 8000
```

Seed demo data:

```bash
uv run python scripts/seed_small_demo.py
```

Run the frontend against the local API:

```bash
cd frontend
VITE_DUEDATEHQ_API_BASE=http://127.0.0.1:8000 npm run dev
```

Preview import parsing from CLI:

```bash
uv run python -m duedatehq.cli import preview demo-data/due-datehq-demo-import.csv
```

Add a notification route from CLI:

```bash
uv run python -m duedatehq.cli notify config add <tenant_id> --channel email --destination ops@example.com
```

## Demo Quality Checklist

Before presenting:

- Import flow uses a real CSV file and does not jump straight to fake results.
- AI draft fields are blank before the user clicks AI draft.
- Work detail can edit task fields.
- Actions menu is compact and uses icons.
- Extensions can be filed and revoked.
- Overdue status is visible.
- Review detail shows affected-client changes, not just a generic card.
- Settings inputs are editable.
- Docs button opens this summary in the app.
- Local build passes.

