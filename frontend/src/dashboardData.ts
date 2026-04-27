// dashboardData.ts
// Pure data + helper module extracted from App.tsx.
// Holds dashboard lane definitions, seed data for non-list lanes,
// and the horizon / event helpers that DashboardSurface depends on.

import type { TaskItem, ViewEnvelope } from "./types";

// ---------- Types ----------

export type DashboardLane = "track" | "waiting" | "notices" | "watchlist";

export type DashboardSurfaceMode = "board" | "calendar" | "timeline";

export type DashboardHorizon =
  | "this-week"
  | "next-30"
  | "this-month"
  | "next-month"
  | "quarter";

export type DashboardTrackItem = TaskItem & {
  task_id?: string;
  title?: string;
  due_at?: string;
  priority?: string;
  task_type?: string;
  source_type?: string;
  source_id?: string;
};

export type DashboardWaitingItem = (typeof dashboardWaitingSeed)[number];
export type DashboardNoticeItem = (typeof dashboardNoticeSeed)[number];
export type DashboardWatchItem = (typeof dashboardWatchSeed)[number];

export type DashboardEvent = {
  id: string;
  lane: DashboardLane;
  selectionId: string;
  title: string;
  subtitle: string;
  dateIso: string;
  dateLabel: string;
  statusLabel: string;
  tone: "urgent" | "medium" | "low";
};

export type DashboardCalendarGroup = {
  dateKey: string;
  label: string;
  items: DashboardEvent[];
};

// ---------- Lane metadata ----------

export const dashboardSectionMeta = {
  track: {
    label: "Track",
    title: "What the firm needs to move this week",
    description:
      "This is the active work queue. Every row here is a task that now requires CPA or staff attention.",
    helper: "Use this when you want to decide what gets worked first."
  },
  waiting: {
    label: "Waiting on info",
    title: "Blockers that stop work from moving",
    description:
      "These are blocker objects, not active tasks. They exist because a document, jurisdiction detail, or confirmation is still missing.",
    helper: "Use this to chase blockers instead of doing deadline work blindly."
  },
  notices: {
    label: "Notice",
    title: "Official source changes that may alter deadlines",
    description:
      "A notice is an official update, not a task. It only becomes active work after the CPA decides it should be escalated.",
    helper: "Use this when a legal or policy change may affect multiple clients."
  },
  watchlist: {
    label: "Watchlist",
    title: "Clients that deserve extra attention this week",
    description:
      "The watchlist is a risk view, not an active work queue. Items only move into Track after a deliberate escalation.",
    helper: "Use this to monitor accounts that could become urgent soon."
  }
} as const;

export const horizonMetaMap: Record<
  DashboardHorizon,
  { title: string; description: string; calendarTitle: string; timelineTitle: string }
> = {
  "this-week": {
    title: "This week across your client portfolio",
    description: "Open deadlines, blockers, notices, and watchlist items in one place.",
    calendarTitle: "This week's calendar",
    timelineTitle: "This week's timeline"
  },
  "next-30": {
    title: "The next 30 days across the portfolio",
    description:
      "Use this range to review active work, blockers, notices, and watchlist items over the next month.",
    calendarTitle: "Next 30 days on the calendar",
    timelineTitle: "Next 30 days in sequence"
  },
  "this-month": {
    title: "Everything that matters this month",
    description: "Review the current month without limiting the board to only urgent items.",
    calendarTitle: "This month's calendar",
    timelineTitle: "This month's timeline"
  },
  "next-month": {
    title: "What is coming up next month",
    description:
      "Plan for work that is not urgent yet but should already shape client communication and staffing.",
    calendarTitle: "Next month's calendar",
    timelineTitle: "Next month's timeline"
  },
  quarter: {
    title: "The quarter at a glance",
    description:
      "Review where risk clusters, where blockers repeat, and where new notice-driven work may appear.",
    calendarTitle: "Quarter calendar",
    timelineTitle: "Quarter timeline"
  }
};

// ---------- Seed data (non-list lanes) ----------
// These remain client-side stubs until backend wiring lands. They were copied
// verbatim from the previous inline definitions so behavior is preserved.

