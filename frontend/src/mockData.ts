// mockData.ts
// Demo seed data for the DueDateHQ frontend. The 5-section IA pages render
// against this dataset directly so each tab feels lived-in even when the
// FastAPI backend isn't running. When the backend IS up, sections still keep
// this mock as fallback while the live result merges in.
//
// Keep all dates anchored to today=2026-04-26 so the upcoming-deadline math
// reads naturally in screenshots.

export type EntityType = "LLC" | "S-Corp" | "C-Corp" | "Partnership" | "Sole Proprietorship" | "Professional Corp";
export type TaxType =
  | "Federal income"
  | "State income"
  | "Sales/Use"
  | "Property"
  | "Payroll (941)"
  | "Franchise"
  | "Excise"
  | "PTE election";
export type DeadlineStatus = "pending" | "completed" | "extension-filed" | "extension-approved" | "blocked";
export type Urgency = "urgent" | "medium" | "low";
export type ChannelKind = "email" | "sms" | "inapp" | "slack";
export type ReminderStep = 30 | 14 | 7 | 1;

export type MockClient = {
  id: string;
  name: string;
  entity_type: EntityType;
  states: string[];
  primary_contact_name: string;
  primary_contact_email: string;
  applicable_taxes: TaxType[];
  active_deadlines: number;
  blocked_deadlines: number;
  extensions_filed: number;
  risk_label: "high" | "watch" | null;
  notes: string;
};

export type MockDeadline = {
  id: string;
  client_id: string;
  client_name: string;
  tax_type: TaxType;
  jurisdiction: string;
  due_date: string;
  due_label: string;
  days_remaining: number;
  status: DeadlineStatus;
  extension_status: "submitted" | "approved" | "denied" | null;
  extended_due_date: string | null;
  source: string;
  blocker_reason: string | null;
  assignee: string;
  // When set, this deadline is flagged into the Notice bucket because
  // the referenced rule (in mockRules) materially changed something
  // about it. Independent of days_remaining — a deadline 19 days out
  // can still be in Notice if a pending-review rule changes how it
  // should be filed.
  notice_rule_id?: string;
};

export type MockReminder = {
  id: string;
  client_id: string;
  client_name: string;
  deadline_id: string;
  tax_type: TaxType;
  jurisdiction: string;
  step: ReminderStep;
  channel: ChannelKind;
  send_at: string;
  recipient: string;
  status: "scheduled" | "queued" | "sent";
};

export type MockRule = {
  id: string;
  title: string;
  jurisdiction: string;
  source: string;
  detected_at: string;
  affected_count: number;
  status: "pending-review" | "auto-applied" | "dismissed";
  summary: string;
  diff_before: string;
  diff_after: string;
};

export type MockBlocker = {
  id: string;
  client_id: string;
  client_name: string;
  deadline_label: string;
  reason: string;
  waiting_on: string;
  asked_at: string;
  days_open: number;
  next_step: string;
};

export type MockActivity = {
  id: string;
  when: string;
  actor: string;
  action: string;
  detail: string;
  category: "filing" | "reminder" | "rule" | "import" | "extension";
};

export type MockTeamMember = {
  id: string;
  name: string;
  initials: string;
  role: string;
  email: string;
  active_clients: number;
};

export type MockChannel = {
  id: string;
  kind: ChannelKind;
  label: string;
  description: string;
  enabled: boolean;
  last_send: string | null;
};

export type MockIntegration = {
  id: string;
  name: string;
  description: string;
  status: "connected" | "disconnected" | "error";
  last_sync: string | null;
};

export type MockExportRecord = {
  id: string;
  format: "csv" | "pdf";
  scope: string;
  generated_at: string;
  size: string;
};

export type MockSyncStatus = {
  jurisdictions_covered: number;
  jurisdictions_total: number;
  last_full_sync: string;
  next_scheduled_sync: string;
  pending_rule_changes: number;
  rules_auto_applied_today: number;
  source_count: number;
};

export type MockKPI = {
  id: string;
  label: string;
  value: string | number;
  delta: string;
  tone: "ink" | "red" | "gold" | "green" | "blue";
  helper: string;
};

// ---------- Clients ----------

