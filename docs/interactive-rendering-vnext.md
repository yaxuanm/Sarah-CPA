# Interactive Rendering vNext

## Purpose

This document reframes the next-step interaction direction around the product-design logic captured in `docs/interaction-design-assessment.md`.

It is not a pure technical architecture note.

It is a product-facing interaction direction document for answering one question:

- if the current interaction approach is directionally correct, what should the next version optimize for?

## 1. Starting Point

The interaction problem is not:

- how to add more AI behavior
- how to make the interface feel more agentic
- how to let the system generate more things dynamically

The real problem is:

- how to present the right work context fast enough that Sarah can confidently move her work forward

That means vNext should not be framed as "more autonomous agent capability."

It should be framed as:

- a better decision surface
- stronger intent recognition
- better preparation of working context
- safer and faster execution of user judgment

## 2. Problem Definition

The product is not solving a calendar-display problem.

It is solving a cognitive-burden problem.

Sarah's recurring pain is:

- not knowing whether something important was missed
- spending too much time reconstructing the week's working context
- switching between multiple tools just to determine what matters
- carrying responsibility for deadlines while using systems that do not create enough confidence

So the interaction system should be designed around this core question:

- what does Sarah need to act on now, and how can the system present that with minimal reconstruction effort?

## 3. Value Proposition

The product promise is not "a better tax calendar."

The product promise is:

- reduce the time required to determine what matters
- reduce omission anxiety
- present the minimum complete context required for action
- let Sarah spend time advancing work instead of rebuilding context

The strongest concrete version of that promise is:

- Sarah should be able to understand the week's actionable deadlines in under 30 seconds
- the weekly triage should take minutes instead of 45 minutes

That is the standard vNext should optimize toward.

## 4. Why This Interaction Shape Still Makes Sense

The current design direction remains fundamentally correct:

- conversational or interactive text
- dynamic rendering of context-specific views
- deterministic execution under clear confirmation boundaries

This shape works because it matches the real job.

Sarah is not opening the product to browse.

She is opening the product to respond.

Traditional dashboards assume the user should:

- browse modules
- inspect many widgets
- decide what matters
- navigate into a function area before acting

That logic is wrong for this workflow. It pushes the sorting burden back onto the user.

The better model is:

- text provides orientation and conclusion
- dynamic rendering provides a concrete working surface

The goal is not "chat-first."

The goal is:

- task-first
- decision-first
- context-compressed

## 5. Core Design Thesis For vNext

vNext should treat the interface as a stage, not a canvas.

That means:

- the center of the interface should be dominated by the single most relevant work surface
- supporting context should stay available but not compete for attention
- the system should lead with what currently requires judgment

The key design principle is:

- Sarah should be shown the minimum complete context for the judgment she needs to make now

If the system shows less, she has to search.

If the system shows more, the system is leaking complexity back to her.

## 6. The Missing Piece In The Current Direction

The current interaction model is broadly correct, but it is still too generic.

It supports:

- dynamic views
- summaries
- drill-down
- confirmation flows

What it still lacks is a sufficiently strong default stage.

The opening experience should not feel like:

- a generic conversation shell
- a freeform agent workspace
- a plain list with optional commands

It should feel like:

- the system has already prepared this week's decision surface

That is the most important shift vNext should make.

## 7. The Hero Scenario

The hero scenario should anchor the whole interaction model:

- Monday morning weekly triage during filing season

This is where the value proposition becomes concrete and measurable.

The hero scenario should define:

- what appears first
- how it is grouped
- what counts as urgent
- what actions are immediately available
- what counts as "done for now"

If this scenario is weak, the whole interaction model will feel abstract even if the architecture is sound.

## 8. The Default Decision Surface

The default surface in vNext should be a strong decision surface, not an empty shell.

Its job is to answer, immediately:

- how many things need action this week
- what is most urgent
- why it is urgent
- what Sarah can do next

The default shape should therefore privilege:

- one top-line summary
- one dominant work surface
- one clear action hierarchy

Possible supporting regions can exist, but they should remain subordinate:

- history
- audit trail
- secondary filters
- deeper drill-down

The default opening state should feel prepared, not neutral.

## 9. What vNext Should Improve

### 9.1 Stronger intent recognition

LLMs should continue to be used primarily for understanding:

- user requests
- entity references
- implied filters
- exploration versus execution intent

This remains the highest-leverage use of model capability.

### 9.2 Better work preparation

The system should do more setup work before asking the user to judge:

- gather relevant records
- organize urgency
- collect available actions
- prepare drafts where useful
- group records into meaningful work surfaces

### 9.3 Better stage selection

The system should get better at deciding which view deserves center stage.

This is not the same as "dynamic rendering" in the abstract.

It is:

- choosing the right current work surface
- suppressing less relevant structure
- preserving a strong main-stage feeling

### 9.4 Better recommendation signals

The system can help the user judge by surfacing:

- urgency
- risk
- confidence
- confirmation requirement
- likely next actions

These remain advisory signals, not autonomous decisions.

## 10. What vNext Should Not Become

The product should not evolve into:

- a general autonomous agent
- a chat-heavy assistant with weak working context
- a runtime code-generation product loop
- a system that substitutes for CPA business judgment

The correct boundary remains:

- the system recognizes intent
- the system prepares context
- the user makes the judgment
- the system executes that judgment reliably

That boundary is not a limitation. It is what makes the product trustworthy.

## 11. Technical Direction

The existing technical stack still makes sense:

- `LLM / intent recognition`
- `Planning`
- `PlanExecutor`
- `InteractionBackend`
- `ResponseGenerator`

But vNext should evaluate these layers through a more product-centered lens.

### Intent Layer

Primary job:

- understand what Sarah means with minimal friction

### Planning Layer

Primary job:

- translate that understanding into safe, deterministic work preparation

### Execution Layer

Primary job:

- perform confirmed operations reliably and audibly

### Presentation Layer

Primary job:

- render the most useful decision surface for the current task

The important shift is that presentation should no longer be treated only as "render the output of execution."

It should also be treated as:

- choose the best stage for the user's current judgment task

## 12. Near-Term Product Direction

The most realistic near-term goals are:

- sharpen the default opening surface
- anchor the experience around weekly triage
- improve one-line summaries
- improve grouping and stage selection
- improve drill-down from summary to client or deadline context
- keep confirmation and execution deterministic

This is enough to materially improve the product without changing its philosophical boundaries.

## 13. Working Conclusion

vNext should not be driven by the question:

- what else can the agent do?

It should be driven by the question:

- how do we turn the current interaction model into a stronger decision surface for Sarah?

The design logic remains sound:

- interactive text for orientation
- dynamic rendering for context-specific work surfaces
- deterministic execution for trust

What changes in vNext is emphasis.

The product should move from:

- flexible interaction system

toward:

- a sharply staged, judgment-support interaction layer centered on Sarah's real working rhythm