export const dashboardWaitingSeed = [
  {
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    reason: "Payroll support documents missing",
    requested_from: "Maya Chen",
    next_step: "Draft a short email requesting payroll support docs before Apr 22.",
    due_label: "Apr 22",
    date_iso: "2026-04-22"
  },
  {
    client_id: "cl-002",
    client_name: "Harbor Studio Partners",
    reason: "Home state and extension intent still unconfirmed",
    requested_from: "Evan Malik",
    next_step: "Confirm home jurisdiction and whether the partners want extension planning.",
    due_label: "Apr 24",
    date_iso: "2026-04-24"
  }
];

export const dashboardNoticeSeed = [
  {
    notice_id: "notice-001",
    title: "California extension update detected",
    summary: "Affects eight clients. Two still require human review before updating dates.",
    affected_count: 8,
    next_step: "Review the two California clients before bulk-updating deadline dates.",
    read: false,
    due_label: "Apr 26",
    date_iso: "2026-04-26"
  },
  {
    notice_id: "notice-002",
    title: "Texas nexus threshold clarification",
    summary: "Could expand California filing scope for one importer client.",
    affected_count: 1,
    next_step: "Check whether Sierra's California footprint is strong enough to create a new filing.",
    read: true,
    due_label: "May 03",
    date_iso: "2026-05-03"
  }
];

export const dashboardWatchSeed = [
  {
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    risk_label: "High" as const,
    headline: "Payroll filing is due soon and documents are still missing.",
    why_it_matters: "This is the closest deadline in the portfolio and it is still blocked.",
    next_step: "Escalate the document request or decide whether to remind later.",
    due_label: "Apr 22",
    date_iso: "2026-04-22"
  },
  {
    client_id: "cl-002",
    client_name: "Harbor Studio Partners",
    risk_label: "Watch" as const,
    headline: "PTE election may change this year's strategy.",
    why_it_matters: "The deadline is not the earliest, but the CPA decision affects filing approach.",
    next_step: "Review the owner memo and confirm whether the election should stay on the queue.",
    due_label: "Apr 24",
    date_iso: "2026-04-24"
  },
  {
    client_id: "cl-003",
    client_name: "Sierra Wholesale Inc.",
    risk_label: "Watch" as const,
    headline: "A Texas notice may create a California obligation.",
    why_it_matters: "A notice-driven change could add work that is not yet reflected as a final deadline.",
    next_step: "Open the notice and confirm whether nexus rules should change this account.",
    due_label: "May 03",
    date_iso: "2026-05-03"
  }
];

// ---------- Helpers ----------

export function urgencyClass(item: TaskItem | DashboardTrackItem): "urgent" | "medium" | "low" {
  const normalizedStatus = String(item.status || "").toLowerCase();
  if (
    normalizedStatus.includes("blocked") ||
    normalizedStatus.includes("overdue") ||
    item.days_remaining <= 0
  ) {
    return "urgent";
  }
  if (item.days_remaining <= 7) return "medium";
  return "low";
}

export function badgeClass(urgency: "urgent" | "medium" | "low") {
  if (urgency === "urgent") return "urgent";
  if (urgency === "medium") return "medium";
  return "low";
}

export function itemSelectionValue(
  item:
    | DashboardTrackItem
    | DashboardWaitingItem
    | DashboardNoticeItem
    | DashboardWatchItem,
  lane: DashboardLane
): string {
  if (lane === "track") return String((item as DashboardTrackItem).deadline_id || "");
  if (lane === "notices") return String((item as DashboardNoticeItem).notice_id || "");
  return String(
    (item as DashboardWaitingItem | DashboardWatchItem).client_id || ""
  );
}

export function extractTrackItems(view: ViewEnvelope): DashboardTrackItem[] {
  if (view.type !== "ListCard") return [];
  const data = view.data as { items?: Array<Record<string, unknown>> };
  const rawItems = data.items || [];
  return rawItems.map((item, index) => ({
    deadline_id: String(item.deadline_id || item.task_id || `track-${index + 1}`),
    client_id: String(item.client_id || `client-${index + 1}`),
    client_name: String(item.client_name || item.title || `Client ${index + 1}`),
    tax_type: String(item.tax_type || item.task_type || "Active work"),
    jurisdiction: String(item.jurisdiction || item.priority || "Cross-state"),
    due_date: String(item.due_date || item.due_at || "TBD"),
    status: String(item.status || "Open"),
    days_remaining: Number(item.days_remaining ?? 7),
    risk: item.risk ? String(item.risk) : undefined,
    missing: item.missing ? String(item.missing) : undefined,
    task_id: item.task_id ? String(item.task_id) : undefined,
    title: item.title ? String(item.title) : undefined,
    due_at: item.due_at ? String(item.due_at) : undefined,
    priority: item.priority ? String(item.priority) : undefined,
    task_type: item.task_type ? String(item.task_type) : undefined,
    source_type: item.source_type ? String(item.source_type) : undefined,
    source_id: item.source_id ? String(item.source_id) : undefined
  }));
}

