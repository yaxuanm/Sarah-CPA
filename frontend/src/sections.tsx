// sections.tsx
// 5-section IA components. Each section owns the affordances unique to its
// page (filters, mock-data labels, etc.) and delegates the ViewEnvelope
// rendering to <ViewRenderer> from cards.tsx.
//
// Architectural rule from duedatehq-frontend-skill/SKILL.md:
//   - Chat drawer  → natural language only
//   - Section body → structured data only
// So sections never carry their own message history; they only fetch plans
// (via runPlan callbacks) and render the resulting view envelope.

import { ReactElement, useEffect, useMemo, useState } from "react";
import type { DirectAction, ViewEnvelope } from "./types";
import { ViewRenderer } from "./cards";
import { DirectActionHandler, EmptyStateRow, EyebrowHeader } from "./coreUI";
import {
  blockerListPlan,
  clientListPlan,
  notifyPreviewPlan,
  ruleReviewQueuePlan,
  todayPlan,
  upcomingDeadlinesPlan
} from "./plans";

export type SectionId = "today" | "calendar" | "clients" | "updates" | "settings";

export type SectionDispatch = (
  plan: Record<string, unknown>,
  expectedView: string,
  echo: string
) => void;

export type SectionContext = {
  tenantId: string;
  view: ViewEnvelope;
  busy: boolean;
  dispatch: SectionDispatch;
  onPrompt: (prompt: string) => void;
  onAction: DirectActionHandler;
};

export const sectionMeta: Record<SectionId, { eyebrow: string; title: string; subtitle: string }> = {
  today: {
    eyebrow: "Today",
    title: "Work that should move now",
    subtitle: "Active deadlines and follow-ups for the current portfolio."
  },
  calendar: {
    eyebrow: "Calendar",
    title: "Upcoming deadlines",
    subtitle: "Filter by horizon or jurisdiction to plan ahead without losing context."
  },
  clients: {
    eyebrow: "Clients",
    title: "Client directory",
    subtitle: "Open a client to review their tax profile and active deadlines."
  },
  updates: {
    eyebrow: "Updates",
    title: "Notices, reminders, and rule review",
    subtitle: "External signals that may turn into work — review before escalating."
  },
  settings: {
    eyebrow: "Settings",
    title: "Workspace settings",
    subtitle: "Tenant, notification channels, and integration preferences."
  }
};

// ---------- Today ----------

