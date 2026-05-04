import { Dispatch, ReactElement, SetStateAction, useEffect, useMemo, useState } from "react";
import type { ViewEnvelope } from "./types";
import {
  BlockedIcon,
  ChevronRightIcon,
  DownloadIcon,
  DirectActionHandler,
  EmptyStateRow,
  ExtensionIcon,
  EyebrowHeader,
  FilterIcon,
  UploadIcon,
  WorkIcon
} from "./coreUI";
import {
  mockActivity,
  mockBlockers,
  EntityType,
  mockChannels,
  mockClients,
  mockDeadlines,
  mockReminders,
  mockRules,
  mockSyncStatus,
  type MockClient,
  type MockActivity,
  type MockBlocker,
  type MockDeadline,
  type MockReminder,
  type MockRule,
  TaxType
} from "./mockData";

export type SectionId = "work" | "clients" | "review" | "settings";

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
  openSection?: (section: SectionId, options?: { ruleId?: string }) => void;
  onPrompt: (prompt: string) => void;
  onAction: DirectActionHandler;
  onExport?: (scope: string, format: "csv" | "pdf") => void;
  onOpenClient?: (clientId: string) => void;
  onNotify?: (text: string, tone?: "green" | "blue" | "gold" | "red") => void;
  deadlines?: MockDeadline[];
  setDeadlines?: Dispatch<SetStateAction<MockDeadline[]>>;
  rules?: MockRule[];
  setRules?: Dispatch<SetStateAction<MockRule[]>>;
  resolvedRuleIds?: string[];
  setResolvedRuleIds?: Dispatch<SetStateAction<string[]>>;
  changedDeadlineIds?: string[];
  setChangedDeadlineIds?: Dispatch<SetStateAction<string[]>>;
  reviewFocusRuleId?: string | null;
  importLaunchToken?: number;
};

export const sectionMeta: Record<SectionId, { eyebrow: string; title: string; subtitle: string }> = {
  work: {
    eyebrow: "Work",
    title: "Work queue",
    subtitle: "This week's actionable deadlines, blockers, and rule-change alerts."
  },
  clients: {
    eyebrow: "Clients",
    title: "Client directory",
    subtitle: "Open a client profile or import a portfolio."
  },
  review: {
    eyebrow: "Review",
    title: "Official changes that need a decision",
    subtitle: "Review only the tax-rule changes that affect the current client portfolio."
  },
  settings: {
    eyebrow: "Settings",
    title: "Workspace settings",
    subtitle: "Tenant identity, reminders, and connected channels."
  }
};

const stateOptions = [
  "All",
  "CA",
  "TX",
  "NY",
  "NJ",
  "WA",
  "MN",
  "WI",
  "IL",
  "IN",
  "OH",
  "MI",
  "MA",
  "NH",
  "CO",
  "UT",
  "ID",
  "OR",
  "FL",
  "NV",
  "AZ",
  "Federal"
];

const taxTypeOptions = [
  "All",
  "Federal income",
  "State income",
  "Sales/Use",
  "Property",
  "Payroll (941)",
  "Franchise",
  "Excise",
  "PTE election"
];

function formatDaysRemaining(deadline: MockDeadline) {
  if (deadline.status === "completed") return "Filed";
  if (deadline.extension_status && deadline.extended_due_date) return `Extended -> ${deadline.extended_due_date}`;
  if (deadline.days_remaining < 0) return `Overdue by ${Math.abs(deadline.days_remaining)} days`;
  if (deadline.days_remaining === 0) return "Due today";
  if (deadline.days_remaining === 1) return "Due tomorrow";
  return `In ${deadline.days_remaining} days`;
}

function statusClass(deadline: MockDeadline) {
  if (deadline.status === "blocked") return "cb";
  if (deadline.status === "extension-filed" || deadline.status === "extension-approved") return "ci";
  return "ca";
}

function statusLabel(deadline: MockDeadline) {
  if (deadline.status === "blocked") return deadline.blocker_reason ? `Blocked - ${deadline.blocker_reason}` : "Blocked";
  if (deadline.status === "extension-approved") return "Extension approved";
  if (deadline.status === "extension-filed") return "Extension filed";
  return "Active";
}

function summarizeRuleImpact(before: MockDeadline, after: MockDeadline) {
  if (before.due_date !== after.due_date) {
    return `${before.tax_type} moved from ${before.due_label} to ${after.due_label}.`;
  }
  if (before.status !== after.status && after.status === "blocked") {
    return `${before.tax_type} now requires CPA confirmation and is blocked.`;
  }
  if (before.source !== after.source) {
    return `${before.tax_type} source and filing guidance were updated.`;
  }
  return `${before.tax_type} was updated for this client.`;
}

function applyRuleToDeadline(deadline: MockDeadline, ruleId: string): MockDeadline {
  if (deadline.notice_rule_id !== ruleId) return deadline;

  if (ruleId === "rule-001") {
    return {
      ...deadline,
      due_date: "2026-05-30",
      due_label: "May 30",
      days_remaining: 34,
      source: "FTB Notice 2026-04 - applied to client filing calendar",
      notice_rule_id: undefined
    };
  }

  if (ruleId === "rule-002") {
    return {
      ...deadline,
      status: "blocked",
      blocker_reason: "Nexus confirmation required after TX threshold change",
      source: "TX Comptroller 34-Tex.Admin.Code §3.286 - pending nexus confirmation",
      notice_rule_id: undefined
    };
  }

  if (ruleId === "rule-005") {
    return {
      ...deadline,
      source: "OR DOR Rate Notice 2026-Q2 - rate update applied to template",
      notice_rule_id: undefined
    };
  }

  return {
    ...deadline,
    notice_rule_id: undefined
  };
}

function isThisWeek(deadline: MockDeadline) {
  return deadline.status !== "completed" && deadline.days_remaining >= 0 && deadline.days_remaining <= 7;
}

function clientTags(client: MockClient) {
  if (client.risk_label === "high") return ["Q2 941 doc missing", "CA nexus review"];
  if (client.risk_label === "watch") return client.name.includes("Harbor")
    ? ["PTE decision pending", "Federal ext filed"]
    : ["TX notice - CA nexus"];
  if (client.states.length === 1) return ["Single-state", "Payroll current"];
  if (client.name.includes("Riverbend")) return ["Property: 3 counties"];
  if (client.name.includes("Atlas")) return ["IFTA extensions approved"];
  if (client.name.includes("Kestrel")) return ["Remote-first - PEO payroll"];
  if (client.name.includes("Maple")) return ["Two-clinic group"];
  if (client.name.includes("Glacier")) return ["E-commerce - Avalara"];
  return [client.applicable_taxes[0] || "Active profile"];
}

type ClientRecord = {
  client: MockClient;
  deadlines: MockDeadline[];
  blockers: MockBlocker[];
  reminders: MockReminder[];
  activity: MockActivity[];
};

type ImportDecision = "keep" | "merge" | "skip";

type ImportApplyResult = {
  records: ClientRecord[];
  created: number;
  merged: number;
  skipped: number;
  createdClientIds: string[];
  mergedClientIds: string[];
  createdClientNames: string[];
  mergedClientNames: string[];
};

function ChangeBadge({ kind = "changed" }: { kind?: "new" | "changed" }) {
  return <span className={`badge-pill ${kind === "new" ? "green" : "blue"} thin`}>{kind === "new" ? "New" : "Changed"}</span>;
}