export function buildDashboardEvents(
  trackItems: DashboardTrackItem[],
  waitingItems: DashboardWaitingItem[],
  noticeItems: DashboardNoticeItem[],
  watchItems: DashboardWatchItem[]
): DashboardEvent[] {
  const events: DashboardEvent[] = [
    ...trackItems.map((item) => ({
      id: `track-${item.deadline_id}`,
      lane: "track" as const,
      selectionId: String(item.deadline_id),
      title: item.client_name,
      subtitle: `${item.title || item.tax_type} · ${item.jurisdiction}`,
      dateIso: normalizeDashboardDate(item.due_date, item.days_remaining),
      dateLabel: item.due_date,
      statusLabel: item.status || "Open",
      tone: urgencyClass(item)
    })),
    ...waitingItems.map((item) => ({
      id: `waiting-${item.client_id}`,
      lane: "waiting" as const,
      selectionId: item.client_id,
      title: item.client_name,
      subtitle: item.reason,
      dateIso: item.date_iso,
      dateLabel: item.due_label,
      statusLabel: "Blocked",
      tone: "urgent" as const
    })),
    ...noticeItems.map((item) => ({
      id: `notice-${item.notice_id}`,
      lane: "notices" as const,
      selectionId: item.notice_id,
      title: item.title,
      subtitle: item.summary,
      dateIso: item.date_iso,
      dateLabel: item.due_label,
      statusLabel: item.read ? "Read" : "Needs review",
      tone: item.read ? ("low" as const) : ("medium" as const)
    })),
    ...watchItems.map((item) => ({
      id: `watch-${item.client_id}`,
      lane: "watchlist" as const,
      selectionId: item.client_id,
      title: item.client_name,
      subtitle: item.headline,
      dateIso: item.date_iso,
      dateLabel: item.due_label,
      statusLabel: item.risk_label,
      tone: item.risk_label === "High" ? ("urgent" as const) : ("medium" as const)
    }))
  ];

  return events.sort((a, b) => a.dateIso.localeCompare(b.dateIso));
}

export function filterDashboardEventsByHorizon(
  events: DashboardEvent[],
  horizon: DashboardHorizon
): DashboardEvent[] {
  const base = new Date("2026-04-20T00:00:00");
  return events.filter((event) => {
    const date = new Date(`${event.dateIso}T00:00:00`);
    const diffDays = Math.floor((date.getTime() - base.getTime()) / 86400000);
    if (horizon === "this-week") return diffDays <= 7;
    if (horizon === "next-30") return diffDays <= 30;
    if (horizon === "this-month") return date.getMonth() === 3;
    if (horizon === "next-month") return date.getMonth() === 4;
    return diffDays <= 90;
  });
}

export function groupDashboardEventsByDate(
  events: DashboardEvent[]
): DashboardCalendarGroup[] {
  const grouped = new Map<string, DashboardEvent[]>();
  events.forEach((event) => {
    const bucket = grouped.get(event.dateIso) || [];
    bucket.push(event);
    grouped.set(event.dateIso, bucket);
  });
  return [...grouped.entries()].map(([dateKey, items]) => ({
    dateKey,
    label: items[0]?.dateLabel || dateKey,
    items
  }));
}

export function normalizeDashboardDate(label: string, daysRemaining: number): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(label)) return label;
  if (label === "Review now") return "2026-04-21";
  if (label === "This week") return "2026-04-25";
  const parsed = new Date(`${label}, 2026`);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toISOString().slice(0, 10);
  }
  const fallback = new Date("2026-04-20T00:00:00");
  fallback.setDate(fallback.getDate() + Math.max(daysRemaining, 0));
  return fallback.toISOString().slice(0, 10);
}