export const mockClients: MockClient[] = [
  {
    id: "cl-001",
    name: "Northwind Services LLC",
    entity_type: "LLC",
    states: ["CA", "TX", "NV"],
    primary_contact_name: "Maya Chen",
    primary_contact_email: "maya@northwindservices.com",
    applicable_taxes: ["Federal income", "State income", "Payroll (941)", "Sales/Use"],
    active_deadlines: 4,
    blocked_deadlines: 1,
    extensions_filed: 0,
    risk_label: "high",
    notes: "Payroll heavy across three states; needs document chase before Q2 941."
  },
  {
    id: "cl-002",
    name: "Harbor Studio Partners",
    entity_type: "Partnership",
    states: ["NY", "NJ"],
    primary_contact_name: "Evan Malik",
    primary_contact_email: "evan@harborstudio.com",
    applicable_taxes: ["Federal income", "State income", "PTE election"],
    active_deadlines: 3,
    blocked_deadlines: 1,
    extensions_filed: 1,
    risk_label: "watch",
    notes: "PTE election decision pending; extension already filed federally."
  },
  {
    id: "cl-003",
    name: "Sierra Wholesale Inc.",
    entity_type: "C-Corp",
    states: ["TX", "CA", "AZ"],
    primary_contact_name: "Daniel Ortega",
    primary_contact_email: "daniel@sierrawholesale.com",
    applicable_taxes: ["Federal income", "State income", "Sales/Use", "Franchise"],
    active_deadlines: 5,
    blocked_deadlines: 0,
    extensions_filed: 1,
    risk_label: "watch",
    notes: "Texas notice may create new California obligation; nexus review pending."
  },
  {
    id: "cl-004",
    name: "Pinecone Dental P.C.",
    entity_type: "Professional Corp",
    states: ["WA"],
    primary_contact_name: "Dr. Lila Park",
    primary_contact_email: "office@pineconedental.com",
    applicable_taxes: ["Federal income", "State income", "Payroll (941)"],
    active_deadlines: 2,
    blocked_deadlines: 0,
    extensions_filed: 0,
    risk_label: null,
    notes: "Single-state practice; quarterly payroll on track."
  },
  {
    id: "cl-005",
    name: "Riverbend Manufacturing",
    entity_type: "C-Corp",
    states: ["TX", "OK", "LA"],
    primary_contact_name: "Hank Reyes",
    primary_contact_email: "hank@riverbendmfg.com",
    applicable_taxes: ["Federal income", "State income", "Property", "Excise"],
    active_deadlines: 6,
    blocked_deadlines: 0,
    extensions_filed: 0,
    risk_label: null,
    notes: "Property tax filings staggered across three counties."
  },
  {
    id: "cl-006",
    name: "Atlas Logistics LLC",
    entity_type: "LLC",
    states: ["IL", "IN", "OH", "MI"],
    primary_contact_name: "Priya Iyer",
    primary_contact_email: "priya@atlaslogistics.com",
    applicable_taxes: ["Federal income", "State income", "Excise", "Payroll (941)"],
    active_deadlines: 5,
    blocked_deadlines: 0,
    extensions_filed: 2,
    risk_label: null,
    notes: "Multi-state IFTA; both state extensions approved."
  },
  {
    id: "cl-007",
    name: "Kestrel Consulting Group",
    entity_type: "S-Corp",
    states: ["MA", "NH"],
    primary_contact_name: "Owen Patel",
    primary_contact_email: "owen@kestrelconsulting.com",
    applicable_taxes: ["Federal income", "State income", "Payroll (941)"],
    active_deadlines: 3,
    blocked_deadlines: 0,
    extensions_filed: 0,
    risk_label: null,
    notes: "Remote-first team; payroll routed through PEO."
  },
  {
    id: "cl-008",
    name: "Maple Hill Dental Group",
    entity_type: "Professional Corp",
    states: ["MN", "WI"],
    primary_contact_name: "Dr. Anna Holm",
    primary_contact_email: "office@maplehilldental.com",
    applicable_taxes: ["Federal income", "State income", "Payroll (941)", "Sales/Use"],
    active_deadlines: 4,
    blocked_deadlines: 0,
    extensions_filed: 0,
    risk_label: null,
    notes: "Two-clinic group; sales tax for retail items."
  },
  {
    id: "cl-009",
    name: "Glacier Outdoor Co.",
    entity_type: "C-Corp",
    states: ["CO", "UT", "ID"],
    primary_contact_name: "Tess Lindgren",
    primary_contact_email: "tess@glacieroutdoor.com",
    applicable_taxes: ["Federal income", "State income", "Sales/Use", "Property"],
    active_deadlines: 5,
    blocked_deadlines: 0,
    extensions_filed: 1,
    risk_label: null,
    notes: "E-commerce; multi-state sales tax via Avalara."
  },
  {
    id: "cl-010",
    name: "Beacon Bay Investments LLC",
    entity_type: "LLC",
    states: ["FL"],
    primary_contact_name: "Carmen Reyes",
    primary_contact_email: "carmen@beaconbay.com",
    applicable_taxes: ["Federal income", "State income"],
    active_deadlines: 1,
    blocked_deadlines: 0,
    extensions_filed: 1,
    risk_label: null,
    notes: "Federal extension filed; FL has no state income tax."
  },
  {
    id: "cl-011",
    name: "Twin Pines Construction",
    entity_type: "S-Corp",
    states: ["OR", "WA"],
    primary_contact_name: "Marco Davis",
    primary_contact_email: "marco@twinpinesconstruction.com",
    applicable_taxes: ["Federal income", "State income", "Payroll (941)", "Excise"],
    active_deadlines: 4,
    blocked_deadlines: 0,
    extensions_filed: 0,
    risk_label: null,
    notes: "Construction excise tax monthly; OR PTE active."
  },
  {
    id: "cl-012",
    name: "Aurora Tech Labs",
    entity_type: "C-Corp",
    states: ["CA", "NY", "WA"],
    primary_contact_name: "Reese Kim",
    primary_contact_email: "reese@auroratech.io",
    applicable_taxes: ["Federal income", "State income", "Payroll (941)", "Franchise"],
    active_deadlines: 4,
    blocked_deadlines: 1,
    extensions_filed: 0,
    risk_label: "watch",
    notes: "Prior-year return missing; blocking current-year planning."
  }
];