function buildInitialClientRecords(): ClientRecord[] {
  return mockClients.map((client) => ({
    client,
    deadlines: mockDeadlines
      .filter((deadline) => deadline.client_id === client.id)
      .sort((a, b) => a.due_date.localeCompare(b.due_date)),
    blockers: mockBlockers.filter((blocker) => blocker.client_id === client.id),
    reminders: mockReminders
      .filter((reminder) => reminder.client_id === client.id)
      .sort((a, b) => a.send_at.localeCompare(b.send_at)),
    activity: mockActivity.filter((entry) =>
      [client.name, client.name.split(" ")[0]].some((needle) => entry.detail.includes(needle))
    )
  }));
}

function normalizeStates(raw: string): string[] {
  return raw
    .split(/[;,]/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function normalizeTaxes(raw: string): TaxType[] {
  return raw
    .split(/[;,]/)
    .map((value) => value.trim())
    .filter(Boolean) as TaxType[];
}

function makeDueDate(offsetDays: number) {
  const anchor = new Date("2026-04-26T00:00:00");
  anchor.setDate(anchor.getDate() + offsetDays);
  return anchor.toISOString().slice(0, 10);
}

function makeDueLabel(offsetDays: number) {
  const dueDate = new Date(`${makeDueDate(offsetDays)}T00:00:00`);
  return dueDate.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function deriveDeadlinesForImportedClient(client: MockClient, rowIndex: number): MockDeadline[] {
  const taxOffsets: Record<TaxType, number> = {
    "Payroll (941)": 4,
    "Sales/Use": 11,
    "State income": 19,
    "Federal income": 19,
    Franchise: 24,
    Property: 35,
    Excise: 29,
    "PTE election": 9
  };

  return client.applicable_taxes.slice(0, 4).map((taxType, index) => {
    const offset = taxOffsets[taxType] ?? 21 + index * 7;
    const jurisdiction =
      taxType === "Federal income" || taxType === "Payroll (941)"
        ? "Federal"
        : client.states[Math.min(index, client.states.length - 1)] || client.states[0] || "Federal";
    return {
      id: `imp-dl-${client.id}-${index + 1}`,
      client_id: client.id,
      client_name: client.name,
      tax_type: taxType,
      jurisdiction,
      due_date: makeDueDate(offset),
      due_label: makeDueLabel(offset),
      days_remaining: offset,
      status: "pending",
      extension_status: null,
      extended_due_date: null,
      source: `Derived from imported ${client.entity_type} profile · row ${rowIndex + 1}`,
      blocker_reason: null,
      assignee: rowIndex % 2 === 0 ? "Sarah Johnson" : "Maya Chen"
    };
  });
}

function buildImportedRecordFromRow(row: string[], rowIndex: number): ClientRecord {
  const client: MockClient = {
    id: `imp-cl-${rowIndex + 1}-${row[0].toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    name: row[0],
    entity_type: row[1] as EntityType,
    states: normalizeStates(row[2]),
    primary_contact_name: row[3],
    primary_contact_email: row[4],
    applicable_taxes: normalizeTaxes(row[5]),
    active_deadlines: 0,
    blocked_deadlines: 0,
    extensions_filed: 0,
    risk_label:
      row[6].toLowerCase().includes("blocking") || row[6].toLowerCase().includes("nexus")
        ? "watch"
        : null,
    notes: row[6]
  };

  const deadlines = deriveDeadlinesForImportedClient(client, rowIndex);
  client.active_deadlines = deadlines.length;

  return {
    client,
    deadlines,
    blockers: [],
    reminders: [],
    activity: [
      {
        id: `imp-act-${client.id}`,
        when: "Just now",
        actor: "DueDateHQ",
        action: "imported client",
        detail: `Imported ${client.name} from CSV and derived ${deadlines.length} deadlines.`,
        category: "import"
      }
    ]
  };
}

function applyImportedRowsToRecords(
  current: ClientRecord[],
  rows: string[][],
  decisions: ImportDecision[]
): ImportApplyResult {
  const next = [...current];
  let created = 0;
  let merged = 0;
  let skipped = 0;
  const createdClientIds: string[] = [];
  const mergedClientIds: string[] = [];
  const createdClientNames: string[] = [];
  const mergedClientNames: string[] = [];

  rows.forEach((row, rowIndex) => {
    const decision = decisions[rowIndex];
    if (decision === "skip") {
      skipped += 1;
      return;
    }

    const imported = buildImportedRecordFromRow(row, rowIndex);
    const existingIndex = next.findIndex((record) => record.client.name === row[0]);

    if (decision === "merge" && existingIndex >= 0) {
      const existing = next[existingIndex];
      const mergedClient: MockClient = {
        ...existing.client,
        entity_type: imported.client.entity_type,
        primary_contact_name: imported.client.primary_contact_name || existing.client.primary_contact_name,
        primary_contact_email: imported.client.primary_contact_email || existing.client.primary_contact_email,
        states: Array.from(new Set([...existing.client.states, ...imported.client.states])),
        applicable_taxes: Array.from(
          new Set([...existing.client.applicable_taxes, ...imported.client.applicable_taxes])
        ) as TaxType[],
        notes: `${existing.client.notes} Imported update: ${imported.client.notes}`
      };

      const mergedDeadlines = [
        ...existing.deadlines,
        ...imported.deadlines.filter(
          (deadline) =>
            !existing.deadlines.some(
              (currentDeadline) =>
                currentDeadline.tax_type === deadline.tax_type &&
                currentDeadline.jurisdiction === deadline.jurisdiction
            )
        )
      ].sort((a, b) => a.due_date.localeCompare(b.due_date));

      mergedClient.active_deadlines = mergedDeadlines.filter((d) => d.status !== "completed").length;
      mergedClient.blocked_deadlines = existing.blockers.length;
      mergedClient.extensions_filed = mergedDeadlines.filter((d) => d.extension_status).length;

      next[existingIndex] = {
        client: mergedClient,
        deadlines: mergedDeadlines,
        blockers: existing.blockers,
        reminders: existing.reminders,
        activity: [
          {
            id: `merge-${existing.client.id}-${rowIndex}`,
            when: "Just now",
            actor: "DueDateHQ",
            action: "merged import row",
            detail: `Merged imported CSV data into ${existing.client.name}.`,
            category: "import"
          },
          ...existing.activity
        ]
      };
      merged += 1;
      mergedClientIds.push(existing.client.id);
      mergedClientNames.push(existing.client.name);
      return;
    }

    next.push(imported);
    created += 1;
    createdClientIds.push(imported.client.id);
    createdClientNames.push(imported.client.name);
  });

  return {
    records: next,
    created,
    merged,
    skipped,
    createdClientIds,
    mergedClientIds,
    createdClientNames,
    mergedClientNames
  };
}

export function WorkSection({
  deadlines: deadlineStore,
  rules: ruleStore,
  onExport,
  onNotify,
  openSection,
  setResolvedRuleIds,
  setDeadlines: setDeadlineStore
}: SectionContext) {
  const deadlines = deadlineStore ?? mockDeadlines;
  const rules = ruleStore ?? mockRules;
  const [filterOpen, setFilterOpen] = useState(false);
  const [stateFilter, setStateFilter] = useState("All");
  const [taxFilter, setTaxFilter] = useState("All");
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [selectedDeadlineId, setSelectedDeadlineId] = useState<string | null>(null);

  const visibleDeadlines = useMemo(
    () =>
      deadlines
        .filter((deadline) => {
          if (deadline.status === "completed") return archiveOpen;
          if (!archiveOpen && !isThisWeek(deadline)) return false;
          if (stateFilter !== "All" && deadline.jurisdiction !== stateFilter) return false;
          if (taxFilter !== "All" && deadline.tax_type !== taxFilter) return false;
          return true;
        })
        .sort((a, b) => a.days_remaining - b.days_remaining),
    [deadlines, stateFilter, taxFilter, archiveOpen]
  );

  const grouped = useMemo(() => {
    const groups = new Map<string, MockDeadline[]>();
    visibleDeadlines.forEach((deadline) => {
      const key = deadline.days_remaining <= 4 ? "Apr 27 - May 3" : deadline.due_label;
      groups.set(key, [...(groups.get(key) || []), deadline]);
    });
    return [...groups.entries()];
  }, [visibleDeadlines]);

  const selectedDeadline = selectedDeadlineId ? deadlines.find((deadline) => deadline.id === selectedDeadlineId) : null;
  const pendingRules = rules.filter((rule) => rule.status === "pending-review");
  const thisWeekCount = deadlines.filter(isThisWeek).length;
  const blockedCount = deadlines.filter((deadline) => deadline.status === "blocked").length;
  const nextThirty = deadlines.filter((deadline) => deadline.status !== "completed" && deadline.days_remaining >= 0 && deadline.days_remaining <= 30);

  function updateDeadline(deadlineId: string, updater: (deadline: MockDeadline) => MockDeadline) {
    setDeadlineStore?.((current) => current.map((deadline) => (deadline.id === deadlineId ? updater(deadline) : deadline)));
  }

  if (selectedDeadline) {
    return (
      <section className="ddh-work-detail">
        <button type="button" className="ddh-back-link" onClick={() => setSelectedDeadlineId(null)}>
          Back to work queue
        </button>
        <div className="detail-head">
          <div>
            <h2>{selectedDeadline.client_name} - {selectedDeadline.tax_type}</h2>
            <p>Inspect the source, reminders, blockers, and extension state for this item.</p>
          </div>
          <div className="detail-actions">
            <button
              type="button"
              className="ddh-btn"
              onClick={() => {
                updateDeadline(selectedDeadline.id, (deadline) => ({ ...deadline, status: "completed" }));
                setSelectedDeadlineId(null);
                onNotify?.(`${selectedDeadline.client_name} archived from the work queue.`, "blue");
              }}
            >
              Archive
            </button>
            <button
              type="button"
              className="ddh-btn ddh-btn-primary"
              onClick={() => {
                updateDeadline(selectedDeadline.id, (deadline) =>
                  deadline.status === "blocked"
                    ? { ...deadline, status: "pending", blocker_reason: null }
                    : { ...deadline, status: "blocked", blocker_reason: "Waiting on client" }
                );
                setSelectedDeadlineId(null);
              }}
            >
              {selectedDeadline.status === "blocked" ? "Resolve blocker" : "Mark blocked"}
            </button>
          </div>
        </div>

        <div className="detail-grid">
          <article className="detail-card">
            <div className="detail-card-lbl">Deadline</div>
            <div className="detail-bigtext">{selectedDeadline.tax_type} - {selectedDeadline.jurisdiction}</div>
            <div className="detail-date">{selectedDeadline.due_label} - {formatDaysRemaining(selectedDeadline)}</div>
            <div className="detail-fields">
              <div className="df"><span>Status</span><strong>{statusLabel(selectedDeadline)}</strong></div>
              <div className="df"><span>Assignee</span><strong>{selectedDeadline.assignee}</strong></div>
              <div className="df"><span>Source</span><strong>{selectedDeadline.source}</strong></div>
              <div className="df"><span>Extension</span><strong>{selectedDeadline.extended_due_date || "No extension"}</strong></div>
            </div>
          </article>
          <aside className="detail-right">
            <article className="detail-card">
              <div className="detail-card-lbl">Reminders</div>
              <h3>Queued reminder timeline</h3>
              <p>What is already scheduled for this deadline.</p>
              <div className="rem-item"><strong>Final-day push</strong><span>Email - scheduled</span><span>Apr 29, 8:00 AM</span></div>
            </article>
            <article className="detail-card">
              <div className="detail-card-lbl">Blocker</div>
              <h3>Blocking status</h3>
              <p>If this item is waiting on something, it will show here.</p>
              <div className="rem-item">
                <strong>{selectedDeadline.blocker_reason || "No blocker"}</strong>
                <span>{selectedDeadline.blocker_reason ? "Waiting on client to provide supporting information." : "This deadline is not blocked right now."}</span>
              </div>
            </article>
          </aside>
        </div>
      </section>
    );
  }

  return (
    <section className="ddh-work">
      <div className="ddh-summary">
        <SummaryCard label="This week" value={String(thisWeekCount)} sub="Actionable now" />
        <SummaryCard label="Blocked" value={String(blockedCount)} sub="Waiting on client" warn />
        <SummaryCard label="Rule changes" value={String(pendingRules.length)} sub="Need CPA decision" />
        <SummaryCard label="Next 30 days" value={String(nextThirty.length)} sub={`Across ${new Set(nextThirty.map((deadline) => deadline.client_id)).size} clients`} />
      </div>

      <div className="ddh-toolbar">
        <button type="button" className="ddh-btn" onClick={() => setFilterOpen((current) => !current)}>
          <FilterIcon /> Filter
        </button>
        <button type="button" className="ddh-btn" onClick={() => onExport?.("Work queue", "csv")}>
          <DownloadIcon /> Export
        </button>
        <button type="button" className="ddh-btn ddh-btn-sm ddh-archive-btn" onClick={() => setArchiveOpen((current) => !current)}>
          {archiveOpen ? "Back to active" : "View archive (1)"}
        </button>
        {filterOpen ? (
          <FilterPanel
            stateFilter={stateFilter}
            taxFilter={taxFilter}
            onState={setStateFilter}
            onTax={setTaxFilter}
            onClear={() => {
              setStateFilter("All");
              setTaxFilter("All");
            }}
            onDone={() => setFilterOpen(false)}
          />
        ) : null}
      </div>

      {grouped.map(([label, items], index) => (
        <div key={label} className="ddh-table">
          <div className="ddh-group">
            <span>{label}</span>
            <span>{index === 0 ? "This week - " : ""}{items.length} deadline{items.length === 1 ? "" : "s"}</span>
          </div>
          {index === 0 && pendingRules[0] ? (
            <div className="ddh-alert">
              <span className="ddh-alert-dot" />
              {pendingRules[0].source} - {pendingRules[0].title}. Affects {pendingRules[0].affected_count} clients.
              <button
                type="button"
                onClick={() => {
                  openSection?.("review", { ruleId: pendingRules[0].id });
                  onNotify?.("Opened Review and focused the pending rule change.", "blue");
                }}
              >
                Review & apply
              </button>
            </div>
          ) : null}
          <div className="ddh-cols">
            <span>Client</span><span>Tax type</span><span>State</span><span>Status</span><span>Assignee</span><span />
          </div>
          {items.map((deadline) => (
            <button
              type="button"
              key={deadline.id}
              className={`ddh-row ${deadline.status === "blocked" ? "blocked" : ""}`}
              onClick={() => setSelectedDeadlineId(deadline.id)}
            >
              <span className="ddh-client">{deadline.client_name}</span>
              <span><span className="ddh-chip tax">{deadline.tax_type}</span></span>
              <span><span className="ddh-chip jurisdiction">{deadline.jurisdiction}</span></span>
              <span><span className={`ddh-chip ${statusClass(deadline)}`}>{statusLabel(deadline)}</span></span>
              <span className="ddh-assignee">{deadline.assignee}</span>
              <span className="ddh-link">Details</span>
            </button>
          ))}
        </div>
      ))}
    </section>
  );
}

function SummaryCard({ label, value, sub, warn }: { label: string; value: string; sub: string; warn?: boolean }) {
  return (
    <article className={`ddh-summary-card ${warn ? "warn" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{sub}</small>
    </article>
  );
}

function FilterPanel({
  stateFilter,
  taxFilter,
  onState,
  onTax,
  onClear,
  onDone
}: {
  stateFilter: string;
  taxFilter: string;
  onState: (value: string) => void;
  onTax: (value: string) => void;
  onClear: () => void;
  onDone: () => void;
}) {
  return (
    <div className="ddh-filter-panel">
      <div className="ddh-filter-head">
        <strong>Filter</strong>
        <button type="button" onClick={onClear}>Clear all</button>
      </div>
      <FilterPills label="State" value={stateFilter} options={stateOptions} onSelect={onState} />
      <FilterPills label="Tax type" value={taxFilter} options={taxTypeOptions} onSelect={onTax} />
      <button type="button" className="ddh-btn ddh-btn-primary" onClick={onDone}>Done</button>
    </div>
  );
}

function FilterPills({ label, value, options, onSelect }: { label: string; value: string; options: string[]; onSelect: (value: string) => void }) {
  return (
    <>
      <div className="ddh-filter-label">{label}</div>
      <div className="ddh-filter-pills">
        {options.map((option) => (
          <button
            type="button"
            key={option}
            className={`ddh-filter-pill ${option === value ? "on" : ""}`}
            onClick={() => onSelect(option)}
          >
            {option}
          </button>
        ))}
      </div>
    </>
  );
}

type ImportStep = 1 | 2 | 3 | 4;

const IMPORT_SAMPLE_ROWS = [
  [
    "Northwind Services LLC",
    "LLC",
    "CA, TX, NV",
    "Maya Chen",
    "maya@northwindservices.com",
    "Federal income, State income, Payroll (941), Sales/Use",
    "Payroll heavy across three states; refreshed from the latest source file."
  ],
  [
    "Harbor Studio Partners",
    "Partnership",
    "NY, NJ",
    "Evan Malik",
    "evan@harborstudio.com",
    "Federal income, State income, PTE election",
    "PTE election decision pending; extension already filed federally."
  ],
  [
    "Greenway Consulting LLC",
    "LLC",
    "CO",
    "Avery Morris",
    "avery@greenwayconsulting.com",
    "Federal income, State income",
    "New advisory client added from CSV import."
  ],
  [
    "Harbor Ridge Retail",
    "C-Corp",
    "CA, AZ",
    "Lena Ortiz",
    "finance@harborridge.com",
    "Federal income, Sales/Use, Franchise",
    "New retail group with California and Arizona obligations."
  ],
  [
    "Blue Summit Therapy Group",
    "Professional Corp",
    "WA, OR",
    "Dr. Nia Brooks",
    "ops@bluesummittherapy.com",
    "Federal income, State income, Payroll (941)",
    "New multi-state therapy practice requiring payroll setup."
  ]
] as const;

export function ClientsSection({ onExport, onNotify, importLaunchToken = 0, deadlines: deadlineStore, changedDeadlineIds = [] }: SectionContext) {
  const [importOpen, setImportOpen] = useState(false);
  const [importStep, setImportStep] = useState<ImportStep>(1);
  const [filterOpen, setFilterOpen] = useState(false);
  const [stateFilter, setStateFilter] = useState("All");
  const [taxFilter, setTaxFilter] = useState("All");
  const [records, setRecords] = useState<ClientRecord[]>(() => buildInitialClientRecords());
  const [recentImportResult, setRecentImportResult] = useState<ImportApplyResult | null>(null);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);
  const deadlines = deadlineStore ?? mockDeadlines;

  useEffect(() => {
    if (importLaunchToken) {
      setImportOpen(true);
      setImportStep(1);
    }
  }, [importLaunchToken]);

  function openImport() {
    setImportOpen(true);
    setImportStep(1);
  }

  function closeImport() {
    setImportOpen(false);
    setImportStep(1);
  }

  const recordsWithLiveDeadlines = useMemo(
    () =>
      records.map((record) => {
        const liveDeadlines = deadlines
          .filter((deadline) => deadline.client_id === record.client.id)
          .sort((a, b) => a.due_date.localeCompare(b.due_date));
        const extensionCount = liveDeadlines.filter((deadline) => deadline.extension_status).length;
        const blockedCount = liveDeadlines.filter((deadline) => deadline.status === "blocked").length;
        const activeCount = liveDeadlines.filter((deadline) => deadline.status !== "completed").length;
        return {
          ...record,
          client: {
            ...record.client,
            active_deadlines: activeCount,
            blocked_deadlines: blockedCount,
            extensions_filed: extensionCount
          },
          deadlines: liveDeadlines
        };
      }),
    [records, deadlines]
  );

  const filteredRecords = useMemo(
    () =>
      recordsWithLiveDeadlines.filter((record) => {
        if (stateFilter !== "All" && !record.client.states.includes(stateFilter)) return false;
        if (taxFilter !== "All" && !record.client.applicable_taxes.includes(taxFilter as TaxType)) return false;
        return true;
      }),
    [recordsWithLiveDeadlines, stateFilter, taxFilter]
  );

  if (importOpen) {
    return (
      <ImportWizard
        step={importStep}
        onStep={setImportStep}
        onClose={closeImport}
        onApply={(rows, decisions) => {
          const result = applyImportedRowsToRecords(records, rows, decisions);
          setRecords(result.records);
          setRecentImportResult(result);
          onNotify?.(`Import complete: ${result.created} new, ${result.merged} updated, ${result.skipped} skipped.`, "green");
          return result;
        }}
        onDone={() => {
          closeImport();
        }}
      />
    );
  }

  if (selectedClientId) {
    const record = recordsWithLiveDeadlines.find((entry) => entry.client.id === selectedClientId);
    if (record) {
      return (
        <ClientDetailSurface
          record={record}
          changedDeadlineIds={changedDeadlineIds}
          onBack={() => setSelectedClientId(null)}
          onExport={onExport}
        />
      );
    }
  }

  return (
    <section>
      <div className="ddh-page-head">
        <div>
          <div className="ddh-eyebrow">Clients</div>
          <h1>Client directory</h1>
        </div>
        <div className="ddh-actions">
          <button type="button" className="ddh-btn" onClick={() => setFilterOpen((current) => !current)}>
            <FilterIcon active={filterOpen} /> Filter
          </button>
          <button type="button" className="ddh-btn" onClick={() => onExport?.("Client directory", "pdf")}>Export</button>
          <button type="button" className="ddh-btn ddh-btn-primary" onClick={openImport}><UploadIcon /> Import</button>
        </div>
      </div>

      {filterOpen ? (
        <div className="ddh-toolbar">
          <FilterPanel
            stateFilter={stateFilter}
            taxFilter={taxFilter}
            onState={setStateFilter}
            onTax={setTaxFilter}
            onClear={() => {
              setStateFilter("All");
              setTaxFilter("All");
            }}
            onDone={() => setFilterOpen(false)}
          />
        </div>
      ) : null}

      {recentImportResult ? (
        <article className="card import-result-banner">
          <div className="import-result-copy">
            <span className="eyebrow">Latest import</span>
            <strong>{recentImportResult.created} new · {recentImportResult.merged} updated</strong>
            <p>{recentImportResult.skipped} skipped. Client cards below now reflect the imported portfolio changes.</p>
          </div>
          <div className="import-result-groups">
            {recentImportResult.createdClientNames.length ? (
              <div className="import-result-group">
                <span className="import-result-label">New client cards created</span>
                <div className="import-result-chips">
                  {recentImportResult.createdClientNames.map((name) => (
                    <span key={name} className="badge-pill green thin">{name}</span>
                  ))}
                </div>
              </div>
            ) : null}
            {recentImportResult.mergedClientNames.length ? (
              <div className="import-result-group">
                <span className="import-result-label">Existing clients updated</span>
                <div className="import-result-chips">
                  {recentImportResult.mergedClientNames.map((name) => (
                    <span key={name} className="badge-pill blue thin">{name}</span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
          <button type="button" className="ghost-btn" onClick={() => setRecentImportResult(null)}>Dismiss</button>
        </article>
      ) : null}

      <div className="ddh-client-grid">
        {filteredRecords.slice(0, 12).map((record) => {
          const hasChanged = record.deadlines.some((deadline) => changedDeadlineIds.includes(deadline.id));
          const importState = recentImportResult?.createdClientIds.includes(record.client.id)
            ? "new"
            : recentImportResult?.mergedClientIds.includes(record.client.id)
              ? "updated"
              : null;
          return (
            <ClientTile
              key={record.client.id}
              client={record.client}
              hasChanged={hasChanged}
              importState={importState}
              onOpenClient={setSelectedClientId}
            />
          );
        })}
      </div>
    </section>
  );
}

function ClientTile({
  client,
  hasChanged,
  importState,
  onOpenClient
}: {
  client: MockClient;
  hasChanged: boolean;
  importState: "new" | "updated" | null;
  onOpenClient: (clientId: string) => void;
}) {
  const tags = clientTags(client);
  return (
    <button
      type="button"
      className={`ddh-client-card ${client.risk_label === "high" ? "high" : client.risk_label === "watch" ? "watch" : ""}`}
      onClick={() => onOpenClient(client.id)}
    >
      <div className="client-tile-head">
        <div>
          <h2>{client.name}</h2>
          <p>{client.entity_type} - {client.states.join(", ")}</p>
        </div>
        <div className="client-tile-statuses">
          {client.risk_label === "high" ? (
            <span className="badge-pill red">High risk</span>
          ) : client.risk_label === "watch" ? (
            <span className="badge-pill gold">Watch</span>
          ) : (
            <span className="badge-pill green">Calm</span>
          )}
          {importState === "new" ? <ChangeBadge kind="new" /> : null}
          {importState === "updated" ? <span className="badge-pill blue thin">Updated</span> : null}
          {hasChanged ? <ChangeBadge /> : null}
        </div>
      </div>
      <div className="ddh-client-tags">
        {tags.map((tag, index) => (
          <span
            key={tag}
            className={`ddh-client-tag ${
              client.risk_label === "high" && index === 0
                ? "danger"
                : client.risk_label === "watch"
                  ? "warn"
                  : "neutral"
            }`}
          >
            {tag}
          </span>
        ))}
      </div>
      <div className="ddh-client-counts">
        <span><strong>{client.active_deadlines}</strong> active</span>
        <span><strong>{client.blocked_deadlines}</strong> blocked</span>
        <span><strong>{client.extensions_filed}</strong> extensions</span>
      </div>
      <p>{client.notes}</p>
      <div className="ddh-client-foot">
        <span>{client.primary_contact_name}</span>
        <span className="client-tile-link">
          <span>Details</span>
          <ChevronRightIcon />
        </span>
      </div>
    </button>
  );
}

function ImportWizard({
  step,
  onStep,
  onClose,
  onApply,
  onDone
}: {
  step: ImportStep;
  onStep: (step: ImportStep) => void;
  onClose: () => void;
  onApply: (rows: string[][], decisions: ImportDecision[]) => ImportApplyResult;
  onDone: () => void;
}) {
  const [result, setResult] = useState<ImportApplyResult | null>(null);

  function next() {
    if (step < 4) onStep((step + 1) as ImportStep);
  }
  function back() {
    if (step > 1) onStep((step - 1) as ImportStep);
  }

  return (
    <section className="ddh-import">
      <div className="ddh-import-head">
        <div>
          <div className="ddh-eyebrow">Clients - Import</div>
          <h1>Bring a portfolio of clients into DueDateHQ</h1>
          <p>Upload a CSV, confirm how its columns map to our client fields, and review duplicate detection before anything is written.</p>
        </div>
        <button type="button" className="ddh-btn" onClick={onClose}>Cancel & back to clients</button>
      </div>
      <div className="ddh-stepper">
        {["Choose file", "Map columns", "Review rows", "Done"].map((label, index) => {
          const itemStep = (index + 1) as ImportStep;
          return (
            <div key={label} className="ddh-step">
              <span className={itemStep <= step ? "active" : ""}>{index + 1}</span>
              <strong className={itemStep <= step ? "active" : ""}>{label}</strong>
            </div>
          );
        })}
      </div>
      <div className="ddh-import-body">
        {step === 1 ? <ImportStepOne onNext={next} /> : null}
        {step === 2 ? <ImportStepTwo onBack={back} onNext={next} /> : null}
        {step === 3 ? (
          <ImportStepThree
            onBack={back}
            onApply={() => {
              const decisions: ImportDecision[] = IMPORT_SAMPLE_ROWS.map((row) =>
                row[0].trim().toLowerCase() === "northwind services llc" ? "merge" : "keep"
              );
              const applied = onApply(IMPORT_SAMPLE_ROWS.map((row) => [...row]), decisions);
              setResult(applied);
              onStep(4);
            }}
          />
        ) : null}
        {step === 4 ? <ImportStepDone result={result} onDone={onDone} /> : null}
      </div>
    </section>
  );
}

function ImportStepOne({ onNext }: { onNext: () => void }) {
  return (
    <>
      <button type="button" className="ddh-upload-area" onClick={onNext}>
        <span className="ddh-upload-icon"><UploadIcon /></span>
        <strong>Drop your CSV here, or click to browse</strong>
        <small>clients_taxdome_export.csv · 5 rows detected · 1 existing client match</small>
        <span className="ddh-source-tags">
          {["TaxDome", "Drake", "Karbon", "QuickBooks", "Custom CSV"].map((source) => <em key={source}>{source}</em>)}
        </span>
      </button>
      <div className="ddh-step-foot"><button type="button" className="ddh-btn ddh-btn-primary" onClick={onNext}>Continue</button></div>
    </>
  );
}

function ImportStepTwo({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const rows = [
    ["client_name", "Northwind Services LLC", "Client name", "Auto-matched"],
    ["ein", "47-2938471", "EIN / Tax ID", "Auto-matched"],
    ["entity_type", "LLC", "Entity type", "Auto-matched"],
    ["primary_state", "CA", "Primary state", "Auto-matched"],
    ["additional_states", "TX, NV", "Additional states", "Auto-matched"],
    ["tax_types_csv", "Federal income, 941", "Tax types", "Auto-matched"],
    ["assigned_preparer", "Maya Chen", "Assignee", "Auto-matched"],
    ["misc_notes", "Payroll heavy, 3 states", "Skip column", "Review needed"]
  ];
  return (
    <>
      <p className="ddh-import-note">AI detected 7 of 8 fields automatically. Review the mapping before continuing.</p>
      <table className="ddh-map-table">
        <thead><tr><th>CSV column</th><th>Sample value</th><th>Field</th><th>Confidence</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]}>
              <td><code>{row[0]}</code></td>
              <td>{row[1]}</td>
              <td><select defaultValue={row[2]}><option>{row[2]}</option><option>Notes</option><option>Skip column</option></select></td>
              <td><span className={row[3] === "Review needed" ? "review" : "auto"}>{row[3]}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="ddh-step-foot"><button type="button" className="ddh-btn" onClick={onBack}>Back</button><button type="button" className="ddh-btn ddh-btn-primary" onClick={onNext}>Continue</button></div>
    </>
  );
}

function ImportStepThree({ onBack, onApply }: { onBack: () => void; onApply: () => void }) {
  const rows = [
    ["Northwind Services LLC", "LLC", "CA, TX, NV", "Federal income, State income, Payroll (941), Sales/Use", "Maya Chen", "Merge with existing"],
    ["Harbor Studio Partners", "Partnership", "NY, NJ", "Federal income, State income, PTE election", "Evan Malik", "Create"],
    ["Greenway Consulting LLC", "LLC", "CO", "Federal income, State income", "Avery Morris", "Create"],
    ["Harbor Ridge Retail", "C-Corp", "CA, AZ", "Federal income, Sales/Use, Franchise", "Lena Ortiz", "Create"],
    ["Blue Summit Therapy Group", "Prof Corp", "WA, OR", "Federal income, State income, 941", "Dr. Nia Brooks", "Create"]
  ];
  return (
    <>
      <p className="ddh-import-note">5 rows parsed · 1 existing client match · 4 new client cards will be created.</p>
      <table className="ddh-review-table">
        <thead><tr><th>Client</th><th>Entity</th><th>States</th><th>Tax types</th><th>Assignee</th><th>Action</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]} className={row[5] !== "Create" ? "warn" : ""}>
              {row.map((cell, index) => <td key={index}><span className={index === 5 ? (cell === "Create" ? "auto" : "review") : ""}>{cell}</span></td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="ddh-step-foot"><button type="button" className="ddh-btn" onClick={onBack}>Back</button><button type="button" className="ddh-btn ddh-btn-primary" onClick={onApply}>Apply import</button></div>
    </>
  );
}

function ImportStepDone({ result, onDone }: { result: ImportApplyResult | null; onDone: () => void }) {
  return (
    <div className="ddh-import-done">
      <div>✓</div>
      <h2>{result ? `${result.created} new · ${result.merged} updated` : "Import complete"}</h2>
      <p>Full-year deadline calendars generated. New clients were added to the directory and existing matches were updated in place.</p>
      {result ? (
        <div className="import-complete-breakdown">
          {result.createdClientNames.length ? (
            <div className="import-complete-group">
              <span className="import-result-label">New client cards created</span>
              <div className="import-result-chips">
                {result.createdClientNames.map((name) => (
                  <span key={name} className="badge-pill green thin">{name}</span>
                ))}
              </div>
            </div>
          ) : null}
          {result.mergedClientNames.length ? (
            <div className="import-complete-group">
              <span className="import-result-label">Existing clients updated</span>
              <div className="import-result-chips">
                {result.mergedClientNames.map((name) => (
                  <span key={name} className="badge-pill blue thin">{name}</span>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
      <button type="button" className="ddh-btn ddh-btn-primary" onClick={onDone}>Go to client directory</button>
    </div>
  );
}

function ClientDetailSurface({
  record,
  changedDeadlineIds,
  onBack,
  onExport
}: {
  record: ClientRecord;
  changedDeadlineIds: string[];
  onBack: () => void;
  onExport?: (scope: string, format: "csv" | "pdf") => void;
}) {
  const { client, deadlines, blockers, reminders, activity: recentActivity } = record;
  const extensionDeadlines = deadlines.filter((deadline) => deadline.extension_status);
  const hasChangedDeadlines = deadlines.some((deadline) => changedDeadlineIds.includes(deadline.id));
  const nextDeadline = deadlines[0] || null;
  const latestActivity = recentActivity[0] || null;

  return (
    <section className="ddh-work-detail client-detail-lite">
      <button type="button" className="ddh-back-link" onClick={onBack}>
        Back to clients
      </button>
      <div className="detail-head">
        <div>
          <h2>
            {client.name}
            {hasChangedDeadlines ? <ChangeBadge /> : null}
          </h2>
          <p>Review the client profile, derived deadlines, blockers, extensions, and reminders in one place.</p>
        </div>
        <div className="detail-actions">
          <button
            type="button"
            className="ddh-btn"
            onClick={() => onExport?.(`${client.name} — full deadline pack`, "csv")}
          >
            Export CSV
          </button>
          <button
            type="button"
            className="ddh-btn"
            onClick={() => onExport?.(`${client.name} — full deadline pack`, "pdf")}
          >
            Export PDF
          </button>
        </div>
      </div>

      <div className="detail-grid client-detail-grid">
        <article className="detail-card">
          <div className="detail-card-lbl">Client</div>
          <div className="detail-bigtext">{client.entity_type} · {client.states.join(", ")}</div>
          <div className="detail-date">{client.primary_contact_name} · {client.primary_contact_email}</div>
          <div className="detail-fields">
            <div className="df"><span>Taxes</span><strong>{client.applicable_taxes.slice(0, 3).join(" · ")}{client.applicable_taxes.length > 3 ? ` +${client.applicable_taxes.length - 3}` : ""}</strong></div>
            <div className="df"><span>Next due</span><strong>{nextDeadline ? `${nextDeadline.due_label} · ${formatDaysRemaining(nextDeadline)}` : "No deadlines"}</strong></div>
            <div className="df"><span>Open blockers</span><strong>{blockers.length}</strong></div>
            <div className="df"><span>Extensions</span><strong>{extensionDeadlines.length}</strong></div>
          </div>
          <p className="client-tile-notes">{client.notes}</p>
        </article>

        <aside className="detail-right">
          <article className="detail-card detail-history-card">
            <div className="detail-card-lbl">Client history</div>
            <h3>Recent status and activity</h3>
            <p>A compact readout of what is blocking work, what is queued, and what changed most recently.</p>
            <div className="detail-history-list">
              <div className="detail-history-row">
                <span className="detail-history-kicker">Blocking</span>
                <strong>{blockers.length ? blockers[0].reason : "No blocker"}</strong>
                <span>{blockers.length ? `Waiting on ${blockers[0].waiting_on}` : "Nothing is blocking this client right now."}</span>
              </div>
              <div className="detail-history-row">
                <span className="detail-history-kicker">Reminders</span>
                <strong>{reminders.length} reminder{reminders.length === 1 ? "" : "s"} queued</strong>
                <span>{reminders[0] ? `${reminders[0].step}-day ${reminders[0].channel} · ${reminders[0].send_at}` : "No reminder events are scheduled."}</span>
              </div>
              <div className="detail-history-row">
                <span className="detail-history-kicker">Latest activity</span>
                <strong>{latestActivity ? latestActivity.action : "No recent activity"}</strong>
                <span>{latestActivity ? `${latestActivity.when} · ${latestActivity.detail}` : "This client has no activity log entries in the current demo."}</span>
              </div>
            </div>
          </article>
        </aside>
      </div>

      <article className="detail-card client-deadlines-card">
        <div className="detail-card-lbl">Deadline calendar</div>
        <h3>{deadlines.length} deadline{deadlines.length === 1 ? "" : "s"} derived from the current profile</h3>
        <p>Generated from entity type, state footprint, and filing scope.</p>
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
              <span role="columnheader">Assignee</span>
              <span role="columnheader">Change</span>
            </div>
            {deadlines.map((deadline) => (
              <div key={deadline.id} className="deadlines-table-row" role="row">
                <span className="deadlines-cell client" role="cell">{deadline.tax_type}</span>
                <span role="cell">{deadline.jurisdiction}</span>
                <span className="deadlines-cell due" role="cell">
                  <strong>{deadline.due_label}</strong>
                  <span className="muted">{formatDaysRemaining(deadline)}</span>
                </span>
                <span role="cell">
                  <span className={`badge-pill ${statusClass(deadline) === "cb" ? "red" : statusClass(deadline) === "ci" ? "gold" : "blue"} thin`}>
                    {statusLabel(deadline)}
                  </span>
                </span>
                <span role="cell">{deadline.assignee}</span>
                <span role="cell">{changedDeadlineIds.includes(deadline.id) ? <ChangeBadge /> : null}</span>
              </div>
            ))}
          </div>
        )}
      </article>
    </section>
  );
}

export function ReviewSection({
  rules: ruleStore,
  setRules,
  setResolvedRuleIds,
  deadlines: deadlineStore,
  setDeadlines,
  setChangedDeadlineIds,
  onNotify,
  reviewFocusRuleId
}: SectionContext) {
  const rules = ruleStore ?? mockRules;
  const pendingRules = rules.filter((rule) => rule.status === "pending-review");
  const appliedRules = rules.filter((rule) => rule.status === "applied");
  const autoApplied = rules.filter((rule) => rule.status === "auto-applied");
  const dismissedRules = rules.filter((rule) => rule.status === "dismissed");
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);

  useEffect(() => {
    if (!reviewFocusRuleId) return;
    setSelectedRuleId(reviewFocusRuleId);
  }, [reviewFocusRuleId]);

  function applyRule(ruleId: string) {
    const changedIds: string[] = [];
    setRules?.((current) => current.map((rule) => rule.id === ruleId ? { ...rule, status: "applied" } : rule));
    setDeadlines?.((current) =>
      current.map((deadline) => {
        if (deadline.notice_rule_id !== ruleId) return deadline;
        const next = applyRuleToDeadline(deadline, ruleId);
        if (
          next.due_date !== deadline.due_date ||
          next.status !== deadline.status ||
          next.source !== deadline.source ||
          next.notice_rule_id !== deadline.notice_rule_id
        ) {
          changedIds.push(deadline.id);
        }
        return next;
      })
    );
    setResolvedRuleIds?.((current) => current.includes(ruleId) ? current : [...current, ruleId]);
    setChangedDeadlineIds?.((current) => [...new Set([...current, ...changedIds])]);
    onNotify?.("Rule applied to affected clients.", "green");
  }

  function dismissRule(ruleId: string) {
    setRules?.((current) => current.map((rule) => rule.id === ruleId ? { ...rule, status: "dismissed" } : rule));
    setResolvedRuleIds?.((current) => current.includes(ruleId) ? current : [...current, ruleId]);
    onNotify?.("Rule dismissed for this portfolio.", "gold");
  }

  function reopenRule(ruleId: string) {
    setRules?.((current) => current.map((rule) => rule.id === ruleId ? { ...rule, status: "pending-review" } : rule));
    setResolvedRuleIds?.((current) => current.filter((id) => id !== ruleId));
    onNotify?.("Rule moved back to Pending review.", "blue");
  }

  return (
    <section>
      <div className="ddh-page-head review-head">
        <div>
          <div className="ddh-eyebrow">Review</div>
          <h1>Official changes that need a decision</h1>
          <p>Review only the tax-rule changes that affect the current client portfolio.</p>
        </div>
      </div>
      <div className="ddh-review-info">
        <div>
          <strong>{pendingRules.length} official changes need review</strong>
          <span>{mockSyncStatus.rules_auto_applied_today} auto-applied today - {mockSyncStatus.source_count} sources healthy</span>
        </div>
        <div>
          Last full sync <strong>{mockSyncStatus.last_full_sync}</strong> - Next sync <strong>{mockSyncStatus.next_scheduled_sync}</strong>
          <em>Healthy</em>
        </div>
      </div>
      <div className="ddh-review-label">
        <strong>Review queue</strong>
        <span>Open a row for source, diff, and affected clients.</span>
      </div>
      {pendingRules.map((rule) => (
        <ReviewRule
          key={rule.id}
          rule={rule}
          deadlines={deadlineStore ?? mockDeadlines}
          selected={selectedRuleId === rule.id}
          onSelectRule={setSelectedRuleId}
          onApply={applyRule}
          onDismiss={dismissRule}
          onReopen={reopenRule}
        />
      ))}
      {appliedRules.length ? <div className="ddh-section-divider">Applied by CPA</div> : null}
      {appliedRules.map((rule) => (
        <ReviewRule
          key={rule.id}
          rule={rule}
          deadlines={deadlineStore ?? mockDeadlines}
          variant="applied"
          selected={selectedRuleId === rule.id}
          onSelectRule={setSelectedRuleId}
          onApply={applyRule}
          onDismiss={dismissRule}
          onReopen={reopenRule}
        />
      ))}
      {autoApplied.length ? <div className="ddh-section-divider">Auto-applied today</div> : null}
      {autoApplied.map((rule) => (
        <ReviewRule
          key={rule.id}
          rule={rule}
          deadlines={deadlineStore ?? mockDeadlines}
          variant="auto"
          selected={selectedRuleId === rule.id}
          onSelectRule={setSelectedRuleId}
          onApply={applyRule}
          onDismiss={dismissRule}
          onReopen={reopenRule}
        />
      ))}
      {dismissedRules.length ? <div className="ddh-section-divider">Dismissed</div> : null}
      {dismissedRules.map((rule) => (
        <ReviewRule
          key={rule.id}
          rule={rule}
          deadlines={deadlineStore ?? mockDeadlines}
          variant="dismissed"
          selected={selectedRuleId === rule.id}
          onSelectRule={setSelectedRuleId}
          onApply={applyRule}
          onDismiss={dismissRule}
          onReopen={reopenRule}
        />
      ))}
    </section>
  );
}

function ReviewRule({
  rule,
  deadlines,
  variant,
  selected,
  onSelectRule,
  onApply,
  onDismiss,
  onReopen
}: {
  rule: MockRule;
  deadlines: MockDeadline[];
  variant?: "auto" | "applied" | "dismissed";
  selected: boolean;
  onSelectRule: (ruleId: string) => void;
  onApply: (id: string) => void;
  onDismiss: (id: string) => void;
  onReopen: (id: string) => void;
}) {
  const affected = rule.affected_count || deadlines.filter((deadline) => deadline.notice_rule_id === rule.id).length;
  const isApplied = variant === "applied";
  const isAuto = variant === "auto";
  const isDismissed = variant === "dismissed";
  const impactRows = mockDeadlines
    .filter((base) => base.notice_rule_id === rule.id)
    .map((base) => {
      const current = deadlines.find((deadline) => deadline.id === base.id) ?? base;
      return {
        id: base.id,
        clientName: base.client_name,
        taxType: base.tax_type,
        before: base.due_label,
        after: current.due_label,
        summary: summarizeRuleImpact(base, current),
        changed: base.due_date !== current.due_date || base.status !== current.status || base.source !== current.source
      };
    });
  return (
    <article className={`ddh-rule ${isAuto ? "auto" : isApplied ? "applied" : isDismissed ? "dismissed" : ""}`}>
      <div className="ddh-rule-top">
        <div>
          <h2>{rule.title}</h2>
          <p>{rule.jurisdiction} - {rule.source} - detected {new Date(rule.detected_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</p>
        </div>
        <span>{isAuto ? "Auto-applied" : isApplied ? "Applied" : isDismissed ? "Dismissed" : "Pending review"}</span>
      </div>
      <p>{rule.summary}</p>
      <div className="ddh-rule-tags">
        <span>Affects <strong>{affected} client{affected === 1 ? "" : "s"}</strong></span>
        <span><strong>Change</strong> {rule.diff_before} to {rule.diff_after}</span>
      </div>
      <div className="ddh-rule-foot">
        <button type="button" onClick={() => window.open(rule.source.startsWith("http") ? rule.source : "https://www.google.com/search?q=" + encodeURIComponent(rule.source), "_blank", "noopener,noreferrer")}>Official source</button>
        <div>
          {isAuto || isApplied || isDismissed ? (
            <>
              <button type="button" className="ddh-btn ddh-btn-sm" onClick={() => onSelectRule(selected ? "" : rule.id)}>
                {selected ? "Hide changes" : "View changes"}
              </button>
              <button type="button" className="ddh-btn ddh-btn-sm" onClick={() => onReopen(rule.id)}>Undo</button>
            </>
          ) : (
            <>
              <button type="button" className="ddh-btn" onClick={() => onSelectRule(selected ? "" : rule.id)}>
                {selected ? "Close details" : "Review details"}
              </button>
              <button type="button" className="ddh-btn" onClick={() => onDismiss(rule.id)}>Dismiss</button>
              <button type="button" className="ddh-btn ddh-btn-primary" onClick={() => onApply(rule.id)}>Apply to {affected} client{affected === 1 ? "" : "s"}</button>
            </>
          )}
        </div>
      </div>
      {selected ? (
        <div className="rule-impact-list">
          {isDismissed ? (
            <div className="rule-impact-row">
              <div className="rule-impact-head">
                <strong>Dismissed from the current portfolio</strong>
                <span className="badge-pill gold thin">Dismissed</span>
              </div>
              <div className="rule-impact-copy">
                <p>This change will not update client deadlines until it is restored to review.</p>
              </div>
            </div>
          ) : impactRows.length ? (
            impactRows.map((impact) => (
              <div key={impact.id} className="rule-impact-row">
                <div className="rule-impact-head">
                  <strong>{impact.clientName}</strong>
                  <span className="badge-pill blue thin">{impact.taxType}</span>
                  {impact.changed ? <ChangeBadge /> : null}
                </div>
                <div className="rule-impact-copy">
                  <span className="muted">
                    {impact.before !== impact.after ? `${impact.before} → ${impact.after}` : impact.after}
                  </span>
                  <p>{impact.summary}</p>
                </div>
              </div>
            ))
          ) : (
            <div className="rule-impact-row">
              <div className="rule-impact-head">
                <strong>No client-level changes to show yet</strong>
              </div>
              <div className="rule-impact-copy">
                <p>This change does not currently map to a visible deadline in the demo dataset.</p>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </article>
  );
}

export function SettingsSection({ tenantId, onNotify }: SectionContext) {
  return (
    <section>
      <div className="ddh-page-head"><div><div className="ddh-eyebrow">Settings</div><h1>Workspace settings</h1></div></div>
      <SettingsCard label="Workspace" title="Tenant identity" subtitle="Display name, time zone, and fiscal year shown across the app.">
        <SettingRow label="Display name" sub="Shown in the topbar and on exports." value="Johnson CPA PLLC" />
        <SettingRow label="Time zone" sub="Used for reminder send times." value="America/Los_Angeles" />
        <SettingRow label="Fiscal year" sub="Used to bucket extensions and YTD totals." value="Calendar (Jan - Dec)" />
        <SettingRow label="Tenant ID" sub="Sent on every backend request - read only." value={tenantId} mono />
        <div className="ddh-settings-foot">
          <span>Anchored today: Apr 26, 2026</span>
          <button
            type="button"
            className="ddh-btn ddh-btn-primary"
            onClick={() => onNotify?.("Settings saved for this demo workspace.", "green")}
          >
            Save changes
          </button>
        </div>
      </SettingsCard>
      <SettingsCard label="Notifications" title="Reminder channels" subtitle="Toggle which channels carry the 30/14/7/1 stepped reminders.">
        {mockChannels.slice(0, 3).map((channel) => (
          <div key={channel.id} className="ddh-setting-row">
            <div><strong>{channel.label}</strong><span>{channel.description}</span></div>
            <em className={channel.enabled ? "enabled" : ""}>{channel.enabled ? "Enabled" : "Not connected"}</em>
          </div>
        ))}
      </SettingsCard>
    </section>
  );
}

function SettingsCard({ label, title, subtitle, children }: { label: string; title: string; subtitle: string; children: ReactElement | ReactElement[] }) {
  return (
    <article className="ddh-settings-card">
      <div className="ddh-eyebrow">{label}</div>
      <h2>{title}</h2>
      <p>{subtitle}</p>
      {children}
    </article>
  );
}

function SettingRow({ label, sub, value, mono }: { label: string; sub: string; value: string; mono?: boolean }) {
  return (
    <div className="ddh-setting-row">
      <div><strong>{label}</strong><span>{sub}</span></div>
      <input className={mono ? "mono" : ""} value={value} readOnly />
    </div>
  );
}

export const sectionOrder: SectionId[] = ["work", "clients", "review", "settings"];

export function SectionNav({
  current,
  onSelect
}: {
  current: SectionId;
  onSelect: (id: SectionId) => void;
}) {
  const pendingRules = mockRules.filter((rule) => rule.status === "pending-review").length;
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
          {id === "review" && pendingRules ? <span className="tab-badge">{pendingRules}</span> : null}
        </button>
      ))}
    </nav>
  );
}

export const sectionComponents: Record<SectionId, (ctx: SectionContext) => ReactElement> = {
  work: WorkSection,
  clients: ClientsSection,
  review: ReviewSection,
  settings: SettingsSection
};
