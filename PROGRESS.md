# Progress

## Current State

The repository now has a working deterministic interaction backbone plus a small seeded demo dataset for LLM smoke tests.

## Completed Phases

### 1. Documentation Alignment

- added `docs/cli-reference.md`
- aligned `duedatehq-interaction-dev-guide-v5.md` with the current CLI surface and response shapes
- clarified LLM vs deterministic boundaries

Branch:

- `feat/conversational-realtime`

### 2. Interactive CLI Prerequisites

- added `chat` CLI mode and API entry point
- added `today --enrich`
- added deadline filtering and pagination options
- added `deadline available-actions`
- added `export --client`
- added focused tests for the new CLI and engine behavior

Branch:

- `feat/interactive-cli-prereqs`

### 3. Plan Executor Skeleton

- added `PlanExecutor`
- implemented `cli_call`, `resolve_entity`, `foreach`, and `post_filter`
- added executor tests

Branch:

- `feat/plan-executor-skeleton`

## In Progress On Top Of The Executor Branch

### Response and Interaction Pipeline

- added `ResponseGenerator`
- added `InteractionBackend`
- wired executor/response backend into `create_app()`
- added structured API helpers:
  - `process_plan(...)`
  - `process_action(...)`
- added tests for response generation, interaction backend flow, and API structured responses

### Demo Data and LLM Smoke Testing

- added `scripts/seed_small_demo.py`
- seeded one small demo tenant into the default SQLite database
- verified OpenAI connectivity using the key in `.env`
- verified one end-to-end LLM smoke test:
  - natural-language request
  - model-generated plan JSON
  - local execution through `process_plan(...)`

## Latest Local Verification

The following targeted test groups passed locally:

```bash
C:\sarah-cpa\.tools\python\3.11.9\python.exe -m pytest tests/test_executor.py --basetemp C:\sarah-cpa\.tmp\pytest
C:\sarah-cpa\.tools\python\3.11.9\python.exe -m pytest tests/test_response_generator.py tests/test_interaction_backend.py tests/test_smoke.py -k "api_ or interaction_backend or response_generator or wires_executor_and_response_generator" --basetemp C:\sarah-cpa\.tmp\pytest
```

## Next Likely Work

- formalize the temporary LLM smoke-test script into a real `llm_nlu.py`
- connect LLM-generated plans to `InteractionBackend` behind a stable interface
- introduce session persistence for the new structured interaction path