// ---------- Deadlines ----------

export const mockDeadlines: MockDeadline[] = [
  {
    id: "dl-001",
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    tax_type: "Payroll (941)",
    jurisdiction: "Federal",
    due_date: "2026-04-30",
    due_label: "Apr 30",
    days_remaining: 4,
    status: "blocked",
    extension_status: null,
    extended_due_date: null,
    source: "IRS Pub 15 — Q1 2026 941 due Apr 30",
    blocker_reason: "Payroll support documents missing for CA/TX",
    assignee: "Maya Chen"
  },
  {
    id: "dl-002",
    client_id: "cl-002",
    client_name: "Harbor Studio Partners",
    tax_type: "PTE election",
    jurisdiction: "NY",
    due_date: "2026-04-30",
    due_label: "Apr 30",
    days_remaining: 4,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "NY DTF — PTE annual election deadline",
    blocker_reason: null,
    assignee: "Evan Malik"
  },
  {
    id: "dl-003",
    client_id: "cl-003",
    client_name: "Sierra Wholesale Inc.",
    tax_type: "Franchise",
    jurisdiction: "TX",
    due_date: "2026-05-15",
    due_label: "May 15",
    days_remaining: 19,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "TX Comptroller — Franchise tax annual",
    blocker_reason: null,
    assignee: "Sarah Johnson",
    notice_rule_id: "rule-002"
  },
  {
    id: "dl-004",
    client_id: "cl-006",
    client_name: "Atlas Logistics LLC",
    tax_type: "Federal income",
    jurisdiction: "Federal",
    due_date: "2026-04-15",
    due_label: "Apr 15",
    days_remaining: -11,
    status: "extension-approved",
    extension_status: "approved",
    extended_due_date: "2026-10-15",
    source: "IRS Form 7004",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-005",
    client_id: "cl-006",
    client_name: "Atlas Logistics LLC",
    tax_type: "State income",
    jurisdiction: "IL",
    due_date: "2026-04-15",
    due_label: "Apr 15",
    days_remaining: -11,
    status: "extension-approved",
    extension_status: "approved",
    extended_due_date: "2026-10-15",
    source: "IL-1120 extension",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-006",
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    tax_type: "Sales/Use",
    jurisdiction: "CA",
    due_date: "2026-04-30",
    due_label: "Apr 30",
    days_remaining: 4,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "CDTFA monthly filer",
    blocker_reason: null,
    assignee: "Maya Chen"
  },
  {
    id: "dl-007",
    client_id: "cl-005",
    client_name: "Riverbend Manufacturing",
    tax_type: "Property",
    jurisdiction: "TX",
    due_date: "2026-04-30",
    due_label: "Apr 30",
    days_remaining: 4,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "Harris County Appraisal District",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-008",
    client_id: "cl-009",
    client_name: "Glacier Outdoor Co.",
    tax_type: "Sales/Use",
    jurisdiction: "CO",
    due_date: "2026-05-20",
    due_label: "May 20",
    days_remaining: 24,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "CO DOR monthly",
    blocker_reason: null,
    assignee: "Owen Patel"
  },
  {
    id: "dl-009",
    client_id: "cl-009",
    client_name: "Glacier Outdoor Co.",
    tax_type: "Federal income",
    jurisdiction: "Federal",
    due_date: "2026-04-15",
    due_label: "Apr 15",
    days_remaining: -11,
    status: "extension-filed",
    extension_status: "submitted",
    extended_due_date: "2026-10-15",
    source: "IRS Form 7004 — submitted Apr 14",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-010",
    client_id: "cl-010",
    client_name: "Beacon Bay Investments LLC",
    tax_type: "Federal income",
    jurisdiction: "Federal",
    due_date: "2026-04-15",
    due_label: "Apr 15",
    days_remaining: -11,
    status: "extension-approved",
    extension_status: "approved",
    extended_due_date: "2026-10-15",
    source: "IRS Form 7004",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-011",
    client_id: "cl-008",
    client_name: "Maple Hill Dental Group",
    tax_type: "State income",
    jurisdiction: "MN",
    due_date: "2026-05-01",
    due_label: "May 1",
    days_remaining: 5,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "MN DOR — annual",
    blocker_reason: null,
    assignee: "Owen Patel"
  },
  {
    id: "dl-012",
    client_id: "cl-007",
    client_name: "Kestrel Consulting Group",
    tax_type: "Payroll (941)",
    jurisdiction: "Federal",
    due_date: "2026-04-30",
    due_label: "Apr 30",
    days_remaining: 4,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "IRS — Q1 2026 941",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-013",
    client_id: "cl-011",
    client_name: "Twin Pines Construction",
    tax_type: "Excise",
    jurisdiction: "OR",
    due_date: "2026-04-30",
    due_label: "Apr 30",
    days_remaining: 4,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "OR DOR — construction excise",
    blocker_reason: null,
    assignee: "Maya Chen",
    notice_rule_id: "rule-005"
  },
  {
    id: "dl-014",
    client_id: "cl-012",
    client_name: "Aurora Tech Labs",
    tax_type: "State income",
    jurisdiction: "CA",
    due_date: "2026-05-15",
    due_label: "May 15",
    days_remaining: 19,
    status: "blocked",
    extension_status: null,
    extended_due_date: null,
    source: "FTB Form 100",
    blocker_reason: "Prior-year return still missing",
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-015",
    client_id: "cl-003",
    client_name: "Sierra Wholesale Inc.",
    tax_type: "State income",
    jurisdiction: "CA",
    due_date: "2026-05-15",
    due_label: "May 15",
    days_remaining: 19,
    status: "extension-filed",
    extension_status: "submitted",
    extended_due_date: "2026-11-15",
    source: "FTB Form 3539",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-016",
    client_id: "cl-002",
    client_name: "Harbor Studio Partners",
    tax_type: "Federal income",
    jurisdiction: "Federal",
    due_date: "2026-04-15",
    due_label: "Apr 15",
    days_remaining: -11,
    status: "extension-approved",
    extension_status: "approved",
    extended_due_date: "2026-09-15",
    source: "IRS Form 7004 — partnership",
    blocker_reason: null,
    assignee: "Evan Malik"
  },
  {
    id: "dl-017",
    client_id: "cl-004",
    client_name: "Pinecone Dental P.C.",
    tax_type: "Payroll (941)",
    jurisdiction: "Federal",
    due_date: "2026-04-30",
    due_label: "Apr 30",
    days_remaining: 4,
    status: "completed",
    extension_status: null,
    extended_due_date: null,
    source: "IRS — Q1 2026 941",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-018",
    client_id: "cl-005",
    client_name: "Riverbend Manufacturing",
    tax_type: "Excise",
    jurisdiction: "OK",
    due_date: "2026-04-21",
    due_label: "Apr 21",
    days_remaining: -5,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "OK Tax Commission — gross production",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-019",
    client_id: "cl-006",
    client_name: "Atlas Logistics LLC",
    tax_type: "Excise",
    jurisdiction: "IL",
    due_date: "2026-05-25",
    due_label: "May 25",
    days_remaining: 29,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "IL — IFTA Q1",
    blocker_reason: null,
    assignee: "Owen Patel"
  },
  {
    id: "dl-020",
    client_id: "cl-008",
    client_name: "Maple Hill Dental Group",
    tax_type: "Sales/Use",
    jurisdiction: "WI",
    due_date: "2026-04-30",
    due_label: "Apr 30",
    days_remaining: 4,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "WI DOR — monthly",
    blocker_reason: null,
    assignee: "Maya Chen"
  },
  {
    id: "dl-021",
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    tax_type: "State income",
    jurisdiction: "CA",
    due_date: "2026-04-24",
    due_label: "Apr 24",
    days_remaining: -2,
    status: "blocked",
    extension_status: null,
    extended_due_date: null,
    source: "FTB Form 568",
    blocker_reason: "CA apportionment workpapers still missing",
    assignee: "Maya Chen"
  },
  {
    id: "dl-022",
    client_id: "cl-005",
    client_name: "Riverbend Manufacturing",
    tax_type: "Property",
    jurisdiction: "OK",
    due_date: "2026-05-31",
    due_label: "May 31",
    days_remaining: 35,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "OK Tax — personal property",
    blocker_reason: null,
    assignee: "Sarah Johnson"
  },
  {
    id: "dl-023",
    client_id: "cl-012",
    client_name: "Aurora Tech Labs",
    tax_type: "Franchise",
    jurisdiction: "CA",
    due_date: "2026-05-15",
    due_label: "May 15",
    days_remaining: 19,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "FTB Form 100 — minimum franchise",
    blocker_reason: null,
    assignee: "Sarah Johnson",
    notice_rule_id: "rule-001"
  },
  {
    id: "dl-024",
    client_id: "cl-009",
    client_name: "Glacier Outdoor Co.",
    tax_type: "Property",
    jurisdiction: "CO",
    due_date: "2026-06-15",
    due_label: "Jun 15",
    days_remaining: 50,
    status: "pending",
    extension_status: null,
    extended_due_date: null,
    source: "CO DOR — personal property",
    blocker_reason: null,
    assignee: "Owen Patel"
  }
];

