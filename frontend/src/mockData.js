export const navItems = [
  { id: "dashboard", label: "Dashboard" },
  { id: "clients", label: "Clients" },
  { id: "import", label: "Import" },
  { id: "notices", label: "Notices" },
  { id: "calendar", label: "Calendar" },
  { id: "rules", label: "Rules" }
];

export const clientRecords = [
  {
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    entity_type: "LLC",
    home_jurisdiction: "CA",
    registered_states: ["CA", "NV"],
    intake_status: "Needs follow-up",
    risk_label: "High",
    next_deadline: "Apr 22",
    contact_name: "Maya Chen",
    preferred_channel: "Email",
    portfolio_note:
      "Payroll documents are still missing, so the main risk this week is operational follow-up.",
    annual_profile: {
      tax_year: 2026,
      payroll_present: true,
      estimated_tax_required: false,
      extension_status: "Not started"
    },
    deadlines: [
      {
        deadline_id: "dl-001",
        tax_type: "Q1 payroll filing",
        jurisdiction: "CA",
        due_date: "2026-04-22",
        days_remaining: 4,
        status: "Waiting on documents",
        available_actions: ["complete", "snooze", "override"]
      },
      {
        deadline_id: "dl-008",
        tax_type: "Quarterly payroll report",
        jurisdiction: "CA",
        due_date: "2026-04-24",
        days_remaining: 6,
        status: "Pending",
        available_actions: ["complete", "snooze"]
      }
    ],
    activity: [
      "Apr 18 · AI flagged payroll docs as missing from the imported spreadsheet.",
      "Apr 17 · CPA confirmed Nevada registration is still active.",
      "Apr 16 · Reminder queue rebuilt after due date refresh."
    ]
  },
  {
    client_id: "cl-002",
    client_name: "Harbor Studio Partners",
    entity_type: "Partnership",
    home_jurisdiction: "NY",
    registered_states: ["NY"],
    intake_status: "In progress",
    risk_label: "Watch",
    next_deadline: "Apr 24",
    contact_name: "Evan Malik",
    preferred_channel: "SMS",
    portfolio_note:
      "The filing itself is straightforward. The uncertainty is whether the owners want to opt in this year.",
    annual_profile: {
      tax_year: 2026,
      payroll_present: false,
      estimated_tax_required: false,
      extension_status: "Considering"
    },
    deadlines: [
      {
        deadline_id: "dl-002",
        tax_type: "PTE election review",
        jurisdiction: "NY",
        due_date: "2026-04-24",
        days_remaining: 6,
        status: "Needs CPA decision",
        available_actions: ["snooze", "override", "waive"]
      },
      {
        deadline_id: "dl-009",
        tax_type: "Partnership filing",
        jurisdiction: "NY",
        due_date: "2026-05-15",
        days_remaining: 27,
        status: "Pending",
        available_actions: ["complete", "override"]
      }
    ],
    activity: [
      "Apr 19 · Imported owner memo suggests PTE may be beneficial this year.",
      "Apr 18 · Missing field follow-up drafted for home jurisdiction confirmation.",
      "Apr 17 · Client profile created from spreadsheet import."
    ]
  },
  {
    client_id: "cl-003",
    client_name: "Sierra Wholesale Inc.",
    entity_type: "C-Corp",
    home_jurisdiction: "TX",
    registered_states: ["TX", "CA"],
    intake_status: "Ready",
    risk_label: "Watch",
    next_deadline: "Apr 30",
    contact_name: "Lena Ortiz",
    preferred_channel: "Email",
    portfolio_note:
      "The business is broadly on track, but a recent notice may create a new California obligation if nexus is confirmed.",
    annual_profile: {
      tax_year: 2026,
      payroll_present: true,
      estimated_tax_required: true,
      extension_status: "Not started"
    },
    deadlines: [
      {
        deadline_id: "dl-003",
        tax_type: "Franchise tax notice",
        jurisdiction: "TX",
        due_date: "2026-04-30",
        days_remaining: 12,
        status: "Pending",
        available_actions: ["complete", "override"]
      }
    ],
    activity: [
      "Apr 20 · California notice linked to client for manual review.",
      "Apr 18 · Estimated tax cadence confirmed from prior-year profile.",
      "Apr 17 · Intake profile marked ready."
    ]
  }
];