export function TodaySection({ tenantId, view, dispatch, onPrompt, onAction }: SectionContext) {
  useEffect(() => {
    dispatch(todayPlan(tenantId), "ListCard", "Open today's work");
    // Run only on mount + tenant change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  return (
    <div className="section-shell">
      <ViewRenderer view={view} onPrompt={onPrompt} onAction={onAction} tenantId={tenantId} />
    </div>
  );
}

// ---------- Calendar ----------

type Horizon = { key: string; label: string; days: number };

const horizonOptions: Horizon[] = [
  { key: "this-week", label: "This week", days: 7 },
  { key: "next-30", label: "Next 30 days", days: 30 },
  { key: "quarter", label: "Quarter", days: 90 }
];

const jurisdictionOptions = ["All", "California", "Texas", "New York", "Federal"];

export function CalendarSection({ tenantId, view, dispatch, onPrompt, onAction }: SectionContext) {
  const [horizon, setHorizon] = useState<Horizon>(horizonOptions[0]);
  const [jurisdiction, setJurisdiction] = useState<string>(jurisdictionOptions[0]);

  useEffect(() => {
    const plan = upcomingDeadlinesPlan(
      tenantId,
      horizon.days,
      jurisdiction === "All" ? {} : { jurisdiction }
    );
    dispatch(plan, "ListCard", `Show ${horizon.label.toLowerCase()} deadlines`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, horizon.key, jurisdiction]);

  return (
    <div className="section-shell">
      <section className="card section-filter-card">
        <EyebrowHeader
          eyebrow="Filters"
          title="Narrow the calendar"
          subtitle="Choose a horizon and a jurisdiction. The list below updates automatically."
        />
        <div className="section-filters">
          <div className="filter-group">
            <span className="filter-label">Horizon</span>
            <div className="filter-chips">
              {horizonOptions.map((option) => (
                <button
                  key={option.key}
                  className={`filter-chip ${option.key === horizon.key ? "active" : ""}`}
                  onClick={() => setHorizon(option)}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className="filter-group">
            <span className="filter-label">Jurisdiction</span>
            <div className="filter-chips">
              {jurisdictionOptions.map((option) => (
                <button
                  key={option}
                  className={`filter-chip ${option === jurisdiction ? "active" : ""}`}
                  onClick={() => setJurisdiction(option)}
                  type="button"
                >
                  {option}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>
      <ViewRenderer view={view} onPrompt={onPrompt} onAction={onAction} tenantId={tenantId} />
    </div>
  );
}

// ---------- Clients ----------

export function ClientsSection({ tenantId, view, dispatch, onPrompt, onAction }: SectionContext) {
  useEffect(() => {
    dispatch(clientListPlan(tenantId), "ClientListCard", "Show all clients");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  return (
    <div className="section-shell">
      <ViewRenderer view={view} onPrompt={onPrompt} onAction={onAction} tenantId={tenantId} />
    </div>
  );
}

// ---------- Updates ----------

type UpdatesTab = "reminders" | "rules" | "blockers";

const updatesTabs: Array<{ key: UpdatesTab; label: string; description: string }> = [
  {
    key: "reminders",
    label: "Reminder preview",
    description: "Reminders queued to send in the next seven days. Review before they go out."
  },
  {
    key: "rules",
    label: "Rule review",
    description: "Pending tax-rule changes that need a CPA decision before becoming work."
  },
  {
    key: "blockers",
    label: "Open blockers",
    description: "Clients waiting on documents or confirmations across the portfolio."
  }
];

export function UpdatesSection({ tenantId, view, dispatch, onPrompt, onAction }: SectionContext) {
  const [tab, setTab] = useState<UpdatesTab>("reminders");

  useEffect(() => {
    if (tab === "reminders") {
      dispatch(notifyPreviewPlan(tenantId, 7), "ReminderPreviewCard", "Show reminder preview");
    } else if (tab === "rules") {
      dispatch(ruleReviewQueuePlan(), "ReviewQueueCard", "Show rule review queue");
    } else {
      dispatch(blockerListPlan(tenantId), "ListCard", "Show open blockers");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, tab]);

  const activeMeta = useMemo(() => updatesTabs.find((entry) => entry.key === tab)!, [tab]);

  return (
    <div className="section-shell">
      <section className="card section-tab-card">
        <EyebrowHeader eyebrow="Updates" title={activeMeta.label} subtitle={activeMeta.description} />
        <div className="section-tabs">
          {updatesTabs.map((entry) => (
            <button
              key={entry.key}
              className={`section-tab ${entry.key === tab ? "active" : ""}`}
              type="button"
              onClick={() => setTab(entry.key)}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </section>
      <ViewRenderer view={view} onPrompt={onPrompt} onAction={onAction} tenantId={tenantId} />
    </div>
  );
}

// ---------- Settings ----------
// The backend exposes notify.config via CLI but not via PlanExecutor, so this
// section is intentionally static. Configuration changes go through the chat
// drawer (which routes to a real backend command path).

export function SettingsSection({ tenantId, onPrompt }: SectionContext) {
  return (
    <div className="section-shell">
      <article className="card">
        <EyebrowHeader
          eyebrow="Tenant"
          title="Workspace identity"
          subtitle="The tenant ID below is the value sent on every backend request."
          pillLabel="Read-only"
          pillTone="blue"
        />
        <div className="settings-grid">
          <div className="settings-row">
            <span>Tenant ID</span>
            <code>{tenantId}</code>
          </div>
          <div className="settings-row">
            <span>Display name</span>
            <strong>Johnson CPA PLLC</strong>
          </div>
        </div>
      </article>

      <article className="card">
        <EyebrowHeader
          eyebrow="Notifications"
          title="Reminder and notice channels"
          subtitle="Channel configuration is currently managed via the chat drawer because the backend exposes notify.config only through a CLI path."
        />
        <EmptyStateRow
          title="Configure a channel"
          body="Ask the assistant — for example: 'Add an email reminder channel for Northwind Services'."
        />
        <div className="settings-row">
          <span>Configure via chat</span>
          <button
            className="primary"
            type="button"
            onClick={() => onPrompt("Show notification channel configuration")}
          >
            Open in chat
          </button>
        </div>
      </article>

      <article className="card">
        <EyebrowHeader
          eyebrow="Imports"
          title="Client data import"
          subtitle="Importing a client roster runs through the backend import.preview / import.apply plan path."
        />
        <EmptyStateRow
          title="Start an import"
          body="Drag a CSV into the chat drawer to preview the mapping before any record is written."
        />
        <div className="settings-row">
          <span>Begin via chat</span>
          <button
            className="primary"
            type="button"
            onClick={() => onPrompt("I want to import a client portfolio CSV")}
          >
            Open in chat
          </button>
        </div>
      </article>
    </div>
  );
}

// ---------- Helper: the section nav ----------

export const sectionOrder: SectionId[] = ["today", "calendar", "clients", "updates", "settings"];

export function SectionNav({
  current,
  onSelect
}: {
  current: SectionId;
  onSelect: (next: SectionId) => void;
}) {
  return (
    <nav className="section-nav">
      {sectionOrder.map((id) => (
        <button
          key={id}
          type="button"
          className={`section-nav-btn ${id === current ? "active" : ""}`}
          onClick={() => onSelect(id)}
        >
          {sectionMeta[id].eyebrow}
        </button>
      ))}
    </nav>
  );
}

// Used by App.tsx to look up the matching component for a SectionId.
export const sectionComponents: Record<SectionId, (ctx: SectionContext) => ReactElement> = {
  today: TodaySection,
  calendar: CalendarSection,
  clients: ClientsSection,
  updates: UpdatesSection,
  settings: SettingsSection
};

// Avoid unused-import warning for DirectAction (it's part of the public type
// surface that section consumers may need).
export type SectionDirectAction = DirectAction;