// ---------- Reminders (30/14/7/1 stepped) ----------

export const mockReminders: MockReminder[] = [
  {
    id: "rm-001",
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    deadline_id: "dl-001",
    tax_type: "Payroll (941)",
    jurisdiction: "Federal",
    step: 1,
    channel: "email",
    send_at: "2026-04-29T08:00:00",
    recipient: "maya@northwindservices.com",
    status: "scheduled"
  },
  {
    id: "rm-002",
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    deadline_id: "dl-001",
    tax_type: "Payroll (941)",
    jurisdiction: "Federal",
    step: 1,
    channel: "sms",
    send_at: "2026-04-29T08:05:00",
    recipient: "+1 415-555-0142",
    status: "scheduled"
  },
  {
    id: "rm-003",
    client_id: "cl-002",
    client_name: "Harbor Studio Partners",
    deadline_id: "dl-002",
    tax_type: "PTE election",
    jurisdiction: "NY",
    step: 1,
    channel: "email",
    send_at: "2026-04-29T08:00:00",
    recipient: "evan@harborstudio.com",
    status: "scheduled"
  },
  {
    id: "rm-004",
    client_id: "cl-007",
    client_name: "Kestrel Consulting Group",
    deadline_id: "dl-012",
    tax_type: "Payroll (941)",
    jurisdiction: "Federal",
    step: 7,
    channel: "email",
    send_at: "2026-04-23T08:00:00",
    recipient: "owen@kestrelconsulting.com",
    status: "sent"
  },
  {
    id: "rm-005",
    client_id: "cl-008",
    client_name: "Maple Hill Dental Group",
    deadline_id: "dl-011",
    tax_type: "State income",
    jurisdiction: "MN",
    step: 7,
    channel: "email",
    send_at: "2026-04-24T08:00:00",
    recipient: "office@maplehilldental.com",
    status: "queued"
  },
  {
    id: "rm-006",
    client_id: "cl-003",
    client_name: "Sierra Wholesale Inc.",
    deadline_id: "dl-003",
    tax_type: "Franchise",
    jurisdiction: "TX",
    step: 14,
    channel: "email",
    send_at: "2026-05-01T08:00:00",
    recipient: "daniel@sierrawholesale.com",
    status: "scheduled"
  },
  {
    id: "rm-007",
    client_id: "cl-005",
    client_name: "Riverbend Manufacturing",
    deadline_id: "dl-018",
    tax_type: "Excise",
    jurisdiction: "OK",
    step: 14,
    channel: "inapp",
    send_at: "2026-04-26T07:00:00",
    recipient: "Sarah Johnson",
    status: "queued"
  },
  {
    id: "rm-008",
    client_id: "cl-012",
    client_name: "Aurora Tech Labs",
    deadline_id: "dl-023",
    tax_type: "Franchise",
    jurisdiction: "CA",
    step: 30,
    channel: "email",
    send_at: "2026-04-15T08:00:00",
    recipient: "reese@auroratech.io",
    status: "sent"
  },
  {
    id: "rm-009",
    client_id: "cl-009",
    client_name: "Glacier Outdoor Co.",
    deadline_id: "dl-008",
    tax_type: "Sales/Use",
    jurisdiction: "CO",
    step: 30,
    channel: "email",
    send_at: "2026-04-20T08:00:00",
    recipient: "tess@glacieroutdoor.com",
    status: "sent"
  },
  {
    id: "rm-010",
    client_id: "cl-006",
    client_name: "Atlas Logistics LLC",
    deadline_id: "dl-019",
    tax_type: "Excise",
    jurisdiction: "IL",
    step: 30,
    channel: "slack",
    send_at: "2026-04-25T08:00:00",
    recipient: "#atlas-logistics-tax",
    status: "sent"
  },
  {
    id: "rm-011",
    client_id: "cl-008",
    client_name: "Maple Hill Dental Group",
    deadline_id: "dl-020",
    tax_type: "Sales/Use",
    jurisdiction: "WI",
    step: 7,
    channel: "email",
    send_at: "2026-04-23T08:00:00",
    recipient: "office@maplehilldental.com",
    status: "sent"
  },
  {
    id: "rm-012",
    client_id: "cl-011",
    client_name: "Twin Pines Construction",
    deadline_id: "dl-013",
    tax_type: "Excise",
    jurisdiction: "OR",
    step: 7,
    channel: "email",
    send_at: "2026-04-23T08:00:00",
    recipient: "marco@twinpinesconstruction.com",
    status: "sent"
  }
];

