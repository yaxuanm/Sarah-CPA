// sections.tsx
// 5-section IA components.
//
// Architectural rule from duedatehq-frontend-skill/SKILL.md:
//   - Chat drawer  → natural language only
//   - Section body → structured data only
//
// Each section renders rich, lived-in UI directly from mockData.ts. The
// chat drawer (in App.tsx) still owns conversation; when a chat-triggered
// plan resolves to a ViewEnvelope, App overlays a drilldown card on top of
// the active section.

import { ReactElement, useMemo, useState } from "react";
import type { DirectAction, ViewEnvelope } from "./types";
import {
  DirectActionHandler,
  EmptyStateRow,
  EyebrowHeader,
  FilterPopover,
  SearchInput
} from "./coreUI";
import {
  channelLabel,
  groupDeadlinesByWeek,
  mockActivity,
  mockBlockers,
  mockChannels,
  mockClients,
  mockDeadlines,
  mockExports,
  mockIntegrations,
  mockReminders,
  mockRules,
  mockSyncStatus,
  mockTeam,
  quickViewOptions,
  reminderStepLabel,
  stateOptions,
  statusBadgeLabel,
  statusBadgeTone,
  taxTypeOptions,
  todayKpis,
  urgencyOf,
  type MockClient,
  type MockDeadline,
  type ReminderStep
} from "./mockData";

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
  onExport?: (scope: string, format: "csv" | "pdf") => void;
  onOpenClient?: (clientId: string) => void;
};

export const sectionMeta: Record<SectionId, { eyebrow: string; title: string; subtitle: string }> = {
  today: {
    eyebrow: "Today",
    title: "Work that should move now",
    subtitle: "Active deadlines, blockers, and the activity feed for the current portfolio."
  },
  calendar: {
    eyebrow: "Calendar",
    title: "Upcoming deadlines",
    subtitle: "Multi-client cross-state view. Filter by state, tax type, or urgency."
  },
  clients: {
    eyebrow: "Clients",
    title: "Client directory",
    subtitle: "Open a client to see their tax profile and active deadlines."
  },
  updates: {
    eyebrow: "Updates",
    title: "Reminders, rule changes, and blockers",
    subtitle: "External signals that may turn into work — review before escalating."
  },
  settings: {
    eyebrow: "Settings",
    title: "Workspace settings",
    subtitle: "Tenant, notification channels, 50-state coverage, and exports."
  }
};

// ============================================================================
// Helpers
// ============================================================================

function StatusBadge({ deadline }: { deadline: MockDeadline }) {
  const tone = statusBadgeTone(deadline);
  const toneClass =
    tone === "urgent" ? "red" : tone === "medium" ? "gold" : tone === "low" ? "blue" : tone;
  return <span className={`badge-pill ${toneClass}`}>{statusBadgeLabel(deadline)}</span>;
}

function UrgencyDot({ deadline }: { deadline: MockDeadline }) {
  const u = urgencyOf(deadline);
  return <span className={`urgency-dot ${u}`} aria-hidden="true" />;
}

function formatDaysRemaining(d: MockDeadline) {
  if (d.status === "completed") return "Filed";
  if (d.status === "extension-approved" || d.status === "extension-filed") {
    return d.extended_due_date ? `Extended → ${d.extended_due_date}` : "Extension on file";
  }
  if (d.days_remaining < 0) return `${Math.abs(d.days_remaining)}d overdue`;
  if (d.days_remaining === 0) return "Due today";
  if (d.days_remaining === 1) return "Due tomorrow";
  return `In ${d.days_remaining} days`;
}

// ============================================================================
// Today
// ============================================================================

const todayQuickViews = [
  { id: "all", label: "All open" },
  { id: "due-this-week", label: "Due this week" },
  { id: "danger-zone", label: "Danger zone (≤3d)" },
  { id: "blocked", label: "Blocked" },
  { id: "extensions", label: "Extensions" }
] as const;

type TodayQuickView = (typeof todayQuickViews)[number]["id"];

