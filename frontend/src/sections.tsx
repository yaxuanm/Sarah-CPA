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

import { ChangeEvent, Dispatch, ReactElement, SetStateAction, useEffect, useMemo, useRef, useState } from "react";
import type { DirectAction, ViewEnvelope } from "./types";
import {
  BlockedIcon,
  ChevronRightIcon,
  DownloadIcon,
  DirectActionHandler,
  EmptyStateRow,
  EyebrowHeader,
  ExtensionIcon,
  FilterPopover,
  SaveIcon,
  SearchInput,
  SettingField,
  Toggle,
  UploadIcon,
  WorkIcon
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
  urgencyOf,
  type EntityType,
  type MockActivity,
  type MockBlocker,
  type MockClient,
  type MockDeadline,
  type MockReminder,
  type MockRule,
  type ReminderStep,
  type TaxType,
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
  onNotify?: (text: string, tone?: "green" | "blue" | "gold" | "red") => void;
  deadlines?: MockDeadline[];
  setDeadlines?: Dispatch<SetStateAction<MockDeadline[]>>;
  rules?: MockRule[];
  setRules?: Dispatch<SetStateAction<MockRule[]>>;
  resolvedRuleIds?: string[];
  setResolvedRuleIds?: Dispatch<SetStateAction<string[]>>;
  changedDeadlineIds?: string[];
  setChangedDeadlineIds?: Dispatch<SetStateAction<string[]>>;
  importLaunchToken?: number;
};