// ---------- Rules (50-state DB sync output) ----------

export const mockRules: MockRule[] = [
  {
    id: "rule-001",
    title: "California PTE election deadline shifted",
    jurisdiction: "CA",
    source: "FTB Notice 2026-04",
    detected_at: "2026-04-25T11:42:00",
    affected_count: 8,
    status: "pending-review",
    summary:
      "California Franchise Tax Board pushed the 2026 PTE election deadline by 30 days. Eight clients with active PTE elections are affected.",
    diff_before: "PTE election due Apr 30, 2026",
    diff_after: "PTE election due May 30, 2026"
  },
  {
    id: "rule-002",
    title: "Texas sales tax economic-nexus threshold update",
    jurisdiction: "TX",
    source: "TX Comptroller 34-Tex.Admin.Code §3.286",
    detected_at: "2026-04-24T16:08:00",
    affected_count: 1,
    status: "pending-review",
    summary:
      "Threshold for remote-seller registration drops from $500K to $400K. One client (Sierra Wholesale) sits in the new band — review nexus before next filing.",
    diff_before: "Economic nexus threshold: $500,000 of TX-sourced sales / 12 mo",
    diff_after: "Economic nexus threshold: $400,000 of TX-sourced sales / 12 mo"
  },
  {
    id: "rule-003",
    title: "IRS extension granted for federally declared disaster — TX counties",
    jurisdiction: "Federal/TX",
    source: "IRS-DR-4801-TX",
    detected_at: "2026-04-23T09:15:00",
    affected_count: 2,
    status: "auto-applied",
    summary:
      "FEMA disaster declaration triggered an automatic federal-tax-deadline push to Sep 1 for taxpayers in 14 TX counties. Riverbend Manufacturing and Sierra Wholesale match.",
    diff_before: "Federal Form 1120 / 941 due as scheduled",
    diff_after: "Federal Form 1120 / 941 deadlines pushed to Sep 1, 2026"
  },
  {
    id: "rule-004",
    title: "Minnesota DOR — corporate franchise tax form revision",
    jurisdiction: "MN",
    source: "MN DOR Bulletin 2026-12",
    detected_at: "2026-04-22T13:50:00",
    affected_count: 1,
    status: "auto-applied",
    summary:
      "Form M4 revised; new Schedule M4-NPI replaces prior NOL line. Maple Hill Dental's filing template updated automatically.",
    diff_before: "M4 line 7: NOL deduction (consolidated)",
    diff_after: "M4 Schedule M4-NPI: NOL deduction itemized by year"
  },
  {
    id: "rule-005",
    title: "Oregon — construction excise rate adjustment",
    jurisdiction: "OR",
    source: "OR DOR Rate Notice 2026-Q2",
    detected_at: "2026-04-21T10:30:00",
    affected_count: 1,
    status: "pending-review",
    summary:
      "Construction excise tax rate moved from 0.7% to 0.85% effective Jul 1. Twin Pines Construction needs rate update on monthly templates.",
    diff_before: "Construction excise rate: 0.70%",
    diff_after: "Construction excise rate: 0.85% (eff. Jul 1, 2026)"
  }
];