export const dashboardData = {
  section_meta: {
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
  },
  stats: [
    { label: "Open deadlines", value: "11", tone: "neutral" },
    { label: "Need review", value: "3", tone: "review" },
    { label: "Waiting on info", value: "2", tone: "critical" },
    { label: "Safe auto-updates", value: "5", tone: "success" }
  ],
  triage_queue: [
    {
      task_id: "task-001",
      client_id: "cl-001",
      client_name: "Northwind Services LLC",
      title: "Follow up on payroll filing package",
      due_at: "Apr 22",
      status: "Open",
      priority: "Critical",
      task_type: "follow_up",
      source_type: "blocker",
      source_id: "blocker-northwind-payroll"
    },
    {
      task_id: "task-002",
      client_id: "cl-002",
      client_name: "Harbor Studio Partners",
      title: "Review PTE election decision",
      due_at: "Apr 24",
      status: "Open",
      priority: "Review",
      task_type: "review",
      source_type: "deadline",
      source_id: "dl-002"
    },
    {
      task_id: "task-003",
      client_id: "cl-003",
      client_name: "Sierra Wholesale Inc.",
      title: "Check California notice impact",
      due_at: "Apr 30",
      status: "Open",
      priority: "Upcoming",
      task_type: "review",
      source_type: "notice",
      source_id: "notice-002"
    }
  ],
  waiting_on_info: [
    {
      client_id: "cl-001",
      client_name: "Northwind Services LLC",
      reason: "Payroll support documents missing",
      requested_from: "Maya Chen",
      next_step: "Draft a short email requesting payroll support docs before Apr 22."
    },
    {
      client_id: "cl-002",
      client_name: "Harbor Studio Partners",
      reason: "Home state and extension intent still unconfirmed",
      requested_from: "Evan Malik",
      next_step: "Confirm home jurisdiction and whether the partners want extension planning."
    }
  ],
  notice_watchlist: [
    {
      notice_id: "notice-001",
      title: "California extension update detected",
      summary: "Affects eight clients. Two still require human review before updating dates.",
      affected_count: 8,
      next_step: "Review the two California clients before bulk-updating deadline dates."
    },
    {
      notice_id: "notice-002",
      title: "Texas nexus threshold clarification",
      summary: "Could expand California filing scope for one importer client.",
      affected_count: 1,
      next_step: "Check whether Sierra's California footprint is strong enough to create a new filing."
    }
  ],
  client_watchlist: [
    {
      client_id: "cl-001",
      client_name: "Northwind Services LLC",
      risk_label: "High",
      headline: "Payroll filing is due soon and documents are still missing.",
      why_it_matters: "This is the closest deadline in the portfolio and it is still blocked.",
      next_step: "Escalate the document request or decide whether to remind later."
    },
    {
      client_id: "cl-002",
      client_name: "Harbor Studio Partners",
      risk_label: "Watch",
      headline: "PTE election may change this year's strategy.",
      why_it_matters: "The deadline is not the earliest, but the CPA decision affects filing approach.",
      next_step: "Review the owner memo and confirm whether the election should stay on the queue."
    },
    {
      client_id: "cl-003",
      client_name: "Sierra Wholesale Inc.",
      risk_label: "Watch",
      headline: "A Texas notice may create a California obligation.",
      why_it_matters: "A notice-driven change could add work that is not yet reflected as a final deadline.",
      next_step: "Open the notice and confirm whether nexus rules should change this account."
    }
  ]
};

export const importDraft = {
  source_name: "q2-client-portfolio.xlsx",
  source_kind: "Spreadsheet import",
  imported_rows: 43,
  summary:
    "Most firms already maintain some version of this spreadsheet. The product should start here, normalize it, and only ask for the fields that are truly missing.",
  mappings: [
    { target_field: "Client name", source_column: "Client Name", confidence: 0.98, status: "Mapped" },
    { target_field: "Entity type", source_column: "Entity / Return Type", confidence: 0.94, status: "Mapped" },
    { target_field: "Operating states", source_column: "State Footprint", confidence: 0.9, status: "Mapped" },
    { target_field: "Home jurisdiction", source_column: "", confidence: 0, status: "Needs follow-up" },
    { target_field: "Payroll states", source_column: "Payroll States", confidence: 0.86, status: "Mapped" }
  ],
  missing_fields: [
    "Confirm Harbor Studio Partners home jurisdiction",
    "Decide whether Harbor should be considered for extension planning",
    "Upload payroll support docs for Northwind Services LLC"
  ],
  extra_columns: ["Partner note", "Custom service tier", "Special remark"],
  sample_rows: [
    ["Northwind Services LLC", "LLC", "CA, NV", "CA"],
    ["Harbor Studio Partners", "Partnership", "NY", "—"],
    ["Sierra Wholesale Inc.", "C-Corp", "TX, CA", "TX"]
  ]
};