export const sectionMeta: Record<SectionId, { eyebrow: string; title: string; subtitle: string }> = {
  today: {
    eyebrow: "Today",
    title: "Portfolio board",
    subtitle:
      "Start with work now, then resolve blockers, then review anything that still needs a CPA decision."
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

function ChangeBadge({ kind = "changed" }: { kind?: "new" | "changed" }) {
  return <span className={`badge-pill ${kind === "new" ? "green" : "blue"} thin`}>{kind === "new" ? "New" : "Changed"}</span>;
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
  if (d.days_remaining < 0) return `Overdue by ${Math.abs(d.days_remaining)} day${Math.abs(d.days_remaining) === 1 ? "" : "s"}`;
  if (d.days_remaining === 0) return "Due today";
  if (d.days_remaining === 1) return "Due tomorrow";
  return `In ${d.days_remaining} days`;
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

function buildInitialClientRecords(): ClientRecord[] {
  return mockClients.map((client) => ({
    client,
    deadlines: mockDeadlines
      .filter((deadline) => deadline.client_id === client.id)
      .sort((a, b) => a.days_remaining - b.days_remaining),
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

function deriveDeadlinesForImportedClient(
  client: MockClient,
  rowIndex: number
): MockDeadline[] {
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
      status: taxType === "Payroll (941)" ? "pending" : "pending",
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

  const activity: MockActivity[] = [
    {
      id: `imp-act-${client.id}`,
      when: "Just now",
      actor: "DueDateHQ",
      action: "imported client",
      detail: `Imported ${client.name} from CSV and derived ${deadlines.length} deadlines.`,
      category: "import"
    }
  ];

  return {
    client,
    deadlines,
    blockers: [],
    reminders: [],
    activity
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
      ].sort((a, b) => a.days_remaining - b.days_remaining);

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

function bucketForBoard(deadline: MockDeadline, resolvedRuleIds: string[] = []): "notice" | "waiting" | "track" | "watchlist" | "completed" {
  if (deadline.status === "completed") return "completed";
  if (deadline.status === "blocked") return "waiting";
  if (deadline.notice_rule_id && !resolvedRuleIds.includes(deadline.notice_rule_id)) return "notice";
  if (deadline.status === "extension-filed" || deadline.status === "extension-approved") return "watchlist";
  if (deadline.days_remaining < 0) return "notice";
  if (deadline.days_remaining <= 3) return "notice";
  if (deadline.days_remaining <= 30) return "track";
  return "watchlist";
}

function applyRuleToDeadline(deadline: MockDeadline, ruleId: string): MockDeadline {
  if (deadline.notice_rule_id !== ruleId) return deadline;

  if (ruleId === "rule-001") {
    return {
      ...deadline,
      due_date: "2026-05-30",
      due_label: "May 30",
      days_remaining: 34,
      source: "FTB Notice 2026-04 — applied to client filing calendar",
      notice_rule_id: undefined
    };
  }

  if (ruleId === "rule-002") {
    return {
      ...deadline,
      status: "blocked",
      blocker_reason: "Nexus confirmation required after TX threshold change",
      source: "TX Comptroller 34-Tex.Admin.Code §3.286 — pending nexus confirmation",
      notice_rule_id: undefined
    };
  }

  if (ruleId === "rule-005") {
    return {
      ...deadline,
      source: "OR DOR Rate Notice 2026-Q2 — rate update applied to template",
      notice_rule_id: undefined
    };
  }

  return {
    ...deadline,
    notice_rule_id: undefined
  };
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

function normalizeDeadlineMatcher(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function findBlockerForDeadline(deadline: MockDeadline) {
  if (deadline.status !== "blocked" && !deadline.blocker_reason) {
    return null;
  }
  const normalizedTaxType = normalizeDeadlineMatcher(deadline.tax_type);
  const normalizedSource = normalizeDeadlineMatcher(deadline.source);
  const normalizedReason = normalizeDeadlineMatcher(deadline.blocker_reason || "");

  return (
    mockBlockers.find((blocker) => {
      if (blocker.client_id !== deadline.client_id) return false;
      const normalizedLabel = normalizeDeadlineMatcher(blocker.deadline_label);
      const normalizedBlockerReason = normalizeDeadlineMatcher(blocker.reason);

      if (normalizedReason && normalizedBlockerReason.includes(normalizedReason)) return true;
      if (normalizedReason && normalizedReason.includes(normalizedBlockerReason)) return true;
      if (normalizedLabel.includes(normalizedTaxType) || normalizedSource.includes(normalizedLabel)) return true;
      if (normalizedTaxType.includes("payroll 941") && normalizedLabel.includes("941")) return true;
      if (normalizedTaxType.includes("state income") && normalizedLabel.includes("form 100")) return true;
      return false;
    }) || null
  );
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

export function TodaySection({
  onExport,
  onNotify,
  deadlines: deadlineStore,
  setDeadlines: setDeadlineStore,
  rules: ruleStore,
  resolvedRuleIds = [],
  changedDeadlineIds = []
}: SectionContext) {
  type DisplayLane = "work" | "blocked" | "review";
  type TodayViewMode = "board" | "archive";
  const [stateFilter, setStateFilter] = useState<string>("All");
  const [taxFilter, setTaxFilter] = useState<string>("All");
  const [selectedDeadlineId, setSelectedDeadlineId] = useState<string | null>(null);
  const [activeLane, setActiveLane] = useState<DisplayLane>("work");
  const [viewMode, setViewMode] = useState<TodayViewMode>("board");

  const deadlines = deadlineStore ?? mockDeadlines;
  const rules = ruleStore ?? mockRules;
  const rulesById = useMemo(() => Object.fromEntries(rules.map((rule) => [rule.id, rule])), [rules]);

  function updateDeadline(deadlineId: string, updater: (deadline: MockDeadline) => MockDeadline) {
    if (!setDeadlineStore) return;
    setDeadlineStore((current) =>
      current.map((deadline) => (deadline.id === deadlineId ? updater(deadline) : deadline))
    );
  }

  const filtered = useMemo(() => {
    return deadlines.filter((d) => {
      if (d.status === "completed") return false;
      if (stateFilter !== "All" && d.jurisdiction !== stateFilter) return false;
      if (taxFilter !== "All" && d.tax_type !== taxFilter) return false;
      return true;
    });
  }, [deadlines, stateFilter, taxFilter]);

  const grouped = useMemo(() => {
    const map: Record<DisplayLane, MockDeadline[]> = {
      work: [],
      blocked: [],
      review: []
    };
    filtered.forEach((d) => {
      const b = bucketForBoard(d, resolvedRuleIds);
      if (b === "completed") return;
      if (b === "track") {
        map.work.push(d);
        return;
      }
      if (b === "waiting") {
        map.blocked.push(d);
        return;
      }
      map.review.push(d);
    });
    (Object.keys(map) as DisplayLane[]).forEach((lane) => {
      map[lane].sort((a, b2) => a.days_remaining - b2.days_remaining);
    });
    return map;
  }, [filtered, resolvedRuleIds]);

  const archivedDeadlines = useMemo(
    () => deadlines.filter((deadline) => deadline.status === "completed").sort((a, b) => a.client_name.localeCompare(b.client_name)),
    [deadlines]
  );

  const activeCount = (stateFilter !== "All" ? 1 : 0) + (taxFilter !== "All" ? 1 : 0);
  const selectedDeadline =
    selectedDeadlineId ? filtered.find((deadline) => deadline.id === selectedDeadlineId) || null : null;
  const activeItems = grouped[activeLane];
  const laneMeta: Record<DisplayLane, { title: string; helper: string; tone: "ink" | "gold" | "blue" }> = {
    work: {
      title: "Work now",
      helper: "Items you can actively move today without waiting on more information.",
      tone: "ink"
    },
    blocked: {
      title: "Blocked",
      helper: "Items that cannot move until a document, confirmation, or profile detail arrives.",
      tone: "gold"
    },
    review: {
      title: "Needs review",
      helper: "Items still being watched or reviewed before they become active work.",
      tone: "blue"
    }
  };
  const activeMeta = laneMeta[activeLane];
  const laneGuide: Record<
    DisplayLane,
    { boundary: string; moveWhen: string; nextStep: string }
  > = {
    work: {
      boundary: "Show only the items a CPA or staff member can actively advance right now.",
      moveWhen: "Keep it here while the work is moving. Move it out only when it becomes blocked or no longer needs action.",
      nextStep: "Work the soonest due item first, then batch similar state or client work together."
    },
    blocked: {
      boundary: "Show only the items that are waiting on supporting documents, confirmation, or missing profile data.",
      moveWhen: "Move it back into Work now once the missing information has been received and confirmed.",
      nextStep: "Identify exactly what is missing and who needs to provide it."
    },
    review: {
      boundary: "Use this lane for things that are not active work yet but still need a CPA decision or monitoring.",
      moveWhen: "Move it into Work now once the change is confirmed to matter for the portfolio.",
      nextStep: "Review the source or watch condition, then either promote it into work or leave it under review."
    }
  };
  const laneCounts: Record<DisplayLane, number> = {
    work: grouped.work.length,
    blocked: grouped.blocked.length,
    review: grouped.review.length
  };

  function renderTodayReason(deadline: MockDeadline) {
    if (activeLane === "blocked") {
      return <span className="badge-pill gold">{deadline.blocker_reason || "Waiting on client"}</span>;
    }
    if (activeLane === "review") {
      if (bucketOfDeadline(deadline) === "notice") {
        return <span className="badge-pill red">{noticeReason(deadline)}</span>;
      }
      if (deadline.extension_status) {
        return (
          <span className="badge-pill blue">
            {deadline.extension_status === "approved"
              ? `Extended → ${deadline.extended_due_date}`
              : deadline.extension_status === "submitted"
                ? `Filed → ${deadline.extended_due_date}`
                : "Extension denied"}
          </span>
        );
      }
      return <span className="badge-pill blue">Watch item</span>;
    }
    return <StatusBadge deadline={deadline} />;
  }

  return (
    <div className="section-shell">
      <div className="kpi-strip lane-selector-strip">
        {(Object.keys(laneMeta) as DisplayLane[]).map((lane) => {
          const meta = laneMeta[lane];
          return (
            <button
              type="button"
              key={lane}
              className={`kpi-tile bucket bucket-${lane} tone-${meta.tone} ${activeLane === lane ? "active" : ""}`}
              onClick={() => {
                setActiveLane(lane);
                setSelectedDeadlineId(null);
              }}
            >
              <span className="kpi-label">{meta.title}</span>
              <span className="kpi-value">{laneCounts[lane]}</span>
              <span className="kpi-delta">{meta.helper}</span>
            </button>
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
        <button
          type="button"
          className={`ghost-btn ${viewMode === "archive" ? "active" : ""}`}
          onClick={() => {
            setViewMode((current) => (current === "archive" ? "board" : "archive"));
            setSelectedDeadlineId(null);
          }}
        >
          {viewMode === "archive" ? "Back to board" : `View archive${archivedDeadlines.length ? ` (${archivedDeadlines.length})` : ""}`}
        </button>
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
          <DownloadIcon />
          <span>Export</span>
        </button>
      </section>

      {viewMode === "board" ? (
        <section className={`card bucket-card bucket-${activeLane} tone-${activeMeta.tone}`}>
          <div className="bucket-head">
            <div className="bucket-title-row">
              <span className={`bucket-tag tone-${activeMeta.tone}`}>{activeMeta.title}</span>
              <span className="bucket-count">
                {activeItems.length} item{activeItems.length === 1 ? "" : "s"}
              </span>
              <div className="lane-help-shell">
                <button type="button" className="lane-help-trigger" aria-label={`How ${activeMeta.title} works`}>
                  ?
                </button>
                <div className="lane-help-tooltip" role="tooltip">
                  <strong>Boundary</strong>
                  <p>{laneGuide[activeLane].boundary}</p>
                  <strong>Move it when</strong>
                  <p>{laneGuide[activeLane].moveWhen}</p>
                  <strong>Next step</strong>
                  <p>{laneGuide[activeLane].nextStep}</p>
                </div>
              </div>
            </div>
            <span className="bucket-helper">{activeMeta.helper}</span>
          </div>
          {activeItems.length === 0 ? (
            <EmptyStateRow
              title="Empty lane"
              body={`No deadlines currently classified as ${activeMeta.title.toLowerCase()}.`}
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
              {activeItems.map((d) => (
                <div key={d.id} className="bucket-table-row" role="row">
                  <span className="bucket-cell client" role="cell">
                    <UrgencyDot deadline={d} />
                    <span>{d.client_name}</span>
                    {changedDeadlineIds.includes(d.id) ? <ChangeBadge /> : null}
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
                  <span className="bucket-cell reason" role="cell">{renderTodayReason(d)}</span>
                  <span className="bucket-cell" role="cell">
                    {d.assignee}
                  </span>
                  <span className="bucket-cell actions" role="cell">
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => setSelectedDeadlineId(d.id)}
                    >
                      View details
                    </button>
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : (
        <section className="card archive-card">
          <div className="archive-head">
            <div>
              <div className="eyebrow">Archive</div>
              <h3>Completed or manually archived items</h3>
              <p className="muted">Keep evidence of what moved off the active board without mixing it into live work.</p>
            </div>
          </div>
          {archivedDeadlines.length === 0 ? (
            <EmptyStateRow title="No archived items yet" body="Archived work will stay here so the CPA can prove what moved off the board." />
          ) : (
            <ul className="archive-list">
              {archivedDeadlines.map((deadline) => (
                <li key={deadline.id} className="archive-row">
                  <div className="archive-copy">
                    <strong>{deadline.client_name}</strong>
                    <span className="muted">
                      {deadline.tax_type} · {deadline.jurisdiction} · {deadline.due_label}
                    </span>
                  </div>
                  <div className="archive-actions">
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => setSelectedDeadlineId(deadline.id)}
                    >
                      View details
                    </button>
                    <button
                      type="button"
                      className="ghost-btn"
                      onClick={() =>
                        updateDeadline(deadline.id, (current) => ({
                          ...current,
                          status: "pending"
                        }))
                      }
                    >
                      Restore
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {selectedDeadline ? (
        <DeadlineDetailCard
          deadline={selectedDeadline}
          linkedRule={selectedDeadline.notice_rule_id ? rulesById[selectedDeadline.notice_rule_id] || null : null}
          title="Deadline detail"
          subtitle="Inspect the source, reminders, blockers, and extension state for this item."
          onClose={() => setSelectedDeadlineId(null)}
          onPrimaryAction={
            activeLane === "blocked"
              ? () => {
                  updateDeadline(selectedDeadline.id, (deadline) => ({
                    ...deadline,
                    status: "pending",
                    blocker_reason: null
                  }));
                  setSelectedDeadlineId(null);
                  onNotify?.(`Resolved blocker for ${selectedDeadline.client_name}; item moved to Work now.`, "green");
                }
              : activeLane === "review"
                ? () => {
                    updateDeadline(selectedDeadline.id, (deadline) => ({
                      ...deadline,
                      notice_rule_id: undefined
                    }));
                    setSelectedDeadlineId(null);
                    onNotify?.(`Moved ${selectedDeadline.client_name} into Work now for active follow-up.`, "blue");
                  }
                : () => {
                    updateDeadline(selectedDeadline.id, (deadline) => ({
                      ...deadline,
                      status: "blocked",
                      blocker_reason: deadline.blocker_reason || "Waiting on CPA follow-up"
                    }));
                    setSelectedDeadlineId(null);
                    onNotify?.(`Moved ${selectedDeadline.client_name} into Blocked.`, "gold");
                  }
          }
          primaryLabel={
            activeLane === "blocked"
              ? "Resolve blocker"
              : activeLane === "review"
                ? "Move to work now"
                : "Mark blocked"
          }
          onArchive={() => {
            updateDeadline(selectedDeadline.id, (deadline) => ({
              ...deadline,
              status: "completed"
            }));
            setSelectedDeadlineId(null);
            setViewMode("archive");
            onNotify?.(`Archived ${selectedDeadline.client_name} from the board.`, "blue");
          }}
        />
      ) : null}
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

export function CalendarSection({
  onExport,
  onNotify,
  deadlines: deadlineStore,
  rules: ruleStore,
  changedDeadlineIds = []
}: SectionContext) {
  const [horizon, setHorizon] = useState<string>("next-30");
  const [stateFilter, setStateFilter] = useState<string>("All");
  const [taxFilter, setTaxFilter] = useState<string>("All");
  const [urgencyFilter, setUrgencyFilter] = useState<string>("All");
  const [selectedDeadlineId, setSelectedDeadlineId] = useState<string | null>(null);

  const horizonDef = horizonChoices.find((h) => h.id === horizon)!;

  const deadlines = deadlineStore ?? mockDeadlines;
  const rules = ruleStore ?? mockRules;
  const rulesById = useMemo(() => Object.fromEntries(rules.map((rule) => [rule.id, rule])), [rules]);

  const filtered = useMemo(() => {
    return deadlines.filter((d) => {
      if (d.status === "completed") return false;
      if (d.days_remaining < 0) return false;
      if (d.days_remaining > horizonDef.days) return false;
      if (stateFilter !== "All" && d.jurisdiction !== stateFilter) return false;
      if (taxFilter !== "All" && d.tax_type !== taxFilter) return false;
      if (urgencyFilter !== "All" && urgencyOf(d) !== urgencyFilter) return false;
      return true;
    });
  }, [deadlines, horizon, stateFilter, taxFilter, urgencyFilter, horizonDef.days]);

  const groups = groupDeadlinesByWeek(filtered);
  const activeCount =
    (stateFilter !== "All" ? 1 : 0) +
    (taxFilter !== "All" ? 1 : 0) +
    (urgencyFilter !== "All" ? 1 : 0);
  const selectedDeadline =
    selectedDeadlineId ? filtered.find((deadline) => deadline.id === selectedDeadlineId) || null : null;
  const planFacts = [
    { label: "Urgent", value: String(filtered.filter((d) => urgencyOf(d) === "urgent").length) },
    { label: "This week", value: String(filtered.filter((d) => d.days_remaining <= 7).length) },
    { label: "States", value: String(new Set(filtered.map((d) => d.jurisdiction)).size) },
    { label: "Clients", value: String(new Set(filtered.map((d) => d.client_id)).size) }
  ];
  const calendarGuide = {
    boundary:
      "Use Calendar to understand when work clusters happen across the next 7 to 90 days.",
    bestFor:
      "Finding crowded weeks, spotting state-specific clusters, and planning staffing before deadlines bunch together.",
    notFor:
      "Deciding whether something belongs in Notice, Track, Waiting on info, or Watchlist. That belongs on Today.",
    nextStep:
      "Pick a crowded week, review the due items, then go back to Today if one of them should become active work now."
  };

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
          <DownloadIcon />
          <span>Export</span>
        </button>
        <button
          type="button"
          className="ghost-btn"
          onClick={() => onNotify?.(`Calendar export prepared for ${horizonDef.label}.`, "green")}
        >
          <SaveIcon />
          <span>Save</span>
        </button>
      </section>

      <div className="calendar-focus-grid">
        <section className="card calendar-overview">
          <div className="card-header calendar-overview-header">
            <div>
              <div className="eyebrow">Time horizon</div>
              <h2>{`What is coming up in ${horizonDef.label.toLowerCase()}`}</h2>
              <p className="card-description">
                Calendar is for time distribution, not lane triage. Use Today to decide what to work first.
              </p>
            </div>
            <div className="lane-help-shell">
              <button type="button" className="lane-help-trigger" aria-label="How to use Calendar">
                ?
              </button>
              <div className="lane-help-tooltip" role="tooltip">
                <strong>Boundary</strong>
                <p>{calendarGuide.boundary}</p>
                <strong>Best for</strong>
                <p>{calendarGuide.bestFor}</p>
                <strong>Not for</strong>
                <p>{calendarGuide.notFor}</p>
                <strong>Next step</strong>
                <p>{calendarGuide.nextStep}</p>
              </div>
            </div>
          </div>
          <div className="local-plan-grid">
            {planFacts.map((fact) => (
              <div key={fact.label} className="local-plan-fact">
                <span>{fact.label}</span>
                <strong>{fact.value}</strong>
              </div>
            ))}
          </div>
        </section>
      </div>

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
                    <div className="calendar-event-top">
                      <div className="calendar-event-title">
                        {d.client_name}
                        {changedDeadlineIds.includes(d.id) ? <ChangeBadge /> : null}
                        <span className="badge-pill blue thin">{d.tax_type}</span>
                        <span className="badge-pill thin">{d.jurisdiction}</span>
                      </div>
                      <span className="calendar-event-hook">{formatDaysRemaining(d)}</span>
                    </div>
                    <div className="calendar-event-meta">
                      <StatusBadge deadline={d} />
                      <span className="muted">{d.source}</span>
                    </div>
                    <div className="calendar-event-actions">
                      <button
                        type="button"
                        className="link-btn calendar-inline-action"
                        onClick={() => setSelectedDeadlineId(d.id)}
                      >
                        View details
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      {selectedDeadline ? (
        <DeadlineDetailCard
          deadline={selectedDeadline}
          linkedRule={selectedDeadline.notice_rule_id ? rulesById[selectedDeadline.notice_rule_id] || null : null}
          title="Calendar detail"
          subtitle="Source, reminders, blockers, and extension state."
          onClose={() => setSelectedDeadlineId(null)}
        />
      ) : null}
    </div>
  );
}

// ============================================================================
// Clients
// ============================================================================

export function ClientsSection({
  onExport,
  onNotify,
  deadlines: deadlineStore,
  changedDeadlineIds = [],
  importLaunchToken = 0
}: SectionContext) {
  const [importMode, setImportMode] = useState(false);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);
  const [records, setRecords] = useState<ClientRecord[]>(() => buildInitialClientRecords());
  const [recentImportResult, setRecentImportResult] = useState<ImportApplyResult | null>(null);
  const deadlines = deadlineStore ?? mockDeadlines;

  useEffect(() => {
    if (!importLaunchToken) return;
    setSelectedClientId(null);
    setImportMode(true);
  }, [importLaunchToken]);

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

  if (importMode) {
    return (
      <ImportWizard
        onClose={() => setImportMode(false)}
        onApply={(rows, decisions) => {
          const result = applyImportedRowsToRecords(records, rows, decisions);
          setRecords(result.records);
          setRecentImportResult(result);
          onNotify?.(
            `Import complete: ${result.created} created, ${result.merged} merged, ${result.skipped} skipped.`,
            "green"
          );
          return result;
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
    <ClientDirectory
      records={recordsWithLiveDeadlines}
      changedDeadlineIds={changedDeadlineIds}
      recentImportResult={recentImportResult}
      onDismissImportResult={() => setRecentImportResult(null)}
      onExport={onExport}
      onImport={() => setImportMode(true)}
      onOpenClient={setSelectedClientId}
    />
  );
}

function ClientDirectory({
  records,
  changedDeadlineIds,
  recentImportResult,
  onDismissImportResult,
  onExport,
  onImport,
  onOpenClient
}: {
  records: ClientRecord[];
  changedDeadlineIds: string[];
  recentImportResult: ImportApplyResult | null;
  onDismissImportResult: () => void;
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
    return records.map((record) => record.client).filter((c) => {
      if (needle && !c.name.toLowerCase().includes(needle) && !c.primary_contact_name.toLowerCase().includes(needle))
        return false;
      if (stateFilter !== "All" && !c.states.includes(stateFilter)) return false;
      if (entityFilter !== "All" && c.entity_type !== entityFilter) return false;
      if (riskFilter === "high" && c.risk_label !== "high") return false;
      if (riskFilter === "watch" && c.risk_label !== "watch") return false;
      if (riskFilter === "calm" && c.risk_label !== null) return false;
      return true;
    });
  }, [records, query, stateFilter, entityFilter, riskFilter]);

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
          <DownloadIcon />
          <span>Export</span>
        </button>
        <button type="button" className="primary" onClick={onImport}>
          <UploadIcon />
          <span>Import</span>
        </button>
      </section>

      {recentImportResult ? (
        <section className="card import-result-banner">
          <div className="import-result-copy">
            <span className="eyebrow">Latest import</span>
            <strong>
              {recentImportResult.created} new · {recentImportResult.merged} updated · {recentImportResult.skipped} skipped
            </strong>
            <p className="muted">New rows created new client cards. Duplicate matches updated existing clients in place.</p>
          </div>
          <div className="import-result-groups">
            {recentImportResult.createdClientNames.length ? (
              <div className="import-result-group">
                <span className="import-result-label">New clients</span>
                <div className="import-result-chips">
                  {recentImportResult.createdClientNames.map((name) => (
                    <span key={name} className="badge-pill green">{name}</span>
                  ))}
                </div>
              </div>
            ) : null}
            {recentImportResult.mergedClientNames.length ? (
              <div className="import-result-group">
                <span className="import-result-label">Updated clients</span>
                <div className="import-result-chips">
                  {recentImportResult.mergedClientNames.map((name) => (
                    <span key={name} className="badge-pill blue">{name}</span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
          <button type="button" className="icon-btn" aria-label="Dismiss import result" onClick={onDismissImportResult}>
            ×
          </button>
        </section>
      ) : null}

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
            <ClientCardTile
              key={c.id}
              client={c}
              hasChanged={
                records
                  .find((record) => record.client.id === c.id)
                  ?.deadlines.some((deadline) => changedDeadlineIds.includes(deadline.id)) ?? false
              }
              importState={
                recentImportResult?.createdClientIds.includes(c.id)
                  ? "new"
                  : recentImportResult?.mergedClientIds.includes(c.id)
                    ? "updated"
                    : null
              }
              onOpenClient={onOpenClient}
            />
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

function splitCsvLine(line: string, delimiter: string) {
  const out: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (!inQuotes && char === delimiter) {
      out.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }
  out.push(current.trim());
  return out;
}

function parseCsvText(text: string, delimiter: string, hasHeader: boolean) {
  const lines = text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    return { headers: [...sampleCsvHeaders], rows: [] as string[][] };
  }

  const parsed = lines.map((line) => splitCsvLine(line, delimiter));
  const width = Math.max(...parsed.map((row) => row.length));
  const padded = parsed.map((row) => [...row, ...Array.from({ length: Math.max(0, width - row.length) }, () => "")]);

  if (hasHeader) {
    return {
      headers: padded[0].map((header, index) => header || `Column ${index + 1}`),
      rows: padded.slice(1)
    };
  }

  return {
    headers: Array.from({ length: width }, (_, index) => `Column ${index + 1}`),
    rows: padded
  };
}

function guessImportMapping(headers: string[]): Record<ImportFieldKey, string | null> {
  const aliases: Record<ImportFieldKey, string[]> = {
    name: ["company", "client name", "name"],
    entity_type: ["type", "entity type"],
    states: ["states", "registered states", "state footprint"],
    primary_contact_name: ["contact", "primary contact", "contact name"],
    primary_contact_email: ["email", "contact email", "primary contact email"],
    applicable_taxes: ["taxes", "applicable taxes", "tax scope"],
    notes: ["notes", "remarks", "memo"]
  };

  return importFields.reduce(
    (acc, field) => {
      const match = headers.find((header) =>
        aliases[field.key].includes(header.trim().toLowerCase())
      );
      acc[field.key] = match ?? null;
      return acc;
    },
    {} as Record<ImportFieldKey, string | null>
  );
}

function ImportWizard({
  onClose,
  onApply
}: {
  onClose: () => void;
  onApply: (rows: string[][], decisions: ImportDecision[]) => ImportApplyResult;
}) {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [fileName, setFileName] = useState<string | null>(null);
  const [delimiter, setDelimiter] = useState(",");
  const [hasHeader, setHasHeader] = useState(true);
  const [result, setResult] = useState<ImportApplyResult | null>(null);
  const [csvHeaders, setCsvHeaders] = useState<string[]>(sampleCsvHeaders);
  const [csvRows, setCsvRows] = useState<string[][]>(sampleCsvRows);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Auto-detect column → field mapping. Re-derive when CSV changes; user can
  // override.
  const [mapping, setMapping] = useState<Record<ImportFieldKey, string | null>>(guessImportMapping(sampleCsvHeaders));

  // Per-row decision (keep / merge / skip). The duplicate row index 1 is
  // pre-flagged as merge.
  const [decisions, setDecisions] = useState<Array<"keep" | "merge" | "skip">>(
    sampleCsvRows.map((_, i) => (i === 1 ? "merge" : ("keep" as "keep" | "merge" | "skip")))
  );

  const stepLabels = [
    { id: 1, label: "Choose file" },
    { id: 2, label: "Map columns" },
    { id: 3, label: "Review rows" },
    { id: 4, label: "Done" }
  ] as const;

  function chooseSampleFile() {
    setFileName("client-portfolio-2026-Q2.csv");
    setCsvHeaders(sampleCsvHeaders);
    setCsvRows(sampleCsvRows);
    setMapping(guessImportMapping(sampleCsvHeaders));
    setDecisions(sampleCsvRows.map((_, i) => (i === 1 ? "merge" : ("keep" as "keep" | "merge" | "skip"))));
    setStep(2);
  }

  async function handleFileChosen(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const parsed = parseCsvText(text, delimiter, hasHeader);
    setFileName(file.name);
    setCsvHeaders(parsed.headers);
    setCsvRows(parsed.rows);
    setMapping(guessImportMapping(parsed.headers));
    setDecisions(
      parsed.rows.map((row) =>
        row[0]?.trim().toLowerCase() === "northwind services llc" ? "merge" : ("keep" as ImportDecision)
      )
    );
    setStep(2);
    event.target.value = "";
  }

  const canonicalRows = useMemo(() => {
    return csvRows.map((row) =>
      importFields.map((field) => {
        const header = mapping[field.key];
        const csvIndex = header ? csvHeaders.indexOf(header) : -1;
        return csvIndex >= 0 ? row[csvIndex] || "" : "";
      })
    );
  }, [csvHeaders, csvRows, mapping]);

  const created = result?.created ?? 0;
  const merged = result?.merged ?? 0;
  const skipped = result?.skipped ?? 0;

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
            <div className="import-drop-actions">
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,text/csv"
                className="sr-only"
                onChange={handleFileChosen}
              />
              <button type="button" className="primary" onClick={() => fileInputRef.current?.click()}>
                Upload CSV
              </button>
              <button type="button" className="ghost-btn" onClick={chooseSampleFile}>
                Use sample file
              </button>
            </div>
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
              const csvIndex = csvHeader ? csvHeaders.indexOf(csvHeader) : -1;
              const sampleValue = csvIndex >= 0 ? csvRows[0]?.[csvIndex] || "—" : "—";
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
                    {csvHeaders.map((h) => (
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
            title={`Review ${canonicalRows.length} rows`}
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
            {canonicalRows.map((row, idx) => {
              const isDuplicate = row[0]?.trim().toLowerCase() === "northwind services llc";
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
            <button
              type="button"
              className="primary"
              onClick={() => {
                setResult(onApply(canonicalRows, decisions));
                setStep(4);
              }}
            >
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
          <div className="import-complete-breakdown">
            {result?.createdClientNames.length ? (
              <div className="import-complete-group">
                <span className="import-result-label">New client cards created</span>
                <div className="import-result-chips">
                  {result.createdClientNames.map((name) => (
                    <span key={name} className="badge-pill green">{name}</span>
                  ))}
                </div>
              </div>
            ) : null}
            {result?.mergedClientNames.length ? (
              <div className="import-complete-group">
                <span className="import-result-label">Existing clients updated</span>
                <div className="import-result-chips">
                  {result.mergedClientNames.map((name) => (
                    <span key={name} className="badge-pill blue">{name}</span>
                  ))}
                </div>
              </div>
            ) : null}
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
  hasChanged,
  importState,
  onOpenClient
}: {
  client: MockClient;
  hasChanged: boolean;
  importState: "new" | "updated" | null;
  onOpenClient: (clientId: string) => void;
}) {
  const visibleTaxes = client.applicable_taxes.slice(0, 3);
  const hiddenTaxCount = Math.max(client.applicable_taxes.length - visibleTaxes.length, 0);
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
        {importState === "new" ? <span className="badge-pill blue">New</span> : null}
        {importState === "updated" ? <span className="badge-pill blue">Updated</span> : null}
        {hasChanged ? <ChangeBadge /> : null}
      </div>
      <div className="client-tile-metrics">
        <span className="client-metric">
          <WorkIcon />
          <strong>{client.active_deadlines}</strong>
          <span>active</span>
        </span>
        <span className="client-metric">
          <BlockedIcon />
          <strong>{client.blocked_deadlines}</strong>
          <span>blocked</span>
        </span>
        <span className="client-metric">
          <ExtensionIcon />
          <strong>{client.extensions_filed}</strong>
          <span>extensions</span>
        </span>
      </div>
      <div className="client-tile-taxes">
        <span>{visibleTaxes.join(" · ")}</span>
        {hiddenTaxCount > 0 ? <span className="client-tile-tax-more">+{hiddenTaxCount} more</span> : null}
      </div>
      <p className="client-tile-notes">{client.notes}</p>
      <div className="client-tile-foot">
        <span className="muted">{client.primary_contact_name}</span>
        <span className="client-tile-link">
          <span>Details</span>
          <ChevronRightIcon />
        </span>
      </div>
    </button>
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

  return (
    <div className="section-shell client-detail-shell">
      <section className="card section-toolbar detail-toolbar">
        <div className="detail-toolbar-left">
          <button type="button" className="ghost-btn" onClick={onBack}>
            Back to clients
          </button>
          <div className="detail-toolbar-copy">
            <div className="eyebrow">Client detail</div>
            <strong>
              {client.name}
              {hasChangedDeadlines ? <ChangeBadge /> : null}
            </strong>
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
                      <span className="deadline-cell-title">
                        {deadline.tax_type}
                        {changedDeadlineIds.includes(deadline.id) ? <ChangeBadge /> : null}
                      </span>
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

function DeadlineDetailCard({
  deadline,
  linkedRule,
  title,
  subtitle,
  onClose,
  onPrimaryAction,
  primaryLabel,
  onArchive
}: {
  deadline: MockDeadline;
  linkedRule: MockRule | null;
  title: string;
  subtitle: string;
  onClose: () => void;
  onPrimaryAction?: () => void;
  primaryLabel?: string;
  onArchive?: () => void;
}) {
  const linkedReminders = mockReminders
    .filter((reminder) => reminder.deadline_id === deadline.id)
    .sort((a, b) => a.send_at.localeCompare(b.send_at));
  const linkedBlocker = findBlockerForDeadline(deadline);

  return (
    <section className="card deadline-detail-card">
      <div className="detail-toolbar">
        <div className="detail-toolbar-left">
          <div className="detail-toolbar-copy">
            <div className="eyebrow">{title}</div>
            <strong>
              {deadline.client_name} · {deadline.tax_type}
            </strong>
            <span className="muted">{subtitle}</span>
          </div>
        </div>
        <div className="detail-toolbar-actions">
          {onArchive ? (
            <button type="button" className="ghost-btn" onClick={onArchive}>
              Archive
            </button>
          ) : null}
          {onPrimaryAction && primaryLabel ? (
            <button type="button" className="primary" onClick={onPrimaryAction}>
              {primaryLabel}
            </button>
          ) : null}
          <button type="button" className="icon-btn" aria-label="Close detail" onClick={onClose}>
            ×
          </button>
        </div>
      </div>

      <div className="client-detail-grid">
        <div className="client-detail-main">
          <section className="card detail-side-card">
            <EyebrowHeader
              eyebrow="Deadline"
              title={`${deadline.tax_type} · ${deadline.jurisdiction}`}
              subtitle={`${deadline.due_label} · ${formatDaysRemaining(deadline)}`}
            />
            <div className="profile-grid">
              <div className="profile-block">
                <span className="profile-label">Status</span>
                <StatusBadge deadline={deadline} />
              </div>
              <div className="profile-block">
                <span className="profile-label">Assignee</span>
                <strong>{deadline.assignee}</strong>
              </div>
              <div className="profile-block">
                <span className="profile-label">Source</span>
                <span>{deadline.source}</span>
              </div>
              <div className="profile-block">
                <span className="profile-label">Extension</span>
                <span>
                  {deadline.extension_status
                    ? `${deadline.extension_status} → ${deadline.extended_due_date || "pending"}`
                    : "No extension"}
                </span>
              </div>
            </div>
          </section>

          {linkedRule ? (
            <section className="card detail-side-card">
              <EyebrowHeader
                eyebrow="Rule change"
                title={linkedRule.title}
                subtitle={`${linkedRule.jurisdiction} · ${linkedRule.source}`}
              />
              <p>{linkedRule.summary}</p>
              <div className="rule-diff">
                <div className="diff-side before">
                  <span className="diff-label">Before</span>
                  <code>{linkedRule.diff_before}</code>
                </div>
                <span className="diff-arrow" aria-hidden="true">
                  →
                </span>
                <div className="diff-side after">
                  <span className="diff-label">After</span>
                  <code>{linkedRule.diff_after}</code>
                </div>
              </div>
            </section>
          ) : null}
        </div>

        <div className="client-detail-rail">
          <section className="card detail-side-card">
            <EyebrowHeader
              eyebrow="Reminders"
              title="Queued reminder timeline"
              subtitle="What is already scheduled for this deadline."
            />
            {linkedReminders.length === 0 ? (
              <EmptyStateRow title="No reminders" body="No reminder has been queued for this item yet." />
            ) : (
              <ul className="mini-log">
                {linkedReminders.map((reminder) => (
                  <li key={reminder.id} className="mini-log-row">
                    <strong>{reminderStepLabel(reminder.step)}</strong>
                    <span className="muted">{channelLabel(reminder.channel)} · {reminder.status}</span>
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

          <section className="card detail-side-card">
            <EyebrowHeader
              eyebrow="Blocker"
              title="Blocking status"
              subtitle="If this item is waiting on something, it will show here."
            />
            {linkedBlocker ? (
              <ul className="mini-log">
                <li className="mini-log-row">
                  <strong>{linkedBlocker.reason}</strong>
                  <span className="muted">Waiting on {linkedBlocker.waiting_on}</span>
                  <span className="muted">{linkedBlocker.next_step}</span>
                </li>
              </ul>
            ) : (
              <EmptyStateRow title="No blocker" body="This deadline is not blocked right now." />
            )}
          </section>
        </div>
      </div>
    </section>
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

export function UpdatesSection({
  onNotify,
  rules: ruleStore,
  setRules: setRuleStore,
  deadlines: deadlineStore,
  setDeadlines: setDeadlineStore,
  resolvedRuleIds = [],
  setResolvedRuleIds,
  setChangedDeadlineIds
}: SectionContext) {
  const [tab, setTab] = useState<UpdatesTab>("rules");
  const activeMeta = updatesTabs.find((entry) => entry.key === tab)!;
  const [localRules, setLocalRules] = useState<MockRule[]>(mockRules);
  const [archivedRuleIds, setArchivedRuleIds] = useState<string[]>([]);
  const rules = ruleStore ?? localRules;
  const setRules = setRuleStore ?? setLocalRules;
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(mockRules[0]?.id || null);
  const visibleRules = rules.filter((rule) => !archivedRuleIds.includes(rule.id));
  const selectedRule = selectedRuleId ? visibleRules.find((rule) => rule.id === selectedRuleId) || null : null;

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

      {tab === "rules" ? (
        <RulesReview
          rules={visibleRules}
          deadlines={deadlineStore ?? mockDeadlines}
          selectedRule={selectedRule}
          onSelectRule={setSelectedRuleId}
          onDismissRule={(ruleId) => {
            setRules((current) =>
              current.map((rule) => (rule.id === ruleId ? { ...rule, status: "dismissed" } : rule))
            );
            setResolvedRuleIds?.((current) => (current.includes(ruleId) ? current : [...current, ruleId]));
            onNotify?.("Rule review dismissed. The change will not alter the current portfolio.", "gold");
          }}
          onApplyRule={(ruleId) => {
            const changedIds: string[] = [];
            setRules((current) =>
              current.map((rule) => (rule.id === ruleId ? { ...rule, status: "auto-applied" } : rule))
            );
            setDeadlineStore?.((current) =>
              current.map((deadline) => {
                const next = applyRuleToDeadline(deadline, ruleId);
                if (next !== deadline) {
                  changedIds.push(deadline.id);
                }
                return next;
              })
            );
            setResolvedRuleIds?.((current) => (current.includes(ruleId) ? current : [...current, ruleId]));
            setChangedDeadlineIds?.((current) => [...new Set([...current, ...changedIds])]);
            onNotify?.("Rule applied. Related items have been pushed back into the portfolio board.", "green");
          }}
          onReopenRule={(ruleId) => {
            setRules((current) =>
              current.map((rule) => (rule.id === ruleId ? { ...rule, status: "pending-review" } : rule))
            );
            setResolvedRuleIds?.((current) => current.filter((id) => id !== ruleId));
            onNotify?.("Rule review reopened and sent back to Pending review.", "blue");
          }}
          onArchiveRule={(ruleId) => {
            setArchivedRuleIds((current) => [...current, ruleId]);
            if (selectedRuleId === ruleId) setSelectedRuleId(null);
            onNotify?.("Rule review archived from the active queue.", "blue");
          }}
        />
      ) : null}
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

function RulesReview({
  rules,
  deadlines,
  selectedRule,
  onSelectRule,
  onDismissRule,
  onApplyRule,
  onReopenRule,
  onArchiveRule
}: {
  rules: MockRule[];
  deadlines: MockDeadline[];
  selectedRule: MockRule | null;
  onSelectRule: (ruleId: string) => void;
  onDismissRule: (ruleId: string) => void;
  onApplyRule: (ruleId: string) => void;
  onReopenRule: (ruleId: string) => void;
  onArchiveRule: (ruleId: string) => void;
}) {
  const impactRowsByRule = useMemo(() => {
    return Object.fromEntries(
      rules.map((rule) => {
        const rows = mockDeadlines
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
        return [rule.id, rows];
      })
    ) as Record<string, { id: string; clientName: string; taxType: string; before: string; after: string; summary: string; changed: boolean }[]>;
  }, [rules, deadlines]);

  return (
    <div className="section-shell">
      <section className="card rules-card">
        <ul className="rules-list">
          {rules.map((rule) => (
            <li
              key={rule.id}
              className={`rule-row status-${rule.status} ${selectedRule?.id === rule.id ? "selected" : ""}`}
            >
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
                <div className="rule-row-actions">
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => onSelectRule(selectedRule?.id === rule.id ? "" : rule.id)}
                  >
                    {selectedRule?.id === rule.id
                      ? "Close details"
                      : rule.status === "pending-review"
                        ? "Review details"
                        : "View result"}
                  </button>
                  {rule.status === "pending-review" ? (
                    <>
                      <button
                        type="button"
                        className="ghost-btn compact"
                        onClick={() => onDismissRule(rule.id)}
                      >
                        Dismiss
                      </button>
                      <button
                        type="button"
                        className="primary compact"
                        onClick={() => onApplyRule(rule.id)}
                      >
                        Apply to {rule.affected_count} client{rule.affected_count === 1 ? "" : "s"}
                      </button>
                    </>
                  ) : null}
                  {(rule.status === "auto-applied" || rule.status === "dismissed") ? (
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => onArchiveRule(rule.id)}
                    >
                      Archive
                    </button>
                  ) : null}
                </div>
              </div>
              {selectedRule?.id === rule.id ? (
                <div className="rule-inline-detail">
                  <div className="rule-inline-copy">
                    <span className="eyebrow">Rule action</span>
                    <strong>
                      {rule.status === "pending-review"
                        ? "Choose what to do with this change"
                        : rule.status === "auto-applied"
                          ? "Applied changes across affected clients"
                          : "Dismissed from the current portfolio"}
                    </strong>
                    <p className="muted">
                      {rule.status === "pending-review"
                        ? "Apply it to the affected clients, or dismiss it if this rule should not change the current portfolio."
                        : rule.status === "auto-applied"
                          ? `This change has already been applied to ${rule.affected_count} client${rule.affected_count === 1 ? "" : "s"}.`
                          : "This change has been dismissed and will not update the current portfolio."}
                    </p>
                  </div>
                  <div className="rule-inline-actions">
                    {rule.status === "pending-review" ? (
                      <>
                        <span className="badge-pill gold">Pending review</span>
                      </>
                    ) : (
                      <>
                        <span className={`badge-pill ${rule.status === "auto-applied" ? "green" : "gold"}`}>
                          {rule.status === "auto-applied" ? "Applied" : "Dismissed"}
                        </span>
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => onReopenRule(rule.id)}
                        >
                          Restore to review
                        </button>
                        <button
                          type="button"
                          className="ghost-btn"
                          onClick={() => onArchiveRule(rule.id)}
                        >
                          Archive
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label="Close review details"
                      onClick={() => onSelectRule("")}
                    >
                      ×
                    </button>
                  </div>
                  {rule.status === "auto-applied" ? (
                    <div className="rule-impact-list">
                      {(impactRowsByRule[rule.id] ?? []).map((impact) => (
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
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
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
export function SettingsSection({ tenantId, onNotify }: SectionContext) {
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
          <button
            type="button"
            className="primary"
            onClick={() => onNotify?.("Invite flow staged locally. Backend invite endpoint not connected in this demo.", "blue")}
          >
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