// ---------- Blockers ----------

export const mockBlockers: MockBlocker[] = [
  {
    id: "blk-001",
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    deadline_label: "Q1 941 — due Apr 30",
    reason: "Payroll support documents missing for CA and TX",
    waiting_on: "Maya Chen (client contact)",
    asked_at: "2026-04-22",
    days_open: 4,
    next_step: "Send second follow-up email; if no reply by Apr 28, escalate to owner."
  },
  {
    id: "blk-002",
    client_id: "cl-002",
    client_name: "Harbor Studio Partners",
    deadline_label: "PTE election — due Apr 30",
    reason: "Home jurisdiction and election intent unconfirmed",
    waiting_on: "Evan Malik (client contact)",
    asked_at: "2026-04-19",
    days_open: 7,
    next_step: "Hop on a 15-min call this week to walk through PTE election trade-off."
  },
  {
    id: "blk-003",
    client_id: "cl-012",
    client_name: "Aurora Tech Labs",
    deadline_label: "CA Form 100 — due May 15",
    reason: "Prior-year return missing; cannot reconcile current-year NOL",
    waiting_on: "Reese Kim (client contact)",
    asked_at: "2026-04-15",
    days_open: 11,
    next_step: "Request prior CPA hand-off pack; offer to file 2848 for direct retrieval."
  }
];

// ---------- Activity feed ----------

export const mockActivity: MockActivity[] = [
  {
    id: "act-001",
    when: "2 hours ago",
    actor: "Sarah Johnson",
    action: "filed",
    detail: "Pinecone Dental Q1 941 — federal payroll",
    category: "filing"
  },
  {
    id: "act-002",
    when: "5 hours ago",
    actor: "DueDateHQ",
    action: "auto-applied rule",
    detail: "IRS-DR-4801-TX disaster extension applied to Sierra Wholesale and Riverbend",
    category: "rule"
  },
  {
    id: "act-003",
    when: "Yesterday, 4:12 PM",
    actor: "DueDateHQ",
    action: "sent reminder",
    detail: "Glacier Outdoor — 30-day notice for CO sales/use (May 20)",
    category: "reminder"
  },
  {
    id: "act-004",
    when: "Yesterday, 11:38 AM",
    actor: "Maya Chen",
    action: "logged blocker",
    detail: "Northwind Services — missing payroll docs",
    category: "filing"
  },
  {
    id: "act-005",
    when: "2 days ago",
    actor: "Sarah Johnson",
    action: "approved extension",
    detail: "Atlas Logistics — IL-1120 extension to Oct 15",
    category: "extension"
  },
  {
    id: "act-006",
    when: "2 days ago",
    actor: "DueDateHQ",
    action: "detected rule change",
    detail: "California PTE deadline shifted by 30 days",
    category: "rule"
  },
  {
    id: "act-007",
    when: "3 days ago",
    actor: "Owen Patel",
    action: "imported clients",
    detail: "Imported 3 new clients from Q1 onboarding CSV",
    category: "import"
  }
];

// ---------- Team ----------

export const mockTeam: MockTeamMember[] = [
  { id: "u-001", name: "Sarah Johnson", initials: "SJ", role: "Owner / CPA", email: "sarah@johnsoncpa.com", active_clients: 12 },
  { id: "u-002", name: "Maya Chen", initials: "MC", role: "Senior associate", email: "maya@johnsoncpa.com", active_clients: 7 },
  { id: "u-003", name: "Evan Malik", initials: "EM", role: "Tax associate", email: "evan@johnsoncpa.com", active_clients: 5 },
  { id: "u-004", name: "Owen Patel", initials: "OP", role: "Tax associate", email: "owen@johnsoncpa.com", active_clients: 4 },
  { id: "u-005", name: "Tara Wong", initials: "TW", role: "Practice admin", email: "tara@johnsoncpa.com", active_clients: 0 }
];

// ---------- Channels & integrations ----------

