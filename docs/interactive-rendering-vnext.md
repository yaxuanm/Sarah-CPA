# Interactive Rendering vNext

## Positioning

The current interaction stack is a strong first step:

- natural language or button input
- plan generation
- deterministic execution
- structured response rendering

That architecture upgrades DueDateHQ from a raw CLI into a usable interaction layer. But recent agent capabilities suggest a larger opportunity.

Modern LLM agents can already:

- call tools reliably
- write small amounts of code on demand
- compose temporary UI structures at runtime
- reason across multiple steps before returning a result

The next version of interaction should not stop at "translate language into commands." It should move toward "produce working results for the operator."

## Product Thesis

DueDateHQ should evolve from a command translator into a task agent for tax operations.

That means the interaction layer should increasingly help Sarah:

- decide what matters now
- assemble the right working context
- prepare draft outputs
- batch safe work
- pause only where human judgment is required

The goal is not to make the product feel more like a chatbot. The goal is to make it feel more like a capable operating partner.

## What Changes

### 1. From Answers To Work Products

Today:

- "What is due today?"
- "Show California clients."
- "What notifications are pending?"

Next:

- "Rank the five most important things to handle today and explain why."
- "Build a worklist for deadlines due in 14 days that still need reminders."
- "Draft reminder messages for these clients and let me confirm send."

The output is no longer just data retrieval. It becomes a work product:

- prioritized action list
- grouped work queue
- draft communication
- batch confirmation package

### 2. From Fixed Cards To Task-Specific Workspaces

The current response model uses a fixed set of cards such as:

- `ListCard`
- `ClientCard`
- `ConfirmCard`
- `GuidanceCard`

Those remain useful, but vNext should allow the agent to compose a higher-level workspace schema for a task.

Examples:

- a quarterly filing prep board
- a "needs reminder" action panel
- a client operations card with timeline, history, and next actions
- a disaster-extension watch board

The frontend would still render deterministically, but it would render from a richer agent-selected schema rather than only from a small set of static views.

### 3. From Single Commands To Managed Flows

The executor today handles multi-step plans. vNext should let the agent use that ability to manage larger flows while preserving confirmation boundaries.

Examples:

- identify deadlines due this week
- filter to records with no reminder sent
- group by channel availability
- draft reminder messages
- present one confirmable batch

Or:

- identify suspicious state mismatches
- classify them
- propose fixes
- let the operator confirm only the risky writes

This is the difference between command execution and operational assistance.

### 4. From State Awareness To Strategy Awareness

A stronger interaction layer should not only know the system state. It should also help evaluate:

- urgency
- risk
- importance
- whether a task can be batched
- whether a task requires explicit human review

That suggests a strategy layer with scores or labels such as:

- urgency score
- risk score
- confidence score
- confirmation requirement
- batchability

The agent can then justify recommendations instead of just listing records.

### 5. From Static Capability To Controlled Self-Extension

This is the most ambitious direction.

If the agent can already write code and compose renderable structures, then some narrow classes of missing capability do not always need to wait for a full product cycle.

Possible examples:

- temporary reporting views
- one-off filters
- ad hoc grouped summaries
- temporary visualizations
- narrowly scoped data investigation helpers

This should only happen inside strict guardrails. But if done well, it gives the product a controlled path to generate short-lived operator tooling before promoting repeated patterns into permanent features.

## Capability Ladder

### Near Term

These are realistic on top of the current architecture:

- LLM-generated plans for read-heavy tasks
- richer recommendation messages
- prioritized action lists
- grouped and ranked work queues
- reminder draft generation
- batch confirmation payloads

### Mid Term

These likely require a richer response schema and frontend support:

- task-specific workspaces
- multi-panel operational dashboards generated from context
- durable drafts and pending confirmation queues
- "resume where I left off" interaction state

### Long Term

These are high-upside but require stronger controls:

- generated temporary reports or query helpers
- agent-authored micro-views for novel questions
- controlled code or query generation inside a sandbox
- adaptive operational tooling that can later be promoted into first-class product features

## Required Guardrails

More capability is only useful if the trust boundaries remain clear.

The following constraints should stay firm:

- execution remains deterministic
- writes remain auditable
- risky actions require explicit confirmation
- rendered output is validated against a server-owned schema
- generated code or queries run only in a sandboxed and observable environment
- the agent never becomes the final authority on business rules or legal interpretation

The right model is not "let the LLM do everything." The right model is "let the agent do more preparation and orchestration while the system keeps control of execution and safety."

## Architectural Direction

The current stack remains the right base:

- `LLM / planner`
- `PlanExecutor`
- `InteractionBackend`
- `ResponseGenerator`

vNext extends this with three additional ideas:

1. A strategy layer

- ranking
- grouping
- risk labels
- confirmation policy

2. A richer workspace schema

- task boards
- grouped action panels
- draft queues
- resumable operator context

3. A controlled extension layer

- temporary query helpers
- temporary reporting blocks
- sandboxed generated utilities

## Practical Framing

This vision should not replace the current implementation guide.

`duedatehq-interaction-dev-guide-v5.md` should remain the execution-focused guide for the current phase.

This document is a product and architecture direction for what comes next after the deterministic interaction backbone is stable.

## Core Takeaway

The biggest upgrade is not "better chat."

The biggest upgrade is a shift from:

- translating user language into system commands

to:

- producing structured, confirmable, high-value work on the user's behalf

That is the path from interactive CLI wrapper to agent-assisted tax operations workspace.
