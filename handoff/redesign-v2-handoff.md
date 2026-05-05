# DueDateHQ Handoff

## Background files

This folder includes the current product background files:

- `DueDateHQ — 用户故事与价值主张画布.html`
- `DueDateHQ — 商业计划书.html`
- `duedatehq-mock.html`
- `due-datehq-demo-import.csv`

## Current frontend track

Primary frontend work is happening in a separate worktree:

- Worktree: `/tmp/sarah-cpa-redesign`
- Branch: `codex/redesign-v2-frontend`
- Latest local commit seen during handoff: `804db06`

This redesign v2 track should be treated as the active UI direction.

### Frontend themes already agreed

- Keep the `redesign v2` visual style.
- Patch missing logic before adding new surface area.
- Dashboard/chat should stay separate surfaces.
- MVP demo is story-based, not feature-dump based.

### Current MVP demo stories

1. Import an existing client portfolio
2. Weekly triage on the board
3. Review and apply a state tax / rule change

## What is already working on the redesign v2 frontend

### Story 1: Import existing portfolio

- Real local CSV upload from the browser
- Local CSV parse from the uploaded file
- `Map columns` step supports:
  - manual remap
  - skip column
  - create custom field
  - lightweight "Mapping assistant (beta)" suggestion flow
- `Review rows` supports:
  - create
  - update
  - skip
- Import now has a `Review plan` step before the work enters the queue
- Import `Done` result distinguishes:
  - new clients
  - updated clients
- Imported records write back into the local `Clients` directory state

### Story 2: Weekly triage on the board

- Work queue detail opens in a dedicated sheet-style view
- Work detail supports editing:
  - task title
  - task note
  - assignee
  - due date
  - priority
  - blocker reason when blocked
- Triage buckets now behave as switches:
  - `Work now`
  - `Blocked`
  - `Needs review`
  - `Archive`
- Overdue labeling is visible
- Archive is a separate view, not a bottom card

### Story 3: Review / apply state change

- Review details / view changes are wired
- Apply / dismiss / undo have working local behavior
- Apply updates shared frontend state
- Changed badges propagate to:
  - Work
  - Clients
  - Client detail

### Clients

- `Clients -> Details` is wired
- `Client detail` exists and has been simplified to fit redesign v2 better
- `Client Directory` layout was intentionally pulled back closer to the redesign v2 original visual layout

## Current backend track

Main backend work is in the main repo worktree:

- Repo path: `/Users/scarlettmao/Desktop/test/Sarah-CPA`
- Branch seen during handoff: `codex/frontend-5section-ia`
- Latest local commit seen during handoff: `74ada1e`

### Backend work already added locally

- Real `task update` backend support
  - title
  - description
  - priority
  - owner_user_id
  - due_at
- CLI route for `task update`
- Import plan review backend path:
  - `import apply --defer-task-creation`
  - returns `proposed_plan`
  - `import approve-plan`
  - creates approved tasks
  - returns updated dashboard payload

### Important backend note

The backend changes above were developed in the main repo worktree and were validated with targeted `.venv/bin/python3.11` checks, but they were not fully moved into the redesign v2 frontend worktree.

## Known gaps / next best tasks

### Frontend

1. Wire the redesign v2 `Review plan` step to the new backend plan-review flow
2. Make reminder / blocker actions in `Work detail` more interactive
3. Reduce information density further where obvious
4. Keep repairing existing visible buttons before adding new features

### Backend

1. Expose import plan review flow to any frontend integration layer
2. Consider a real backend-driven import preview for more believable matching
3. LLM-based document handling is still not implemented

## Product decisions currently in play

- Deadline is the final constraint, not the plan itself
- System should propose work
- CPA should review and decide:
  - do now
  - do later
  - skip
- Work item is the main user-facing unit
- Internal object complexity should stay hidden from the CPA where possible

## Demo data

The included CSV is the current demo import file:

- `due-datehq-demo-import.csv`

Use it for the import story unless a fresh live CSV is preferred on-site.