export const mockChannels: MockChannel[] = [
  {
    id: "ch-email",
    kind: "email",
    label: "Email",
    description: "Primary client touchpoint; default for 30/14/7/1 stepped reminders.",
    enabled: true,
    last_send: "Apr 25, 8:00 AM"
  },
  {
    id: "ch-sms",
    kind: "sms",
    label: "SMS",
    description: "Final-day nudge; only fires for the 1-day step.",
    enabled: true,
    last_send: "Apr 14, 8:00 AM"
  },
  {
    id: "ch-inapp",
    kind: "inapp",
    label: "In-app",
    description: "Internal-team reminder; never goes to clients.",
    enabled: true,
    last_send: "Apr 26, 7:00 AM"
  },
  {
    id: "ch-slack",
    kind: "slack",
    label: "Slack",
    description: "Send to a per-client channel when available.",
    enabled: true,
    last_send: "Apr 25, 8:00 AM"
  }
];

export const mockIntegrations: MockIntegration[] = [
  {
    id: "int-quickbooks",
    name: "QuickBooks Online",
    description: "Pulls client list and entity types nightly.",
    status: "connected",
    last_sync: "Today, 6:02 AM"
  },
  {
    id: "int-outlook",
    name: "Outlook calendar",
    description: "Mirrors deadlines onto each assignee's calendar.",
    status: "connected",
    last_sync: "Today, 7:14 AM"
  },
  {
    id: "int-slack",
    name: "Slack workspace",
    description: "Used for internal-team alerts and per-client channels.",
    status: "connected",
    last_sync: "Today, 7:14 AM"
  },
  {
    id: "int-twilio",
    name: "Twilio (SMS)",
    description: "Carrier for the 1-day SMS reminders.",
    status: "connected",
    last_sync: "Today, 7:14 AM"
  },
  {
    id: "int-drive",
    name: "Google Drive",
    description: "Stores generated CSV/PDF exports under a per-client folder.",
    status: "disconnected",
    last_sync: null
  }
];

// ---------- Exports ----------

export const mockExports: MockExportRecord[] = [
  { id: "ex-001", format: "pdf", scope: "All clients — Q2 deadline pack", generated_at: "Apr 25, 2:14 PM", size: "1.8 MB" },
  { id: "ex-002", format: "csv", scope: "Northwind Services — full deadline log", generated_at: "Apr 24, 11:02 AM", size: "32 KB" },
  { id: "ex-003", format: "pdf", scope: "Atlas Logistics — extension confirmation pack", generated_at: "Apr 22, 4:48 PM", size: "624 KB" },
  { id: "ex-004", format: "csv", scope: "All extensions filed YTD", generated_at: "Apr 18, 9:30 AM", size: "21 KB" }
];

// ---------- 50-state DB sync status ----------

export const mockSyncStatus: MockSyncStatus = {
  jurisdictions_covered: 51,
  jurisdictions_total: 51,
  last_full_sync: "Apr 26, 6:00 AM",
  next_scheduled_sync: "Apr 27, 6:00 AM",
  pending_rule_changes: 3,
  rules_auto_applied_today: 2,
  source_count: 84
};

// ---------- KPIs ----------

export const todayKpis: MockKPI[] = [
  {
    id: "kpi-due-this-week",
    label: "Due this week",
    value: 11,
    delta: "+3 vs last week",
    tone: "red",
    helper: "Active deadlines with due_date within 7 days."
  },
  {
    id: "kpi-blocked",
    label: "Blocked",
    value: 3,
    delta: "+1 since yesterday",
    tone: "gold",
    helper: "Deadlines waiting on client documents or confirmations."
  },
  {
    id: "kpi-extensions",
    label: "Extensions filed",
    value: 6,
    delta: "5 approved · 1 pending",
    tone: "blue",
    helper: "Total extension requests on the books for this fiscal year."
  },
  {
    id: "kpi-clients",
    label: "Active clients",
    value: 12,
    delta: "0 churn this month",
    tone: "green",
    helper: "Clients with at least one open deadline."
  }
];

// ---------- Filter option lists ----------

