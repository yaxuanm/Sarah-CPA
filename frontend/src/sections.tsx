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
  SearchInput,
  SettingField,
  Toggle
} from "./coreUI";
import {
  bucketOfDeadline,
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
  noticeReason,
  quickViewOptions,
  reminderStepLabel,
  stateOptions,
  statusBadgeLabel,
  statusBadgeTone,
  taxTypeOptions,
  triageBucketMeta,
  triageCounts,
  triageOrder,
  urgencyOf,
  type MockClient,
  type MockDeadline,
  type ReminderStep,
  type TriageBucket
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
    title: "Portfolio board",
    subtitle:
      "Every active deadline triaged into Notice, Waiting on info, Track, or Watchlist — one place to scan."
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
    title: "Rule changes and system activity",
    subtitle: "Track sync health, review rule changes, and monitor recent portfolio activity."
  },
  settings: {
    eyebrow: "Settings",
    title: "Workspace settings",
    subtitle:
      "Workspace identity, notification channels, reminder cadence, integrations, team, and export defaults."
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
// Today — portfolio board (4-bucket triage)
//
// Single-page mental model: every active deadline across every client lands
// in one of four buckets — Notice / Waiting on info / Track / Watchlist —
// determined by `bucketOfDeadline()` in mockData. The CPA scans top to
// bottom and never has to switch tabs to know what's on fire.
//
// Design moves:
//   - KPI strip = the 4 bucket counts (not generic metrics).
//   - Body = 4 grouped sections, with bucket header (title + helper) and
//     the deadlines as table rows. Notice rows surface the reason chip.
//   - Filter popover (state / tax) reduces the whole board at once.
//   - Activity feed + recent exports are admin monitoring; they live
//     under Updates → Activity tab now, not on this board.
// ============================================================================

export function TodaySection({ onAction, onExport }: SectionContext) {
  const [stateFilter, setStateFilter] = useState<string>("All");
  const [taxFilter, setTaxFilter] = useState<string>("All");

  const filtered = useMemo(() => {
    return mockDeadlines.filter((d) => {
      if (d.status === "completed") return false;
      if (stateFilter !== "All" && d.jurisdiction !== stateFilter) return false;
      if (taxFilter !== "All" && d.tax_type !== taxFilter) return false;
      return true;
    });
  }, [stateFilter, taxFilter]);

  const counts = useMemo(() => triageCounts(filtered), [filtered]);

  // Group by bucket. Within each bucket, sort by days_remaining ascending
  // (most urgent first).
  const grouped = useMemo(() => {
    const map: Record<TriageBucket, MockDeadline[]> = {
      notice: [],
      waiting: [],
      track: [],
      watchlist: []
    };
    filtered.forEach((d) => {
      const b = bucketOfDeadline(d);
      if (b !== "completed") map[b].push(d);
    });
    triageOrder.forEach((b) => {
      map[b].sort((a, b2) => a.days_remaining - b2.days_remaining);
    });
    return map;
  }, [filtered]);

  const activeCount = (stateFilter !== "All" ? 1 : 0) + (taxFilter !== "All" ? 1 : 0);

  return (
    <div className="section-shell">
      {/* KPI strip = the 4 bucket counts */}
      <div className="kpi-strip">
        {triageOrder.map((b) => {
          const meta = triageBucketMeta[b];
          return (
            <div key={b} className={`kpi-tile bucket bucket-${b} tone-${meta.tone}`}>
              <span className="kpi-label">{meta.title}</span>
              <span className="kpi-value">{counts[b]}</span>
              <span className="kpi-delta">{meta.helper}</span>
            </div>
          );
        })}
      </div>

      {/* Toolbar: filter + export. No quick-view tabs — the board IS the
          quick view. */}
      <section className="card section-toolbar">
        <div className="board-toolbar-label">
          <strong>Portfolio board</strong>
          <span className="muted">
            {filtered.length} active deadline{filtered.length === 1 ? "" : "s"} across{" "}
            {new Set(filtered.map((d) => d.client_id)).size} clients
          </span>
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
          onClick={() => onExport?.("Portfolio board — all active deadlines", "csv")}
        >
          Export CSV
        </button>
      </section>

      {/* The board: 4 buckets stacked top-to-bottom. */}
      {triageOrder.map((b) => {
        const meta = triageBucketMeta[b];
        const items = grouped[b];
        return (
          <section key={b} className={`card bucket-card bucket-${b} tone-${meta.tone}`}>
            <div className="bucket-head">
              <div>
                <span className={`bucket-tag tone-${meta.tone}`}>{meta.title}</span>
                <span className="bucket-count">
                  {items.length} item{items.length === 1 ? "" : "s"}
                </span>
              </div>
              <span className="bucket-helper">{meta.helper}</span>
            </div>
            {items.length === 0 ? (
              <EmptyStateRow
                title="Empty bucket"
                body={`No deadlines currently classified as ${meta.title.toLowerCase()}.`}
              />
            ) : (
              <div className="bucket-table" role="table">
                <div className="bucket-table-head" role="row">
                  <span role="columnheader">Client</span>
                  <span role="columnheader">Tax type</span>
                  <span role="columnheader">Jurisdiction</span>
                  <span role="columnheader">Due</span>
                  <span role="columnheader">Status / reason</span>
                  <span role="columnheader">Assignee</span>
                  <span role="columnheader" aria-label="Actions" />
                </div>
                {items.map((d) => (
                  <div key={d.id} className="bucket-table-row" role="row">
                    <span className="bucket-cell client" role="cell">
                      <UrgencyDot deadline={d} />
                      <span>{d.client_name}</span>
                    </span>
                    <span className="bucket-cell" role="cell">
                      {d.tax_type}
                    </span>
                    <span className="bucket-cell" role="cell">
                      {d.jurisdiction}
                    </span>
                    <span className="bucket-cell due" role="cell">
                      <strong>{d.due_label}</strong>
                      <span className="muted">{formatDaysRemaining(d)}</span>
                    </span>
                    <span className="bucket-cell reason" role="cell">
                      {b === "notice" ? (
                        <span className="badge-pill red">{noticeReason(d)}</span>
                      ) : b === "waiting" ? (
                        <span className="badge-pill gold">
                          {d.blocker_reason || "Waiting on client"}
                        </span>
                      ) : b === "watchlist" && d.extension_status ? (
                        <span className="badge-pill blue">
                          {d.extension_status === "approved"
                            ? `Extended → ${d.extended_due_date}`
                            : d.extension_status === "submitted"
                              ? `Filed → ${d.extended_due_date}`
                              : "Extension denied"}
                        </span>
                      ) : (
                        <StatusBadge deadline={d} />
                      )}
                    </span>
                    <span className="bucket-cell" role="cell">
                      {d.assignee}
                    </span>
                    <span className="bucket-cell actions" role="cell">
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
        );
      })}
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

export function ClientsSection({ onExport }: SectionContext) {
  const [importMode, setImportMode] = useState(false);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);

  if (importMode) {
    return <ImportWizard onClose={() => setImportMode(false)} />;
  }

  if (selectedClientId) {
    const client = mockClients.find((entry) => entry.id === selectedClientId);
    if (client) {
      return (
        <ClientDetailSurface
          client={client}
          onBack={() => setSelectedClientId(null)}
          onExport={onExport}
        />
      );
    }
  }

  return (
    <ClientDirectory
      onExport={onExport}
      onImport={() => setImportMode(true)}
      onOpenClient={setSelectedClientId}
    />
  );
}

function ClientDirectory({
  onExport,
  onImport,
  onOpenClient
}: {
  onExport?: (scope: string, format: "csv" | "pdf") => void;
  onImport: () => void;
  onOpenClient: (clientId: string) => void;
}) {
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
        <button type="button" className="primary" onClick={onImport}>
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
          filtered.map((c) => (
            <ClientCardTile key={c.id} client={c} onOpenClient={onOpenClient} />
          ))
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Structured Import wizard (no chat handoff).
//
// 4 stops: choose file → map columns → preview rows → apply. The CSV upload
// step only resolves the parse locally; the actual rows then flow through
// the column-map / preview / apply screens. State is local-only — the
// backend hook (client.import) will be added in a follow-up.
// ---------------------------------------------------------------------------

const importFields = [
  { key: "name", label: "Client name", required: true },
  { key: "entity_type", label: "Entity type", required: true },
  { key: "states", label: "Registered states", required: true },
  { key: "primary_contact_name", label: "Primary contact name", required: false },
  { key: "primary_contact_email", label: "Primary contact email", required: false },
  { key: "applicable_taxes", label: "Applicable taxes", required: false },
  { key: "notes", label: "Notes", required: false }
] as const;

type ImportFieldKey = (typeof importFields)[number]["key"];

const sampleCsvHeaders = [
  "Company",
  "Type",
  "States",
  "Contact",
  "Email",
  "Taxes",
  "Notes",
  "Internal ID"
];

const sampleCsvRows: string[][] = [
  [
    "Westlake Restaurants Group",
    "S-Corp",
    "CA;NV",
    "Marisol Vega",
    "marisol@westlakerg.com",
    "Federal income;State income;Sales/Use;Payroll (941)",
    "Restaurant chain — 4 locations",
    "WLR-001"
  ],
  [
    "Northwind Services LLC",
    "LLC",
    "CA;TX;NV",
    "Maya Chen",
    "maya@northwindservices.com",
    "Federal income;State income;Payroll (941);Sales/Use",
    "Existing client — same EIN",
    "DUP-NW-001"
  ],
  [
    "Cedar Creek Vineyards",
    "Partnership",
    "OR",
    "James Holloway",
    "james@cedarcreek.wine",
    "Federal income;State income;Excise",
    "Bonded winery; OBLP excise filings monthly",
    "CCV-001"
  ],
  [
    "Beacon Coastal Realty",
    "S-Corp",
    "FL",
    "Aniya Brooks",
    "aniya@beaconcoastal.com",
    "Federal income",
    "FL has no state income tax",
    "BCR-001"
  ],
  [
    "Polaris Robotics Inc.",
    "C-Corp",
    "WA;CA;MA",
    "Henry Tanaka",
    "henry@polarisrobotics.com",
    "Federal income;State income;Franchise;Payroll (941)",
    "VC-backed; multi-state nexus review needed",
    "POL-001"
  ]
];

function ImportWizard({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [fileName, setFileName] = useState<string | null>(null);
  const [delimiter, setDelimiter] = useState(",");
  const [hasHeader, setHasHeader] = useState(true);

  // Auto-detect column → field mapping. Re-derive when CSV changes; user can
  // override.
  const autoMap: Record<ImportFieldKey, string | null> = {
    name: "Company",
    entity_type: "Type",
    states: "States",
    primary_contact_name: "Contact",
    primary_contact_email: "Email",
    applicable_taxes: "Taxes",
    notes: "Notes"
  };
  const [mapping, setMapping] = useState<Record<ImportFieldKey, string | null>>(autoMap);

  // Per-row decision (keep / merge / skip). The duplicate row index 1 is
  // pre-flagged as merge.
  const initialDecisions = sampleCsvRows.map((_, i) =>
    i === 1 ? "merge" : ("keep" as "keep" | "merge" | "skip")
  );
  const [decisions, setDecisions] = useState<Array<"keep" | "merge" | "skip">>(initialDecisions);

  const stepLabels = [
    { id: 1, label: "Choose file" },
    { id: 2, label: "Map columns" },
    { id: 3, label: "Review rows" },
    { id: 4, label: "Done" }
  ] as const;

  function chooseSampleFile() {
    setFileName("client-portfolio-2026-Q2.csv");
    setStep(2);
  }

  const created = decisions.filter((d) => d === "keep").length;
  const merged = decisions.filter((d) => d === "merge").length;
  const skipped = decisions.filter((d) => d === "skip").length;

  return (
    <div className="section-shell">
      <section className="card import-header">
        <div>
          <span className="eyebrow">Clients · Import</span>
          <h2>Bring a portfolio of clients into DueDateHQ</h2>
          <p className="muted">
            Upload a CSV, confirm how its columns map to our client fields, and review duplicate detection before
            anything is written. No chat — every decision is structured.
          </p>
        </div>
        <button type="button" className="ghost-btn" onClick={onClose}>
          Cancel & back to clients
        </button>
      </section>

      <section className="card import-stepper">
        <ol className="stepper">
          {stepLabels.map((s, i) => (
            <li key={s.id} className={`stepper-step ${step === s.id ? "active" : ""} ${step > s.id ? "done" : ""}`}>
              <span className="stepper-num">{i + 1}</span>
              <span className="stepper-label">{s.label}</span>
            </li>
          ))}
        </ol>
      </section>

      {step === 1 ? (
        <section className="card import-step">
          <EyebrowHeader
            eyebrow="Step 1"
            title="Choose a CSV file"
            subtitle="The file should have one client per row. Headers are optional but recommended."
          />
          <div className="import-drop">
            <div className="import-drop-text">
              <strong>Drag a CSV here, or click to browse</strong>
              <span className="muted">
                Up to 5,000 rows per import. We recommend including state, entity type, and applicable taxes.
              </span>
            </div>
            <button type="button" className="primary" onClick={chooseSampleFile}>
              Use sample file
            </button>
          </div>

          <div className="import-options">
            <SettingField label="Delimiter" hint="Almost always a comma; some firms export with semicolons.">
              <select className="setting-input compact" value={delimiter} onChange={(e) => setDelimiter(e.target.value)}>
                <option value=",">, (comma)</option>
                <option value=";">; (semicolon)</option>
                <option value="\t">tab</option>
              </select>
            </SettingField>
            <SettingField label="First row is a header" hint="Uncheck if the file starts with data.">
              <Toggle checked={hasHeader} onChange={setHasHeader} label="First row is a header" />
            </SettingField>
          </div>

          <div className="setting-foot">
            <span className="muted">{fileName ? `Loaded: ${fileName}` : "No file selected"}</span>
            <button
              type="button"
              className="primary"
              disabled={!fileName}
              onClick={() => setStep(2)}
            >
              Next: map columns
            </button>
          </div>
        </section>
      ) : null}

      {step === 2 ? (
        <section className="card import-step">
          <EyebrowHeader
            eyebrow="Step 2"
            title="Map CSV columns to client fields"
            subtitle="We auto-detected the matches we could; review and adjust before continuing."
          />
          <div className="import-map-table">
            <div className="import-map-row head">
              <span>Field</span>
              <span>CSV column</span>
              <span>Sample value</span>
            </div>
            {importFields.map((f) => {
              const csvHeader = mapping[f.key];
              const csvIndex = csvHeader ? sampleCsvHeaders.indexOf(csvHeader) : -1;
              const sampleValue = csvIndex >= 0 ? sampleCsvRows[0][csvIndex] : "—";
              return (
                <div key={f.key} className="import-map-row">
                  <span>
                    {f.label}
                    {f.required ? <span className="required-mark">*</span> : null}
                  </span>
                  <select
                    className="setting-input compact"
                    value={csvHeader || ""}
                    onChange={(e) =>
                      setMapping((current) => ({
                        ...current,
                        [f.key]: e.target.value || null
                      }))
                    }
                  >
                    <option value="">— skip —</option>
                    {sampleCsvHeaders.map((h) => (
                      <option key={h}>{h}</option>
                    ))}
                  </select>
                  <span className="muted">{sampleValue}</span>
                </div>
              );
            })}
          </div>
          <div className="setting-foot">
            <button type="button" className="ghost-btn" onClick={() => setStep(1)}>
              Back
            </button>
            <button type="button" className="primary" onClick={() => setStep(3)}>
              Next: review rows
            </button>
          </div>
        </section>
      ) : null}

      {step === 3 ? (
        <section className="card import-step">
          <EyebrowHeader
            eyebrow="Step 3"
            title={`Review ${sampleCsvRows.length} rows`}
            subtitle="One duplicate detected (matched by company name and EIN). Pick how to resolve each row."
          />
          <div className="import-review-table">
            <div className="import-review-row head">
              <span>Client</span>
              <span>Entity</span>
              <span>States</span>
              <span>Status</span>
              <span>Decision</span>
            </div>
            {sampleCsvRows.map((row, idx) => {
              const isDuplicate = idx === 1;
              const decision = decisions[idx];
              return (
                <div key={idx} className={`import-review-row ${isDuplicate ? "duplicate" : ""}`}>
                  <span>
                    <strong>{row[0]}</strong>
                    <span className="muted">{row[3]}</span>
                  </span>
                  <span>{row[1]}</span>
                  <span>{row[2]}</span>
                  <span>
                    {isDuplicate ? (
                      <span className="badge-pill gold">Duplicate of Northwind Services LLC</span>
                    ) : (
                      <span className="badge-pill green">New</span>
                    )}
                  </span>
                  <span className="import-decision">
                    {(["keep", "merge", "skip"] as const).map((opt) => {
                      const disabled = !isDuplicate && opt === "merge";
                      return (
                        <label
                          key={opt}
                          className={`radio-pill ${decision === opt ? "active" : ""} ${disabled ? "disabled" : ""}`}
                        >
                          <input
                            type="radio"
                            name={`decision-${idx}`}
                            checked={decision === opt}
                            disabled={disabled}
                            onChange={() =>
                              setDecisions((current) => current.map((d, i) => (i === idx ? opt : d)))
                            }
                          />
                          {opt[0].toUpperCase() + opt.slice(1)}
                        </label>
                      );
                    })}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="setting-foot">
            <button type="button" className="ghost-btn" onClick={() => setStep(2)}>
              Back
            </button>
            <button type="button" className="primary" onClick={() => setStep(4)}>
              Apply import
            </button>
          </div>
        </section>
      ) : null}

      {step === 4 ? (
        <section className="card import-step">
          <EyebrowHeader
            eyebrow="Step 4"
            title="Import complete"
            subtitle="The portfolio has been written to DueDateHQ. Each new client is now visible on the directory."
            pillLabel="Done"
            pillTone="green"
          />
          <div className="import-summary">
            <div>
              <strong>{created}</strong>
              <span>Created</span>
            </div>
            <div>
              <strong>{merged}</strong>
              <span>Merged</span>
            </div>
            <div>
              <strong>{skipped}</strong>
              <span>Skipped</span>
            </div>
          </div>
          <div className="setting-foot">
            <button type="button" className="ghost-btn" onClick={() => setStep(1)}>
              Import another file
            </button>
            <button type="button" className="primary" onClick={onClose}>
              Back to clients
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function ClientCardTile({
  client,
  onOpenClient
}: {
  client: MockClient;
  onOpenClient: (clientId: string) => void;
}) {
  return (
    <button
      type="button"
      className={`card client-tile ${client.risk_label || ""}`}
      onClick={() => onOpenClient(client.id)}
    >
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
        <span className="client-tile-link">View details</span>
      </div>
    </button>
  );
}

function ClientDetailSurface({
  client,
  onBack,
  onExport
}: {
  client: MockClient;
  onBack: () => void;
  onExport?: (scope: string, format: "csv" | "pdf") => void;
}) {
  const deadlines = useMemo(
    () =>
      mockDeadlines
        .filter((deadline) => deadline.client_id === client.id)
        .sort((a, b) => a.days_remaining - b.days_remaining),
    [client.id]
  );

  const blockers = useMemo(
    () => mockBlockers.filter((blocker) => blocker.client_id === client.id),
    [client.id]
  );

  const reminders = useMemo(
    () =>
      mockReminders
        .filter((reminder) => reminder.client_id === client.id)
        .sort((a, b) => a.send_at.localeCompare(b.send_at)),
    [client.id]
  );

  const extensionDeadlines = useMemo(
    () => deadlines.filter((deadline) => deadline.extension_status),
    [deadlines]
  );

  const recentActivity = useMemo(() => {
    const nameNeedles = [
      client.name,
      client.name.split(" ").slice(0, 2).join(" "),
      client.name.split(" ")[0]
    ].filter(Boolean);
    return mockActivity.filter((entry) =>
      nameNeedles.some((needle) => entry.detail.includes(needle))
    );
  }, [client.name]);

  return (
    <div className="section-shell client-detail-shell">
      <section className="card section-toolbar detail-toolbar">
        <div className="detail-toolbar-left">
          <button type="button" className="ghost-btn" onClick={onBack}>
            Back to clients
          </button>
          <div className="detail-toolbar-copy">
            <div className="eyebrow">Client detail</div>
            <strong>{client.name}</strong>
          </div>
        </div>
        <div className="detail-toolbar-actions">
          <button
            type="button"
            className="ghost-btn"
            onClick={() => onExport?.(`${client.name} — full deadline pack`, "csv")}
          >
            Export CSV
          </button>
          <button
            type="button"
            className="ghost-btn"
            onClick={() => onExport?.(`${client.name} — full deadline pack`, "pdf")}
          >
            Export PDF
          </button>
        </div>
      </section>

      <div className="client-detail-grid">
        <div className="client-detail-main">
          <section className="card client-profile-card">
            <EyebrowHeader
              eyebrow="Profile"
              title={client.name}
              subtitle="Entity type, state footprint, filing scope, and primary contact."
            />
            <div className="profile-grid">
              <div className="profile-block">
                <span className="profile-label">Entity type</span>
                <strong>{client.entity_type}</strong>
              </div>
              <div className="profile-block">
                <span className="profile-label">Registered states</span>
                <strong>{client.states.join(", ")}</strong>
              </div>
              <div className="profile-block">
                <span className="profile-label">Primary contact</span>
                <strong>{client.primary_contact_name}</strong>
                <span className="muted">{client.primary_contact_email}</span>
              </div>
              <div className="profile-block">
                <span className="profile-label">Applicable taxes</span>
                <div className="client-tile-taxes">
                  {client.applicable_taxes.map((tax) => (
                    <span key={tax} className="badge-pill thin">
                      {tax}
                    </span>
                  ))}
                </div>
              </div>
            </div>
            <p className="client-tile-notes">{client.notes}</p>
          </section>

          <section className="card deadlines-card">
            <EyebrowHeader
              eyebrow="Deadline calendar"
              title={`${deadlines.length} deadline${deadlines.length === 1 ? "" : "s"}`}
              subtitle="Derived from entity type, state footprint, and filing scope."
            />
            {deadlines.length === 0 ? (
              <EmptyStateRow
                title="No deadlines yet"
                body="This client has no generated deadlines in the current demo dataset."
              />
            ) : (
              <div className="deadlines-table" role="table">
                <div className="deadlines-table-head" role="row">
                  <span role="columnheader">Tax type</span>
                  <span role="columnheader">Jurisdiction</span>
                  <span role="columnheader">Due</span>
                  <span role="columnheader">Status</span>
                  <span role="columnheader">Extension</span>
                  <span role="columnheader">Source</span>
                </div>
                {deadlines.map((deadline) => (
                  <div key={deadline.id} className="deadlines-table-row" role="row">
                    <span className="deadlines-cell" role="cell">
                      {deadline.tax_type}
                    </span>
                    <span className="deadlines-cell" role="cell">
                      {deadline.jurisdiction}
                    </span>
                    <span className="deadlines-cell due" role="cell">
                      <strong>{deadline.due_label}</strong>
                      <span className="muted">{formatDaysRemaining(deadline)}</span>
                    </span>
                    <span className="deadlines-cell" role="cell">
                      <StatusBadge deadline={deadline} />
                    </span>
                    <span className="deadlines-cell" role="cell">
                      {deadline.extension_status ? (
                        <span className={`badge-pill ${deadline.extension_status === "approved" ? "green" : "blue"}`}>
                          {deadline.extension_status === "approved"
                            ? `Approved → ${deadline.extended_due_date}`
                            : deadline.extension_status === "submitted"
                              ? `Filed → ${deadline.extended_due_date}`
                              : "Denied"}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </span>
                    <span className="deadlines-cell source" role="cell">
                      {deadline.source}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card activity-card">
            <EyebrowHeader
              eyebrow="Recent activity"
              title="What changed for this client"
              subtitle="Imports, reminders, filings, and rule-driven changes tied to this client."
            />
            {recentActivity.length === 0 ? (
              <EmptyStateRow
                title="No recent activity"
                body="This client has no matching recent activity in the current demo dataset."
              />
            ) : (
              <ul className="activity-list">
                {recentActivity.map((entry) => (
                  <li key={entry.id} className={`activity-row category-${entry.category}`}>
                    <span className="activity-when">{entry.when}</span>
                    <span className="activity-actor">{entry.actor}</span>
                    <span className="activity-action">{entry.action}</span>
                    <span className="activity-detail">{entry.detail}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <div className="client-detail-rail">
          <section className="card detail-side-card">
            <EyebrowHeader
              eyebrow="Extensions"
              title="Extension log"
              subtitle="Original due dates, filed status, and effective extended dates."
            />
            {extensionDeadlines.length === 0 ? (
              <EmptyStateRow
                title="No extensions"
                body="This client has no extension history in the current demo dataset."
              />
            ) : (
              <ul className="mini-log">
                {extensionDeadlines.map((deadline) => (
                  <li key={deadline.id} className="mini-log-row">
                    <strong>{deadline.tax_type} · {deadline.jurisdiction}</strong>
                    <span className="muted">Original {deadline.due_label}</span>
                    <span className={`badge-pill ${deadline.extension_status === "approved" ? "green" : "blue"}`}>
                      {deadline.extension_status === "approved" ? "Approved" : "Filed"}
                    </span>
                    <span className="muted">Extended to {deadline.extended_due_date}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card detail-side-card">
            <EyebrowHeader
              eyebrow="Blockers"
              title="Open blocker timeline"
              subtitle="What is still stopping work from moving for this client."
            />
            {blockers.length === 0 ? (
              <EmptyStateRow
                title="No blockers"
                body="This client has no open blockers right now."
              />
            ) : (
              <ul className="mini-log">
                {blockers.map((blocker) => (
                  <li key={blocker.id} className="mini-log-row">
                    <strong>{blocker.deadline_label}</strong>
                    <span>{blocker.reason}</span>
                    <span className="muted">Waiting on {blocker.waiting_on}</span>
                    <span className="muted">{blocker.next_step}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card detail-side-card">
            <EyebrowHeader
              eyebrow="Reminders"
              title="Queued reminders"
              subtitle="Upcoming notifications already scheduled for this client."
            />
            {reminders.length === 0 ? (
              <EmptyStateRow
                title="No reminders queued"
                body="This client has no queued reminders in the current demo dataset."
              />
            ) : (
              <ul className="mini-log">
                {reminders.map((reminder) => (
                  <li key={reminder.id} className="mini-log-row">
                    <strong>{reminder.tax_type} · {reminder.jurisdiction}</strong>
                    <span className="muted">{reminderStepLabel(reminder.step)} · {channelLabel(reminder.channel)}</span>
                    <span className="muted">
                      {new Date(reminder.send_at).toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit"
                      })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Updates
// ============================================================================

type UpdatesTab = "rules" | "activity";

const updatesTabs: Array<{ key: UpdatesTab; label: string; description: string }> = [
  {
    key: "rules",
    label: "Rule review",
    description: "Pending tax-rule changes from the 50-state DB sync that need a CPA decision."
  },
  {
    key: "activity",
    label: "Activity",
      description:
      "Admin monitoring: filings, reminder sends, rule applications, imports, and recent exports."
  }
];

export function UpdatesSection({ onAction, onPrompt }: SectionContext) {
  const [tab, setTab] = useState<UpdatesTab>("rules");
  const activeMeta = updatesTabs.find((entry) => entry.key === tab)!;

  return (
    <div className="section-shell">
      {/* 50-state DB sync status — moved here from Settings because it
          describes the UPSTREAM signal that produces rule changes and
          reminders. Belongs alongside the things it generates. */}
      <section className="card sync-banner">
        <div className="sync-banner-head">
          <div>
            <span className="eyebrow">50-state DB · auto-sync</span>
            <h3>
              {mockSyncStatus.jurisdictions_covered}/{mockSyncStatus.jurisdictions_total} jurisdictions covered ·
              monitoring {mockSyncStatus.source_count} sources
            </h3>
          </div>
          <span className="badge-pill green">Healthy</span>
        </div>
        <div className="sync-banner-row">
          <span>
            Last full sync <strong>{mockSyncStatus.last_full_sync}</strong>
          </span>
          <span>
            Next sync <strong>{mockSyncStatus.next_scheduled_sync}</strong>
          </span>
          <span>
            Auto-applied today <strong>{mockSyncStatus.rules_auto_applied_today}</strong>
          </span>
          <span>
            Pending review <strong>{mockSyncStatus.pending_rule_changes}</strong>
          </span>
        </div>
      </section>

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

      {tab === "rules" ? <RulesReview onAction={onAction} onPrompt={onPrompt} /> : null}
      {tab === "activity" ? <ActivityMonitor /> : null}
    </div>
  );
}

function ActivityMonitor() {
  return (
    <>
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

      <section className="card recent-exports-card">
        <EyebrowHeader
          eyebrow="Recent exports"
          title="CSV / PDF generated for the firm"
          subtitle="Most recent exports across the portfolio."
        />
        <ul className="recent-exports-list">
          {mockExports.map((ex) => (
            <li key={ex.id} className="recent-export-row">
              <span className={`badge-pill ${ex.format === "csv" ? "blue" : "gold"}`}>
                {ex.format.toUpperCase()}
              </span>
              <div className="recent-export-text">
                <strong>{ex.scope}</strong>
                <span className="muted">
                  {ex.generated_at} · {ex.size}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </>
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

// ============================================================================
// Settings
// ============================================================================

// SettingsSection — pure configuration. Status & history live elsewhere:
//   - 50-state DB sync status → top of Updates (it produces what's in Updates)
//   - Export history → Today (recent activity-adjacent panel)
//   - Per-view export buttons → Today / Calendar / Clients toolbars
// Settings only contains things you can flip, name, schedule, connect,
// disconnect, invite, or remove.
export function SettingsSection({ tenantId, onPrompt }: SectionContext) {
  // Local-only state — these are mock toggles. They look real but don't
  // round-trip to the backend yet (notify.config isn't whitelisted in
  // PlanExecutor). When that endpoint lands, replace setState with a
  // dispatch() call.
  const [displayName, setDisplayName] = useState("Johnson CPA PLLC");
  const [timezone, setTimezone] = useState("America/Los_Angeles");
  const [fiscalYear, setFiscalYear] = useState("Calendar (Jan – Dec)");

  const [channelEnabled, setChannelEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(mockChannels.map((c) => [c.id, c.enabled]))
  );

  const [steps, setSteps] = useState({
    30: { enabled: true, time: "08:00" },
    14: { enabled: true, time: "08:00" },
    7: { enabled: true, time: "08:00" },
    1: { enabled: true, time: "07:30" }
  });

  const [integrationConnected, setIntegrationConnected] = useState<Record<string, boolean>>(
    Object.fromEntries(mockIntegrations.map((i) => [i.id, i.status === "connected"]))
  );

  const [teamRoles, setTeamRoles] = useState<Record<string, string>>(
    Object.fromEntries(mockTeam.map((m) => [m.id, m.role]))
  );

  const [defaultFormat, setDefaultFormat] = useState<"csv" | "pdf">("pdf");
  const [defaultDestination, setDefaultDestination] = useState("Google Drive");
  const [autoIncludeExtensions, setAutoIncludeExtensions] = useState(true);
  const [namingPattern, setNamingPattern] = useState("{client}-{tax}-{quarter}");

  const roleOptions = ["Owner / CPA", "Senior associate", "Tax associate", "Practice admin", "View-only"];

  return (
    <div className="section-shell">
      {/* Workspace */}
      <article className="card">
        <EyebrowHeader
          eyebrow="Workspace"
          title="Tenant identity"
          subtitle="Display name, time zone, and fiscal year shown across the app."
        />
        <div className="setting-fields">
          <SettingField label="Display name" hint="Shown in the topbar and on exports.">
            <input
              type="text"
              className="setting-input"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </SettingField>
          <SettingField label="Time zone" hint="Used for reminder send times.">
            <select
              className="setting-input"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
            >
              <option>America/Los_Angeles</option>
              <option>America/Denver</option>
              <option>America/Chicago</option>
              <option>America/New_York</option>
              <option>UTC</option>
            </select>
          </SettingField>
          <SettingField label="Fiscal year" hint="Used to bucket extensions and YTD totals.">
            <select
              className="setting-input"
              value={fiscalYear}
              onChange={(e) => setFiscalYear(e.target.value)}
            >
              <option>Calendar (Jan – Dec)</option>
              <option>Fiscal (Jul – Jun)</option>
              <option>Fiscal (Oct – Sep)</option>
            </select>
          </SettingField>
          <SettingField label="Tenant ID" hint="Sent on every backend request — read only.">
            <code className="setting-code">{tenantId}</code>
          </SettingField>
        </div>
        <div className="setting-foot">
          <span className="muted">Anchored today: Apr 26, 2026</span>
          <button type="button" className="primary">
            Save changes
          </button>
        </div>
      </article>

      {/* Notification channels */}
      <article className="card">
        <EyebrowHeader
          eyebrow="Notifications"
          title="Reminder channels"
          subtitle="Toggle which channels carry the 30/14/7/1 stepped reminders."
        />
        <div className="setting-fields">
          {mockChannels.map((ch) => (
            <SettingField key={ch.id} label={ch.label} hint={ch.description}>
              <Toggle
                checked={!!channelEnabled[ch.id]}
                onChange={(next) =>
                  setChannelEnabled((current) => ({ ...current, [ch.id]: next }))
                }
                label={`Toggle ${ch.label}`}
              />
            </SettingField>
          ))}
        </div>
      </article>

      {/* Reminder cadence */}
      <article className="card">
        <EyebrowHeader
          eyebrow="Reminder cadence"
          title="When stepped reminders fire"
          subtitle="Each step can be turned off. Time-of-day applies to all channels."
        />
        <div className="cadence-grid">
          {([30, 14, 7, 1] as ReminderStep[]).map((step) => (
            <div key={step} className={`cadence-row step-${step}`}>
              <div className="cadence-row-head">
                <strong>{step}d</strong>
                <span>{reminderStepLabel(step)}</span>
              </div>
              <Toggle
                checked={steps[step].enabled}
                onChange={(next) =>
                  setSteps((current) => ({
                    ...current,
                    [step]: { ...current[step], enabled: next }
                  }))
                }
                label={`Toggle ${step}-day reminder`}
              />
              <input
                type="time"
                className="setting-input compact"
                value={steps[step].time}
                onChange={(e) =>
                  setSteps((current) => ({
                    ...current,
                    [step]: { ...current[step], time: e.target.value }
                  }))
                }
                disabled={!steps[step].enabled}
              />
            </div>
          ))}
        </div>
      </article>

      {/* Integrations */}
      <article className="card">
        <EyebrowHeader
          eyebrow="Integrations"
          title="Connected systems"
          subtitle="Connect or disconnect data sources and delivery carriers."
        />
        <ul className="integration-list">
          {mockIntegrations.map((i) => {
            const connected = integrationConnected[i.id];
            return (
              <li key={i.id} className={`integration-row status-${connected ? "connected" : "disconnected"}`}>
                <div>
                  <strong>{i.name}</strong>
                  <span className="muted">{i.description}</span>
                </div>
                <div className="integration-meta">
                  <span className={`badge-pill ${connected ? "green" : ""}`}>
                    {connected ? "Connected" : "Not connected"}
                  </span>
                  <button
                    type="button"
                    className={connected ? "ghost-btn" : "primary"}
                    onClick={() =>
                      setIntegrationConnected((current) => ({ ...current, [i.id]: !connected }))
                    }
                  >
                    {connected ? "Disconnect" : "Connect"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </article>

      {/* Team & permissions */}
      <article className="card">
        <EyebrowHeader
          eyebrow="Team & permissions"
          title="Members"
          subtitle={`${mockTeam.length} seats in this tenant. Role determines what each member can edit.`}
        />
        <ul className="team-list">
          {mockTeam.map((m) => (
            <li key={m.id} className="team-row editable">
              <span className="avatar small">{m.initials}</span>
              <div>
                <strong>{m.name}</strong>
                <span className="muted">{m.email}</span>
              </div>
              <select
                className="setting-input compact"
                value={teamRoles[m.id]}
                onChange={(e) =>
                  setTeamRoles((current) => ({ ...current, [m.id]: e.target.value }))
                }
              >
                {roleOptions.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
              <button type="button" className="ghost-btn" aria-label={`Remove ${m.name}`}>
                Remove
              </button>
            </li>
          ))}
        </ul>
        <div className="setting-foot">
          <button type="button" className="primary" onClick={() => onPrompt("Invite a new team member")}>
            + Invite member
          </button>
        </div>
      </article>

      {/* Export preferences */}
      <article className="card">
        <EyebrowHeader
          eyebrow="Export preferences"
          title="Defaults for CSV / PDF deadline reports"
          subtitle="These defaults apply when you click Export from Today, Calendar, or Clients."
        />
        <div className="setting-fields">
          <SettingField label="Default format">
            <div className="radio-row">
              {(["csv", "pdf"] as const).map((f) => (
                <label key={f} className={`radio-pill ${defaultFormat === f ? "active" : ""}`}>
                  <input
                    type="radio"
                    name="default-format"
                    checked={defaultFormat === f}
                    onChange={() => setDefaultFormat(f)}
                  />
                  {f.toUpperCase()}
                </label>
              ))}
            </div>
          </SettingField>
          <SettingField label="Default destination" hint="Where new exports are saved.">
            <select
              className="setting-input"
              value={defaultDestination}
              onChange={(e) => setDefaultDestination(e.target.value)}
            >
              <option>Download to browser</option>
              <option>Google Drive</option>
              <option>Email to firm inbox</option>
            </select>
          </SettingField>
          <SettingField
            label="Auto-include extensions"
            hint="Show pushed-out due dates next to original deadlines on every export."
          >
            <Toggle
              checked={autoIncludeExtensions}
              onChange={setAutoIncludeExtensions}
              label="Auto-include extensions"
            />
          </SettingField>
          <SettingField label="File naming pattern" hint="Tokens: {client} {tax} {quarter} {date}">
            <input
              type="text"
              className="setting-input"
              value={namingPattern}
              onChange={(e) => setNamingPattern(e.target.value)}
            />
          </SettingField>
        </div>
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
