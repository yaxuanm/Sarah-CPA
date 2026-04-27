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
- Free-form input is now Agent-first. Claude gets the first chance to interpret
  the user's real need and decide whether to answer, gather more data, render a
  purpose-built surface, or hand off. Deterministic/planner routes are now a
  fallback for explicit object navigation such as `打开第 1 条`, not a semantic
  gate in front of the model.
- Added the first real dual-path interaction contract. Known buttons and list
  rows can carry a `direct_execute` action with a complete plan and expected
  view; the frontend sends those to `/action` instead of converting the click
  into a natural-language prompt.
- `ClaudeAgentKernel` now uses Anthropic's native SDK Tool Use flow plus a
  small ReAct loop. The model can call controlled read tools such as
  `get_current_view`, `list_all_clients`, `list_all_deadlines`,
  `list_client_deadlines`, `list_blockers`, and `list_tasks`, observe the
  results, then return one constrained routing/rendering decision.
- Tool Use is still bounded by DueDateHQ's allowed action space. The LLM can
  decide what it needs to inspect, but writes remain behind `ConfirmCard`, and
  backend code still builds the final `view.type` payload.
- Claude Agent Kernel no longer lets the local deterministic guard block model
  reasoning when Claude is available. The local guard remains only as an
  outage/low-confidence fallback and for clearly deterministic planner handoff.
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
  a frozen "thinking" bubble. The first text is user-facing assistant copy such
  as “好的，我帮你看看今天哪些事最需要先处理”, not an internal status line.
- `/chat/stream` now emits a separate `thinking` event immediately after the
  opening reply. The frontend renders it as a lightweight status line while the
  backend is reading data or planning the work surface.
- `/bootstrap/today` is the fast default entry. It bypasses Agent/NLU and
  directly renders the today `ListCard`, because opening the daily queue is the
  product's default starting state rather than an ambiguous user intent.
- `/action` is now the deterministic button path. Read actions execute their
  plan and render the expected stock surface without Agent/NLU. Write actions
  still stop at `ConfirmCard`; direct actions do not bypass confirmation.
- `/action` now also supports deterministic button commands such as
  `confirm_pending` and `cancel_pending`. Confirm/cancel clicks no longer go
  through `/chat` or Agent interpretation; they operate on the current session's
  pending action and then re-render state.
- Sessions now maintain the first minimal `SystemState` fields from
  `duedatehq-interaction-architecture.md`: `current_workspace`,
  `previous_workspace`, `breadcrumb`, `operation_log`, and `prefetch_pool`.
  Existing `current_view`, `selectable_items`, and `current_actions` are kept as
  the concrete rendering payloads under that same state.
- `ListCard` generation now precomputes the visible rows' target
  `ClientWorkspace` snapshots. Row actions carry `prefetch_key`, `view_data`,
  `selectable_items`, and `workspace`, so the frontend can switch instantly
  without routing a deterministic click through the Agent.
- Added a workspace registry that gives Agent/SystemState a shared semantic
  contract for `TodayQueue`, `ClientWorkspace`, `AuditWorkspace`,
  `ConfirmWorkspace`, `GuidanceWorkspace`, and generated work surfaces.
- Added a cross-workspace guard for edit-like requests from read-only
  workspaces. For example, asking to change a due date while looking at
  `AuditWorkspace` now returns a deterministic guidance surface with a direct
  action back to `ClientWorkspace` instead of letting Agent invent an edit path.
- Added the first `WorkSurfacePlanner` slice. It introduces explicit
  `NeedFrame`, `EvidencePlan`, `SurfaceDecision`, `SurfacePlan`, and
  `ActionContract` structures between Agent understanding and rendering.
- Registered the first purpose-built surface kind, `TaxChangeRadar`, for
  monitoring tax changes / notices / rule changes that may affect current
  clients. This path does not let the current page hijack the user request, and
  it states the data boundary when realtime external tax news is unavailable.
- `scripts/seed_small_demo.py` now seeds enough fictional tax data for the
  policy/tax-change use case to be visible in the product shell: four demo rule
  signals, two rule-review queue entries, three escalated notice scenarios, and
  notice-derived tasks/blockers tied back to demo clients.
- The tax demo seed is idempotent. Re-running it updates/ensures the demo
  notices and skips already-created notice work, so local validation can reset
  frontend sessions without duplicating tasks or blockers.
- Agent decisions can now request rules, rule review queue, notices, clients,
  and deadlines, and can explicitly select `surface_kind=TaxChangeRadar`. This
  lets policy/tax-change questions become a registered work surface instead of
  a generic fallback panel.
