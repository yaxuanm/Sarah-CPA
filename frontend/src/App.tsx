import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { bootstrapToday, executeAction, streamChat } from "./apiClient";
import { validateRenderSpec } from "./renderSpec";
import type { ActionPlan, ChatMessage, DirectAction, RenderBlock, RenderSpec, TaskItem, ViewEnvelope, VisualContext } from "./types";

const tenantId = import.meta.env.VITE_DUEDATEHQ_TENANT_ID || "2403c5e1-85ac-4593-86cc-02f8d97a8d92";
const apiBase = import.meta.env.VITE_DUEDATEHQ_API_BASE || "http://127.0.0.1:8000";
const initialView: ViewEnvelope = {
  type: "GuidanceCard",
  data: {
    message: "Opening today's work."
  },
  selectable_items: []
};
const initialActions: ActionPlan[] = [];
const defaultTopActions = [
  { label: "Dashboard", kind: "dashboard" as const },
  { label: "Workspace", kind: "workspace" as const },
  { label: "Import", kind: "import" as const },
  { label: "Notices", prompt: "Show notice review" }
];
const helpItems = [
  "Start with Today to review the current work queue.",
  "Open a client when you need detail before making a decision.",
  "Use Import when you need to map incoming spreadsheet data.",
  "Use Notices when a policy change needs review before it becomes work."
];
const dashboardSectionMeta = {
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
const dashboardWaitingSeed = [
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
const dashboardNoticeSeed = [
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
const dashboardWatchSeed = [
  {
    client_id: "cl-001",
    client_name: "Northwind Services LLC",
    risk_label: "High",
    headline: "Payroll filing is due soon and documents are still missing.",
    why_it_matters: "This is the closest deadline in the portfolio and it is still blocked.",
    next_step: "Escalate the document request or decide whether to remind later.",
    due_label: "Apr 22",
    date_iso: "2026-04-22"
  },
  {
    client_id: "cl-002",
    client_name: "Harbor Studio Partners",
    risk_label: "Watch",
    headline: "PTE election may change this year's strategy.",
    why_it_matters: "The deadline is not the earliest, but the CPA decision affects filing approach.",
    next_step: "Review the owner memo and confirm whether the election should stay on the queue.",
    due_label: "Apr 24",
    date_iso: "2026-04-24"
  },
  {
    client_id: "cl-003",
    client_name: "Sierra Wholesale Inc.",
    risk_label: "Watch",
    headline: "A Texas notice may create a California obligation.",
    why_it_matters: "A notice-driven change could add work that is not yet reflected as a final deadline.",
    next_step: "Open the notice and confirm whether nexus rules should change this account.",
    due_label: "May 03",
    date_iso: "2026-05-03"
  }
];

function id(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

function todayPlan(): Record<string, unknown> {
  return {
    plan: [
      {
        step_id: "s1",
        type: "cli_call",
        cli_group: "today",
        cli_command: "today",
        args: { tenant_id: tenantId, limit: 5, enrich: true }
      }
    ],
    intent_label: "today",
    op_class: "read"
  };
}

function deadlineHistoryPlan(deadlineId: string): Record<string, unknown> {
  return {
    plan: [
      {
        step_id: "s1",
        type: "cli_call",
        cli_group: "deadline",
        cli_command: "transitions",
        args: { tenant_id: tenantId, deadline_id: deadlineId }
      }
    ],
    intent_label: "deadline_history",
    op_class: "read"
  };
}

export function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: id(), role: "status", text: String(initialView.data.message) }
  ]);
  const [view, setView] = useState<ViewEnvelope>(initialView);
  const [dashboardSeedView, setDashboardSeedView] = useState<ViewEnvelope | null>(null);
  const [actions, setActions] = useState<ActionPlan[]>(initialActions);
  const [seenVisualContexts, setSeenVisualContexts] = useState<VisualContext[]>([
    summarizeView(initialView, initialActions)
  ]);
  const [input, setInput] = useState("");
  const [session, setSession] = useState<Record<string, unknown>>({
    tenant_id: tenantId,
    session_id: "frontend-validation-session",
    today: "2025-05-15"
  });
  const [busy, setBusy] = useState(false);
  const [apiBootstrapped, setApiBootstrapped] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [backendState, setBackendState] = useState<"connecting" | "ready" | "degraded">("connecting");
  const [shellMode, setShellMode] = useState<"dashboard" | "workspace" | "import">("dashboard");
  const streamRef = useRef<HTMLDivElement | null>(null);
  const helpRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const context = summarizeView(view, actions);
    setSeenVisualContexts((current) => [
      context,
      ...current.filter((item) => item.summary !== context.summary)
    ].slice(0, 8));
  }, [view, actions]);

  useEffect(() => {
    if (view.type === "ListCard") {
      setDashboardSeedView(view);
    }
  }, [view]);

  useEffect(() => {
    if (apiBootstrapped) return;
    setApiBootstrapped(true);
    void loadBackendOverview();
  }, [apiBootstrapped]);

  useEffect(() => {
    function handlePointer(event: MouseEvent) {
      if (!helpRef.current?.contains(event.target as Node)) {
        setHelpOpen(false);
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setHelpOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointer);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handlePointer);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  function scrollStream() {
    requestAnimationFrame(() => {
      streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight, behavior: "smooth" });
    });
  }

  function append(role: ChatMessage["role"], text: string) {
    const messageId = id();
    setMessages((current) => [...current, { id: messageId, role, text }]);
    scrollStream();
    return messageId;
  }

  function appendToMessage(messageId: string, text: string) {
    setMessages((current) =>
      current.map((message) =>
        message.id === messageId ? { ...message, text: `${message.text}${text}` } : message
      )
    );
    scrollStream();
  }

  function replaceMessage(messageId: string, text: string) {
    setMessages((current) =>
      current.map((message) =>
        message.id === messageId ? { ...message, text } : message
      )
    );
    scrollStream();
  }

  async function submit(value = input, userEcho?: string) {
    const cleaned = value.trim();
    if (!cleaned || busy) return;
    setShellMode("workspace");
    setInput("");
    append("user", userEcho?.trim() || cleaned);

    setBusy(true);
    let streamedMessageId: string | null = null;
    let thinkingMessageId: string | null = null;
    try {
      const nextSession = await streamChat({
        apiBase,
        userInput: cleaned,
        tenantId,
        session: {
          ...session,
          current_view: view,
          visual_context: summarizeView(view, actions),
          seen_visual_contexts: seenVisualContexts.slice(0, 6)
        },
        onUpdate: (update) => {
          if (update.event === "thinking") {
            if (thinkingMessageId) {
              replaceMessage(thinkingMessageId, update.message);
            } else {
              thinkingMessageId = append("status", update.message);
            }
            return;
          }
          if (update.event === "intent_confirmed") {
            const message = humanIntentStatus(update.intentLabel, update.planSource);
            if (thinkingMessageId) {
              replaceMessage(thinkingMessageId, message);
            } else {
              thinkingMessageId = append("status", message);
            }
          }
          if (update.event === "view_rendered") {
            if (thinkingMessageId) {
              replaceMessage(thinkingMessageId, "The next workspace is ready.");
            }
            if (update.view) setView(update.view);
            setActions(update.actions || []);
          }
          if (update.event === "feedback_recorded") {
            if (update.signal === "correction") {
              append("status", "I'll use that correction next time.");
            }
          }
          if (update.event === "message_delta" && update.delta) {
            streamedMessageId ??= append("system", "");
            appendToMessage(streamedMessageId, update.delta);
          }
          if (update.event === "done" && update.response?.message && !streamedMessageId) {
            append("system", update.response.message);
          }
        }
      });
      setSession(nextSession);
      setBackendState("ready");
    } catch (error) {
      setBackendState("degraded");
      append("system", `The AI backend is unavailable. No records were changed. Please confirm FastAPI is running, then try again. ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runDirectAction(action: DirectAction, userEcho?: string) {
    if (busy) return;
    setShellMode("workspace");
    if (action.type === "agent_input" && action.text) {
      await submit(action.text, userEcho);
      return;
    }
    if (action.type !== "direct_execute") return;

    append("user", userEcho?.trim() || describeDirectAction(action));

    if (action.view_data && action.expected_view) {
      const nextView = {
        type: action.expected_view,
        data: action.view_data,
        selectable_items: action.selectable_items || []
      };
      const previousWorkspace = session.current_workspace || null;
      const nextWorkspace = action.workspace || buildWorkspaceSnapshot(nextView);
      const currentBreadcrumb = Array.isArray(session.breadcrumb) ? session.breadcrumb : [];
      const nextBreadcrumb = nextWorkspace
        ? appendBreadcrumb(currentBreadcrumb, String(nextWorkspace.type || nextView.type))
        : currentBreadcrumb;
      setView(nextView);
      setActions([]);
      setSession((current) => ({
        ...current,
        previous_workspace: previousWorkspace,
        current_workspace: nextWorkspace,
        breadcrumb: nextBreadcrumb,
        current_view: nextView,
        selectable_items: nextView.selectable_items,
        current_actions: []
      }));
      append("status", "Opened.");
      return;
    }

    setBusy(true);
    try {
      const result = await executeAction({
        apiBase,
        tenantId,
        session: {
          ...session,
          current_view: view,
          visual_context: summarizeView(view, actions),
          seen_visual_contexts: seenVisualContexts.slice(0, 6)
        },
        action
      });
      if (result.response.view) setView(result.response.view);
      setActions(result.response.actions || []);
      setSession(result.session);
      setBackendState("ready");
      if (result.response.message) append("system", result.response.message);
    } catch (error) {
      setBackendState("degraded");
      append("system", `That action could not be completed. No records were changed. ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function loadBackendOverview() {
    setBusy(true);
    try {
      const result = await bootstrapToday({
        apiBase,
        tenantId,
        session: {
          ...session,
          current_view: view
        }
      });
      if (result.response.view) setView(result.response.view);
      setActions(result.response.actions || []);
      setSession(result.session);
      setBackendState("ready");
      setMessages([{ id: id(), role: "system", text: result.response.message || "Today's work is open." }]);
    } catch (error) {
      setBackendState("degraded");
      append("system", `Couldn't load today's work from the backend. ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function openToday() {
    setShellMode("workspace");
    void runDirectAction(
      {
        type: "direct_execute",
        expected_view: "ListCard",
        plan: todayPlan()
      },
      "Open today's work"
    );
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  const quickActions = buildQuickActions(view, actions);
  const topbarActions = defaultTopActions;
  const statusLabel =
    backendState === "ready"
      ? "Live backend"
      : backendState === "degraded"
        ? "Backend issue"
        : "Connecting";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">DueDate<em>HQ</em></div>
        <div className="topbar-right">
          <div className="topbar-actions">
            {topbarActions.map((action) => (
              <button
                key={action.label}
                className={`quick-btn topbar-btn ${("kind" in action && action.kind === shellMode) ? "active" : ""}`}
                onClick={() => {
                  if ("kind" in action && action.kind === "dashboard") {
                    setShellMode("dashboard");
                    return;
                  }
                  if ("kind" in action && action.kind === "workspace") {
                    setShellMode("workspace");
                    return;
                  }
                  if ("kind" in action && action.kind === "import") {
                    setShellMode("import");
                    return;
                  }
                  if ("prompt" in action && action.prompt) {
                    void submit(action.prompt, action.label);
                  }
                }}
              >
                {action.label}
              </button>
            ))}
            <div className="help-shell" ref={helpRef}>
              <button
                className="help-trigger"
                type="button"
                aria-expanded={helpOpen}
                aria-label="Open help"
                onClick={() => setHelpOpen((current) => !current)}
              >
                ?
              </button>
              {helpOpen ? (
                <div className="help-menu">
                  <div className="eyebrow">How to use this</div>
                  <h3>Use the workspace in this order</h3>
                  <ul>
                    {helpItems.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </div>
          <div className="tenant-name">Johnson CPA PLLC</div>
          <div className={`connection-pill ${backendState}`}>{statusLabel}</div>
          <div className="avatar">SJ</div>
        </div>
      </header>

      <main className={shellMode === "workspace" ? "workspace" : "workspace workspace--wide"}>
        {shellMode === "workspace" ? (
          <aside className="conv-panel">
            <div className="conv-header">
              <div className="conv-header-label">Conversation</div>
              <div className="conv-header-date">Sarah's work queue</div>
            </div>
            <button
              className="dashboard-entry"
              type="button"
              onClick={() => setShellMode("dashboard")}
            >
              <div className="eyebrow">Task board</div>
              <strong>Open cross-state dashboard</strong>
              <span>Go from conversation into the full portfolio board.</span>
            </button>
            <div className="stream" ref={streamRef}>
              {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
            </div>
            <div className="quick-actions-label">Suggested next steps</div>
            <div className="quick-actions">
              {quickActions.map((action) => (
                <button
                  key={action.label}
                  className="quick-btn"
                  onClick={() => action.action ? void runDirectAction(action.action, action.label) : void submit(action.prompt || action.label, action.label)}
                >
                  {action.label}
                </button>
              ))}
            </div>
            <form className="composer" onSubmit={onSubmit}>
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask DueDateHQ what to do next"
              />
              <button type="submit" disabled={busy}>{busy ? "..." : "Send"}</button>
            </form>
          </aside>
        ) : null}

        <section className="render-panel">
          <div className="surface-meta">
            <div>
              <div className="eyebrow">{shellMode === "dashboard" ? "Dashboard" : shellMode === "import" ? "Import" : "Current workspace"}</div>
              <h1>{shellMode === "dashboard" ? "Cross-state task board" : shellMode === "import" ? "Import client data" : surfaceTitle(view)}</h1>
              <p className="surface-summary">
                {shellMode === "dashboard"
                  ? "See deadlines, blockers, notices, and watchlist items across the full client portfolio."
                  : shellMode === "import"
                    ? "Upload a client file, confirm the mapping, resolve missing information, and generate the dashboard."
                  : surfaceSummary(view)}
              </p>
            </div>
            <div className="status-pills">
              <span className={`pill ${backendState === "ready" ? "green" : backendState === "degraded" ? "red" : "gold"}`}>{statusLabel}</span>
              <span className="pill blue">{shellMode === "dashboard" ? "Dashboard" : shellMode === "import" ? "Import" : view.type}</span>
            </div>
          </div>
          {shellMode === "dashboard" ? (
            <DashboardSurface
              view={dashboardSeedView || view}
              seenVisualContexts={seenVisualContexts}
            />
          ) : shellMode === "import" ? (
            <ImportSurface />
          ) : (
            <ViewRenderer view={view} onPrompt={(prompt) => void submit(prompt)} onAction={(action, label) => void runDirectAction(action, label)} />
          )}
        </section>
      </main>
    </div>
  );
}

function ImportSurface() {
  const [step, setStep] = useState<"file" | "mapping" | "missing" | "ready">("file");
  const [importMessage, setImportMessage] = useState(
    "Use this page to review a client file before creating records and work items."
  );

  return (
    <div className="import-surface">
      <section className="card import-card">
        <div className="card-header">
          <div>
            <div className="eyebrow">Client import</div>
            <h2>Bring in a client spreadsheet</h2>
            <p className="card-description">
              Choose a file, review the mapping, resolve missing information, and generate the dashboard.
            </p>
          </div>
          <span className="pill gold">Step {step === "file" ? "1" : step === "mapping" ? "2" : step === "missing" ? "3" : "4"}</span>
        </div>

        <div className="import-steps">
          <button className={`import-step ${step === "file" ? "active" : ""}`} onClick={() => setStep("file")}>Choose file</button>
          <button className={`import-step ${step === "mapping" ? "active" : ""}`} onClick={() => setStep("mapping")}>Confirm mapping</button>
          <button className={`import-step ${step === "missing" ? "active" : ""}`} onClick={() => setStep("missing")}>Resolve missing fields</button>
          <button className={`import-step ${step === "ready" ? "active" : ""}`} onClick={() => setStep("ready")}>Generate dashboard</button>
        </div>

        {step === "file" ? (
          <div className="import-section">
            <div className="import-dropzone">
              <strong>client-portfolio.csv</strong>
              <span>Upload or drag a spreadsheet here. DueDateHQ will analyze the columns before anything is written.</span>
            </div>
            <div className="action-bar">
              <button className="primary" onClick={() => setStep("mapping")}>Preview mapping</button>
              <button className="secondary">Download sample CSV</button>
            </div>
          </div>
        ) : null}

        {step === "mapping" ? (
          <div className="import-section">
            <div className="import-grid">
              <div className="import-panel">
                <div className="eyebrow">Detected mapping</div>
                <div className="plain-row"><strong>Client name</strong><span>client_name</span></div>
                <div className="plain-row"><strong>Entity type</strong><span>entity_type</span></div>
                <div className="plain-row"><strong>State footprint</strong><span>registered_states</span></div>
                <div className="plain-row"><strong>Primary contact</strong><span>contact_email</span></div>
              </div>
              <div className="import-panel">
                <div className="eyebrow">Needs review</div>
                <div className="plain-row"><strong>Payroll state</strong><span>Column not found</span></div>
                <div className="plain-row"><strong>Extension status</strong><span>Column not found</span></div>
                <div className="plain-row"><strong>Tax year</strong><span>Ask once during import</span></div>
              </div>
            </div>
            <div className="action-bar">
              <button className="primary" onClick={() => setStep("missing")}>Continue</button>
              <button className="secondary" onClick={() => setStep("file")}>Back</button>
            </div>
          </div>
        ) : null}

        {step === "missing" ? (
          <div className="import-section">
            <div className="import-grid">
              <div className="import-panel">
                <div className="eyebrow">Required before import</div>
                <div className="plain-row"><strong>Tax year</strong><span>2026</span></div>
                <div className="plain-row"><strong>Payroll states</strong><span>Missing for 2 clients</span></div>
              </div>
              <div className="import-panel">
                <div className="eyebrow">Can ask later</div>
                <div className="plain-row"><strong>Extension status</strong><span>Follow up after import</span></div>
                <div className="plain-row"><strong>Special remarks</strong><span>Optional metadata</span></div>
              </div>
            </div>
            <div className="action-bar">
              <button className="primary" onClick={() => setStep("ready")}>Mark ready</button>
              <button className="secondary" onClick={() => setStep("mapping")}>Back</button>
            </div>
          </div>
        ) : null}

        {step === "ready" ? (
          <div className="import-section">
            <div className="weak-notice">
              <div className="dot" />
              <div className="text">
                <strong>Ready to generate.</strong> DueDateHQ can now create client records, tax profiles,
                jurisdictions, and the initial blockers and active work.
              </div>
            </div>
            <div className="action-bar">
              <button
                className="primary"
                onClick={() => {
                  setImportMessage(
                    "Import is ready. Generate the dashboard to create client records, blockers, and active work."
                  );
                }}
              >
                Generate dashboard
              </button>
              <button className="secondary" onClick={() => setStep("missing")}>Back</button>
            </div>
            <div className="callout-card">
              <span className="panel-label">Import status</span>
              <p>{importMessage}</p>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function DashboardSurface({
  view,
  seenVisualContexts
}: {
  view: ViewEnvelope;
  seenVisualContexts: VisualContext[];
}) {
  const [trackItems, setTrackItems] = useState<DashboardTrackItem[]>(() => extractTrackItems(view));
  const [dashboardMode, setDashboardMode] = useState<DashboardSurfaceMode>("board");
  const [timeHorizon, setTimeHorizon] = useState<DashboardHorizon>("this-week");
  const [activeLane, setActiveLane] = useState<DashboardLane>("track");
  const [waitingItems, setWaitingItems] = useState<DashboardWaitingItem[]>(dashboardWaitingSeed);
  const [noticeItems, setNoticeItems] = useState<DashboardNoticeItem[]>(dashboardNoticeSeed);
  const [watchItems, setWatchItems] = useState<DashboardWatchItem[]>(dashboardWatchSeed);
  const [actionMessage, setActionMessage] = useState(
    "Choose a lane to review work, blockers, notices, or watchlist items."
  );
  const [selectedIds, setSelectedIds] = useState({
    track: trackItems[0]?.deadline_id || null,
    waiting: dashboardWaitingSeed[0]?.client_id || null,
    notices: dashboardNoticeSeed[0]?.notice_id || null,
    watchlist: dashboardWatchSeed[0]?.client_id || null
  });

  useEffect(() => {
    const nextTrackItems = extractTrackItems(view);
    setTrackItems(nextTrackItems);
    setSelectedIds((current) => ({
      ...current,
      track: nextTrackItems.some((item) => String(item.deadline_id) === String(current.track))
        ? current.track
        : nextTrackItems[0]?.deadline_id || null
    }));
  }, [view]);

  const laneConfig = {
    track: { items: trackItems, itemKey: "deadline_id" },
    waiting: { items: waitingItems, itemKey: "client_id" },
    notices: { items: noticeItems, itemKey: "notice_id" },
    watchlist: { items: watchItems, itemKey: "client_id" }
  } as const;

  const currentLane = laneConfig[activeLane];
  const currentMeta = dashboardSectionMeta[activeLane];
  const currentItem =
    currentLane.items.find((item) => itemSelectionValue(item, activeLane) === String(selectedIds[activeLane])) ||
    currentLane.items[0] ||
    null;
  const horizonMeta = horizonMetaMap[timeHorizon];
  const dashboardEvents = filterDashboardEventsByHorizon(
    buildDashboardEvents(trackItems, waitingItems, noticeItems, watchItems),
    timeHorizon
  );
  const calendarGroups = groupDashboardEventsByDate(dashboardEvents);

  function selectLane(lane: DashboardLane) {
    setActiveLane(lane);
  }

  function selectItem(lane: DashboardLane, id: string) {
    setActiveLane(lane);
    setSelectedIds((current) => ({ ...current, [lane]: id }));
  }

  function replaceLaneSelection<T extends { [key: string]: unknown }>(
    lane: DashboardLane,
    nextItems: T[],
    itemKey: string
  ) {
    setSelectedIds((current) => ({
      ...current,
      [lane]: nextItems.some((item) => String(item[itemKey]) === String(current[lane])) ? current[lane] : String(nextItems[0]?.[itemKey] || "")
    }));
  }

  function handleTrackAction(action: "complete" | "snooze") {
    if (!currentItem || activeLane !== "track") return;
    const item = currentItem as DashboardTrackItem;

    if (action === "complete") {
      const remaining = trackItems.filter((entry: DashboardTrackItem) => entry.deadline_id !== item.deadline_id);
      setTrackItems(remaining);
      replaceLaneSelection("track", remaining, "deadline_id");
      setActionMessage(`Marked ${item.client_name} as done. Review the next active item, or switch to Waiting on info if something is blocked.`);
      return;
    }

    const nextItems = trackItems.map((entry: DashboardTrackItem) =>
      entry.deadline_id === item.deadline_id
        ? { ...entry, status: "Remind later", days_remaining: Math.max(entry.days_remaining + 3, 3) }
        : entry
    );
    setTrackItems(nextItems);
    setActionMessage(`Moved ${item.client_name} to remind later. It remains on the board but is no longer at the top of this week's queue.`);
  }

  function handleWaitingAction(action: "draft" | "received") {
    if (!currentItem || activeLane !== "waiting") return;
    const item = currentItem as DashboardWaitingItem;

    if (action === "received") {
      const nextItems = waitingItems.filter((entry: DashboardWaitingItem) => entry.client_id !== item.client_id);
      setWaitingItems(nextItems);
      replaceLaneSelection("waiting", nextItems, "client_id");
      setActionMessage(`Marked the missing information as received for ${item.client_name}. The blocker is cleared, so active work can move again.`);
      return;
    }

    setActionMessage(`Prepared the next outreach step for ${item.client_name}. The blocker will remain until the missing information is received.`);
  }

  function handleNoticeAction(action: "read" | "create-task" | "dismiss") {
    if (!currentItem || activeLane !== "notices") return;
    const item = currentItem as DashboardNoticeItem;

    if (action === "read") {
      const nextItems = noticeItems.map((entry: DashboardNoticeItem) =>
        entry.notice_id === item.notice_id ? { ...entry, read: true } : entry
      );
      setNoticeItems(nextItems);
      setActionMessage(`Marked ${item.title} as read. It stays on the notice queue until you either add it to active work or dismiss it.`);
      return;
    }

    if (action === "dismiss") {
      const nextItems = noticeItems.filter((entry: DashboardNoticeItem) => entry.notice_id !== item.notice_id);
      setNoticeItems(nextItems);
      replaceLaneSelection("notices", nextItems, "notice_id");
      setActionMessage(`Dismissed ${item.title} from the notice queue.`);
      return;
    }

    const nextTask: DashboardTrackItem = {
      deadline_id: item.notice_id,
      client_id: `notice-${item.notice_id}`,
      client_name: item.title,
      tax_type: "Notice review",
      jurisdiction: "Cross-state",
      due_date: "Review now",
      status: "Open",
      days_remaining: 2,
      task_id: `task-${item.notice_id}`,
      title: item.title,
      priority: "Review",
      task_type: "review",
      source_type: "notice",
      source_id: item.notice_id
    };
    setTrackItems((current) => [nextTask, ...current]);
    setActionMessage(`Added ${item.title} to active work. It now appears in Track for follow-up.`);
    setActiveLane("track");
    setSelectedIds((current) => ({ ...current, track: nextTask.deadline_id }));
  }

  function handleWatchAction(action: "escalate" | "dismiss") {
    if (!currentItem || activeLane !== "watchlist") return;
    const item = currentItem as DashboardWatchItem;

    if (action === "dismiss") {
      const nextItems = watchItems.filter((entry: DashboardWatchItem) => entry.client_id !== item.client_id);
      setWatchItems(nextItems);
      replaceLaneSelection("watchlist", nextItems, "client_id");
      setActionMessage(`Removed ${item.client_name} from the watchlist.`);
      return;
    }

    const nextTask: DashboardTrackItem = {
      deadline_id: `watch-${item.client_id}`,
      client_id: item.client_id,
      client_name: item.client_name,
      tax_type: "Risk review",
      jurisdiction: item.risk_label,
      due_date: "This week",
      status: "Open",
      days_remaining: 5,
      task_id: `task-watch-${item.client_id}`,
      title: item.headline,
      priority: item.risk_label,
      task_type: "review",
      source_type: "watchlist",
      source_id: item.client_id
    };
    setTrackItems((current) => [nextTask, ...current]);
    setActionMessage(`Added ${item.client_name} to active work. Use Track to decide the next action.`);
    setActiveLane("track");
    setSelectedIds((current) => ({ ...current, track: nextTask.deadline_id }));
  }

  return (
    <div className="dashboard-surface">
      <section className="dashboard-hero card">
        <div className="card-header">
          <div>
            <div className="eyebrow">Portfolio overview</div>
            <h2>{horizonMeta.title}</h2>
            <p className="card-description">
              {horizonMeta.description}
            </p>
          </div>
          <span className="pill gold">{trackItems.length} active items</span>
        </div>
        <div className="dashboard-toolbar">
          <div className="dashboard-view-switch">
            {([
              { key: "board", label: "Board" },
              { key: "calendar", label: "Calendar" },
              { key: "timeline", label: "Timeline" }
            ] as const).map((option) => (
              <button
                key={option.key}
                className={`dashboard-chip ${dashboardMode === option.key ? "active" : ""}`}
                onClick={() => setDashboardMode(option.key)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="dashboard-horizon-switch">
            {([
              { key: "this-week", label: "This week" },
              { key: "next-30", label: "Next 30 days" },
              { key: "this-month", label: "This month" },
              { key: "next-month", label: "Next month" },
              { key: "quarter", label: "Quarter" }
            ] as const).map((option) => (
              <button
                key={option.key}
                className={`dashboard-chip ${timeHorizon === option.key ? "active" : ""}`}
                onClick={() => setTimeHorizon(option.key)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div className="dashboard-lanes">
          {[
            { key: "track" as DashboardLane, count: trackItems.length },
            { key: "waiting" as DashboardLane, count: waitingItems.length },
            { key: "notices" as DashboardLane, count: noticeItems.length },
            { key: "watchlist" as DashboardLane, count: watchItems.length }
          ].map((lane) => (
            <button
              key={lane.key}
              className={`lane-card ${lane.key === activeLane ? "active" : ""}`}
              onClick={() => selectLane(lane.key)}
            >
              <div className="eyebrow">{dashboardSectionMeta[lane.key].label}</div>
              <strong>{lane.count}</strong>
              <p>{dashboardSectionMeta[lane.key].helper}</p>
            </button>
          ))}
        </div>
      </section>

      {dashboardMode === "board" ? (
      <section className="dashboard-grid">
        <article className="card dashboard-queue">
          <div className="card-header">
            <div>
              <div className="eyebrow">{currentMeta.label}</div>
              <h2>{currentMeta.title}</h2>
              <p className="card-description">{currentMeta.description}</p>
            </div>
          </div>
          <div className="list">
            {activeLane === "track" ? trackItems.map((item: DashboardTrackItem, index: number) => (
              <button
                key={item.deadline_id || `${item.client_name}-${index}`}
                className={`deadline-row ${urgencyClass(item)} ${String((currentItem as TaskItem | null)?.deadline_id) === String(item.deadline_id) ? "selected" : ""}`}
                onClick={() => selectItem("track", String(item.deadline_id))}
              >
                <span className="row-accent" />
                <div className="row-main">
                  <div className="row-client">{item.client_name}</div>
                  <div className="row-detail">{item.title || item.tax_type} · {item.jurisdiction}</div>
                </div>
                <div className="row-right">
                  <div className={item.days_remaining <= 0 ? "row-due hot" : "row-due"}>{item.due_date}</div>
                  <span className={`badge-pill ${badgeClass(urgencyClass(item))}`}>{item.status || "Open"}</span>
                </div>
              </button>
            )) : null}
            {activeLane === "waiting" ? waitingItems.map((item) => (
              <button
                key={item.client_id}
                className={`deadline-row urgent ${String((currentItem as typeof dashboardWaitingSeed[number] | null)?.client_id) === String(item.client_id) ? "selected" : ""}`}
                onClick={() => selectItem("waiting", item.client_id)}
              >
                <span className="row-accent" />
                <div className="row-main">
                  <div className="row-client">{item.client_name}</div>
                  <div className="row-detail">{item.reason}</div>
                </div>
                <div className="row-right">
                  <span className="badge-pill urgent">Blocked</span>
                </div>
              </button>
            )) : null}
            {activeLane === "notices" ? noticeItems.map((item) => (
              <button
                key={item.notice_id}
                className={`deadline-row medium ${String((currentItem as typeof dashboardNoticeSeed[number] | null)?.notice_id) === String(item.notice_id) ? "selected" : ""}`}
                onClick={() => selectItem("notices", item.notice_id)}
              >
                <span className="row-accent" />
                <div className="row-main">
                  <div className="row-client">{item.title}</div>
                  <div className="row-detail">{item.summary}</div>
                </div>
                <div className="row-right">
                  <span className={`badge-pill ${item.read ? "low" : "medium"}`}>{item.read ? "Read" : "Review"}</span>
                </div>
              </button>
            )) : null}
            {activeLane === "watchlist" ? watchItems.map((item) => (
              <button
                key={item.client_id}
                className={`deadline-row ${item.risk_label === "High" ? "urgent" : "medium"} ${String((currentItem as typeof dashboardWatchSeed[number] | null)?.client_id) === String(item.client_id) ? "selected" : ""}`}
                onClick={() => selectItem("watchlist", item.client_id)}
              >
                <span className="row-accent" />
                <div className="row-main">
                  <div className="row-client">{item.client_name}</div>
                  <div className="row-detail">{item.headline}</div>
                </div>
                <div className="row-right">
                  <span className={`badge-pill ${item.risk_label === "High" ? "urgent" : "medium"}`}>{item.risk_label}</span>
                </div>
              </button>
            )) : null}
            {currentLane.items.length === 0 ? (
              <div className="dashboard-empty">
                <strong>No items in this lane.</strong>
                <span>Move to another lane, or come back later when new work appears.</span>
              </div>
            ) : null}
          </div>
        </article>

        <article className="card dashboard-context">
          <div className="card-header">
            <div>
              <div className="eyebrow">Decision panel</div>
              <h2>{currentItem ? currentMeta.label : "Choose an item"}</h2>
            </div>
          </div>
          <div className="callout-card callout-banner">
            <span className="panel-label">CPA action</span>
            <p>{actionMessage}</p>
          </div>
          {currentItem ? (
            <>
              {activeLane === "track" ? (
                <>
                  <div className="inspector-block">
                    <span className="panel-label">Selected task</span>
                    <h4>{(currentItem as TaskItem).client_name}</h4>
                    <p>
                      {(currentItem as TaskItem).client_name} has active work tied to {(currentItem as TaskItem).tax_type} in {(currentItem as TaskItem).jurisdiction}.
                    </p>
                  </div>
                  <div className="fact-grid dashboard-facts">
                    <Fact label="Task type" value="Active work" />
                    <Fact label="Due" value={(currentItem as TaskItem).due_date} tone={urgencyClass(currentItem as TaskItem) === "urgent" ? "red" : urgencyClass(currentItem as TaskItem) === "medium" ? "gold" : "green"} />
                    <Fact label="Status" value={(currentItem as TaskItem).status || "Open"} />
                  </div>
                  <div className="action-bar">
                    <button className="primary" onClick={() => {
                      setActionMessage(
                        `${String((currentItem as TaskItem).client_name)} remains selected on the board.`
                      );
                    }}>
                      Open client
                    </button>
                    <button className="secondary" onClick={() => handleTrackAction("snooze")}>
                      Remind later
                    </button>
                    <button className="secondary" onClick={() => handleTrackAction("complete")}>
                      Mark done
                    </button>
                  </div>
                </>
              ) : null}
              {activeLane === "waiting" ? (
                <>
                  <div className="inspector-block">
                    <span className="panel-label">Selected blocker</span>
                    <h4>{(currentItem as typeof dashboardWaitingSeed[number]).client_name}</h4>
                    <p>{(currentItem as typeof dashboardWaitingSeed[number]).reason}</p>
                  </div>
                  <div className="fact-grid dashboard-facts">
                    <Fact label="Waiting on" value={(currentItem as typeof dashboardWaitingSeed[number]).requested_from} />
                    <Fact label="Object" value="Blocker" />
                    <Fact label="Impact" value="Stops active work" tone="red" />
                  </div>
                  <div className="callout-card">
                    <span className="panel-label">Next step</span>
                    <p>{(currentItem as typeof dashboardWaitingSeed[number]).next_step}</p>
                  </div>
                  <div className="action-bar">
                    <button className="primary" onClick={() => {
                      setActionMessage(
                        `${(currentItem as typeof dashboardWaitingSeed[number]).client_name} remains selected in Waiting on info.`
                      );
                    }}>
                      Open client
                    </button>
                    <button className="secondary" onClick={() => handleWaitingAction("draft")}>
                      Draft outreach
                    </button>
                    <button className="secondary" onClick={() => handleWaitingAction("received")}>
                      Mark received
                    </button>
                  </div>
                </>
              ) : null}
              {activeLane === "notices" ? (
                <>
                  <div className="inspector-block">
                    <span className="panel-label">Selected notice</span>
                    <h4>{(currentItem as typeof dashboardNoticeSeed[number]).title}</h4>
                    <p>{(currentItem as typeof dashboardNoticeSeed[number]).summary}</p>
                  </div>
                  <div className="fact-grid dashboard-facts">
                    <Fact label="Affected clients" value={String((currentItem as typeof dashboardNoticeSeed[number]).affected_count)} />
                    <Fact label="Handling mode" value={(currentItem as typeof dashboardNoticeSeed[number]).read ? "Read by CPA" : "Needs CPA review"} />
                    <Fact label="Object" value="Notice" tone="gold" />
                  </div>
                  <div className="callout-card">
                    <span className="panel-label">Next step</span>
                    <p>{(currentItem as typeof dashboardNoticeSeed[number]).next_step}</p>
                  </div>
                  <div className="action-bar">
                    <button className="primary" onClick={() => {
                      setActionMessage(
                        `This notice remains selected on the board for review.`
                      );
                    }}>
                      Open notice
                    </button>
                    <button className="secondary" onClick={() => handleNoticeAction("read")}>
                      Mark read
                    </button>
                    <button className="secondary" onClick={() => handleNoticeAction("create-task")}>
                      Add to active work
                    </button>
                    <button className="secondary" onClick={() => handleNoticeAction("dismiss")}>
                      Dismiss
                    </button>
                  </div>
                </>
              ) : null}
              {activeLane === "watchlist" ? (
                <>
                  <div className="inspector-block">
                    <span className="panel-label">Selected watch item</span>
                    <h4>{(currentItem as typeof dashboardWatchSeed[number]).client_name}</h4>
                    <p>{(currentItem as typeof dashboardWatchSeed[number]).headline}</p>
                  </div>
                  <div className="callout-card">
                    <span className="panel-label">Why it matters</span>
                    <p>{(currentItem as typeof dashboardWatchSeed[number]).why_it_matters}</p>
                  </div>
                  <div className="callout-card">
                    <span className="panel-label">Next step</span>
                    <p>{(currentItem as typeof dashboardWatchSeed[number]).next_step}</p>
                  </div>
                  <div className="action-bar">
                    <button className="primary" onClick={() => {
                      setActionMessage(
                        `${(currentItem as typeof dashboardWatchSeed[number]).client_name} remains selected in Watchlist.`
                      );
                    }}>
                      Open client
                    </button>
                    <button className="secondary" onClick={() => handleWatchAction("escalate")}>
                      Add to active work
                    </button>
                    <button className="secondary" onClick={() => handleWatchAction("dismiss")}>
                      Remove
                    </button>
                  </div>
                </>
              ) : null}
            </>
          ) : (
            <div className="dashboard-empty">
              <strong>Nothing to process here.</strong>
                <span>Move to another lane or return after new items are created.</span>
            </div>
          )}
        </article>
      </section>
      ) : null}

      {dashboardMode === "calendar" ? (
        <section className="card dashboard-calendar">
          <div className="card-header">
            <div>
              <div className="eyebrow">Calendar view</div>
              <h2>{horizonMeta.calendarTitle}</h2>
              <p className="card-description">
                Scan upcoming work across the portfolio by date.
              </p>
            </div>
            <span className="pill blue">{dashboardEvents.length} scheduled items</span>
          </div>
          <div className="calendar-grid">
            {calendarGroups.map((group) => (
              <section key={group.dateKey} className="calendar-day">
                <div className="calendar-day-head">
                  <span className="calendar-date">{group.label}</span>
                  <span className="calendar-count">{group.items.length}</span>
                </div>
                <div className="calendar-day-list">
                  {group.items.map((item) => (
                    <button
                      key={item.id}
                      className={`calendar-event ${item.tone}`}
                      onClick={() => {
                        if (item.lane === "track") selectItem("track", item.selectionId);
                        if (item.lane === "waiting") selectItem("waiting", item.selectionId);
                        if (item.lane === "notices") selectItem("notices", item.selectionId);
                        if (item.lane === "watchlist") selectItem("watchlist", item.selectionId);
                        setDashboardMode("board");
                        setActionMessage(`Opened ${item.title} from Calendar. You are back on the board so you can act on it.`);
                      }}
                    >
                      <span className="calendar-event-lane">{dashboardSectionMeta[item.lane].label}</span>
                      <strong>{item.title}</strong>
                      <span>{item.subtitle}</span>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </section>
      ) : null}

      {dashboardMode === "timeline" ? (
        <section className="card dashboard-timeline">
          <div className="card-header">
            <div>
              <div className="eyebrow">Timeline view</div>
              <h2>{horizonMeta.timelineTitle}</h2>
              <p className="card-description">
                Review the portfolio as a chronological sequence of work.
              </p>
            </div>
            <span className="pill blue">{dashboardEvents.length} items in sequence</span>
          </div>
          <div className="timeline-feed">
            {dashboardEvents.map((item) => (
              <button
                key={item.id}
                className="timeline-entry"
                onClick={() => {
                  if (item.lane === "track") selectItem("track", item.selectionId);
                  if (item.lane === "waiting") selectItem("waiting", item.selectionId);
                  if (item.lane === "notices") selectItem("notices", item.selectionId);
                  if (item.lane === "watchlist") selectItem("watchlist", item.selectionId);
                  setDashboardMode("board");
                  setActionMessage(`Opened ${item.title} from Timeline. You are back on the board so you can continue from the same item.`);
                }}
              >
                <div className="timeline-entry-date">
                  <span>{item.dateLabel}</span>
                </div>
                <div className={`timeline-entry-body ${item.tone}`}>
                  <div className="timeline-entry-meta">
                    <span className="timeline-entry-lane">{dashboardSectionMeta[item.lane].label}</span>
                    <span className={`badge-pill ${item.tone}`}>{item.statusLabel}</span>
                  </div>
                  <strong>{item.title}</strong>
                  <p>{item.subtitle}</p>
                </div>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function buildWorkspaceSnapshot(view: ViewEnvelope): Record<string, unknown> {
  const data = view.data || {};
  const workspaceType = workspaceTypeForView(view.type);
  const semanticId = String(
    data.client_id ||
      data.client_name ||
      data.deadline_id ||
      data.title ||
      data.headline ||
      view.type
  );
  return {
    key: `${workspaceType}:${semanticId}`,
    type: workspaceType,
    view_type: view.type,
    semantic_id: semanticId,
    title: String(data.client_name || data.title || data.headline || data.message || view.type),
    selectable_count: view.selectable_items?.length || 0
  };
}

function workspaceTypeForView(viewType: string): string {
  const mapping: Record<string, string> = {
    ListCard: "TodayQueue",
    ClientCard: "ClientWorkspace",
    HistoryCard: "AuditWorkspace",
    ConfirmCard: "ConfirmWorkspace",
    GuidanceCard: "GuidanceWorkspace",
    TaxChangeRadarCard: "TaxChangeRadarWorkspace",
    RenderSpecSurface: "GeneratedWorkspace",
    ReminderPreviewCard: "ReminderPreviewWorkspace",
    ClientListCard: "ClientDirectoryWorkspace",
    ReviewQueueCard: "ReviewQueueWorkspace"
  };
  return mapping[viewType] || `${viewType}Workspace`;
}

function appendBreadcrumb(current: unknown[], workspaceType: string): string[] {
  const breadcrumb = current.map((item) => String(item));
  if (!breadcrumb.length || breadcrumb[breadcrumb.length - 1] !== workspaceType) {
    breadcrumb.push(workspaceType);
  }
  return breadcrumb.slice(-8);
}

function describeDirectAction(action: DirectAction): string {
  if (action.command === "confirm_pending") return "Confirm this change";
  if (action.command === "cancel_pending") return "Cancel";
  if (action.expected_view === "ListCard") return "Back to today's work";
  if (action.expected_view === "ClientCard") return "Open this client";
  if (action.expected_view === "HistoryCard") return "Show source";
  if (action.expected_view === "ConfirmCard") return "Review before writing";
  if (action.expected_view === "RenderSpecSurface") return "Continue";
  return "Run this action";
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const isThinking =
    message.role === "status" &&
    (/^opening/i.test(message.text) || /^the next workspace/i.test(message.text) || /^connecting/i.test(message.text));
  return (
    <div className={`msg ${isUser ? "user" : ""} ${message.role === "status" ? "status" : ""} ${isThinking ? "thinking" : ""}`}>
      <div className={`msg-badge ${isUser ? "usr" : "sys"}`}>{isThinking ? "" : isUser ? "SJ" : "DH"}</div>
      <div className="msg-bubble">
        <MarkdownText text={message.text} />
      </div>
    </div>
  );
}

function MarkdownText({ text }: { text: string }) {
  const lines = normalizeMarkdownLines(text);
  const blocks: ReactNode[] = [];
  let orderedItems: ReactNode[] = [];
  let unorderedItems: ReactNode[] = [];

  function flushLists() {
    if (orderedItems.length) {
      blocks.push(<ol key={`ol-${blocks.length}`}>{orderedItems}</ol>);
      orderedItems = [];
    }
    if (unorderedItems.length) {
      blocks.push(<ul key={`ul-${blocks.length}`}>{unorderedItems}</ul>);
      unorderedItems = [];
    }
  }

  for (const line of lines.length ? lines : [text]) {
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    if (ordered) {
      if (unorderedItems.length) flushLists();
      orderedItems.push(<li key={`li-${orderedItems.length}`}>{renderInlineMarkdown(ordered[1])}</li>);
      continue;
    }
    if (unordered) {
      if (orderedItems.length) flushLists();
      unorderedItems.push(<li key={`li-${unorderedItems.length}`}>{renderInlineMarkdown(unordered[1])}</li>);
      continue;
    }
    flushLists();
    blocks.push(<p key={`p-${blocks.length}`}>{renderInlineMarkdown(line)}</p>);
  }
  flushLists();

  return <div className="md-content">{blocks}</div>;
}

function normalizeMarkdownLines(text: string) {
  return text
    .replace(/\r\n/g, "\n")
    .split(/\n+/)
    .flatMap((line) =>
      line
        .trim()
        .replace(/(\S)\s+(\d+[.)]\s+)/g, "$1\n$2")
        .replace(/([。！？.!?])\s+(?=\*\*[^*]+\*\*)/g, "$1\n")
        .split("\n")
    )
    .map((line) => line.trim())
    .filter(Boolean);
}

function renderInlineMarkdown(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    return <span key={index}>{part}</span>;
  });
}

type DirectActionHandler = (action: DirectAction, userEcho?: string) => void;

function ViewRenderer({ view, onPrompt, onAction }: { view: ViewEnvelope; onPrompt: (prompt: string) => void; onAction: DirectActionHandler }) {
  if (view.type === "ListCard") return <ListCard view={view} onPrompt={onPrompt} onAction={onAction} />;
  if (view.type === "ClientCard") return <ClientCard view={view} onPrompt={onPrompt} onAction={onAction} />;
  if (view.type === "ConfirmCard") return <ConfirmCard view={view} onAction={onAction} />;
  if (view.type === "HistoryCard") return <HistoryCard view={view} />;
  if (view.type === "ReminderPreviewCard") return <ReminderPreviewCard view={view} />;
  if (view.type === "ClientListCard") return <ClientListCard view={view} onPrompt={onPrompt} />;
  if (view.type === "ReviewQueueCard") return <ReviewQueueCard view={view} />;
  if (view.type === "GuidanceCard") return <GuidanceCard view={view} onPrompt={onPrompt} />;
  if (view.type === "TaxChangeRadarCard") return <TaxChangeRadarCard view={view} onPrompt={onPrompt} />;
  if (view.type === "RenderSpecSurface") return <RenderSpecSurface spec={view.data.render_spec as RenderSpec} onPrompt={onPrompt} onAction={onAction} />;
  return <UnknownView view={view} />;
}

function ListCard({ view, onPrompt, onAction }: { view: ViewEnvelope; onPrompt: (prompt: string) => void; onAction: DirectActionHandler }) {
  const data = view.data as {
    title?: string;
    headline?: string;
    description?: string;
    items?: TaskItem[];
    total?: number;
    status_label?: string;
  };
  const items = data.items || [];
  return (
    <article className="card">
      <div className="card-header">
        <div>
          <div className="eyebrow">{data.title || "Deadline list"}</div>
          <h2>{items.length ? data.headline || "Review the matching deadlines" : "No matching work"}</h2>
          {data.description ? <p className="card-description">{data.description}</p> : null}
        </div>
        <span className="pill red">{data.total ?? items.length} {data.status_label || "items"}</span>
      </div>
      <div className="list">
        {items.map((item, index) => {
          const clientName = item.client_name || `Item ${index + 1}`;
          const detail = [item.tax_type, item.jurisdiction].filter(Boolean).join(" · ");
          const urgency = urgencyClass(item);
          const statusLabel = item.status || (urgency === "urgent" ? "Needs review" : "Open");
          return (
          <button
            className={`deadline-row ${urgency}`}
            key={item.deadline_id || `${clientName}-${index}`}
            onClick={() => {
              const action = view.selectable_items?.[index]?.action;
              if (action) {
                onAction(action, `Open ${clientName}`);
              return;
            }
              onPrompt(`Open item ${index + 1}`);
            }}
            aria-label={`Open ${clientName}`}
            title={`Open ${clientName}`}
          >
            <span className="row-accent" />
            <div className="row-main">
              <div className="row-client">{clientName}</div>
              <div className="row-detail">{detail || "Deadline item"}</div>
            </div>
            <div className="row-right">
              <div className={item.days_remaining <= 0 ? "row-due hot" : "row-due"}>{item.due_date}</div>
              <span className={`badge-pill ${badgeClass(urgency)}`}>{statusLabel}</span>
            </div>
          </button>
          );
        })}
      </div>
    </article>
  );
}

function ClientCard({ view, onPrompt, onAction }: { view: ViewEnvelope; onPrompt: (prompt: string) => void; onAction: DirectActionHandler }) {
  const data = view.data as { client_name?: string; entity_type?: string; registered_states?: string[]; deadlines?: TaskItem[] };
  const deadline = data.deadlines?.[0];
  const deadlines = data.deadlines || [];
  const clientName = data.client_name || deadline?.client_name || "This client";
  const status = deadline?.status ? deadline.status.toLowerCase() : "open";
  const reason = deadline?.missing || deadline?.tax_type || "the next deadline";
  return (
    <article className="card client-card">
      <div className="client-hero">
        <div className="eyebrow">Focused task</div>
        <h2>{clientName}</h2>
        <p>{deadline ? `${clientName} has an ${status} item: ${reason}.` : "No active deadline found."}</p>
      </div>
      <div className="fact-grid">
        <Fact label="Entity" value={data.entity_type || "Unknown"} />
        <Fact label="States" value={(data.registered_states || []).join(", ") || "None"} />
        <Fact label="Due" value={deadline?.due_date || "Unknown"} tone="red" />
      </div>
      {deadlines.length ? (
        <div className="list compact-list">
          {deadlines.map((item) => (
            <div className="plain-row" key={item.deadline_id}>
              <strong>{item.tax_type} · {item.jurisdiction}</strong>
              <span>{item.due_date} · {item.status}</span>
            </div>
          ))}
        </div>
      ) : null}
      <div className="action-bar">
        <button
          className="primary"
          onClick={() =>
            onAction(
              {
                type: "direct_execute",
                expected_view: "RenderSpecSurface",
                plan: {
                  special: "render_spec_needed",
                  intent_label: "client_request_draft",
                  op_class: "read",
                  message: "Draft a client request from the current item.",
                  user_input: `prepare request for ${clientName}`
                }
              },
              "Prepare request"
            )
          }
        >
          Prepare request
        </button>
        <button
          className="secondary"
          onClick={() => {
            if (deadline?.deadline_id) {
              onAction(
                {
                  type: "direct_execute",
                  expected_view: "HistoryCard",
                  plan: deadlineHistoryPlan(deadline.deadline_id)
                },
                "Show source"
              );
              return;
            }
            onPrompt("show source");
          }}
        >
          Show source
        </button>
        <button
          className="secondary"
          onClick={() =>
            onAction(
              {
                type: "direct_execute",
                expected_view: "ListCard",
                plan: todayPlan()
              },
              "Back to today"
            )
          }
        >
          Back to today
        </button>
      </div>
    </article>
  );
}

function ConfirmCard({ view, onAction }: { view: ViewEnvelope; onAction: DirectActionHandler }) {
  const data = view.data as { description?: string; due_date?: string; consequence?: string; options?: Array<{ label: string; style?: string; plan?: Record<string, unknown> | null }> };
  return (
    <article className="card confirm-card">
      <div className="card-header">
        <div>
          <div className="eyebrow">Confirm before changing records</div>
          <h2>{data.description || "Confirm action"}</h2>
        </div>
        <span className="pill gold">{data.due_date || "pending"}</span>
      </div>
      <p className="consequence">{data.consequence}</p>
      <div className="action-bar">
        {(data.options || [{ label: "Confirm", style: "primary" }, { label: "Cancel" }]).map((option) => (
          <button
            key={option.label}
            className={option.style === "primary" ? "primary" : "secondary"}
            onClick={() =>
              onAction(
                {
                  type: "direct_execute",
                  command: option.style === "primary" ? "confirm_pending" : "cancel_pending",
                  expected_view: option.style === "primary" ? "ListCard" : "GuidanceCard"
                },
                option.label
              )
            }
          >
            {option.label}
          </button>
        ))}
      </div>
    </article>
  );
}

function HistoryCard({ view }: { view: ViewEnvelope }) {
  const data = view.data as {
    client_name?: string;
    tax_type?: string;
    due_date?: string;
    status?: string;
    source_url?: string;
    transitions?: Array<Record<string, string>>;
  };
  return (
    <article className="card">
      <div className="card-header">
        <div>
          <div className="eyebrow">Source and audit trail</div>
          <h2>{data.client_name || "Current item"}</h2>
        </div>
        <span className="pill blue">{data.status || "record"}</span>
      </div>
      <div className="fact-grid">
        <Fact label="Tax type" value={data.tax_type || "Unknown"} />
        <Fact label="Due" value={data.due_date || "Unknown"} />
        <Fact label="Source" value={data.source_url || "No source URL"} />
      </div>
      <div className="timeline">
        {(data.transitions || []).map((transition, index) => (
          <div className="timeline-row" key={index}>
            <span>{transition.at || transition.created_at || "event"}</span>
            <p>{transition.note || `${transition.from_status || "previous"} → ${transition.to_status || "current"}`}</p>
          </div>
        ))}
      </div>
    </article>
  );
}

function ReminderPreviewCard({ view }: { view: ViewEnvelope }) {
  const data = view.data as { reminders?: Array<Record<string, string>>; total?: number };
  return (
    <article className="card">
      <div className="card-header">
        <div>
          <div className="eyebrow">Reminder preview</div>
          <h2>{data.total || 0} reminders ready</h2>
        </div>
      </div>
      <div className="list">
        {(data.reminders || []).map((reminder, index) => (
          <div className="plain-row" key={index}>
            <strong>{reminder.client_name}</strong>
            <span>{reminder.tax_type} · due {reminder.due_date}</span>
          </div>
        ))}
      </div>
    </article>
  );
}

function ClientListCard({ view, onPrompt }: { view: ViewEnvelope; onPrompt: (prompt: string) => void }) {
  const data = view.data as { clients?: Array<{ client_id: string; name: string; entity_type?: string; registered_states?: string[] }>; total?: number };
  return (
    <article className="card">
      <div className="card-header">
        <div>
          <div className="eyebrow">Clients</div>
          <h2>{data.total || 0} clients</h2>
        </div>
      </div>
      <div className="list">
        {(data.clients || []).map((client) => (
          <button className="task-row" key={client.client_id} onClick={() => onPrompt(`focus ${client.name}`)}>
            <div>
              <strong>{client.name}</strong>
              <span>{client.entity_type || "Entity"} · {(client.registered_states || []).join(", ")}</span>
            </div>
          </button>
        ))}
      </div>
    </article>
  );
}

function ReviewQueueCard({ view }: { view: ViewEnvelope }) {
  const data = view.data as { items?: Array<Record<string, string | number>>; total?: number };
  return (
    <article className="card">
      <div className="card-header">
        <div>
          <div className="eyebrow">Rule review</div>
          <h2>{data.total || 0} items need review</h2>
        </div>
      </div>
      <div className="list">
        {(data.items || []).map((item, index) => (
          <div className="plain-row" key={index}>
            <strong>{String(item.review_id || `review_${index + 1}`)}</strong>
            <span>{String(item.source_url || item.raw_text || "No source")}</span>
          </div>
        ))}
      </div>
    </article>
  );
}

function TaxChangeRadarCard({ view, onPrompt }: { view: ViewEnvelope; onPrompt: (prompt: string) => void }) {
  const data = view.data as {
    title?: string;
    primary_question?: string;
    data_boundary_notice?: string;
    metrics?: Array<{ label: string; value: string; tone?: "red" | "green" | "blue" | "gold" }>;
    rule_signals?: Array<{ title: string; detail?: string; source?: string }>;
    impacted_deadlines?: Array<{ client_name: string; tax_type: string; jurisdiction: string; due_date: string; status: string }>;
  };
  return (
    <article className="card radar-card">
      <div className="card-header">
        <div>
          <div className="eyebrow">Tax change radar</div>
          <h2>{data.title || "This month's tax change radar"}</h2>
          {data.primary_question ? <p className="card-description">{data.primary_question}</p> : null}
        </div>
      </div>
      {data.data_boundary_notice ? (
        <section className="boundary-note">
          <strong>Data boundary</strong>
          <p>{data.data_boundary_notice}</p>
        </section>
      ) : null}
      <section className="fact-grid">
        {(data.metrics || []).map((metric) => <Fact key={metric.label} label={metric.label} value={metric.value} tone={metric.tone} />)}
      </section>
      <section className="radar-section">
        <div>
          <div className="eyebrow">Signals</div>
          <h3>Signals detected so far</h3>
        </div>
        <div className="list compact-list">
          {(data.rule_signals || []).map((signal, index) => (
            <div className="plain-row" key={`${signal.title}-${index}`}>
              <strong>{signal.title}</strong>
              <span>{[signal.detail, signal.source].filter(Boolean).join(" · ")}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="radar-section">
        <div>
          <div className="eyebrow">Client impact</div>
          <h3>Upcoming items that may be affected</h3>
        </div>
        <div className="list compact-list">
          {(data.impacted_deadlines || []).map((item, index) => (
            <button className="task-row" key={`${item.client_name}-${item.tax_type}-${index}`} onClick={() => onPrompt(`Open ${item.client_name}`)}>
              <div>
                <strong>{item.client_name}</strong>
                <span>{item.tax_type} · {item.jurisdiction}</span>
              </div>
              <div className="task-right">
                <span className="due">{item.due_date}</span>
                <span>{item.status}</span>
              </div>
            </button>
          ))}
        </div>
      </section>
    </article>
  );
}

function GuidanceCard({ view, onPrompt }: { view: ViewEnvelope; onPrompt: (prompt: string) => void }) {
  const data = view.data as {
    title?: string;
    eyebrow?: string;
    message?: string;
    options?: string[];
    context_options?: Array<Record<string, string>>;
  };
  return (
    <article className="card guidance-card">
      <div className="card-header">
        <div>
          <div className="eyebrow">{data.eyebrow || "Need one more bit of context"}</div>
          <h2>{data.title || "Choose the item first"}</h2>
        </div>
      </div>
      <p className="consequence">{data.message || "I need a little more context before changing the work surface."}</p>
      {data.context_options?.length ? (
        <div className="list compact-list">
          {data.context_options.map((option, index) => (
            <button
              className="task-row"
              key={`${option.ref || index}`}
              onClick={() => onPrompt(String(option.client_name || option.ref || "show today"))}
            >
              <div>
                <strong>{option.client_name || option.ref || `Item ${index + 1}`}</strong>
                <span>{option.deadline_id || option.client_id || "Available context"}</span>
              </div>
            </button>
          ))}
        </div>
      ) : null}
      <div className="action-bar">
        {(data.options?.length ? data.options : ["Show today's work"]).map((option) => (
          <button key={option} className="secondary" onClick={() => onPrompt(option)}>
            {option}
          </button>
        ))}
      </div>
    </article>
  );
}

function RenderSpecSurface({ spec, onPrompt, onAction }: { spec: RenderSpec; onPrompt: (prompt: string) => void; onAction: DirectActionHandler }) {
  const validation = validateRenderSpec(spec);
  if (!validation.ok) {
    return (
      <article className="card">
        <div className="card-header">
          <div>
            <div className="eyebrow">Render spec rejected</div>
            <h2>This surface did not pass validation</h2>
          </div>
        </div>
        <p className="consequence">{validation.errors.join(" ")}</p>
      </article>
    );
  }
  return (
    <article className="card spec-card">
      <div className="card-header">
        <div>
          <div className="eyebrow">{spec.surface_kind || "Rendered for this question"}</div>
          <h2>{spec.title}</h2>
        </div>
      </div>
      <p className="spec-summary">{spec.intent_summary}</p>
      {spec.data_boundary_notice ? <p className="consequence">{spec.data_boundary_notice}</p> : null}
      <div className="spec-blocks">
        {spec.blocks.map((block, index) => (
          <RenderBlockView key={index} block={block} onPrompt={onPrompt} onAction={onAction} />
        ))}
      </div>
    </article>
  );
}

function RenderBlockView({ block, onPrompt, onAction }: { block: RenderBlock; onPrompt: (prompt: string) => void; onAction: DirectActionHandler }) {
  if (block.type === "decision_brief") {
    return (
      <section className="spec-block">
        <h3>{block.title}</h3>
        <p>{block.body}</p>
      </section>
    );
  }
  if (block.type === "fact_strip") {
    return (
      <section className="fact-grid">
        {block.facts.map((fact) => <Fact key={fact.label} label={fact.label} value={fact.value} tone={fact.tone} />)}
      </section>
    );
  }
  if (block.type === "action_draft") {
    return (
      <section className="draft-block">
        <div className="eyebrow">{block.label}</div>
        <pre>{block.body}</pre>
        {block.note ? <p>{block.note}</p> : null}
      </section>
    );
  }
  if (block.type === "source_list") {
    return (
      <section className="spec-block">
        {block.sources.map((source) => (
          <p key={source.label}><strong>{source.label}</strong> {source.detail}</p>
        ))}
      </section>
    );
  }
  if (block.type === "choice_set") {
    return (
      <section className="choice-block">
        <h3>{block.question}</h3>
        <div className="action-bar">
          {block.choices.map((choice) => (
            <button
              key={choice.label}
              className={choice.style === "primary" ? "primary" : "secondary"}
              onClick={() => {
                if (choice.action) {
                  onAction(choice.action, choice.label);
                  return;
                }
                onPrompt(choice.intent);
              }}
            >
              {choice.label}
            </button>
          ))}
        </div>
      </section>
    );
  }
  return (
    <section className="spec-block">
      <h3>{block.title}</h3>
      <p>{block.body}</p>
    </section>
  );
}

function UnknownView({ view }: { view: ViewEnvelope }) {
  return (
    <article className="card">
      <div className="card-header">
        <div>
          <div className="eyebrow">Unknown view</div>
          <h2>{view.type}</h2>
        </div>
      </div>
      <pre className="json-preview">{JSON.stringify(view.data, null, 2)}</pre>
    </article>
  );
}

function Fact({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className={`fact ${tone || ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

type DashboardTrackItem = TaskItem & {
  task_id?: string;
  title?: string;
  due_at?: string;
  priority?: string;
  task_type?: string;
  source_type?: string;
  source_id?: string;
};

type DashboardWaitingItem = (typeof dashboardWaitingSeed)[number];
type DashboardNoticeItem = (typeof dashboardNoticeSeed)[number];
type DashboardWatchItem = (typeof dashboardWatchSeed)[number];
type DashboardSurfaceMode = "board" | "calendar" | "timeline";
type DashboardHorizon = "this-week" | "next-30" | "this-month" | "next-month" | "quarter";

type DashboardEvent = {
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

type DashboardCalendarGroup = {
  dateKey: string;
  label: string;
  items: DashboardEvent[];
};

const horizonMetaMap: Record<
  DashboardHorizon,
  { title: string; description: string; calendarTitle: string; timelineTitle: string }
> = {
  "this-week": {
    title: "This week across your client portfolio",
    description:
      "Open deadlines, blockers, notices, and watchlist items in one place.",
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
    description:
      "Review the current month without limiting the board to only urgent items.",
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

function itemSelectionValue(
  item: DashboardTrackItem | DashboardWaitingItem | DashboardNoticeItem | DashboardWatchItem,
  lane: DashboardLane
): string {
  if (lane === "track") return String((item as DashboardTrackItem).deadline_id || "");
  if (lane === "notices") return String((item as DashboardNoticeItem).notice_id || "");
  return String((item as DashboardWaitingItem | DashboardWatchItem).client_id || "");
}

function extractTrackItems(view: ViewEnvelope): DashboardTrackItem[] {
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

function buildDashboardEvents(
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

function filterDashboardEventsByHorizon(
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

function groupDashboardEventsByDate(events: DashboardEvent[]): DashboardCalendarGroup[] {
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

function normalizeDashboardDate(label: string, daysRemaining: number): string {
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

function urgencyClass(item: TaskItem | DashboardTrackItem): "urgent" | "medium" | "low" {
  const normalizedStatus = String(item.status || "").toLowerCase();
  if (normalizedStatus.includes("blocked") || normalizedStatus.includes("overdue") || item.days_remaining <= 0) {
    return "urgent";
  }
  if (item.days_remaining <= 7) return "medium";
  return "low";
}

function badgeClass(urgency: "urgent" | "medium" | "low") {
  if (urgency === "urgent") return "urgent";
  if (urgency === "medium") return "medium";
  return "low";
}

function buildDashboardSummary(view: ViewEnvelope, seenVisualContexts: VisualContext[]) {
  const listData = view.type === "ListCard" ? (view.data as { items?: TaskItem[]; title?: string; headline?: string; description?: string }) : null;
  const items = listData?.items || [];
  const trackItems = items;
  const waitingItems = items.filter((item) => String(item.status || "").toLowerCase().includes("blocked") || Boolean(item.missing));
  const noticeItems = seenVisualContexts.filter((context) => context.view_type === "TaxChangeRadarCard");
  const watchItems = items.filter((item) => urgencyClass(item) !== "urgent");

  return {
    heroTitle: listData?.headline || "This week across the client portfolio",
    heroDescription:
      "Review active work, clear blockers, review policy changes, and decide which clients need attention next.",
    trackCount: trackItems.length,
    lanes: [
      {
        id: "track" as DashboardLane,
        label: "Track",
        count: trackItems.length,
        description: "Active work items that should move this week.",
        prompt: "Open today's work"
      },
      {
        id: "waiting" as DashboardLane,
        label: "Waiting on info",
        count: waitingItems.length,
        description: "Items blocked by missing documents or confirmations.",
        prompt: "Show blocked items"
      },
      {
        id: "notice" as DashboardLane,
        label: "Notice",
        count: Math.max(1, noticeItems.length),
        description: "Policy changes that may need review before they become work.",
        prompt: "Show notice review"
      },
      {
        id: "watchlist" as DashboardLane,
        label: "Watchlist",
        count: watchItems.length,
        description: "Clients or deadlines that deserve monitoring but are not urgent yet.",
        prompt: "Show upcoming deadlines"
      }
    ],
    laneMeta: {
      track: {
        eyebrow: "Track",
        title: "Work that should move now",
        description: "Use this lane to decide what gets worked first.",
        empty: "No active work is waiting in Track.",
        shortLabel: "Active work"
      },
      waiting: {
        eyebrow: "Waiting on info",
        title: "Blocked until someone responds",
        description: "Use this lane to clear blockers before you push more deadline work.",
        empty: "Nothing is blocked by missing information right now.",
        shortLabel: "Blocked"
      },
      notice: {
        eyebrow: "Notice",
        title: "Policy changes that need review",
        description: "Review official updates here before they become real work.",
        empty: "No current notices need review.",
        shortLabel: "Notice"
      },
      watchlist: {
        eyebrow: "Watchlist",
        title: "Accounts worth monitoring",
        description: "Keep an eye on these clients before they turn urgent.",
        empty: "No clients are on the watchlist right now.",
        shortLabel: "Watchlist"
      }
    },
    rows: [
      ...trackItems.slice(0, 6).map((item, index) => ({
        key: item.deadline_id || `${item.client_name}-${index}-track`,
        lane: "track" as DashboardLane,
        title: item.client_name || `Client ${index + 1}`,
        detail: [item.tax_type, item.jurisdiction].filter(Boolean).join(" · ") || "Deadline item",
        due: item.due_date,
        badge: item.status || "Open",
        urgency: urgencyClass(item),
        prompt: `Open item ${index + 1}`,
        secondaryPrompt: "Show source",
        secondaryLabel: "Show source",
        explanation: `${item.client_name || "This client"} has active work tied to ${item.tax_type || "a filing"} in ${item.jurisdiction || "the current jurisdiction"}.`
      })),
      ...waitingItems.slice(0, 4).map((item, index) => ({
        key: item.deadline_id || `${item.client_name}-${index}-waiting`,
        lane: "waiting" as DashboardLane,
        title: item.client_name || `Blocked client ${index + 1}`,
        detail: item.missing || [item.tax_type, item.jurisdiction].filter(Boolean).join(" · ") || "Missing information",
        due: item.due_date,
        badge: "Blocked",
        urgency: "urgent" as const,
        prompt: `Open ${item.client_name || `item ${index + 1}`}`,
        secondaryPrompt: `prepare request for ${item.client_name || "this client"}`,
        secondaryLabel: "Prepare request",
        explanation: `${item.client_name || "This client"} is blocked by missing information. Clear the blocker first, then return to the filing work.`
      })),
      ...noticeItems.slice(0, 4).map((context, index) => ({
        key: `notice-${index}-${context.summary}`,
        lane: "notice" as DashboardLane,
        title: context.headline || "Notice review",
        detail: context.summary,
        due: "",
        badge: "Needs review",
        urgency: "medium" as const,
        prompt: "Show notice review",
        secondaryPrompt: "Show notice review",
        secondaryLabel: "Review notice",
        explanation: "This lane holds official changes that may affect clients or deadlines. Review the notice before converting it into active work."
      })),
      ...watchItems.slice(0, 4).map((item, index) => ({
        key: item.deadline_id || `${item.client_name}-${index}-watch`,
        lane: "watchlist" as DashboardLane,
        title: item.client_name || `Watch client ${index + 1}`,
        detail: [item.tax_type, item.jurisdiction].filter(Boolean).join(" · ") || "Monitor this account",
        due: item.due_date,
        badge: "Watch",
        urgency: urgencyClass(item),
        prompt: `Open ${item.client_name || `item ${index + 1}`}`,
        secondaryPrompt: "Show upcoming deadlines",
        secondaryLabel: "Show upcoming",
        explanation: `${item.client_name || "This client"} is not urgent yet, but it is close enough to monitor before it turns into active work.`
      }))
    ],
    contexts: seenVisualContexts
      .filter((context) => context.view_type !== "ListCard")
      .slice(0, 4)
      .map((context) => ({
        headline: context.headline || context.selected_client || context.view_type,
        summary: context.summary,
        prompt: context.selected_client ? `Open ${context.selected_client}` : context.view_type === "TaxChangeRadarCard" ? "Show notice review" : "Open today's work"
      }))
  };
}

type DashboardLane = "track" | "waiting" | "notices" | "watchlist";

type QuickAction = { label: string; prompt?: string; action?: DirectAction };

function buildQuickActions(view: ViewEnvelope, actions: ActionPlan[]): QuickAction[] {
  const fromBackend = actions.slice(0, 3).map((action) => ({
    label: action.label,
    prompt: action.label,
    action: action.action || (action.plan ? { type: "direct_execute" as const, plan: action.plan } : undefined)
  }));
  if (fromBackend.length) return fromBackend;
  if (view.type === "GuidanceCard") {
    const data = view.data as { options?: string[] };
    return (data.options?.length ? data.options : ["Show today's work"]).slice(0, 3).map((option) => ({
      label: option,
      prompt: option
    }));
  }
  if (view.type === "ListCard") {
    const data = view.data as { suggested_prompts?: string[] };
    if (data.suggested_prompts?.length) {
      return data.suggested_prompts.slice(0, 3).map((prompt) => ({ label: prompt, prompt }));
    }
    return [];
  }
  if (view.type === "RenderSpecSurface") {
    const spec = view.data.render_spec as RenderSpec | undefined;
    const choiceBlock = spec?.blocks.find((block) => block.type === "choice_set");
    if (choiceBlock?.type === "choice_set") {
      return choiceBlock.choices.slice(0, 3).map((choice) => ({
        label: choice.label,
        prompt: choice.intent,
        action: choice.action
      }));
    }
  }
  return [];
}

function summarizeView(view: ViewEnvelope, actions: ActionPlan[]): VisualContext {
  const visibleActions = actions.map((action) => action.label).filter(Boolean);
  if (view.type === "ListCard") {
    const data = view.data as { headline?: string; title?: string; items?: TaskItem[] };
    const items = data.items || [];
    const clientNames = items.map((item, index) => item.client_name || `Item ${index + 1}`);
    return {
      view_type: view.type,
      headline: data.headline || data.title,
      visible_clients: clientNames,
      visible_deadlines: items.map((item, index) => `${clientNames[index]}: ${item.tax_type}, ${item.jurisdiction}, due ${item.due_date}, status ${item.status}`),
      visible_actions: visibleActions,
      summary: `${data.headline || data.title || "List"}; visible clients: ${clientNames.join(", ")}`
    };
  }
  if (view.type === "ClientCard") {
    const data = view.data as { client_name?: string; deadlines?: TaskItem[] };
    const deadlines = data.deadlines || [];
    return {
      view_type: view.type,
      headline: data.client_name,
      selected_client: data.client_name,
      visible_clients: data.client_name ? [data.client_name] : [],
      visible_deadlines: deadlines.map((item) => `${item.tax_type}, ${item.jurisdiction}, due ${item.due_date}, status ${item.status}`),
      visible_actions: visibleActions,
      summary: `${data.client_name || "Client"} detail; ${deadlines.map((item) => `${item.status}: ${item.missing || "no missing item"}`).join("; ")}`
    };
  }
  if (view.type === "HistoryCard") {
    const data = view.data as { client_name?: string; tax_type?: string; due_date?: string; status?: string; source_url?: string };
    return {
      view_type: view.type,
      headline: "Source and history",
      selected_client: data.client_name,
      visible_clients: data.client_name ? [data.client_name] : [],
      visible_deadlines: [`${data.tax_type || "deadline"}, due ${data.due_date || "unknown"}, status ${data.status || "unknown"}`],
      visible_actions: visibleActions,
      summary: `History for ${data.client_name || "current item"}; source ${data.source_url || "unknown"}`
    };
  }
  if (view.type === "RenderSpecSurface") {
    const spec = view.data.render_spec as RenderSpec | undefined;
    const draftBlock = spec?.blocks.find((block) => block.type === "action_draft");
    return {
      view_type: view.type,
      headline: spec?.title,
      visible_clients: extractClientNames(`${spec?.title || ""} ${spec?.intent_summary || ""}`),
      visible_deadlines: draftBlock?.type === "action_draft" ? [draftBlock.label] : [],
      visible_actions: visibleActions,
      summary: `${spec?.title || "Generated surface"}; ${spec?.intent_summary || "no summary"}`
    };
  }
  if (view.type === "TaxChangeRadarCard") {
    const data = view.data as {
      title?: string;
      primary_question?: string;
      impacted_deadlines?: Array<{ client_name?: string; tax_type?: string; due_date?: string }>;
    };
    return {
      view_type: view.type,
      headline: data.title || "Tax change radar",
      visible_clients: (data.impacted_deadlines || []).map((item) => item.client_name || "").filter(Boolean),
      visible_deadlines: (data.impacted_deadlines || []).map((item) => [item.client_name, item.tax_type, item.due_date].filter(Boolean).join(" · ")),
      visible_actions: visibleActions,
      summary: data.primary_question || data.title || "Tax change radar"
    };
  }
  if (view.type === "GuidanceCard") {
    const data = view.data as { message?: string; options?: string[] };
    return {
      view_type: view.type,
      headline: "Need context",
      visible_clients: [],
      visible_deadlines: [],
      visible_actions: [...visibleActions, ...(data.options || [])].slice(0, 6),
      summary: data.message || "Guidance needs one more bit of context"
    };
  }
  return {
    view_type: view.type,
    visible_clients: extractClientNames(JSON.stringify(view.data)),
    visible_deadlines: [],
    visible_actions: visibleActions,
    summary: `${view.type} view`
  };
}

function extractClientNames(text: string): string[] {
  const names = new Set<string>();
  for (const match of text.matchAll(/\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\s+(?:LLC|Inc|Corp|Dental|Manufacturing|Consulting))\b/g)) {
    names.add(match[1]);
  }
  return [...names];
}

function surfaceTitle(view: ViewEnvelope): string {
  if (view.type === "ListCard") return (view.data as { title?: string }).title || "Deadline list";
  if (view.type === "ClientCard") return "Focused client";
  if (view.type === "ConfirmCard") return "Confirm change";
  if (view.type === "HistoryCard") return "Source and history";
  if (view.type === "GuidanceCard") return "Need context";
  if (view.type === "TaxChangeRadarCard") return "Tax change radar";
  if (view.type === "RenderSpecSurface") return "Next step";
  return "Work surface";
}

function surfaceSummary(view: ViewEnvelope): string {
  if (view.type === "ListCard") {
    const data = view.data as { description?: string; items?: TaskItem[] };
    return data.description || `${data.items?.length || 0} deadline items ready for review.`;
  }
  if (view.type === "ClientCard") return "Review one client before you confirm or outreach.";
  if (view.type === "ConfirmCard") return "This step writes back to the backend, so DueDateHQ asks for confirmation first.";
  if (view.type === "HistoryCard") return "Trace the source, due date, and status changes before you act.";
  if (view.type === "GuidanceCard") return "Use one of the suggested prompts so the workspace can stay constrained and actionable.";
  if (view.type === "TaxChangeRadarCard") return "Review external signals before they turn into active work.";
  if (view.type === "RenderSpecSurface") return "This is a generated work surface for an open-ended question.";
  return "Review the current work surface.";
}

function humanIntentStatus(intentLabel?: string, planSource?: string): string {
  const labels: Record<string, string> = {
    today: "I'll open today's work first.",
    context_advice: "I'll answer from the current workspace before changing the right side.",
    client_deadline_list: "I'll open the current client's active items first.",
    deadline_history: "I'll show the source and audit history first.",
    deadline_action_complete: "This writes back to the backend, so I'll ask for confirmation first.",
    notification_preview: "I'll show the next reminder set first.",
    upcoming_deadlines: "I'll open future deadlines first so you can narrow the scope.",
    completed_deadlines: "I'll show completed items first so you can review them.",
    ad_hoc_render_spec: "This request is open-ended, so I'll turn it into a constrained work surface first."
  };
  const base = labels[intentLabel || ""] || "I'm organizing this request.";
  if (!planSource || planSource === "context_answer") return base;
  return base;
}