export const stateOptions = ["All", "CA", "TX", "NY", "NJ", "WA", "MN", "WI", "IL", "IN", "OH", "MI", "MA", "NH", "CO", "UT", "ID", "OR", "FL", "OK", "LA", "NV", "AZ"];
export const taxTypeOptions: Array<"All" | TaxType> = [
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
export const urgencyOptions: Array<"All" | Urgency> = ["All", "urgent", "medium", "low"];
export const quickViewOptions = [
  { id: "due-this-week", label: "Due this week", days: 7 },
  { id: "due-this-month", label: "Due this month", days: 30 },
  { id: "danger-zone", label: "Danger zone (≤3 days)", days: 3 },
  { id: "extensions", label: "Extensions filed", days: 365 }
] as const;

// ---------- Derived helpers ----------

export function urgencyOf(deadline: MockDeadline): Urgency {
  if (deadline.status === "blocked" || deadline.days_remaining <= 3) return "urgent";
  if (deadline.days_remaining <= 14) return "medium";
  return "low";
}

export function statusBadgeLabel(deadline: MockDeadline): string {
  if (deadline.status === "completed") return "Completed";
  if (deadline.status === "blocked") return "Blocked";
  if (deadline.status === "extension-approved") return "Extension approved";
  if (deadline.status === "extension-filed") return "Extension filed";
  if (deadline.days_remaining <= 0) return "Overdue";
  return "Active";
}

export function statusBadgeTone(deadline: MockDeadline): "urgent" | "medium" | "low" | "green" | "blue" {
  if (deadline.status === "completed") return "green";
  if (deadline.status === "extension-approved" || deadline.status === "extension-filed") return "blue";
  return urgencyOf(deadline);
}

export function groupDeadlinesByWeek(deadlines: MockDeadline[]): Array<{
  weekKey: string;
  weekLabel: string;
  items: MockDeadline[];
}> {
  const groups = new Map<string, MockDeadline[]>();
  deadlines.forEach((deadline) => {
    const date = new Date(`${deadline.due_date}T00:00:00`);
    // Get Monday of that week
    const day = date.getDay();
    const monday = new Date(date);
    monday.setDate(date.getDate() - ((day + 6) % 7));
    const key = monday.toISOString().slice(0, 10);
    const bucket = groups.get(key) || [];
    bucket.push(deadline);
    groups.set(key, bucket);
  });
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([weekKey, items]) => {
      const monday = new Date(`${weekKey}T00:00:00`);
      const sunday = new Date(monday);
      sunday.setDate(monday.getDate() + 6);
      const fmt = (d: Date) =>
        d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      return {
        weekKey,
        weekLabel: `Week of ${fmt(monday)} — ${fmt(sunday)}`,
        items: items.sort((a, b) => a.due_date.localeCompare(b.due_date))
      };
    });
}

export function reminderStepLabel(step: ReminderStep): string {
  if (step === 30) return "30-day notice";
  if (step === 14) return "14-day check-in";
  if (step === 7) return "7-day reminder";
  return "Final-day push";
}

export function channelLabel(kind: ChannelKind): string {
  if (kind === "email") return "Email";
  if (kind === "sms") return "SMS";
  if (kind === "inapp") return "In-app";
  return "Slack";
}

// ---------- Triage buckets (Today portfolio board) ----------
//
// The 4 buckets give the firm one place to triage every active deadline
// across every client. Each deadline is in exactly one bucket.
//
//   Notice          → needs attention NOW. (a) overdue, (b) ≤ 3 days out,
//                     or (c) a pending-review rule is reshaping how it
//                     should be filed.
//   Waiting on info → blocked on the client. Status=blocked.
//   Track           → active firm work, normal pace (4–30 days out,
//                     status=pending, not blocked, no rule notice).
//   Watchlist       → already extended, completed, or > 30 days out.
//
// Completed deadlines are intentionally hidden from the board — they
// belong to history, not today.

export type TriageBucket = "notice" | "waiting" | "track" | "watchlist";

export const mockRulesById: Record<string, MockRule> = Object.fromEntries(
  mockRules.map((r) => [r.id, r])
);

export function bucketOfDeadline(d: MockDeadline): TriageBucket | "completed" {
  if (d.status === "completed") return "completed";
  if (d.status === "blocked") return "waiting";
  if (d.notice_rule_id) return "notice";
  if (d.status === "extension-filed" || d.status === "extension-approved") return "watchlist";
  if (d.days_remaining < 0) return "notice";
  if (d.days_remaining <= 3) return "notice";
  if (d.days_remaining <= 30) return "track";
  return "watchlist";
}

export function noticeReason(d: MockDeadline): string {
  if (d.notice_rule_id) {
    const rule = mockRulesById[d.notice_rule_id];
    if (rule) return `Rule change: ${rule.title}`;
    return "Rule change pending review";
  }
  if (d.days_remaining < 0) return `${Math.abs(d.days_remaining)}d overdue`;
  if (d.days_remaining === 0) return "Due today";
  if (d.days_remaining === 1) return "Due tomorrow";
  if (d.days_remaining <= 3) return `Danger zone — ${d.days_remaining}d out`;
  return "Needs review";
}

export type TriageBucketMeta = {
  id: TriageBucket;
  title: string;
  helper: string;
  tone: "red" | "gold" | "ink" | "blue";
};

export const triageBucketMeta: Record<TriageBucket, TriageBucketMeta> = {
  notice: {
    id: "notice",
    title: "Notice",
    helper: "Overdue, in the danger zone, or reshaped by a pending rule change. Look here first.",
    tone: "red"
  },
  waiting: {
    id: "waiting",
    title: "Waiting on info",
    helper: "Blocked until the client sends documents or confirms a decision.",
    tone: "gold"
  },
  track: {
    id: "track",
    title: "Track",
    helper: "Active firm work moving on schedule. No special attention required.",
    tone: "ink"
  },
  watchlist: {
    id: "watchlist",
    title: "Watchlist",
    helper: "Extended, far out, or otherwise just being monitored.",
    tone: "blue"
  }
};

export const triageOrder: TriageBucket[] = ["notice", "waiting", "track", "watchlist"];

export type TriageCounts = Record<TriageBucket, number>;

export function triageCounts(deadlines: MockDeadline[]): TriageCounts {
  const counts: TriageCounts = { notice: 0, waiting: 0, track: 0, watchlist: 0 };
  deadlines.forEach((d) => {
    const b = bucketOfDeadline(d);
    if (b !== "completed") counts[b] += 1;
  });
  return counts;
}
