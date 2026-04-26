# DueDateHQ Frontend Validation Shell

This React app is a playable validation shell for the on-demand rendering loop.

It is not the final product UI. Its job is to test whether Sarah can use a
conversation to drive work surfaces without being forced through a fixed
dashboard.

## What It Verifies

- Left side accepts real typed conversation input.
- Right side renders from `view.type` when the backend returns known views.
- `/chat/stream` SSE events can drive the UI progressively.
- Assistant answers stream through `message_delta` and render lightweight
  markdown inside the conversation bubbles.
- There is no local mode; every user turn goes through the AI backend so the
  rendered surface can act as context for the next turn.
- Unknown or open-ended needs can become a constrained `RenderSpecSurface`
  instead of a generic fallback panel.
- Random-demand smoke tests check that generated specs use allowed blocks and
  contain a concrete next step.

## Run

```bash
cd frontend
npm install
npm run dev
```

Set the backend URL if it is not running on the default:

```bash
VITE_DUEDATEHQ_API_BASE=http://127.0.0.1:8000 npm run dev
```

## Verify

```bash
npm run build
npm run test:render-spec
```