export const notices = [
  {
    notice_id: "notice-001",
    source_label: "California Franchise Tax Board",
    source_url: "https://ftb.ca.gov/",
    status: "Needs review",
    title: "California extension update detected",
    summary:
      "This source is verified, but county coverage is not universal, so two clients should stay in manual review.",
    affected_clients: [
      {
        client_name: "Sunset Retail Group",
        client_id: "cl-004",
        old_date: "2026-04-30",
        new_date: "2026-10-15",
        auto_updated: true
      },
      {
        client_name: "Northwind Services LLC",
        client_id: "cl-001",
        old_date: "2026-04-22",
        new_date: "2026-10-15",
        auto_updated: false
      }
    ]
  },
  {
    notice_id: "notice-002",
    source_label: "Texas Comptroller",
    source_url: "https://comptroller.texas.gov/",
    status: "Queued",
    title: "Texas nexus threshold clarification",
    summary:
      "The rule text is clear, but the impacted-client set still needs confirmation because imported state footprints are incomplete.",
    affected_clients: [
      {
        client_name: "Sierra Wholesale Inc.",
        client_id: "cl-003",
        old_date: "2026-04-30",
        new_date: "2026-05-08",
        auto_updated: false
      }
    ]
  }
];

export const calendarMonth = {
  label: "April 2026",
  days: [
    { date: "Mon 20", items: [] },
    { date: "Tue 21", items: [] },
    { date: "Wed 22", items: ["Northwind · Q1 payroll filing"] },
    { date: "Thu 23", items: [] },
    { date: "Fri 24", items: ["Harbor · PTE election review", "Northwind · Quarterly payroll report"] },
    { date: "Mon 27", items: [] },
    { date: "Tue 28", items: [] },
    { date: "Wed 29", items: [] },
    { date: "Thu 30", items: ["Sierra · Franchise tax notice"] },
    { date: "Fri 01", items: ["Northwind · NV franchise tax"] }
  ]
};

export const rulesWorkspace = {
  rule_templates: [
    {
      name: "State filing deadline template",
      scope: "Entity type + jurisdiction + tax type",
      status: "Active"
    },
    {
      name: "Reminder cadence",
      scope: "30 / 14 / 7 / 1 day reminders",
      status: "Active"
    },
    {
      name: "Import mapping defaults",
      scope: "Common spreadsheet column aliases",
      status: "Draft"
    }
  ],
  review_queue: [
    "California extension update still needs county-level review",
    "Texas notice may create a new CA filing obligation",
    "Payroll states missing for two imported clients"
  ]
};

export const pagePrompts = {
  dashboard: [
    "Show me what needs attention this week",
    "Open the riskiest client",
    "What notices need review?"
  ],
  clients: [
    "Open Harbor Studio Partners",
    "Which clients are waiting on information?",
    "Show ready clients only"
  ],
  client: [
    "What is blocking this client?",
    "Show allowed actions",
    "Summarize this account for handoff"
  ],
  import: [
    "Review imported spreadsheet",
    "Show missing fields",
    "Generate dashboard from imported data"
  ],
  notices: [
    "What changed today?",
    "Open California extension notice",
    "Which clients were auto-updated?"
  ],
  calendar: [
    "What is due this month?",
    "Show April deadlines",
    "Which week is busiest?"
  ],
  rules: [
    "What rules need review?",
    "Show reminder cadence",
    "Open import mapping defaults"
  ]
};

export function getClientById(clientId) {
  return clientRecords.find((client) => client.client_id === clientId) || clientRecords[0];
}

export function getNoticeById(noticeId) {
  return notices.find((notice) => notice.notice_id === noticeId) || notices[0];
}
