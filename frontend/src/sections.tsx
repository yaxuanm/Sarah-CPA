import { ChangeEvent, Dispatch, DragEvent, ReactElement, SetStateAction, useEffect, useMemo, useRef, useState } from "react";
import type { ViewEnvelope } from "./types";
import {
  ArchiveIcon,
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
  if (deadline.extension_status === "approved" && deadline.extended_due_date) return `Extended -> ${deadline.extended_due_date}`;
  if (deadline.extension_status === "submitted" && deadline.extended_due_date) return "Extension pending approval";
  if (deadline.days_remaining < 0) return `Overdue by ${Math.abs(deadline.days_remaining)} days`;
  if (deadline.days_remaining === 0) return "Due today";
  if (deadline.days_remaining === 1) return "Due tomorrow";
  return `In ${deadline.days_remaining} days`;
}

function statusClass(deadline: MockDeadline) {
  if (deadline.days_remaining < 0 && deadline.status !== "completed" && !deadline.extension_status) return "cb";
  if (deadline.status === "blocked") return "cb";
  if (deadline.status === "extension-filed" || deadline.status === "extension-approved") return "ci";
  return "ca";
}

function statusLabel(deadline: MockDeadline) {
  if (deadline.days_remaining < 0 && deadline.status === "blocked") {
    return deadline.blocker_reason ? `Overdue - ${deadline.blocker_reason}` : "Blocked - overdue";
  }
  if (deadline.days_remaining < 0 && deadline.status !== "completed" && !deadline.extension_status) return "Overdue";
  if (deadline.status === "blocked") return deadline.blocker_reason ? `Blocked - ${deadline.blocker_reason}` : "Blocked";
  if (deadline.status === "extension-approved") return "Extension approved";
  if (deadline.status === "extension-filed") return "Extension requested";
  return "Active";
}

function workTitle(deadline: MockDeadline) {
  return deadline.task_title || `${deadline.tax_type} - ${deadline.jurisdiction}`;
}

function defaultTaskNote(deadline: MockDeadline) {
  if (deadline.task_note) return deadline.task_note;
  if (deadline.blocker_reason) return `${deadline.blocker_reason}.`;
  if (deadline.notice_rule_id) return "A recent rule change affected this filing and should be reviewed before work proceeds.";
  return "Review the source, reminders, blockers, and extension state for this item.";
}

function clientContactEmail(deadline: MockDeadline) {
  const client = mockClients.find((item) => item.id === deadline.client_id);
  return client?.primary_contact_email || `client-${deadline.client_id.replace(/^cl-/, "")}@example.com`;
}

function clientContactName(deadline: MockDeadline) {
  const client = mockClients.find((item) => item.id === deadline.client_id);
  return client?.primary_contact_name || "Client contact";
}

function defaultClientEmailSubject(deadline: MockDeadline) {
  if (deadline.status === "blocked") return `${deadline.client_name}: information needed for ${workTitle(deadline)}`;
  if (deadline.days_remaining < 0) return `${deadline.client_name}: overdue ${workTitle(deadline)} follow-up`;
  return `${deadline.client_name}: upcoming ${workTitle(deadline)} deadline`;
}

function defaultClientEmailBody(deadline: MockDeadline) {
  const greeting = `Hi ${clientContactName(deadline).split(" ")[0]},`;
  if (deadline.blocker_reason) {
    return [
      greeting,
      "",
      `We are waiting on the following item before we can continue ${workTitle(deadline)}: ${deadline.blocker_reason}.`,
      "",
      `Could you send the supporting information by ${deadline.due_label}?`,
      "",
      "Thank you."
    ].join("\n");
  }
  return [
    greeting,
    "",
    `We are preparing for ${workTitle(deadline)}, currently due ${deadline.due_label}.`,
    "",
    "Please send any missing support documents or let us know if anything has changed.",
    "",
    "Thank you."
  ].join("\n");
}

function generateAiClientEmailDraft(deadline: MockDeadline, previousBody = "") {
  const contactFirstName = clientContactName(deadline).split(" ")[0];
  const urgencyLine =
    deadline.days_remaining < 0
      ? `This item is overdue by ${Math.abs(deadline.days_remaining)} days, so we should ask for a same-day response.`
      : deadline.days_remaining <= 3
        ? `This is due very soon (${deadline.due_label}), so we should make the ask specific and easy to answer.`
        : `This is due ${deadline.due_label}, so we can keep the tone helpful but direct.`;
  const ask = deadline.blocker_reason
    ? `Please send or confirm: ${deadline.blocker_reason}.`
    : `Please send any missing support documents or confirm that nothing has changed for ${workTitle(deadline)}.`;
  const priorContext = previousBody.trim() ? "\n\nI drafted this based on the current work item details and tightened the client ask." : "";
  return {
    subject: defaultClientEmailSubject(deadline),
    body: [
      `Hi ${contactFirstName},`,
      "",
      `We are working on ${workTitle(deadline)} for ${deadline.client_name}. ${urgencyLine}`,
      "",
      ask,
      "",
      "Once we have this, we can move the work item forward and keep the filing timeline on track.",
      "",
      "Thank you."
    ].join("\n") + priorContext
  };
}

function daysRemainingFromDueDate(dueDate: string) {
  const anchor = new Date("2026-04-26T00:00:00");
  const target = new Date(`${dueDate}T00:00:00`);
  return Math.round((target.getTime() - anchor.getTime()) / 86_400_000);
}