- Split work-surface composition out of `InteractionBackend` into
  `SurfaceComposer`. The backend now routes the turn; the composer owns the
  translation from `WorkSurfacePlan` / `AgentKernelDecision` into concrete
  view payloads. This is the first cleanup step toward replacing the old
  fallback-style agent/rendering code with a dedicated surface runtime.
- Removed the old free-text `prepare request` known-route shortcut. Natural
  language draft/preparation requests now stay on the Agent path; only
  deterministic button clicks and explicit visible-item navigation use the
  direct/planner path.

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
  - `TaxChangeRadarCard`
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
- List rows now prefer backend-provided direct actions over text prompts. A row
  click executes the embedded plan through `/action`, which keeps stable
  `ClientCard` navigation out of the Agent path.
- Current-page questions such as “这几件事分别是什么” are handled as normal
  assistant answers while keeping the right-side page unchanged.
- Assistant answers now stream into the left conversation via `message_delta`
  instead of appearing only after `done`.
- The frontend displays backend `thinking` events instead of ignoring them, so
  the user sees active analysis while the right side keeps the current surface
  stable until a result is ready.
- Thinking is rendered as one live status bubble with a pulsing indicator. It
  updates through the turn instead of appending multiple internal log lines.
- The frontend renders lightweight markdown in assistant/user bubbles:
  bold text, inline code, ordered lists, unordered lists, and line breaks.
- Streamed answer chunks now prefer sentence/list boundaries, and the frontend
  normalizes inline numbered markdown into readable list blocks.
- Unknown/random needs generate a constrained `RenderSpecSurface` instead of a
  generic fallback panel.
- Quick action buttons are no longer locally invented by the frontend for
  `ListCard` / `ClientCard`; they come from backend actions or Agent-generated
  `RenderSpecSurface` choices.
- `RenderSpecSurface` choice buttons can now carry direct actions. For example,
  the generated client-message draft surface wires `记录为已发送`, `查看依据`,
  and `回到今日清单` to deterministic actions instead of sending those labels
  back through the Agent as natural language.
- `ConfirmCard` confirmation/cancellation is now a deterministic command path.
  This aligns the prototype with `duedatehq-interaction-architecture.md`:
  button clicks are operations over the current system state, while free-form
  input remains the Agent path.
- Prefetched row actions update the frontend's local workspace state when they
  switch views instantly, preserving `previous_workspace` and `breadcrumb` for
  the next Agent turn.
- `GuidanceCard` now uses backend-provided title/eyebrow copy. It no longer
  hard-codes "Choose the item first" for unrelated guidance such as workspace
  permission boundaries.
- `RenderSpecSurface` can now carry `surface_kind` and
  `data_boundary_notice`, so generated work surfaces can present themselves as
  purpose-built surfaces such as `TaxChangeRadar` rather than generic fallback
  panels.
- `TaxChangeRadar` no longer renders through generic `RenderSpecSurface`.
  It now has a dedicated `TaxChangeRadarCard` with a visible data-boundary
  notice, metrics, rule/notice signals, and impacted deadline rows. This keeps
  registered work surfaces visually distinct from true fallback/ad-hoc specs.
- The conversation timeline now records Sarah's action for every button or row
  click before the system response. Direct actions, prefetched view switches,
  confirmation buttons, and generated-surface choices all echo the clicked
  label into the left rail, so the interaction remains a two-sided transcript.
- `npm run test:render-spec` verifies random demands become valid specs with a
  concrete next step.

## Latest Verification

Backend:

```bash
.tmp/push-venv/bin/python -m pytest
# 137 passed, 1 skipped
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
tax demo seed smoke passed: demo DB has 3 escalated notices and 2 rule-review items
TaxChangeRadar SSE smoke passed: policy-change query returned TaxChangeRadarCard with notice, review, and rule signals
```

## Current Boundary

The system can now test playability, but it is not yet the final production
agent.

Still open:

- frontend is a validation shell, not production routing
- unknown-demand `render_spec` generation still exists as a fallback. It should
  keep shrinking as more Agent-selected registered surfaces are added.
- `WorkSurfacePlanner` currently covers only the first registered surface kind
  (`TaxChangeRadar`). `ClientImpactMatrix`, `WeeklyExecutionList`, and
  `SourceAudit` still need the same treatment and should become dedicated
  cards instead of `RenderSpecSurface` payloads.
- production semantic retrieval still needs embedding/pgvector/rerank
- Sonnet response generation is not connected
- Agent Kernel now covers answer/keep-view, planner handoff, native Tool Use
  reads, and the first registered strategy surface. It is still not a complete
  autonomous multi-step workflow planner for writes.

## Next Likely Work

- add browser-level tests for deterministic row/button paths and workspace
  guards
- move constrained `render_spec` generation behind backend validation
- add browser-level tests for Sarah's full loop:
  `today -> focus client -> prepare draft -> confirm sent -> return to list`