export function TodaySection({ onAction, onPrompt, onExport }: SectionContext) {
  const [view, setView] = useState<TodayQuickView>("all");
  const [stateFilter, setStateFilter] = useState<string>("All");
  const [taxFilter, setTaxFilter] = useState<string>("All");

  const filtered = useMemo(() => {
    return mockDeadlines.filter((d) => {
      // quick view
      if (view === "due-this-week" && d.days_remaining > 7) return false;
      if (view === "due-this-week" && d.days_remaining < 0) return false;
      if (view === "danger-zone" && (d.days_remaining > 3 || d.days_remaining < 0)) return false;
      if (view === "blocked" && d.status !== "blocked") return false;
      if (view === "extensions" && d.status !== "extension-filed" && d.status !== "extension-approved") return false;
      if (view === "all" && d.status === "completed") return false;
      // state filter (jurisdiction may be Federal — keep only when state filter is All)
      if (stateFilter !== "All" && d.jurisdiction !== stateFilter) return false;
      if (taxFilter !== "All" && d.tax_type !== taxFilter) return false;
      return true;
    }).sort((a, b) => a.days_remaining - b.days_remaining);
  }, [view, stateFilter, taxFilter]);

  const activeCount = (stateFilter !== "All" ? 1 : 0) + (taxFilter !== "All" ? 1 : 0);

  return (
    <div className="section-shell">
      {/* KPI strip */}
      <div className="kpi-strip">
        {todayKpis.map((kpi) => (
          <div key={kpi.id} className={`kpi-tile tone-${kpi.tone}`}>
            <span className="kpi-label">{kpi.label}</span>
            <span className="kpi-value">{kpi.value}</span>
            <span className="kpi-delta">{kpi.delta}</span>
          </div>
        ))}
      </div>

      {/* Toolbar: quick views + filter icon + export */}
      <section className="card section-toolbar">
        <div className="quick-view-tabs" role="tablist">
          {todayQuickViews.map((q) => (
            <button
              key={q.id}
              type="button"
              role="tab"
              aria-selected={q.id === view}
              className={`quick-view-tab ${q.id === view ? "active" : ""}`}
              onClick={() => setView(q.id)}
            >
              {q.label}
            </button>
          ))}
        </div>
        <div className="toolbar-spacer" />
        <FilterPopover
          activeCount={activeCount}
          onClear={() => {
            setStateFilter("All");
            setTaxFilter("All");
          }}
          groups={[
            {
              key: "state",
              label: "State",
              selectedId: stateFilter,
              onSelect: setStateFilter,
              options: stateOptions.map((s) => ({ id: s, label: s }))
            },
            {
              key: "tax",
              label: "Tax type",
              selectedId: taxFilter,
              onSelect: setTaxFilter,
              options: taxTypeOptions.map((t) => ({ id: t, label: t }))
            }
          ]}
        />
        <button
          type="button"
          className="ghost-btn"
          onClick={() => onExport?.("Today's open deadlines", "csv")}
        >
          Export CSV
        </button>
        <button
          type="button"
          className="primary"
          onClick={() => onPrompt("Draft a status update I can send to the team about today's open work")}
        >
          Draft team update
        </button>
      </section>

      {/* Deadlines table */}
      <section className="card deadlines-card">
        <EyebrowHeader
          eyebrow="Active deadlines"
          title={`${filtered.length} item${filtered.length === 1 ? "" : "s"} match`}
          subtitle="Sorted by urgency. Extensions surface their pushed-out date."
        />
        {filtered.length === 0 ? (
          <EmptyStateRow
            title="Nothing matches that view"
            body="Loosen the filters or pick a different quick view above."
          />
        ) : (
          <div className="deadlines-table" role="table">
            <div className="deadlines-table-head" role="row">
              <span role="columnheader">Client</span>
              <span role="columnheader">Tax type</span>
              <span role="columnheader">Jurisdiction</span>
              <span role="columnheader">Due</span>
              <span role="columnheader">Status</span>
              <span role="columnheader">Extension</span>
              <span role="columnheader">Assignee</span>
              <span role="columnheader" aria-label="Actions" />
            </div>
            {filtered.map((d) => (
              <div key={d.id} className="deadlines-table-row" role="row">
                <span className="deadlines-cell client" role="cell">
                  <UrgencyDot deadline={d} />
                  <span>{d.client_name}</span>
                </span>
                <span className="deadlines-cell" role="cell">
                  {d.tax_type}
                </span>
                <span className="deadlines-cell" role="cell">
                  {d.jurisdiction}
                </span>
                <span className="deadlines-cell due" role="cell">
                  <strong>{d.due_label}</strong>
                  <span className="muted">{formatDaysRemaining(d)}</span>
                </span>
                <span className="deadlines-cell" role="cell">
                  <StatusBadge deadline={d} />
                </span>
                <span className="deadlines-cell" role="cell">
                  {d.extension_status ? (
                    <span className={`badge-pill ${d.extension_status === "approved" ? "green" : "blue"}`}>
                      {d.extension_status === "approved"
                        ? `Approved → ${d.extended_due_date}`
                        : d.extension_status === "submitted"
                          ? `Filed → ${d.extended_due_date}`
                          : "Denied"}
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </span>
                <span className="deadlines-cell" role="cell">
                  {d.assignee}
                </span>
                <span className="deadlines-cell actions" role="cell">
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() =>
                      onAction(
                        {
                          type: "agent_input",
                          text: `Open ${d.client_name} ${d.tax_type} ${d.jurisdiction} deadline`
                        },
                        `Open ${d.client_name} deadline`
                      )
                    }
                  >
                    Open
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Activity feed */}
      <section className="card activity-card">
        <EyebrowHeader
          eyebrow="Activity"
          title="What changed in the last few days"
          subtitle="Filings, reminders, rule auto-applications, and imports."
        />
        <ul className="activity-list">
          {mockActivity.map((entry) => (
            <li key={entry.id} className={`activity-row category-${entry.category}`}>
              <span className="activity-when">{entry.when}</span>
              <span className="activity-actor">{entry.actor}</span>
              <span className="activity-action">{entry.action}</span>
              <span className="activity-detail">{entry.detail}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

// ============================================================================
// Calendar
// ============================================================================

const horizonChoices = [
  { id: "this-week", label: "This week", days: 7 },
  { id: "next-30", label: "Next 30 days", days: 30 },
  { id: "quarter", label: "Quarter", days: 90 }
];

export function CalendarSection({ onPrompt, onExport, onAction }: SectionContext) {
  const [horizon, setHorizon] = useState<string>("next-30");
  const [stateFilter, setStateFilter] = useState<string>("All");
  const [taxFilter, setTaxFilter] = useState<string>("All");
  const [urgencyFilter, setUrgencyFilter] = useState<string>("All");

  const horizonDef = horizonChoices.find((h) => h.id === horizon)!;

  const filtered = useMemo(() => {
    return mockDeadlines.filter((d) => {
      if (d.status === "completed") return false;
      if (d.days_remaining < 0) return false;
      if (d.days_remaining > horizonDef.days) return false;
      if (stateFilter !== "All" && d.jurisdiction !== stateFilter) return false;
      if (taxFilter !== "All" && d.tax_type !== taxFilter) return false;
      if (urgencyFilter !== "All" && urgencyOf(d) !== urgencyFilter) return false;
      return true;
    });
  }, [horizon, stateFilter, taxFilter, urgencyFilter, horizonDef.days]);

  const groups = groupDeadlinesByWeek(filtered);
  const activeCount =
    (stateFilter !== "All" ? 1 : 0) +
    (taxFilter !== "All" ? 1 : 0) +
    (urgencyFilter !== "All" ? 1 : 0);

  return (
    <div className="section-shell">
      <section className="card section-toolbar">
        <div className="quick-view-tabs">
          {horizonChoices.map((h) => (
            <button
              key={h.id}
              type="button"
              className={`quick-view-tab ${h.id === horizon ? "active" : ""}`}
              onClick={() => setHorizon(h.id)}
            >
              {h.label}
            </button>
          ))}
        </div>
        <div className="toolbar-spacer" />
        <FilterPopover
          activeCount={activeCount}
          onClear={() => {
            setStateFilter("All");
            setTaxFilter("All");
            setUrgencyFilter("All");
          }}
          groups={[
            {
              key: "state",
              label: "State",
              selectedId: stateFilter,
              onSelect: setStateFilter,
              options: stateOptions.map((s) => ({ id: s, label: s }))
            },
            {
              key: "tax",
              label: "Tax type",
              selectedId: taxFilter,
              onSelect: setTaxFilter,
              options: taxTypeOptions.map((t) => ({ id: t, label: t }))
            },
            {
              key: "urgency",
              label: "Urgency",
              selectedId: urgencyFilter,
              onSelect: setUrgencyFilter,
              options: [
                { id: "All", label: "All" },
                { id: "urgent", label: "Urgent" },
                { id: "medium", label: "Medium" },
                { id: "low", label: "Low" }
              ]
            }
          ]}
        />
        <button
          type="button"
          className="ghost-btn"
          onClick={() => onExport?.(`Calendar — ${horizonDef.label}`, "pdf")}
        >
          Export PDF
        </button>
        <button
          type="button"
          className="primary"
          onClick={() => onPrompt(`Plan workload across ${horizonDef.label.toLowerCase()}`)}
        >
          Plan workload
        </button>
      </section>

      <section className="card calendar-overview">
        <div className="calendar-pill-row">
          {quickViewOptions.map((q) => {
            const count = mockDeadlines.filter(
              (d) => d.days_remaining >= 0 && d.days_remaining <= q.days && d.status !== "completed"
            ).length;
            return (
              <div key={q.id} className="calendar-pill">
                <span>{q.label}</span>
                <strong>{count}</strong>
              </div>
            );
          })}
        </div>
      </section>

      {groups.length === 0 ? (
        <section className="card">
          <EmptyStateRow
            title="No deadlines match that horizon"
            body="Widen the horizon or clear filters to see more."
          />
        </section>
      ) : (
        groups.map((group) => (
          <section key={group.weekKey} className="card calendar-week">
            <div className="calendar-week-head">
              <strong>{group.weekLabel}</strong>
              <span className="muted">
                {group.items.length} deadline{group.items.length === 1 ? "" : "s"}
              </span>
            </div>
            <ul className="calendar-event-list">
              {group.items.map((d) => (
                <li key={d.id} className={`calendar-event urgency-${urgencyOf(d)}`}>
                  <div className="calendar-event-date">
                    <strong>{d.due_label}</strong>
                    <span>{formatDaysRemaining(d)}</span>
                  </div>
                  <div className="calendar-event-body">
                    <div className="calendar-event-title">
                      {d.client_name}
                      <span className="badge-pill blue thin">{d.tax_type}</span>
                      <span className="badge-pill thin">{d.jurisdiction}</span>
                    </div>
                    <div className="calendar-event-meta">
                      <StatusBadge deadline={d} />
                      <span className="muted">{d.source}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() =>
                      onAction(
                        {
                          type: "agent_input",
                          text: `Open ${d.client_name} ${d.tax_type} ${d.jurisdiction} deadline`
                        },
                        `Open ${d.client_name}`
                      )
                    }
                  >
                    Open
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}

// ============================================================================
// Clients
// ============================================================================

export function ClientsSection({ onAction, onPrompt, onExport }: SectionContext) {
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState<string>("All");
  const [entityFilter, setEntityFilter] = useState<string>("All");
  const [riskFilter, setRiskFilter] = useState<string>("All");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return mockClients.filter((c) => {
      if (needle && !c.name.toLowerCase().includes(needle) && !c.primary_contact_name.toLowerCase().includes(needle))
        return false;
      if (stateFilter !== "All" && !c.states.includes(stateFilter)) return false;
      if (entityFilter !== "All" && c.entity_type !== entityFilter) return false;
      if (riskFilter === "high" && c.risk_label !== "high") return false;
      if (riskFilter === "watch" && c.risk_label !== "watch") return false;
      if (riskFilter === "calm" && c.risk_label !== null) return false;
      return true;
    });
  }, [query, stateFilter, entityFilter, riskFilter]);

  const activeCount =
    (stateFilter !== "All" ? 1 : 0) + (entityFilter !== "All" ? 1 : 0) + (riskFilter !== "All" ? 1 : 0);

  const entityOptions = [
    "All",
    "LLC",
    "S-Corp",
    "C-Corp",
    "Partnership",
    "Sole Proprietorship",
    "Professional Corp"
  ];

  return (
    <div className="section-shell">
      <section className="card section-toolbar">
        <SearchInput value={query} onChange={setQuery} placeholder="Search clients or contacts" />
        <div className="toolbar-spacer" />
        <FilterPopover
          activeCount={activeCount}
          onClear={() => {
            setStateFilter("All");
            setEntityFilter("All");
            setRiskFilter("All");
          }}
          groups={[
            {
              key: "state",
              label: "Registered state",
              selectedId: stateFilter,
              onSelect: setStateFilter,
              options: stateOptions.map((s) => ({ id: s, label: s }))
            },
            {
              key: "entity",
              label: "Entity type",
              selectedId: entityFilter,
              onSelect: setEntityFilter,
              options: entityOptions.map((s) => ({ id: s, label: s }))
            },
            {
              key: "risk",
              label: "Risk",
              selectedId: riskFilter,
              onSelect: setRiskFilter,
              options: [
                { id: "All", label: "All" },
                { id: "high", label: "High risk" },
                { id: "watch", label: "Watch" },
                { id: "calm", label: "Calm" }
              ]
            }
          ]}
        />
        <button
          type="button"
          className="ghost-btn"
          onClick={() => onExport?.("Client roster — full deadline pack", "pdf")}
        >
          Export PDF
        </button>
        <button
          type="button"
          className="primary"
          onClick={() => onPrompt("I want to import a client portfolio CSV")}
        >
          Import clients
        </button>
      </section>

      <section className="client-grid">
        {filtered.length === 0 ? (
          <div className="card">
            <EmptyStateRow
              title="No clients match"
              body="Try a different search term or clear the filter."
            />
          </div>
        ) : (
          filtered.map((c) => <ClientCardTile key={c.id} client={c} onAction={onAction} />)
        )}
      </section>
    </div>
  );
}

function ClientCardTile({ client, onAction }: { client: MockClient; onAction: DirectActionHandler }) {
  const action: DirectAction = {
    type: "agent_input",
    text: `Open ${client.name}`
  };
  return (
    <article className={`card client-tile ${client.risk_label || ""}`}>
      <div className="client-tile-head">
        <div>
          <h3>{client.name}</h3>
          <span className="muted">
            {client.entity_type} · {client.states.join(", ")}
          </span>
        </div>
        {client.risk_label === "high" ? (
          <span className="badge-pill red">High risk</span>
        ) : client.risk_label === "watch" ? (
          <span className="badge-pill gold">Watch</span>
        ) : (
          <span className="badge-pill green">Calm</span>
        )}
      </div>
      <div className="client-tile-stats">
        <div>
          <strong>{client.active_deadlines}</strong>
          <span>Active</span>
        </div>
        <div>
          <strong>{client.blocked_deadlines}</strong>
          <span>Blocked</span>
        </div>
        <div>
          <strong>{client.extensions_filed}</strong>
          <span>Extensions</span>
        </div>
      </div>
      <div className="client-tile-taxes">
        {client.applicable_taxes.map((t) => (
          <span key={t} className="badge-pill thin">
            {t}
          </span>
        ))}
      </div>
      <p className="client-tile-notes">{client.notes}</p>
      <div className="client-tile-foot">
        <span className="muted">{client.primary_contact_name}</span>
        <button
          type="button"
          className="primary"
          onClick={() => onAction(action, `Open ${client.name}`)}
        >
          Open client
        </button>
      </div>
    </article>
  );
}

// ============================================================================
// Updates
// ============================================================================

type UpdatesTab = "reminders" | "rules" | "blockers";

const updatesTabs: Array<{ key: UpdatesTab; label: string; description: string }> = [
  {
    key: "reminders",
    label: "Reminder pipeline",
    description: "30/14/7/1 stepped reminders across email, SMS, in-app, and Slack."
  },
  {
    key: "rules",
    label: "Rule review",
    description: "Pending tax-rule changes from the 50-state DB sync that need a CPA decision."
  },
  {
    key: "blockers",
    label: "Open blockers",
    description: "Clients waiting on documents or confirmations across the portfolio."
  }
];

export function UpdatesSection({ onAction, onPrompt }: SectionContext) {
  const [tab, setTab] = useState<UpdatesTab>("reminders");
  const activeMeta = updatesTabs.find((entry) => entry.key === tab)!;

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

      {tab === "reminders" ? <ReminderPipeline /> : null}
      {tab === "rules" ? <RulesReview onAction={onAction} onPrompt={onPrompt} /> : null}
      {tab === "blockers" ? <BlockersList onAction={onAction} onPrompt={onPrompt} /> : null}
    </div>
  );
}

function ReminderPipeline() {
  const stepBuckets: ReminderStep[] = [30, 14, 7, 1];
  return (
    <section className="card reminder-pipeline">
      <div className="reminder-step-grid">
        {stepBuckets.map((step) => {
          const items = mockReminders.filter((r) => r.step === step);
          return (
            <div key={step} className="reminder-step-col">
              <div className="reminder-step-head">
                <strong>{reminderStepLabel(step)}</strong>
                <span className="muted">{items.length} queued</span>
              </div>
              <ul className="reminder-step-list">
                {items.length === 0 ? (
                  <li className="reminder-empty">Nothing scheduled</li>
                ) : (
                  items.map((r) => (
                    <li key={r.id} className={`reminder-row status-${r.status}`}>
                      <div className="reminder-row-head">
                        <strong>{r.client_name}</strong>
                        <span className={`badge-pill thin channel-${r.channel}`}>
                          {channelLabel(r.channel)}
                        </span>
                      </div>
                      <span className="muted">
                        {r.tax_type} · {r.jurisdiction}
                      </span>
                      <span className="reminder-meta">
                        {new Date(r.send_at).toLocaleString("en-US", {
                          month: "short",
                          day: "numeric",
                          hour: "numeric",
                          minute: "2-digit"
                        })}{" "}
                        · {r.recipient}
                      </span>
                      <span className={`badge-pill thin ${r.status === "sent" ? "green" : r.status === "queued" ? "gold" : "blue"}`}>
                        {r.status}
                      </span>
                    </li>
                  ))
                )}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function RulesReview({ onAction, onPrompt }: { onAction: DirectActionHandler; onPrompt: (prompt: string) => void }) {
  return (
    <section className="card rules-card">
      <ul className="rules-list">
        {mockRules.map((rule) => (
          <li key={rule.id} className={`rule-row status-${rule.status}`}>
            <div className="rule-head">
              <div>
                <h3>{rule.title}</h3>
                <span className="muted">
                  {rule.jurisdiction} · {rule.source} · detected{" "}
                  {new Date(rule.detected_at).toLocaleString("en-US", {
                    month: "short",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit"
                  })}
                </span>
              </div>
              <span
                className={`badge-pill ${
                  rule.status === "pending-review" ? "gold" : rule.status === "auto-applied" ? "green" : ""
                }`}
              >
                {rule.status === "pending-review"
                  ? "Pending review"
                  : rule.status === "auto-applied"
                    ? "Auto-applied"
                    : "Dismissed"}
              </span>
            </div>
            <p className="rule-summary">{rule.summary}</p>
            <div className="rule-diff">
              <div className="diff-side before">
                <span className="diff-label">Before</span>
                <code>{rule.diff_before}</code>
              </div>
              <span className="diff-arrow" aria-hidden="true">
                →
              </span>
              <div className="diff-side after">
                <span className="diff-label">After</span>
                <code>{rule.diff_after}</code>
              </div>
            </div>
            <div className="rule-foot">
              <span className="muted">Affects {rule.affected_count} client{rule.affected_count === 1 ? "" : "s"}</span>
              <div className="rule-actions">
                {rule.status === "pending-review" ? (
                  <>
                    <button
                      type="button"
                      className="ghost-btn"
                      onClick={() => onPrompt(`Dismiss rule change "${rule.title}" with a reason`)}
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      className="primary"
                      onClick={() =>
                        onAction(
                          { type: "agent_input", text: `Apply rule change "${rule.title}" to affected clients` },
                          `Apply ${rule.title}`
                        )
                      }
                    >
                      Apply to {rule.affected_count} client{rule.affected_count === 1 ? "" : "s"}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => onPrompt(`Show source for "${rule.title}"`)}
                  >
                    View source
                  </button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function BlockersList({ onPrompt }: { onAction: DirectActionHandler; onPrompt: (prompt: string) => void }) {
  return (
    <section className="card blockers-card">
      {mockBlockers.length === 0 ? (
        <EmptyStateRow title="No blockers" body="All clients are responsive right now." />
      ) : (
        <ul className="blocker-list">
          {mockBlockers.map((b) => (
            <li key={b.id} className="blocker-row">
              <div className="blocker-head">
                <h3>{b.client_name}</h3>
                <span className={`badge-pill ${b.days_open >= 7 ? "red" : "gold"}`}>
                  {b.days_open} day{b.days_open === 1 ? "" : "s"} open
                </span>
              </div>
              <div className="muted">{b.deadline_label}</div>
              <p className="blocker-reason">{b.reason}</p>
              <div className="blocker-meta">
                <span>
                  Waiting on <strong>{b.waiting_on}</strong>
                </span>
                <span>Asked {b.asked_at}</span>
              </div>
              <div className="blocker-next">
                <span className="muted">Next step</span>
                <span>{b.next_step}</span>
              </div>
              <div className="blocker-actions">
                <button
                  type="button"
                  className="ghost-btn"
                  onClick={() => onPrompt(`Send a follow-up to ${b.waiting_on} about ${b.client_name}'s ${b.deadline_label}`)}
                >
                  Send follow-up
                </button>
                <button
                  type="button"
                  className="primary"
                  onClick={() => onPrompt(`Escalate ${b.client_name} blocker to the firm owner`)}
                >
                  Escalate
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ============================================================================
// Settings
// ============================================================================

export function SettingsSection({ tenantId, onPrompt, onExport }: SectionContext) {
  return (
    <div className="section-shell">
      <div className="settings-row-grid">
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
              <span>Display name</span>
              <strong>Johnson CPA PLLC</strong>
            </div>
            <div className="settings-row">
              <span>Tenant ID</span>
              <code>{tenantId}</code>
            </div>
            <div className="settings-row">
              <span>Today (anchored)</span>
              <strong>Apr 26, 2026</strong>
            </div>
          </div>
        </article>

        <article className="card sync-card">
          <EyebrowHeader
            eyebrow="50-state DB"
            title="Auto-maintained tax deadline coverage"
            subtitle="Federal + 50 states + DC. Official extensions are pushed within 24 hours."
            pillLabel="Healthy"
            pillTone="green"
          />
          <div className="sync-grid">
            <div>
              <span>Coverage</span>
              <strong>
                {mockSyncStatus.jurisdictions_covered}/{mockSyncStatus.jurisdictions_total} jurisdictions
              </strong>
            </div>
            <div>
              <span>Last full sync</span>
              <strong>{mockSyncStatus.last_full_sync}</strong>
            </div>
            <div>
              <span>Next scheduled sync</span>
              <strong>{mockSyncStatus.next_scheduled_sync}</strong>
            </div>
            <div>
              <span>Sources monitored</span>
              <strong>{mockSyncStatus.source_count}</strong>
            </div>
            <div>
              <span>Auto-applied today</span>
              <strong>{mockSyncStatus.rules_auto_applied_today}</strong>
            </div>
            <div>
              <span>Pending review</span>
              <strong>{mockSyncStatus.pending_rule_changes}</strong>
            </div>
          </div>
        </article>
      </div>

      <article className="card">
        <EyebrowHeader
          eyebrow="Notifications"
          title="Reminder channels"
          subtitle="30/14/7/1 stepped reminders fan out across these channels."
        />
        <div className="channel-grid">
          {mockChannels.map((ch) => (
            <div key={ch.id} className={`channel-tile ${ch.enabled ? "on" : "off"}`}>
              <div className="channel-tile-head">
                <strong>{ch.label}</strong>
                <span className={`badge-pill ${ch.enabled ? "green" : ""}`}>
                  {ch.enabled ? "Enabled" : "Off"}
                </span>
              </div>
              <span className="muted">{ch.description}</span>
              <span className="muted">Last send: {ch.last_send || "—"}</span>
            </div>
          ))}
        </div>
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
          eyebrow="Reminder schedule"
          title="When clients hear from us"
          subtitle="Stepped reminders happen automatically — adjust the cadence in chat."
        />
        <div className="step-cadence">
          {[30, 14, 7, 1].map((step) => (
            <div key={step} className={`step-tile step-${step}`}>
              <strong>{step}d</strong>
              <span>{reminderStepLabel(step as ReminderStep)}</span>
            </div>
          ))}
        </div>
      </article>

      <div className="settings-row-grid">
        <article className="card">
          <EyebrowHeader eyebrow="Integrations" title="Connected systems" />
          <ul className="integration-list">
            {mockIntegrations.map((i) => (
              <li key={i.id} className={`integration-row status-${i.status}`}>
                <div>
                  <strong>{i.name}</strong>
                  <span className="muted">{i.description}</span>
                </div>
                <div className="integration-meta">
                  <span
                    className={`badge-pill ${
                      i.status === "connected" ? "green" : i.status === "error" ? "red" : ""
                    }`}
                  >
                    {i.status}
                  </span>
                  <span className="muted">{i.last_sync || "Not connected"}</span>
                </div>
              </li>
            ))}
          </ul>
        </article>

        <article className="card">
          <EyebrowHeader eyebrow="Team" title="Members" subtitle={`${mockTeam.length} seats in this tenant`} />
          <ul className="team-list">
            {mockTeam.map((m) => (
              <li key={m.id} className="team-row">
                <span className="avatar small">{m.initials}</span>
                <div>
                  <strong>{m.name}</strong>
                  <span className="muted">{m.role}</span>
                </div>
                <span className="muted">{m.active_clients} clients</span>
              </li>
            ))}
          </ul>
        </article>
      </div>

      <article className="card">
        <EyebrowHeader
          eyebrow="Exports"
          title="CSV & PDF deadline reports"
          subtitle="Generate a portfolio-wide pack or a per-client export."
        />
        <div className="export-actions">
          <button
            type="button"
            className="ghost-btn"
            onClick={() => onExport?.("All clients — full deadline log", "csv")}
          >
            Export all clients (CSV)
          </button>
          <button
            type="button"
            className="ghost-btn"
            onClick={() => onExport?.("All clients — quarterly deadline pack", "pdf")}
          >
            Quarterly pack (PDF)
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => onPrompt("Generate a deadline pack for a specific client")}
          >
            Per-client export
          </button>
        </div>
        <ul className="export-history">
          {mockExports.map((ex) => (
            <li key={ex.id} className="export-row">
              <span className={`badge-pill ${ex.format === "csv" ? "blue" : "gold"}`}>{ex.format.toUpperCase()}</span>
              <span>{ex.scope}</span>
              <span className="muted">{ex.generated_at}</span>
              <span className="muted">{ex.size}</span>
            </li>
          ))}
        </ul>
      </article>
    </div>
  );
}

// ============================================================================
// Section nav
// ============================================================================

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

// Re-export (avoid unused-import warning for DirectAction).
export type SectionDirectAction = DirectAction;
