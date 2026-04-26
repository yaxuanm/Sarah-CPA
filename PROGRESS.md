# Progress

## Current State

The repository now has a deterministic interaction backend, flywheel validation
infrastructure, optional Claude NLU, a minimal FastAPI/SSE surface, and a
playable React frontend validation shell.

The frontend is not the final product UI. It exists to test whether the core
interaction is playable:

```text
left conversation input
  -> AI/SSE backend
  -> view.type / render_spec
  -> right-side work surface
```

## Completed

### Backend Interaction Loop

- `InteractionBackend.process_message()` handles natural-language input,
  confirmation, cancellation, pending write actions, and session updates.
- Added an Agent Kernel layer before planner execution. It is now the intended
  first reasoning hop: a smart agent decides whether to answer from the visible
  surface, call tools for more data, render a new work surface, ask for one
  missing bit of context, prepare a confirmable action, or pass through to the
  flywheel/planner fast path.
- `ClaudeAgentKernel` now uses Anthropic's native SDK Tool Use flow plus a
  small ReAct loop. The model can call controlled read tools such as
  `get_current_view`, `list_all_clients`, `list_all_deadlines`,
  `list_client_deadlines`, `list_blockers`, and `list_tasks`, observe the
  results, then return one constrained routing/rendering decision.
- Tool Use is still bounded by DueDateHQ's allowed action space. The LLM can
  decide what it needs to inspect, but writes remain behind `ConfirmCard`, and
  backend code still builds the final `view.type` payload.
- Removed the legacy `AgentPolicy` layer and the hard-coded portfolio/priority
  strategy branches. Semantic work surfaces now go through the Agent Kernel's
  `view_goal`, data requests, and optional `suggested_actions` instead of
  backend keyword mappings.
- `PlanExecutor` calls engine functions directly.
- `ResponseGenerator` returns structured `view.type` payloads for known work
  surfaces.
- Write actions render `ConfirmCard` before mutation.

### Flywheel Validation

- `InMemoryIntentLibrary` and `SQLiteIntentLibrary` support template learning,
  matching, feedback events, and review queues.
- `FlywheelIntentRouter` can route cache-first and fall back to planner/NLU.
- It skips cache for short/fuzzy visible-client navigation such as `go to gree`,
  so stale templates cannot override current page context.
- Follow-up classification records correction and missing-info signals.
- Runtime and convergence scripts validate cost reduction and template reuse.

### Optional LLM Path

- `ClaudeNLUService` can be enabled with `DUEDATEHQ_USE_CLAUDE_NLU=1`.
- `ClaudeAgentKernel` can be enabled with `DUEDATEHQ_USE_AGENT_KERNEL=1`
  or the legacy `DUEDATEHQ_USE_AGENT_POLICY=1` flag. It makes Sonnet choose
  the per-turn route before planner/executor through Tool Use + ReAct. Default
  tests use the deterministic kernel.
- The default Claude NLU/eval model is now `claude-sonnet-4-6`; Haiku remains
  available through `CLAUDE_NLU_MODEL` when cost is the priority.
- `PlanValidator` validates LLM output through schema, command allowlist, and
  write-operation constraints.
- Real Claude eval scripts exist for labeled samples.

### HTTP/SSE

- Optional FastAPI app exposes `/chat`, `/action`, `/chat/stream`,
  `/bootstrap/today`, `/session/:id`, and `/flywheel/stats`.
- `/chat/stream` emits `message_delta`, `intent_confirmed`, `view_rendered`,
  `feedback_recorded`, and `done`.
- `/chat/stream` now sends an immediate `message_delta` before expensive Agent
  reasoning, so the conversation starts streaming right away instead of showing
  a frozen "thinking" bubble.
- `/bootstrap/today` is the fast default entry. It bypasses Agent/NLU and
  directly renders the today `ListCard`, because opening the daily queue is the
  product's default starting state rather than an ambiguous user intent.

### Frontend Validation Shell

- Added `frontend/` React/Vite app.
- Left side is a real typed conversation surface.
- Right side renders known backend views:
  - `ListCard`
  - `ClientCard`
  - `ConfirmCard`
  - `HistoryCard`
  - `ReminderPreviewCard`
  - `ClientListCard`
  - `ReviewQueueCard`
- Frontend connects to `/chat/stream` through the SSE client. There is no Local
  mode; the UI is only an AI-backend validation shell.
- On startup it loads the backend's real today list first, so the page and
  backend reason over the same customer dataset. This uses `/bootstrap/today`
  instead of `/chat/stream`, so the first screen appears without waiting for
  Agent reasoning.
- The frontend now sends structured visual context with each SSE request:
  current view summary, visible clients/deadlines/actions, and recently viewed
  surfaces. This gives the NLU enough context to interpret partial requests.
- Backend list responses now backfill customer names for plain deadline rows,
  and frontend list rows open the visible item by relative reference, e.g.
  `打开第 2 条`, instead of guessing from a possibly duplicated customer name.
- Current-page questions such as “这几件事分别是什么” are handled as normal
  assistant answers while keeping the right-side page unchanged.
- Assistant answers now stream into the left conversation via `message_delta`
  instead of appearing only after `done`.
- The frontend renders lightweight markdown in assistant/user bubbles:
  bold text, inline code, ordered lists, unordered lists, and line breaks.
- Streamed answer chunks now prefer sentence/list boundaries, and the frontend
  normalizes inline numbered markdown into readable list blocks.
- Unknown/random needs generate a constrained `RenderSpecSurface` instead of a
  generic fallback panel.
- Quick action buttons are no longer locally invented by the frontend for
  `ListCard` / `ClientCard`; they come from backend actions or Agent-generated
  `RenderSpecSurface` choices.
- `npm run test:render-spec` verifies random demands become valid specs with a
  concrete next step.

## Latest Verification

Backend:

```bash
.tmp/push-venv/bin/python -m pytest
# 123 passed, 1 skipped
```

Frontend:

```bash
cd frontend
npm run build
npm run test:render-spec
```

Result:

```text
vite build passed
render-spec smoke passed: 6 random demands generated useful constrained surfaces
agent-kernel smoke passed: "这五件事分别是什么" kept ListCard and answered from current view
strategy smoke passed: all-client status and least-urgent questions render constrained strategy surfaces
SSE smoke passed: /chat/stream emitted message_delta before done
```

## Current Boundary

The system can now test playability, but it is not yet the final production
agent.

Still open:

- frontend is a validation shell, not production routing
- real backend demo data must be seeded for browser-to-SSE testing
- unknown-demand `render_spec` generation is currently deterministic backend
  logic, not yet a backend LLM-assisted generator
- production semantic retrieval still needs embedding/pgvector/rerank
- Sonnet response generation is not connected
- Agent Kernel now covers answer/keep-view, planner handoff, and the first
  strategy surfaces. It is not yet doing full multi-step planning or tool
  orchestration.

## Next Likely Work

- seed a browser-ready demo tenant and document how to start FastAPI + frontend
- connect frontend action buttons to `/action` for direct plan execution
- move constrained `render_spec` generation behind backend validation
- add browser-level tests for Sarah's full loop:
  `today -> focus client -> prepare draft -> confirm sent -> return to list`
