# DueDateHQ Frontend UI Guidelines

## Direction

The frontend should use:

- Product structure inspired by GitHub Primer style application UI
- A light glass treatment for secondary surfaces and overlays
- High readability first, visual effects second

This is a CPA workflow product, not a marketing site. The UI should feel calm, crisp, and deliberate.

## Core Principles

1. The page should always tell the user what to do next.
2. Primary work surfaces must stay easy to read.
3. Glass effects should support hierarchy, not reduce clarity.
4. Lists and tables should feel operational, not decorative.
5. Help and guidance should be on demand, not permanently expanded.

## Visual Rules

### Structure

- Use a product-style shell with sidebar, topbar, main workspace, and assistant rail.
- Keep page hierarchy close to a mature SaaS application.
- Prefer dense but readable layouts over oversized hero sections.

### Glass Usage

Use glass styling on:

- Top navigation and page chrome
- Floating help panels
- Assistant rail cards
- Secondary cards and callouts

Do not overuse glass on:

- Dense tables
- Deadline rows
- Core data-heavy reading surfaces

Those should remain mostly solid and highly legible.

### Typography

- Use a system UI stack
- Strong contrast for headings
- Muted supporting text for context
- Avoid overly stylized fonts

### Color

- Base palette should stay close to neutral GitHub-style product colors
- Use blue as the action color
- Use amber for review states
- Use red for blockers and risk
- Use green for completed or safe states

### Radius and Motion

- Rounded but not overly soft
- Motion should be subtle: hover lift, selection glow, tooltip fade
- Avoid flashy motion on dense workflow pages

## Component Rules

### Buttons

- Primary buttons are for forward workflow actions
- Secondary buttons are for utility actions
- Destructive actions should not look primary

### Tables and Rows

- Rows must respond on hover
- Selected rows must be visually obvious
- Actions should usually live in a side panel or decision area, not explode inline

### Help

- Use a small `Help` entry or `?` icon
- Help opens as a lightweight menu or tooltip
- Never pin a large tutorial card on the page by default

### Workflow Guidance

- The product should guide with:
  - page-level next-step banner
  - contextual help menu
  - action feedback after each decision

Do not rely on large static onboarding blocks once the user is in regular usage.

## Workflow-Specific Guidance

### Dashboard

- `Track` is active work
- `Waiting on info` is blocked work
- `Notice` is policy-source review
- `Watchlist` is risk monitoring

Each lane should clearly tell the CPA:

- why the item is here
- why it matters
- what action to take next

### Import

- Show readiness and progress
- Make mapping confirmation explicit
- Make missing-field handling explicit
- Only unlock dashboard generation once the minimum useful data is ready

### Client Detail

- The user should select one obligation at a time
- The right-side action area should make the next action obvious
- State changes should update the client record immediately

### Notice Review

- The CPA should be able to:
  - read
  - dismiss
  - create task

Notice review should feel like converting policy changes into decisions, not just reading announcements.

## Implementation Note

When updating the frontend, keep using this combination:

- Primer-like structure and interaction hierarchy
- Light glass visuals on chrome and supporting surfaces
- Strong readability on core workflow surfaces