function dueLabelFromDate(dueDate: string) {
  const target = new Date(`${dueDate}T00:00:00`);
  return target.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function addDays(dateText: string, days: number) {
  const target = new Date(`${dateText}T00:00:00`);
  target.setDate(target.getDate() + days);
  return target.toISOString().slice(0, 10);
}

function deriveExtensionDueDate(deadline: MockDeadline) {
  if (
    deadline.tax_type === "Federal income" ||
    deadline.tax_type === "State income" ||
    deadline.tax_type === "Franchise" ||
    deadline.tax_type === "PTE election"
  ) {
    return addDays(deadline.due_date, 153);
  }
  return addDays(deadline.due_date, 30);
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

type RuleImpactRow = {
  id: string;
  clientName: string;
  taxType: string;
  before: string;
  after: string;
  summary: string;
  changed: boolean;
};

function ruleDiffLabels(rule: MockRule) {
  if (rule.id === "rule-001") {
    return {
      before: "PTE election due Apr 30, 2026",
      after: "PTE election due May 30, 2026"
    };
  }
  return {
    before: rule.diff_before,
    after: rule.diff_after
  };
}

function ruleClientScore(rule: MockRule, client: MockClient, clientDeadlines: MockDeadline[]) {
  const text = `${client.entity_type} ${client.states.join(" ")} ${client.applicable_taxes.join(" ")} ${client.notes}`.toLowerCase();
  if (rule.id === "rule-001") {
    let score = 0;
    if (client.applicable_taxes.includes("PTE election")) score += 6;
    if (client.states.includes("CA")) score += 5;
    if (["LLC", "Partnership", "S-Corp"].includes(client.entity_type)) score += 3;
    if (text.includes("pte")) score += 3;
    if (clientDeadlines.some((deadline) => deadline.tax_type === "State income" || deadline.tax_type === "Franchise")) score += 1;
    return score;
  }
  if (rule.id === "rule-002") {
    return client.states.includes("TX") && text.includes("sales") ? 10 : client.states.includes("TX") ? 4 : 0;
  }
  if (rule.id === "rule-005") {
    return client.states.includes("OR") && text.includes("construction") ? 10 : client.states.includes("OR") ? 4 : 0;
  }
  return clientDeadlines.some((deadline) => deadline.notice_rule_id === rule.id) ? 10 : 0;
}

function buildRuleImpactRows(rule: MockRule, deadlines: MockDeadline[], applied: boolean): RuleImpactRow[] {
  const { before, after } = ruleDiffLabels(rule);
  const explicitRows = mockDeadlines
    .filter((base) => base.notice_rule_id === rule.id)
    .map((base) => {
      const current = deadlines.find((deadline) => deadline.id === base.id) ?? base;
      return {
        id: base.id,
        clientName: base.client_name,
        taxType: rule.id === "rule-001" ? "PTE election" : base.tax_type,
        before: rule.id === "rule-001" ? before : base.due_label,
        after: rule.id === "rule-001" ? after : current.due_label,
        summary: rule.id === "rule-001"
          ? "PTE election calendar, reminder queue, and client deadline view will move to the new FTB date."
          : summarizeRuleImpact(base, current),
        changed: applied || base.due_date !== current.due_date || base.status !== current.status || base.source !== current.source
      };
    });

  const existingClientIds = new Set(
    explicitRows
      .map((row) => mockClients.find((client) => client.name === row.clientName)?.id)
      .filter(Boolean)
  );
  const targetCount = rule.affected_count || explicitRows.length;
  if (explicitRows.length >= targetCount) return explicitRows;

  const generatedRows = mockClients
    .filter((client) => !existingClientIds.has(client.id))
    .map((client) => {
      const clientDeadlines = deadlines.filter((deadline) => deadline.client_id === client.id);
      return {
        client,
        score: ruleClientScore(rule, client, clientDeadlines)
      };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.client.name.localeCompare(b.client.name))
    .slice(0, Math.max(0, targetCount - explicitRows.length))
    .map(({ client }) => ({
      id: `${rule.id}-${client.id}`,
      clientName: client.name,
      taxType: rule.id === "rule-001" ? "PTE election" : rule.jurisdiction,
      before,
      after,
      summary:
        rule.id === "rule-001"
          ? "This client matches the PTE-election impact criteria; applying updates its derived calendar and reminders."
          : "This client matches the rule impact criteria; applying updates the relevant client calendar item.",
      changed: applied
    }));

  return [...explicitRows, ...generatedRows];
}

function officialSourceUrl(rule: MockRule) {
  if (rule.source.startsWith("http")) return rule.source;
  if (rule.id === "rule-001") return "https://www.ftb.ca.gov/about-ftb/newsroom/index.html";
  if (rule.id === "rule-002") return "https://comptroller.texas.gov/about/media-center/news/index.php";
  if (rule.id === "rule-003") return "https://www.irs.gov/newsroom/tax-relief-in-disaster-situations";
  if (rule.id === "rule-004") return "https://www.revenue.state.mn.us/news";
  if (rule.id === "rule-005") return "https://www.oregon.gov/dor/news/";
  return `https://www.google.com/search?q=${encodeURIComponent(rule.source)}`;
}

function officialSourceSummary(rule: MockRule) {
  if (rule.id === "rule-001") {
    return "California Franchise Tax Board newsroom notice shifting the annual PTE election due date for affected filers.";
  }
  if (rule.id === "rule-002") {
    return "Texas Comptroller economic nexus guidance lowering the remote-seller threshold and requiring a CPA scope check.";
  }
  if (rule.id === "rule-003") {
    return "IRS disaster-relief update describing automatic filing extensions for taxpayers in covered Texas counties.";
  }
  if (rule.id === "rule-004") {
    return "Minnesota DOR bulletin updating the corporate franchise filing package and related NOL schedule.";
  }
  if (rule.id === "rule-005") {
    return "Oregon rate notice updating the construction excise percentage used on recurring templates.";
  }
  return "Official source detail for this change.";
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

const ENTITY_TYPE_OPTIONS: EntityType[] = ["LLC", "S-Corp", "C-Corp", "Partnership", "Sole Proprietorship", "Professional Corp"];
const TAX_TYPE_OPTIONS: TaxType[] = ["Federal income", "State income", "Sales/Use", "Property", "Payroll (941)", "Franchise", "Excise", "PTE election"];

function ChangeBadge({ kind = "changed" }: { kind?: "new" | "changed" }) {
  return <span className={`badge-pill ${kind === "new" ? "green" : "blue"} thin`}>{kind === "new" ? "New" : "Changed"}</span>;
}

function AiBadge({ label = "AI" }: { label?: string }) {
  return <span className="ai-pill" title="AI-assisted"><span>✦</span>{label}</span>;
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

function recommendedWindowForDeadline(deadline: MockDeadline, note: string) {
  const lowered = note.toLowerCase();
  if (lowered.includes("missing") || lowered.includes("pending") || lowered.includes("blocking")) {
    return {
      taskTitle: `Collect required info for ${deadline.tax_type}`,
      recommendedWindow: deadline.days_remaining <= 7 ? "Do now" : "This week",
      urgency: deadline.days_remaining <= 7 ? ("urgent" as const) : ("medium" as const),
      reason: "This imported row suggests missing or pending information before filing can move."
    };
  }
  if (deadline.days_remaining <= 3) {
    return {
      taskTitle: `Complete ${deadline.tax_type}`,
      recommendedWindow: "Do now",
      urgency: "urgent" as const,
      reason: "The final deadline is close enough that this should be completed immediately."
    };
  }
  if (deadline.days_remaining <= 14) {
    return {
      taskTitle: `Prepare ${deadline.tax_type}`,
      recommendedWindow: "This week",
      urgency: "medium" as const,
      reason: "This filing is approaching and should move into preparation this week."
    };
  }
  return {
    taskTitle: `Confirm filing scope for ${deadline.tax_type}`,
    recommendedWindow: "Next week",
    urgency: "low" as const,
    reason: "This is early enough to confirm scope and keep the plan on schedule."
  };
}

function buildProposedPlan(rows: string[][], decisions: ImportDecision[]): ProposedPlanItem[] {
  const items: ProposedPlanItem[] = [];
  rows.forEach((row, rowIndex) => {
    if (decisions[rowIndex] === "skip") return;
    const imported = buildImportedRecordFromRow(row, rowIndex);
    imported.deadlines.slice(0, 2).forEach((deadline, deadlineIndex) => {
      const recommendation = recommendedWindowForDeadline(deadline, row[6] || "");
      items.push({
        id: `${imported.client.id}-plan-${deadlineIndex + 1}`,
        clientName: imported.client.name,
        taskTitle: recommendation.taskTitle,
        taxType: deadline.tax_type,
        dueLabel: `${deadline.due_label} · ${formatDaysRemaining(deadline)}`,
        recommendedWindow: recommendation.recommendedWindow,
        reason:
          decisions[rowIndex] === "merge"
            ? `${recommendation.reason} This row updates an existing client card.`
            : recommendation.reason,
        urgency: recommendation.urgency
      });
    });
  });
  return items;
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
  setDeadlines: setDeadlineStore,
  changedDeadlineIds = []
}: SectionContext) {
  const deadlines = deadlineStore ?? mockDeadlines;
  const rules = ruleStore ?? mockRules;
  const [filterOpen, setFilterOpen] = useState(false);
  const [stateFilter, setStateFilter] = useState("All");
  const [taxFilter, setTaxFilter] = useState("All");
  const [triageMode, setTriageMode] = useState<"work_now" | "blocked" | "needs_review" | "archive">("work_now");
  const [selectedDeadlineId, setSelectedDeadlineId] = useState<string | null>(null);
  const [editingDeadlineId, setEditingDeadlineId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState({
    taskTitle: "",
    taskNote: "",
    assignee: "",
    dueDate: "",
    priority: "normal",
    blockerReason: ""
  });
  const [followupOpen, setFollowupOpen] = useState(false);
  const [followupDraft, setFollowupDraft] = useState({
    to: "",
    subject: "",
    body: ""
  });
  const [followupAiGenerated, setFollowupAiGenerated] = useState(false);
  const [followupLog, setFollowupLog] = useState<
    Record<string, { id: string; to: string; subject: string; sentAt: string; status: "queued" | "sent" }[]>
  >({});
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const actionMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!actionMenuRef.current) return;
      if (!actionMenuRef.current.contains(event.target as Node)) {
        setActionMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  const visibleDeadlines = useMemo(
    () =>
      deadlines
        .filter((deadline) => {
          if (triageMode === "archive") {
            if (deadline.status !== "completed") return false;
          } else if (triageMode === "blocked") {
            if (deadline.status !== "blocked") return false;
          } else if (triageMode === "needs_review") {
            if (!deadline.notice_rule_id) return false;
            if (deadline.status === "completed") return false;
          } else {
            if (deadline.status === "completed" || deadline.status === "blocked" || deadline.notice_rule_id) return false;
            if (!(isThisWeek(deadline) || deadline.days_remaining < 0)) return false;
          }
          if (stateFilter !== "All" && deadline.jurisdiction !== stateFilter) return false;
          if (taxFilter !== "All" && deadline.tax_type !== taxFilter) return false;
          return true;
        })
        .sort((a, b) => a.days_remaining - b.days_remaining),
    [deadlines, stateFilter, taxFilter, triageMode]
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
  useEffect(() => {
    if (!selectedDeadline) {
      setEditingDeadlineId(null);
      return;
    }
    setEditDraft({
      taskTitle: workTitle(selectedDeadline),
      taskNote: defaultTaskNote(selectedDeadline),
      assignee: selectedDeadline.assignee,
      dueDate: selectedDeadline.due_date,
      priority: selectedDeadline.priority || "normal",
      blockerReason: selectedDeadline.blocker_reason || ""
    });
    setFollowupDraft({
      to: clientContactEmail(selectedDeadline),
      subject: "",
      body: ""
    });
    setFollowupAiGenerated(false);
    setFollowupOpen(false);
    setActionMenuOpen(false);
    setEditingDeadlineId(null);
  }, [selectedDeadlineId, selectedDeadline]);
  const pendingRules = rules.filter((rule) => rule.status === "pending-review");
  const workNowCount = deadlines.filter((deadline) => deadline.status !== "completed" && deadline.status !== "blocked" && !deadline.notice_rule_id && (isThisWeek(deadline) || deadline.days_remaining < 0)).length;
  const blockedCount = deadlines.filter((deadline) => deadline.status === "blocked").length;
  const needsReviewCount = deadlines.filter((deadline) => deadline.status !== "completed" && !!deadline.notice_rule_id).length;
  const archivedCount = deadlines.filter((deadline) => deadline.status === "completed").length;

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
            <p>{defaultTaskNote(selectedDeadline)}</p>
          </div>
          <div className="detail-actions">
            <button
              type="button"
              className="ddh-btn"
              onClick={() => {
                if (editingDeadlineId === selectedDeadline.id) {
                  setEditingDeadlineId(null);
                  return;
                }
                setEditingDeadlineId(selectedDeadline.id);
              }}
            >
              {editingDeadlineId === selectedDeadline.id ? "Cancel edit" : "Edit task"}
            </button>
            <div className="filter-popover-wrap action-menu-wrap" ref={actionMenuRef}>
              <button
                type="button"
                className={`filter-trigger ${actionMenuOpen ? "open" : ""}`}
                onClick={() => setActionMenuOpen((current) => !current)}
              >
                Actions
              </button>
              {actionMenuOpen ? (
                <div className="filter-popover export-menu action-menu" role="menu">
                  <button
                    type="button"
                    className="export-menu-item"
                    onClick={() => {
                      if (!selectedDeadline.extension_status) {
                        const extensionDate = deriveExtensionDueDate(selectedDeadline);
                        updateDeadline(selectedDeadline.id, (deadline) => ({
                          ...deadline,
                          status: "extension-approved",
                          extension_status: "approved",
                          extended_due_date: extensionDate,
                          blocker_reason: null
                        }));
                        onNotify?.(`Filed extension for ${selectedDeadline.client_name}; due date extended through ${dueLabelFromDate(extensionDate)}.`, "blue");
                      } else {
                        updateDeadline(selectedDeadline.id, (deadline) => ({
                          ...deadline,
                          status: "pending",
                          extension_status: null,
                          extended_due_date: null
                        }));
                        onNotify?.(`Revoked extension for ${selectedDeadline.client_name}; restored the original due date.`, "gold");
                      }
                      setActionMenuOpen(false);
                    }}
                  >
                    <span className="menu-item-icon"><ExtensionIcon /></span>
                    <span>{!selectedDeadline.extension_status ? "File extension" : "Revoke extension"}</span>
                  </button>
                  <button
                    type="button"
                    className="export-menu-item"
                    onClick={() => {
                      updateDeadline(selectedDeadline.id, (deadline) =>
                        deadline.status === "blocked"
                          ? { ...deadline, status: "pending", blocker_reason: null }
                          : { ...deadline, status: "blocked", blocker_reason: "Waiting on client" }
                      );
                      onNotify?.(
                        selectedDeadline.status === "blocked"
                          ? `${selectedDeadline.client_name} moved back to active work.`
                          : `${selectedDeadline.client_name} is now waiting on client information.`,
                        "blue"
                      );
                      setActionMenuOpen(false);
                    }}
                  >
                    <span className="menu-item-icon"><BlockedIcon /></span>
                    <span>{selectedDeadline.status === "blocked" ? "Resolve blocker" : "Mark blocked"}</span>
                  </button>
                  <button
                    type="button"
                    className="export-menu-item danger"
                    onClick={() => {
                      updateDeadline(selectedDeadline.id, (deadline) => ({ ...deadline, status: "completed" }));
                      setActionMenuOpen(false);
                      setSelectedDeadlineId(null);
                      onNotify?.(`${selectedDeadline.client_name} archived from the work queue.`, "blue");
                    }}
                  >
                    <span className="menu-item-icon"><ArchiveIcon /></span>
                    <span>Archive</span>
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div className="detail-grid">
          <article className="detail-card">
            <div className="detail-card-lbl">Deadline</div>
            <div className="detail-bigtext">{workTitle(selectedDeadline)}</div>
            <div className="detail-date">{selectedDeadline.due_label} - {formatDaysRemaining(selectedDeadline)}</div>
            {editingDeadlineId === selectedDeadline.id ? (
              <div className="detail-editor">
                <div className="detail-editor-grid">
                  <label>
                    <span>Task title</span>
                    <input
                      className="setting-input"
                      value={editDraft.taskTitle}
                      onChange={(event) => setEditDraft((current) => ({ ...current, taskTitle: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span>Assignee</span>
                    <input
                      className="setting-input"
                      value={editDraft.assignee}
                      onChange={(event) => setEditDraft((current) => ({ ...current, assignee: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span>Due date</span>
                    <input
                      className="setting-input"
                      type="date"
                      value={editDraft.dueDate}
                      onChange={(event) => setEditDraft((current) => ({ ...current, dueDate: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span>Priority</span>
                    <select
                      className="setting-input"
                      value={editDraft.priority}
                      onChange={(event) =>
                        setEditDraft((current) => ({ ...current, priority: event.target.value as "high" | "normal" | "low" }))
                      }
                    >
                      <option value="high">High</option>
                      <option value="normal">Normal</option>
                      <option value="low">Low</option>
                    </select>
                  </label>
                </div>
                <label className="detail-editor-block">
                  <span>Task note</span>
                  <textarea
                    className="setting-input detail-editor-textarea"
                    value={editDraft.taskNote}
                    onChange={(event) => setEditDraft((current) => ({ ...current, taskNote: event.target.value }))}
                    rows={3}
                  />
                </label>
                {selectedDeadline.status === "blocked" ? (
                  <label className="detail-editor-block">
                    <span>Blocker reason</span>
                    <input
                      className="setting-input"
                      value={editDraft.blockerReason}
                      onChange={(event) => setEditDraft((current) => ({ ...current, blockerReason: event.target.value }))}
                    />
                  </label>
                ) : null}
                <div className="detail-editor-actions">
                  <button type="button" className="ddh-btn" onClick={() => setEditingDeadlineId(null)}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="ddh-btn ddh-btn-primary"
                    onClick={() => {
                      updateDeadline(selectedDeadline.id, (deadline) => {
                        const nextDueDate = editDraft.dueDate || deadline.due_date;
                        return {
                          ...deadline,
                          task_title: editDraft.taskTitle.trim() || `${deadline.tax_type} - ${deadline.jurisdiction}`,
                          task_note: editDraft.taskNote.trim() || undefined,
                          assignee: editDraft.assignee.trim() || deadline.assignee,
                          due_date: nextDueDate,
                          due_label: dueLabelFromDate(nextDueDate),
                          days_remaining: daysRemainingFromDueDate(nextDueDate),
                          priority: editDraft.priority as "high" | "normal" | "low",
                          blocker_reason:
                            deadline.status === "blocked" ? (editDraft.blockerReason.trim() || "Waiting on client") : deadline.blocker_reason
                        };
                      });
                      setEditingDeadlineId(null);
                      onNotify?.(`Updated ${selectedDeadline.client_name} work item.`, "blue");
                    }}
                  >
                    Save changes
                  </button>
                </div>
              </div>
            ) : null}
            <div className="detail-fields">
              <div className="df"><span>Status</span><strong>{statusLabel(selectedDeadline)}</strong></div>
              <div className="df"><span>Assignee</span><strong>{selectedDeadline.assignee}</strong></div>
              <div className="df"><span>Priority</span><strong>{(selectedDeadline.priority || "normal").replace(/^./, (s) => s.toUpperCase())}</strong></div>
              <div className="df"><span>Source</span><strong>{selectedDeadline.source}</strong></div>
              <div className="df">
                <span>Extension</span>
                <strong>
                  {selectedDeadline.extension_status === "approved" && selectedDeadline.extended_due_date
                    ? selectedDeadline.extended_due_date
                    : selectedDeadline.extension_status === "submitted" && selectedDeadline.extended_due_date
                      ? `Requested -> ${selectedDeadline.extended_due_date}`
                      : "No extension"}
                </strong>
              </div>
              <div className="df"><span>Task note</span><strong>{defaultTaskNote(selectedDeadline)}</strong></div>
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
            <article className="detail-card client-followup-card">
              <div className="detail-card-lbl">Client follow-up</div>
              <div className="followup-title">
                <h3>Client follow-up</h3>
              </div>
              <p>This action is attached to this work item, not a standalone email thread.</p>
              {followupOpen ? (
                <div className="followup-composer">
                  <div className="followup-ai-row">
                    <button
                      type="button"
                      className="text-action ai-draft-action"
                      onClick={() => {
                        const aiDraft = generateAiClientEmailDraft(selectedDeadline, followupDraft.body);
                        setFollowupDraft((current) => ({
                          ...current,
                          subject: aiDraft.subject,
                          body: aiDraft.body
                        }));
                        setFollowupAiGenerated(true);
                        onNotify?.("AI generated a client follow-up draft from the work item context.", "blue");
                      }}
                    >
                      <span aria-hidden="true">✦</span>
                      {followupAiGenerated ? "Regenerate draft" : "AI draft"}
                    </button>
                    <span>Uses this work item, blocker, due date, and contact to draft the client ask.</span>
                  </div>
                  <label>
                    <span>To</span>
                    <input
                      className="setting-input"
                      value={followupDraft.to}
                      onChange={(event) => setFollowupDraft((current) => ({ ...current, to: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span>Subject</span>
                    <input
                      className="setting-input"
                      value={followupDraft.subject}
                      onChange={(event) => setFollowupDraft((current) => ({ ...current, subject: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span>Message</span>
                    <textarea
                      className="setting-input followup-textarea"
                      value={followupDraft.body}
                      rows={7}
                      onChange={(event) => setFollowupDraft((current) => ({ ...current, body: event.target.value }))}
                    />
                  </label>
                  <div className="followup-actions">
                    <button type="button" className="ddh-btn ddh-btn-sm" onClick={() => setFollowupOpen(false)}>
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="ddh-btn ddh-btn-primary"
                      onClick={() => {
                        const sentAt = new Date().toLocaleString("en-US", {
                          month: "short",
                          day: "numeric",
                          hour: "numeric",
                          minute: "2-digit"
                        });
                        setFollowupLog((current) => ({
                          ...current,
                          [selectedDeadline.id]: [
                            {
                              id: `email-${selectedDeadline.id}-${Date.now()}`,
                              to: followupDraft.to,
                              subject: followupDraft.subject,
                              sentAt,
                              status: "sent"
                            },
                            ...(current[selectedDeadline.id] || [])
                          ]
                        }));
                        setFollowupAiGenerated(false);
                        updateDeadline(selectedDeadline.id, (deadline) => ({
                          ...deadline,
                          status: "blocked",
                          blocker_reason: deadline.blocker_reason || "Waiting on client response to email"
                        }));
                        setFollowupOpen(false);
                        onNotify?.(`Client email sent for ${selectedDeadline.client_name}; work item is waiting on client response.`, "green");
                      }}
                    >
                      Send and wait
                    </button>
                  </div>
                </div>
              ) : (
                <button type="button" className="ddh-btn ddh-btn-sm" onClick={() => setFollowupOpen(true)}>
                  Draft follow-up
                </button>
              )}
              {(followupLog[selectedDeadline.id] || []).length ? (
                <div className="followup-history">
                  {(followupLog[selectedDeadline.id] || []).map((item) => (
                    <div key={item.id} className="followup-history-row">
                      <strong>{item.status === "sent" ? "Email sent" : "Email queued"}</strong>
                      <span>{item.to}</span>
                      <span>{item.subject}</span>
                      <em>{item.sentAt}</em>
                    </div>
                  ))}
                </div>
              ) : null}
            </article>
          </aside>
        </div>
      </section>
    );
  }

  return (
      <section className="ddh-work">
        <div className="ddh-summary">
        <SummaryCard label="Work now" value={String(workNowCount)} sub="Actionable now" active={triageMode === "work_now"} onClick={() => setTriageMode("work_now")} />
        <SummaryCard label="Blocked" value={String(blockedCount)} sub="Waiting on client" warn active={triageMode === "blocked"} onClick={() => setTriageMode("blocked")} />
        <SummaryCard label="Needs review" value={String(needsReviewCount || pendingRules.length)} sub="CPA decision needed" active={triageMode === "needs_review"} onClick={() => setTriageMode("needs_review")} />
        <SummaryCard label="Archive" value={String(archivedCount)} sub="Completed work" active={triageMode === "archive"} onClick={() => setTriageMode("archive")} />
      </div>

      <div className="ddh-toolbar">
        <button type="button" className="ddh-btn" onClick={() => setFilterOpen((current) => !current)}>
          <FilterIcon /> Filter
        </button>
        <button type="button" className="ddh-btn" onClick={() => onExport?.("Work queue", "csv")}>
          <DownloadIcon /> Export
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
            <span>{items.length} item{items.length === 1 ? "" : "s"}</span>
          </div>
          {triageMode === "needs_review" && index === 0 && pendingRules[0] ? (
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
              <span className="ddh-link">{changedDeadlineIds.includes(deadline.id) ? "Changed · details" : "Details"}</span>
            </button>
          ))}
        </div>
      ))}
    </section>
  );
}

function SummaryCard({
  label,
  value,
  sub,
  warn,
  active,
  onClick
}: {
  label: string;
  value: string;
  sub: string;
  warn?: boolean;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button type="button" className={`ddh-summary-card ${warn ? "warn" : ""} ${active ? "active" : ""}`} onClick={onClick}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{sub}</small>
    </button>
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

type ImportStep = 1 | 2 | 3 | 4 | 5;
type ImportFieldKey =
  | "client_name"
  | "entity_type"
  | "operating_states"
  | "primary_contact_name"
  | "primary_contact_email"
  | "applicable_taxes"
  | "notes";
type ImportMappingValue = ImportFieldKey | "skip" | `custom:${string}`;
type ImportMapping = Record<string, ImportMappingValue>;
type CustomImportFieldType = "text" | "date" | "single_select";
type CustomImportField = {
  id: string;
  label: string;
  type: CustomImportFieldType;
};
type ProposedPlanAction = "now" | "later" | "skip";
type ProposedLaterWindow = "tomorrow" | "this_week" | "next_week" | "two_weeks";
type ProposedPlanItem = {
  id: string;
  clientName: string;
  taskTitle: string;
  taxType: string;
  dueLabel: string;
  recommendedWindow: string;
  reason: string;
  urgency: "urgent" | "medium" | "low";
};
type ImportAiProposal = {
  summary: string;
  changes: {
    header: string;
    nextValue: ImportMappingValue;
    note: string;
    customField?: CustomImportField;
  }[];
};

const IMPORT_TARGET_FIELDS: { key: ImportFieldKey; label: string; required?: boolean; aliases: string[] }[] = [
  { key: "client_name", label: "Client name", required: true, aliases: ["client_name", "client", "name", "business name"] },
  { key: "entity_type", label: "Entity type", required: true, aliases: ["entity_type", "entity", "type"] },
  { key: "operating_states", label: "Operating states", required: true, aliases: ["operating_states", "states", "state footprint", "registered states", "state"] },
  { key: "primary_contact_name", label: "Primary contact", aliases: ["primary_contact_name", "contact", "contact name", "owner", "assignee"] },
  { key: "primary_contact_email", label: "Primary contact email", aliases: ["primary_contact_email", "email", "contact email", "primary email"] },
  { key: "applicable_taxes", label: "Tax types", aliases: ["applicable_taxes", "tax_types_csv", "tax types", "tax scope", "services", "forms"] },
  { key: "notes", label: "Notes", aliases: ["notes", "misc_notes", "memo", "remarks", "comment"] }
];

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

function normalizeHeader(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, " ");
}

function slugifyField(value: string) {
  return normalizeHeader(value).replace(/\s+/g, "_").replace(/^_+|_+$/g, "");
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function guessImportField(header: string): ImportFieldKey | "skip" {
  const normalized = normalizeHeader(header);
  for (const field of IMPORT_TARGET_FIELDS) {
    if (field.aliases.some((alias) => normalized === normalizeHeader(alias) || normalized.includes(normalizeHeader(alias)))) {
      return field.key;
    }
  }
  return "skip";
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let current = "";
  let row: string[] = [];
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (char === "\"") {
      if (inQuotes && next === "\"") {
        current += "\"";
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === "," && !inQuotes) {
      row.push(current.trim());
      current = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") i += 1;
      row.push(current.trim());
      current = "";
      if (row.some((cell) => cell.length > 0)) rows.push(row);
      row = [];
      continue;
    }

    current += char;
  }

  if (current.length || row.length) {
    row.push(current.trim());
    if (row.some((cell) => cell.length > 0)) rows.push(row);
  }

  return rows;
}

function buildInitialMapping(headers: string[]): ImportMapping {
  return Object.fromEntries(headers.map((header) => [header, guessImportField(header)]));
}

function isStandardImportField(value: ImportMappingValue): value is ImportFieldKey {
  return value !== "skip" && !value.startsWith("custom:");
}

function mappingLabelForValue(
  value: ImportMappingValue,
  customFields: CustomImportField[]
) {
  if (value === "skip") return "Skip column";
  if (value.startsWith("custom:")) {
    const customField = customFields.find((field) => field.id === value.replace("custom:", ""));
    return customField ? `Custom field: ${customField.label}` : "Custom field";
  }
  return IMPORT_TARGET_FIELDS.find((field) => field.key === value)?.label ?? value;
}

function buildImportAiProposal(
  prompt: string,
  headers: string[],
  customFields: CustomImportField[]
): ImportAiProposal | null {
  const normalizedPrompt = normalizeHeader(prompt);
  if (!normalizedPrompt) return null;

  const matchedHeader = headers.find((header) => normalizedPrompt.includes(normalizeHeader(header)));
  if (!matchedHeader) {
    return {
      summary: "I could not tell which CSV column you want to change.",
      changes: []
    };
  }

  if (normalizedPrompt.includes("skip")) {
    return {
      summary: `Skip ${matchedHeader}`,
      changes: [{ header: matchedHeader, nextValue: "skip", note: "This column will be ignored during import." }]
    };
  }

  if (normalizedPrompt.includes("custom field") || normalizedPrompt.includes("create field")) {
    const namedMatch =
      prompt.match(/(?:called|named)\s+["“]?([^"”]+)["”]?/i) ||
      prompt.match(/custom field\s+["“]?([^"”]+)["”]?/i);
    const label = namedMatch?.[1]?.trim() || matchedHeader;
    const id = slugifyField(label);
    const existing = customFields.find((field) => field.id === id);
    return {
      summary: `Create custom field for ${matchedHeader}`,
      changes: [
        {
          header: matchedHeader,
          nextValue: `custom:${id}`,
          note: `This column will map to the custom field “${label}”.`,
          customField: existing ?? { id, label, type: "text" }
        }
      ]
    };
  }

  const matchedTarget = IMPORT_TARGET_FIELDS.find((field) => {
    const tokens = [field.label, field.key, ...field.aliases];
    return tokens.some((token) => normalizedPrompt.includes(normalizeHeader(token)));
  });

  if (!matchedTarget) {
    return {
      summary: `I found ${matchedHeader}, but I could not tell which field to map it to.`,
      changes: []
    };
  }

  return {
    summary: `Remap ${matchedHeader}`,
    changes: [
      {
        header: matchedHeader,
        nextValue: matchedTarget.key,
        note: `${matchedHeader} will map to ${matchedTarget.label}.`
      }
    ]
  };
}

function buildImportRowsFromUpload(headers: string[], rows: string[][], mapping: ImportMapping): string[][] {
  const valueFor = (row: string[], fieldKey: ImportFieldKey) => {
    const matchedHeader = headers.find((header) => mapping[header] === fieldKey);
    if (!matchedHeader) return "";
    const index = headers.indexOf(matchedHeader);
    return index >= 0 ? row[index] ?? "" : "";
  };

  return rows.map((row) => [
    valueFor(row, "client_name"),
    valueFor(row, "entity_type"),
    valueFor(row, "operating_states"),
    valueFor(row, "primary_contact_name"),
    valueFor(row, "primary_contact_email"),
    valueFor(row, "applicable_taxes"),
    valueFor(row, "notes")
  ]);
}

export function ClientsSection({ onExport, onNotify, importLaunchToken = 0, deadlines: deadlineStore, changedDeadlineIds = [] }: SectionContext) {
  const [importOpen, setImportOpen] = useState(false);
  const [importStep, setImportStep] = useState<ImportStep>(1);
  const [filterOpen, setFilterOpen] = useState(false);
  const [stateFilter, setStateFilter] = useState("All");
  const [taxFilter, setTaxFilter] = useState("All");
  const [records, setRecords] = useState<ClientRecord[]>(() => buildInitialClientRecords());
  const [recentImportResult, setRecentImportResult] = useState<ImportApplyResult | null>(null);
  const [importFocus, setImportFocus] = useState<"all" | "new" | "updated">("all");
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
        if (recentImportResult && importFocus === "new" && !recentImportResult.createdClientIds.includes(record.client.id)) return false;
        if (recentImportResult && importFocus === "updated" && !recentImportResult.mergedClientIds.includes(record.client.id)) return false;
        return true;
      }),
    [recordsWithLiveDeadlines, stateFilter, taxFilter, recentImportResult, importFocus]
  );

  if (importOpen) {
    return (
      <ImportWizard
        step={importStep}
        onStep={setImportStep}
        onClose={closeImport}
        existingClientNames={records.map((record) => record.client.name)}
        onApply={(rows, decisions) => {
          const result = applyImportedRowsToRecords(records, rows, decisions);
          setRecords(result.records);
          setRecentImportResult(result);
          setImportFocus("all");
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
          onNotify={onNotify}
          onUpdateClient={(clientId, nextClient) => {
            setRecords((current) =>
              current.map((entry) =>
                entry.client.id === clientId
                  ? {
                      ...entry,
                      client: nextClient,
                      activity: [
                        {
                          id: `act-client-edit-${clientId}-${Date.now()}`,
                          when: "Just now",
                          actor: "Maya Chen",
                          action: "updated client profile",
                          detail: `Updated ${nextClient.name} profile fields.`,
                          category: "import"
                        },
                        ...entry.activity
                      ]
                    }
                  : entry
              )
            );
          }}
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
            <div className="ddh-inline-actions">
              <button type="button" className={`ddh-btn ${importFocus === "all" ? "ddh-btn-primary" : ""}`} onClick={() => setImportFocus("all")}>
                Show all
              </button>
              {recentImportResult.created > 0 ? (
                <button type="button" className={`ddh-btn ${importFocus === "new" ? "ddh-btn-primary" : ""}`} onClick={() => setImportFocus("new")}>
                  View new clients
                </button>
              ) : null}
              {recentImportResult.merged > 0 ? (
                <button type="button" className={`ddh-btn ${importFocus === "updated" ? "ddh-btn-primary" : ""}`} onClick={() => setImportFocus("updated")}>
                  View updated clients
                </button>
              ) : null}
            </div>
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
  existingClientNames,
  onApply,
  onDone
}: {
  step: ImportStep;
  onStep: (step: ImportStep) => void;
  onClose: () => void;
  existingClientNames: string[];
  onApply: (rows: string[][], decisions: ImportDecision[]) => ImportApplyResult;
  onDone: () => void;
}) {
  const [result, setResult] = useState<ImportApplyResult | null>(null);
  const [fileName, setFileName] = useState("");
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [mapping, setMapping] = useState<ImportMapping>({});
  const [customFields, setCustomFields] = useState<CustomImportField[]>([]);
  const [decisions, setDecisions] = useState<ImportDecision[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [processingState, setProcessingState] = useState<null | "uploading" | "analyzing" | "matching" | "ready" | "applying">(null);
  const [proposedPlan, setProposedPlan] = useState<ProposedPlanItem[]>([]);
  const [planActions, setPlanActions] = useState<ProposedPlanAction[]>([]);
  const [planWindows, setPlanWindows] = useState<ProposedLaterWindow[]>([]);
  const [approvedPlanSummary, setApprovedPlanSummary] = useState<{ now: number; later: number; skipped: number } | null>(null);

  const normalizedRows = useMemo(
    () => buildImportRowsFromUpload(csvHeaders, csvRows, mapping),
    [csvHeaders, csvRows, mapping]
  );
  const missingRequired = useMemo(
    () => IMPORT_TARGET_FIELDS.filter((field) => field.required && !Object.values(mapping).includes(field.key)).map((field) => field.label),
    [mapping]
  );

  useEffect(() => {
    setDecisions(
      normalizedRows.map((row) =>
        existingClientNames.some((name) => name.trim().toLowerCase() === row[0].trim().toLowerCase()) ? "merge" : "keep"
      )
    );
  }, [normalizedRows, existingClientNames]);

  function next() {
    if (step < 5) onStep((step + 1) as ImportStep);
  }
  function back() {
    if (step > 1) onStep((step - 1) as ImportStep);
  }

  async function handleCsvFile(file: File) {
    try {
      setUploadError(null);
      setProcessingState("uploading");
      const text = await file.text();
      await sleep(300);
      setProcessingState("analyzing");
      const parsed = parseCsv(text);
      if (parsed.length < 2) throw new Error("The file needs a header row and at least one client row.");
      const [headers, ...rows] = parsed;
      await sleep(350);
      setProcessingState("matching");
      const initialMapping = buildInitialMapping(headers);
      await sleep(350);
      setFileName(file.name);
      setCsvHeaders(headers);
      setCsvRows(rows);
      setMapping(initialMapping);
      setCustomFields([]);
      setProcessingState("ready");
      await sleep(180);
      onStep(2);
      setProcessingState(null);
    } catch (error) {
      setProcessingState(null);
      setUploadError(error instanceof Error ? error.message : "Could not read this CSV file.");
    }
  }

  return (
    <section className="ddh-import">
      <button type="button" className="ddh-back-link" onClick={onClose}>
        Back to clients
      </button>
      <div className="ddh-import-head">
        <div>
          <div className="ddh-eyebrow">Clients - Import</div>
          <h1>Bring a portfolio of clients into DueDateHQ</h1>
          <p>Upload a CSV, confirm how its columns map to our client fields, and review duplicate detection before anything is written.</p>
        </div>
      </div>
      <div className="ddh-stepper">
        {["Choose file", "Map columns", "Review rows", "Review plan", "Done"].map((label, index) => {
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
        {step === 1 ? <ImportStepOne onFileSelected={handleCsvFile} error={uploadError} processingState={processingState} /> : null}
        {step === 2 ? (
          <ImportStepTwo
            fileName={fileName}
            headers={csvHeaders}
            rows={csvRows}
            mapping={mapping}
            customFields={customFields}
            missingRequired={missingRequired}
            onBack={back}
            onChangeMapping={(header, value) => setMapping((current) => ({ ...current, [header]: value }))}
            onCreateCustomField={(field) =>
              setCustomFields((current) => (current.some((item) => item.id === field.id) ? current : [...current, field]))
            }
            onNext={next}
          />
        ) : null}
        {step === 3 ? (
          <ImportStepThree
            fileName={fileName}
            rows={normalizedRows}
            existingClientNames={existingClientNames}
            decisions={decisions}
            missingRequired={missingRequired}
            onChangeDecision={(rowIndex, decision) =>
              setDecisions((current) => current.map((item, index) => (index === rowIndex ? decision : item)))
            }
            onBack={back}
            onApply={async () => {
              setProcessingState("applying");
              await sleep(450);
              const applied = onApply(normalizedRows.map((row) => [...row]), decisions);
              setResult(applied);
              const nextPlan = buildProposedPlan(normalizedRows, decisions);
              setProposedPlan(nextPlan);
              setPlanActions(nextPlan.map((item) => (item.urgency === "urgent" ? "now" : "later")));
              setPlanWindows(nextPlan.map((item) => (item.urgency === "urgent" ? "this_week" : "next_week")));
              setProcessingState(null);
              onStep(4);
            }}
          />
        ) : null}
        {step === 4 ? (
          <ImportStepPlanReview
            items={proposedPlan}
            actions={planActions}
            windows={planWindows}
            onBack={back}
            onChangeAction={(index, action) =>
              setPlanActions((current) => current.map((item, itemIndex) => (itemIndex === index ? action : item)))
            }
            onChangeWindow={(index, window) =>
              setPlanWindows((current) => current.map((item, itemIndex) => (itemIndex === index ? window : item)))
            }
            onApprove={() => {
              setApprovedPlanSummary({
                now: planActions.filter((action) => action === "now").length,
                later: planActions.filter((action) => action === "later").length,
                skipped: planActions.filter((action) => action === "skip").length
              });
              onStep(5);
            }}
          />
        ) : null}
        {step === 5 ? <ImportStepDone result={result} planSummary={approvedPlanSummary} onDone={onDone} /> : null}
      </div>
    </section>
  );
}

function ImportStepOne({
  onFileSelected,
  error,
  processingState
}: {
  onFileSelected: (file: File) => void;
  error: string | null;
  processingState: null | "uploading" | "analyzing" | "matching" | "ready" | "applying";
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const processingText =
    processingState === "uploading"
      ? "Uploading file…"
      : processingState === "analyzing"
        ? "Analyzing columns…"
        : processingState === "matching"
          ? "Checking existing clients…"
          : processingState === "applying"
            ? "Applying import…"
          : processingState === "ready"
            ? "Preview ready"
            : null;

  function openPicker() {
    fileInputRef.current?.click();
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onFileSelected(file);
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    if (processingState !== null) return;
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) onFileSelected(file);
  }

  return (
    <>
      <input ref={fileInputRef} type="file" accept=".csv,text/csv" hidden onChange={handleInputChange} />
      <button
        type="button"
        className={`ddh-upload-area ${dragging ? "dragging" : ""}`}
        onClick={openPicker}
        disabled={processingState !== null}
        onDragOver={(event) => {
          event.preventDefault();
          if (processingState !== null) return;
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <span className="ddh-upload-icon"><UploadIcon /></span>
        <strong>Drop a CSV here, or click to browse</strong>
        <small>{processingText ?? "We will preview matches and updates before anything changes."}</small>
      </button>
      {error ? <p className="ddh-import-error">{error}</p> : null}
    </>
  );
}

function ImportStepTwo({
  fileName,
  headers,
  rows,
  mapping,
  customFields,
  missingRequired,
  onBack,
  onChangeMapping,
  onCreateCustomField,
  onNext
}: {
  fileName: string;
  headers: string[];
  rows: string[][];
  mapping: ImportMapping;
  customFields: CustomImportField[];
  missingRequired: string[];
  onBack: () => void;
  onChangeMapping: (header: string, value: ImportMappingValue) => void;
  onCreateCustomField: (field: CustomImportField) => void;
  onNext: () => void;
}) {
  const [draftHeader, setDraftHeader] = useState<string | null>(null);
  const [draftLabel, setDraftLabel] = useState("");
  const [draftType, setDraftType] = useState<CustomImportFieldType>("text");
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiProposal, setAiProposal] = useState<ImportAiProposal | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  function startCustomField(header: string) {
    setDraftHeader(header);
    setDraftLabel(header);
    setDraftType("text");
  }

  function saveCustomField() {
    if (!draftHeader) return;
    const trimmed = draftLabel.trim();
    if (!trimmed) return;
    const field: CustomImportField = {
      id: slugifyField(trimmed),
      label: trimmed,
      type: draftType
    };
    onCreateCustomField(field);
    onChangeMapping(draftHeader, `custom:${field.id}`);
    setDraftHeader(null);
    setDraftLabel("");
    setDraftType("text");
  }

  function createAiProposal() {
    const proposal = buildImportAiProposal(aiPrompt, headers, customFields);
    if (!proposal || proposal.changes.length === 0) {
      setAiProposal(null);
      setAiError(proposal?.summary ?? "Try something like: “Map primary_state to Operating states” or “Create custom field onboarding note for misc_notes”.");
      return;
    }
    setAiProposal(proposal);
    setAiError(null);
  }

  function applyAiProposal() {
    if (!aiProposal) return;
    aiProposal.changes.forEach((change) => {
      if (change.customField) onCreateCustomField(change.customField);
      onChangeMapping(change.header, change.nextValue);
    });
    setAiProposal(null);
    setAiPrompt("");
    setAiError(null);
  }

  return (
    <>
      <p className="ddh-import-note">{fileName} · {rows.length} rows detected. Review only the columns that need attention, or use the mapping assistant for a quick suggestion.</p>
      {missingRequired.length ? <p className="ddh-import-warning">Still needed before you can continue: {missingRequired.join(", ")}.</p> : null}
      <div className="ddh-import-ai">
        <div>
          <strong className="ai-row-title">Mapping assistant (beta) <AiBadge /></strong>
          <small>Describe one mapping change in plain language and confirm the suggested update.</small>
        </div>
        <div className="ddh-import-ai-controls">
          <input
            type="text"
            value={aiPrompt}
            onChange={(event) => setAiPrompt(event.target.value)}
            placeholder='Example: "Map primary_state to Operating states"'
          />
          <button type="button" className="ddh-btn" onClick={createAiProposal} disabled={!aiPrompt.trim()}>
            Suggest change
          </button>
        </div>
        {aiError ? <p className="ddh-import-error">{aiError}</p> : null}
        {aiProposal ? (
          <div className="ddh-import-ai-proposal">
            <div>
              <strong>{aiProposal.summary}</strong>
              {aiProposal.changes.map((change) => (
                <p key={change.header}>{change.note}</p>
              ))}
            </div>
            <div className="ddh-inline-actions">
              <button type="button" className="ddh-btn" onClick={() => setAiProposal(null)}>Discard</button>
              <button type="button" className="ddh-btn ddh-btn-primary" onClick={applyAiProposal}>Apply suggestion</button>
            </div>
          </div>
        ) : null}
      </div>
      <table className="ddh-map-table">
        <thead><tr><th>CSV column</th><th>Sample value</th><th>Mapped to</th></tr></thead>
        <tbody>
          {headers.map((header, index) => {
            const guessed = guessImportField(header);
            const selected = mapping[header] ?? "skip";
            const needsReview = selected === "skip" || (isStandardImportField(selected) && guessed === "skip");
            return (
            <tr key={header}>
              <td><code>{header}</code></td>
              <td>{rows[0]?.[index] || "—"}</td>
              <td>
                <select
                  value={selected}
                  onChange={(event) => {
                    const nextValue = event.target.value as ImportMappingValue | "__create_custom__";
                    if (nextValue === "__create_custom__") {
                      startCustomField(header);
                      return;
                    }
                    onChangeMapping(header, nextValue);
                  }}
                >
                  {IMPORT_TARGET_FIELDS.map((field) => (
                    <option key={field.key} value={field.key}>{field.label}</option>
                  ))}
                  {customFields.map((field) => (
                    <option key={field.id} value={`custom:${field.id}`}>{`Custom field: ${field.label}`}</option>
                  ))}
                  <option value="__create_custom__">Create custom field…</option>
                  <option value="skip">Skip column</option>
                </select>
                <span className={`ddh-mapping-status ${needsReview ? "review" : "auto"}`}>
                  {selected.startsWith("custom:")
                    ? "Custom field"
                    : guessed === "skip"
                      ? "Needs review"
                      : "Auto-mapped"}
                </span>
                {selected.startsWith("custom:") ? (
                  <span className="ddh-mapping-meta">{mappingLabelForValue(selected, customFields)}</span>
                ) : null}
                {draftHeader === header ? (
                  <div className="ddh-custom-field-editor">
                    <input
                      type="text"
                      value={draftLabel}
                      onChange={(event) => setDraftLabel(event.target.value)}
                      placeholder="Custom field name"
                    />
                    <select value={draftType} onChange={(event) => setDraftType(event.target.value as CustomImportFieldType)}>
                      <option value="text">Text</option>
                      <option value="date">Date</option>
                      <option value="single_select">Single select</option>
                    </select>
                    <div className="ddh-inline-actions">
                      <button type="button" className="ddh-btn" onClick={() => setDraftHeader(null)}>Cancel</button>
                      <button type="button" className="ddh-btn ddh-btn-primary" onClick={saveCustomField} disabled={!draftLabel.trim()}>
                        Add field
                      </button>
                    </div>
                  </div>
                ) : null}
              </td>
            </tr>
          )})}
        </tbody>
      </table>
      <div className="ddh-step-foot"><button type="button" className="ddh-btn" onClick={onBack}>Back</button><button type="button" className="ddh-btn ddh-btn-primary" onClick={onNext} disabled={missingRequired.length > 0}>Continue</button></div>
    </>
  );
}

function ImportStepThree({
  fileName,
  rows,
  existingClientNames,
  decisions,
  missingRequired,
  onChangeDecision,
  onBack,
  onApply
}: {
  fileName: string;
  rows: string[][];
  existingClientNames: string[];
  decisions: ImportDecision[];
  missingRequired: string[];
  onChangeDecision: (rowIndex: number, decision: ImportDecision) => void;
  onBack: () => void;
  onApply: () => void | Promise<void>;
}) {
  const previewRows = rows.map((row, rowIndex) => ({
    client: row[0] || "—",
    entity: row[1] || "—",
    states: row[2] || "—",
    taxes: row[5] || "—",
    assignee: row[3] || "—",
    matchedExisting: existingClientNames.some((name) => name.trim().toLowerCase() === row[0].trim().toLowerCase()),
    decision: decisions[rowIndex] ?? "keep"
  }));
  const mergeCount = decisions.filter((decision) => decision === "merge").length;
  const createCount = decisions.filter((decision) => decision === "keep").length;
  const skipCount = decisions.filter((decision) => decision === "skip").length;
  return (
    <>
      <p className="ddh-import-note">{fileName} · {rows.length} rows parsed · {mergeCount} update{mergeCount === 1 ? "" : "s"} · {createCount} new card{createCount === 1 ? "" : "s"} · {skipCount} skip{skipCount === 1 ? "" : "s"}.</p>
      {missingRequired.length ? <p className="ddh-import-warning">This file still has unresolved required fields: {missingRequired.join(", ")}.</p> : null}
      <table className="ddh-review-table">
        <thead><tr><th>Client</th><th>Entity</th><th>States</th><th>Tax types</th><th>Assignee</th><th>Action</th></tr></thead>
        <tbody>
          {previewRows.map((row, rowIndex) => (
            <tr key={`${row.client}-${rowIndex}`} className={row.decision !== "keep" ? "warn" : ""}>
              <td>{row.client}</td>
              <td>{row.entity}</td>
              <td>{row.states}</td>
              <td>{row.taxes}</td>
              <td>{row.assignee}</td>
              <td>
                <select value={row.decision} onChange={(event) => onChangeDecision(rowIndex, event.target.value as ImportDecision)}>
                  <option value="keep">Create new card</option>
                  {row.matchedExisting ? <option value="merge">Update existing client</option> : null}
                  <option value="skip">Skip row</option>
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
  <div className="ddh-step-foot"><button type="button" className="ddh-btn" onClick={onBack}>Back</button><button type="button" className="ddh-btn ddh-btn-primary" onClick={() => void onApply()} disabled={rows.length === 0 || missingRequired.length > 0}>Apply import</button></div>
    </>
  );
}

function ImportStepPlanReview({
  items,
  actions,
  windows,
  onBack,
  onChangeAction,
  onChangeWindow,
  onApprove
}: {
  items: ProposedPlanItem[];
  actions: ProposedPlanAction[];
  windows: ProposedLaterWindow[];
  onBack: () => void;
  onChangeAction: (index: number, action: ProposedPlanAction) => void;
  onChangeWindow: (index: number, window: ProposedLaterWindow) => void;
  onApprove: () => void;
}) {
  const nowCount = actions.filter((action) => action === "now").length;
  const laterCount = actions.filter((action) => action === "later").length;
  const skipCount = actions.filter((action) => action === "skip").length;

  return (
    <>
      <p className="ddh-import-note">
        Review the proposed work plan before anything enters the work queue. Decide which items start now and which should be planned for later.
      </p>
      <div className="import-plan-summary">
        <span><strong>{items.length}</strong> proposed items</span>
        <span><strong>{nowCount}</strong> do now</span>
        <span><strong>{laterCount}</strong> plan for later</span>
        <span><strong>{skipCount}</strong> skip</span>
      </div>
      <table className="ddh-review-table">
        <thead><tr><th>Client</th><th>Proposed task</th><th>Deadline</th><th>Why now</th><th>Decision</th><th>Planned time</th></tr></thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={item.id}>
              <td>{item.clientName}</td>
              <td>
                <strong>{item.taskTitle}</strong>
                <div className="muted">{item.taxType}</div>
              </td>
              <td>{item.dueLabel}</td>
              <td>
                <span className={`badge-pill ${item.urgency === "urgent" ? "red" : item.urgency === "medium" ? "gold" : "blue"} thin`}>
                  {item.recommendedWindow}
                </span>
                <div className="muted">{item.reason}</div>
              </td>
              <td>
                <select value={actions[index] ?? "later"} onChange={(event) => onChangeAction(index, event.target.value as ProposedPlanAction)}>
                  <option value="now">Now prepare to do it</option>
                  <option value="later">Leave it for later</option>
                  <option value="skip">Skip for now</option>
                </select>
              </td>
              <td>
                {actions[index] === "later" ? (
                  <select value={windows[index] ?? "next_week"} onChange={(event) => onChangeWindow(index, event.target.value as ProposedLaterWindow)}>
                    <option value="tomorrow">Tomorrow</option>
                    <option value="this_week">This week</option>
                    <option value="next_week">Next week</option>
                    <option value="two_weeks">In two weeks</option>
                  </select>
                ) : (
                  <span className="muted">{actions[index] === "now" ? "Do now" : "Not added"}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="ddh-step-foot">
        <button type="button" className="ddh-btn" onClick={onBack}>Back</button>
        <button type="button" className="ddh-btn ddh-btn-primary" onClick={onApprove}>Approve plan</button>
      </div>
    </>
  );
}

function ImportStepDone({
  result,
  planSummary,
  onDone
}: {
  result: ImportApplyResult | null;
  planSummary: { now: number; later: number; skipped: number } | null;
  onDone: () => void;
}) {
  return (
    <div className="ddh-import-done">
      <div className="ddh-import-done-mark">✓</div>
      <h2>{result ? `${result.created} new · ${result.merged} updated` : "Import complete"}</h2>
      <p>Full-year deadline calendars generated. New clients were added to the directory and existing matches were updated in place.</p>
      {planSummary ? (
        <div className="import-plan-summary import-plan-summary-final">
          <span><strong>{planSummary.now}</strong> start now</span>
          <span><strong>{planSummary.later}</strong> planned for later</span>
          <span><strong>{planSummary.skipped}</strong> skipped</span>
        </div>
      ) : null}
      {result ? (
        <div className="import-complete-breakdown">
          {result.createdClientNames.length ? (
            <div className="import-complete-group">
              <span className="import-result-label">New client cards created</span>
              <ul className="import-complete-list">
                {result.createdClientNames.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {result.mergedClientNames.length ? (
            <div className="import-complete-group">
              <span className="import-result-label">Existing clients updated</span>
              <ul className="import-complete-list">
                {result.mergedClientNames.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
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
  onNotify,
  onUpdateClient
}: {
  record: ClientRecord;
  changedDeadlineIds: string[];
  onBack: () => void;
  onNotify?: (text: string, tone?: "green" | "blue" | "gold" | "red") => void;
  onUpdateClient?: (clientId: string, nextClient: MockClient) => void;
}) {
  const { client, deadlines, blockers, reminders, activity: recentActivity } = record;
  const extensionDeadlines = deadlines.filter((deadline) => deadline.extension_status);
  const hasChangedDeadlines = deadlines.some((deadline) => changedDeadlineIds.includes(deadline.id));
  const nextDeadline = deadlines[0] || null;
  const latestActivity = recentActivity[0] || null;
  const [editingClient, setEditingClient] = useState(false);
  const [clientDraft, setClientDraft] = useState({
    name: client.name,
    entityType: client.entity_type,
    states: client.states.join(", "),
    contactName: client.primary_contact_name,
    contactEmail: client.primary_contact_email,
    taxes: client.applicable_taxes.join(", "),
    notes: client.notes || ""
  });
  useEffect(() => {
    setEditingClient(false);
    setClientDraft({
      name: client.name,
      entityType: client.entity_type,
      states: client.states.join(", "),
      contactName: client.primary_contact_name,
      contactEmail: client.primary_contact_email,
      taxes: client.applicable_taxes.join(", "),
      notes: client.notes || ""
    });
  }, [client.id]);

  function resetClientDraft() {
    setClientDraft({
      name: client.name,
      entityType: client.entity_type,
      states: client.states.join(", "),
      contactName: client.primary_contact_name,
      contactEmail: client.primary_contact_email,
      taxes: client.applicable_taxes.join(", "),
      notes: client.notes || ""
    });
  }

  function saveClientDraft() {
    const nextTaxes = normalizeTaxes(clientDraft.taxes);
    const nextStates = normalizeStates(clientDraft.states);
    const nextClient: MockClient = {
      ...client,
      name: clientDraft.name.trim() || client.name,
      entity_type: clientDraft.entityType as EntityType,
      states: nextStates.length ? nextStates : client.states,
      primary_contact_name: clientDraft.contactName.trim() || client.primary_contact_name,
      primary_contact_email: clientDraft.contactEmail.trim() || client.primary_contact_email,
      applicable_taxes: nextTaxes.length ? nextTaxes : client.applicable_taxes,
      notes: clientDraft.notes.trim()
    };
    onUpdateClient?.(client.id, nextClient);
    setEditingClient(false);
    onNotify?.(`Updated ${nextClient.name} profile.`, "blue");
  }

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
            onClick={() => {
              if (editingClient) {
                resetClientDraft();
                setEditingClient(false);
                return;
              }
              setEditingClient(true);
            }}
          >
            {editingClient ? "Cancel edit" : "Edit client"}
          </button>
        </div>
      </div>

      <div className="detail-grid client-detail-grid">
        <article className="detail-card client-profile-card">
          <div className="detail-card-lbl">Client</div>
          {editingClient ? (
            <div className="detail-editor client-editor">
              <div className="detail-editor-grid">
                <label>
                  <span>Client name</span>
                  <input
                    className="setting-input"
                    value={clientDraft.name}
                    onChange={(event) => setClientDraft((current) => ({ ...current, name: event.target.value }))}
                  />
                </label>
                <label>
                  <span>Entity type</span>
                  <select
                    className="setting-input"
                    value={clientDraft.entityType}
                    onChange={(event) => setClientDraft((current) => ({ ...current, entityType: event.target.value as EntityType }))}
                  >
                    {ENTITY_TYPE_OPTIONS.map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>States</span>
                  <input
                    className="setting-input"
                    value={clientDraft.states}
                    onChange={(event) => setClientDraft((current) => ({ ...current, states: event.target.value }))}
                  />
                </label>
                <label>
                  <span>Contact name</span>
                  <input
                    className="setting-input"
                    value={clientDraft.contactName}
                    onChange={(event) => setClientDraft((current) => ({ ...current, contactName: event.target.value }))}
                  />
                </label>
                <label>
                  <span>Contact email</span>
                  <input
                    className="setting-input"
                    value={clientDraft.contactEmail}
                    onChange={(event) => setClientDraft((current) => ({ ...current, contactEmail: event.target.value }))}
                  />
                </label>
                <label>
                  <span>Tax scope</span>
                  <select
                    className="setting-input"
                    value=""
                    onChange={(event) => {
                      const nextTax = event.target.value as TaxType;
                      if (!nextTax) return;
                      setClientDraft((current) => {
                        const currentTaxes = normalizeTaxes(current.taxes);
                        const nextTaxes = currentTaxes.includes(nextTax)
                          ? currentTaxes.filter((tax) => tax !== nextTax)
                          : [...currentTaxes, nextTax];
                        return { ...current, taxes: nextTaxes.join(", ") };
                      });
                    }}
                  >
                    <option value="">Add or remove tax type</option>
                    {TAX_TYPE_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {normalizeTaxes(clientDraft.taxes).includes(option) ? "Remove" : "Add"} {option}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="client-tax-chip-row">
                {normalizeTaxes(clientDraft.taxes).map((tax) => (
                  <button
                    type="button"
                    key={tax}
                    className="badge-pill blue thin"
                    onClick={() =>
                      setClientDraft((current) => ({
                        ...current,
                        taxes: normalizeTaxes(current.taxes).filter((item) => item !== tax).join(", ")
                      }))
                    }
                  >
                    {tax} ×
                  </button>
                ))}
              </div>
              <label className="detail-editor-block">
                <span>Notes</span>
                <textarea
                  className="setting-input detail-editor-textarea"
                  value={clientDraft.notes}
                  rows={3}
                  onChange={(event) => setClientDraft((current) => ({ ...current, notes: event.target.value }))}
                />
              </label>
              <div className="detail-editor-actions">
                <button
                  type="button"
                  className="ddh-btn"
                  onClick={() => {
                    resetClientDraft();
                    setEditingClient(false);
                  }}
                >
                  Cancel
                </button>
                <button type="button" className="ddh-btn ddh-btn-primary" onClick={saveClientDraft}>
                  Save client
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="detail-bigtext">{client.entity_type} · {client.states.join(", ")}</div>
              <div className="detail-date">{client.primary_contact_name} · {client.primary_contact_email}</div>
              <div className="detail-fields">
                <div className="df"><span>Taxes</span><strong>{client.applicable_taxes.slice(0, 3).join(" · ")}{client.applicable_taxes.length > 3 ? ` +${client.applicable_taxes.length - 3}` : ""}</strong></div>
                <div className="df"><span>Next due</span><strong>{nextDeadline ? `${nextDeadline.due_label} · ${formatDaysRemaining(nextDeadline)}` : "No deadlines"}</strong></div>
                <div className="df"><span>Open blockers</span><strong>{blockers.length}</strong></div>
                <div className="df"><span>Extensions</span><strong>{extensionDeadlines.length}</strong></div>
              </div>
              {client.notes ? <p className="client-note-strip">{client.notes}</p> : null}
            </>
          )}
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
          <div className={`deadlines-table client-deadlines-table ${hasChangedDeadlines ? "with-change" : "no-change"}`} role="table">
            <div className="deadlines-table-head" role="row">
              <span role="columnheader">Tax type</span>
              <span role="columnheader">Jurisdiction</span>
              <span role="columnheader">Due</span>
              <span role="columnheader">Status</span>
              <span role="columnheader">Assignee</span>
              {hasChangedDeadlines ? <span role="columnheader">Change</span> : null}
            </div>
            {deadlines.map((deadline) => (
              <div key={deadline.id} className="deadlines-table-row" role="row">
                <span className="deadlines-cell client" role="cell">{deadline.tax_type}</span>
                <span role="cell">{deadline.jurisdiction}</span>
                <span className="deadlines-cell due" role="cell">
                  <strong>{deadline.due_label}</strong>
                  <span className="muted">{formatDaysRemaining(deadline)}</span>
                  {deadline.extension_status === "approved" && deadline.extended_due_date ? (
                    <span className="muted">Extended to {deadline.extended_due_date}</span>
                  ) : deadline.extension_status === "submitted" && deadline.extended_due_date ? (
                    <span className="muted">Extension requested for {deadline.extended_due_date}</span>
                  ) : null}
                </span>
                <span role="cell">
                  <span className={`badge-pill ${statusClass(deadline) === "cb" ? "red" : statusClass(deadline) === "ci" ? "gold" : "blue"} thin`}>
                    {statusLabel(deadline)}
                  </span>
                </span>
                <span role="cell">{deadline.assignee}</span>
                {hasChangedDeadlines ? <span role="cell">{changedDeadlineIds.includes(deadline.id) ? <ChangeBadge /> : null}</span> : null}
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
          <div className="review-title-row">
            <h1>Official changes that need a decision</h1>
            <span className="lane-help-shell review-info-help">
              <button type="button" className="lane-help-trigger mini" aria-label="How review works">
                i
              </button>
              <span className="lane-help-tooltip">
                <strong>What this queue is</strong>
                <p>DueDateHQ monitors official tax sources, extracts rule changes, and summarizes the impact with AI.</p>
                <strong>Why CPA reviews it</strong>
                <p>Only changes that may affect this client portfolio land here, so you can apply, dismiss, or inspect affected clients before deadlines change.</p>
              </span>
            </span>
          </div>
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
  const [sourceOpen, setSourceOpen] = useState(false);
  const affected = rule.affected_count || deadlines.filter((deadline) => deadline.notice_rule_id === rule.id).length;
  const isApplied = variant === "applied";
  const isAuto = variant === "auto";
  const isDismissed = variant === "dismissed";
  const sourceUrl = officialSourceUrl(rule);
  const impactRows = buildRuleImpactRows(rule, deadlines, isApplied || isAuto);
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
        <button type="button" onClick={() => setSourceOpen((current) => !current)}>
          {sourceOpen ? "Hide source" : "Official source"}
        </button>
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
      {sourceOpen ? (
        <div className="rule-impact-list">
          <div className="rule-impact-row">
            <div className="rule-impact-head">
              <strong>{rule.source}</strong>
              <span className="badge-pill blue thin">Official source</span>
            </div>
            <div className="rule-impact-copy">
              <p>{officialSourceSummary(rule)}</p>
              <p>
                <a
                  className="ddh-inline-link"
                  href={sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {sourceUrl}
                </a>
              </p>
            </div>
          </div>
        </div>
      ) : null}
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
  const [displayName, setDisplayName] = useState("Johnson CPA PLLC");
  const [timezone, setTimezone] = useState("America/Los_Angeles");
  const [fiscalYear, setFiscalYear] = useState("Calendar (Jan - Dec)");
  const [primaryChannel, setPrimaryChannel] = useState("Email");
  const [connections, setConnections] = useState([
    { id: "email", label: "Email", destination: "sarah@johnsoncpa.com", connected: true },
    { id: "wechat", label: "WeChat", destination: "Johnson CPA service account", connected: false }
  ]);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);

  function toggleConnection(connectionId: string) {
    setConnections((current) =>
      current.map((connection) =>
        connection.id === connectionId
          ? { ...connection, connected: !connection.connected }
          : connection
      )
    );
  }

  function saveSettings() {
    const stamp = new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    setLastSavedAt(stamp);
    onNotify?.("Saved workspace settings for this demo workspace.", "green");
  }

  return (
    <section>
      <div className="ddh-page-head"><div><div className="ddh-eyebrow">Settings</div><h1>Workspace settings</h1></div></div>
      <SettingsCard label="Workspace defaults" title="Keep the demo workspace predictable" subtitle="Only the defaults that affect reminders, exports, and displayed workspace identity.">
        <EditableSettingRow label="Display name" sub="Shown in the topbar and on exports." value={displayName} onChange={setDisplayName} />
        <EditableSettingRow label="Time zone" sub="Used for reminder send times." value={timezone} onChange={setTimezone} />
        <SelectSettingRow
          label="Fiscal year"
          sub="Used to bucket extensions and YTD totals."
          value={fiscalYear}
          options={["Calendar (Jan - Dec)", "Fiscal year ending Jun 30", "Fiscal year ending Sep 30"]}
          onChange={setFiscalYear}
        />
        <SelectSettingRow
          label="Default client follow-up"
          sub="Used when a work item needs client information."
          value={primaryChannel}
          options={mockChannels.map((channel) => channel.label)}
          onChange={setPrimaryChannel}
        />
        <SettingRow label="Tenant ID" sub="Sent on every backend request - read only." value={tenantId} mono />
        <div className="ddh-settings-foot">
          <span>{lastSavedAt ? `Saved at ${lastSavedAt}` : "Anchored today: Apr 26, 2026"}</span>
          <button
            type="button"
            className="ddh-btn ddh-btn-primary"
            onClick={saveSettings}
          >
            Save changes
          </button>
        </div>
      </SettingsCard>
      <SettingsCard label="Connections" title="CPA reminder connections" subtitle="Where DueDateHQ can notify the CPA when work needs attention.">
        <div className="settings-connection-grid">
          {connections.map((connection) => (
            <div key={connection.id} className="settings-connection-row">
              <div>
                <strong>{connection.label}</strong>
                <span>{connection.destination}</span>
              </div>
              <div className="settings-connection-actions">
                <em className={connection.connected ? "enabled" : ""}>{connection.connected ? "Connected" : "Not connected"}</em>
                <button type="button" className="ddh-btn ddh-btn-sm" onClick={() => toggleConnection(connection.id)}>
                  {connection.connected ? "Disconnect" : "Connect"}
                </button>
              </div>
            </div>
          ))}
        </div>
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

function EditableSettingRow({
  label,
  sub,
  value,
  onChange
}: {
  label: string;
  sub: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="ddh-setting-row">
      <div><strong>{label}</strong><span>{sub}</span></div>
      <input className="editable" value={value} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function SelectSettingRow({
  label,
  sub,
  value,
  options,
  onChange
}: {
  label: string;
  sub: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="ddh-setting-row">
      <div><strong>{label}</strong><span>{sub}</span></div>
      <select className="setting-input compact" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
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
