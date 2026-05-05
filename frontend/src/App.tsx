// App.tsx
// Slim shell for the DueDateHQ "traditional" frontend (codex/frontend-core-flow).
//
// Information architecture (per duedatehq-frontend-skill/SKILL.md):
//   - 4 top-level sections: Work / Clients / Review / Settings.
//   - Section body renders rich, structured UI from mockData (sections.tsx).
//   - Ask lives as a tool entry, not as a top-level destination.
//   - When chat resolves to a ViewEnvelope (ClientCard, ConfirmCard, etc.),
//     App overlays a drilldown card on top of the active section.
//
// What this file is NOT:
//   - It is not where business logic lives — that's in the backend / cards.tsx.
//   - It does not invent new view types, plan types, or design tokens.

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { bootstrapToday, executeAction, streamChat } from "./apiClient";
import { mockDeadlines, mockRules } from "./mockData";
import type {
  ActionPlan,
  ChatMessage,
  DirectAction,
  ViewEnvelope,
  VisualContext
} from "./types";
import { ViewRenderer } from "./cards";
import { id, MessageBubble } from "./coreUI";
import {
  appendBreadcrumb,
  buildQuickActions,
  buildWorkspaceSnapshot,
  humanIntentStatus,
  summarizeView
} from "./chatHelpers";
import {
  SectionId,
  SectionNav,
  sectionComponents,
  sectionMeta
} from "./sections";

const tenantId = import.meta.env.VITE_DUEDATEHQ_TENANT_ID || "2403c5e1-85ac-4593-86cc-02f8d97a8d92";
const apiBase = import.meta.env.VITE_DUEDATEHQ_API_BASE || "http://127.0.0.1:8000";

const initialActions: ActionPlan[] = [];

// View types that should NOT pop the drilldown overlay — these either
// duplicate what the active section already shows, or are low-information
// fallbacks the user complained about ("Need one more bit of context").
const SECTION_NATIVE_VIEWS = new Set([
  "ListCard",
  "ClientListCard",
  "ReminderPreviewCard",
  "ReviewQueueCard",
  "GuidanceCard"
]);

export function App() {
  const [currentSection, setCurrentSection] = useState<SectionId>("work");
  const [appMode, setAppMode] = useState<"dashboard" | "chat">("dashboard");
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: id(), role: "system", text: "Ask DueDateHQ — try 'Open Northwind Services' or 'Plan workload for next 30 days'." }
  ]);
  const [view, setView] = useState<ViewEnvelope | null>(null);
  const [actions, setActions] = useState<ActionPlan[]>(initialActions);
  const [seenVisualContexts, setSeenVisualContexts] = useState<VisualContext[]>([]);
  const [input, setInput] = useState("");
  const [session, setSession] = useState<Record<string, unknown>>({
    tenant_id: tenantId,
    session_id: "frontend-validation-session",
    today: "2026-04-26"
  });
  const [busy, setBusy] = useState(false);
  const [apiBootstrapped, setApiBootstrapped] = useState(false);
  const [drilldownOpen, setDrilldownOpen] = useState(false);
  const [backendState, setBackendState] = useState<"connecting" | "ready" | "degraded" | "offline">("connecting");
  const [sectionNotice, setSectionNotice] = useState<{
    id: string;
    text: string;
    tone: "green" | "blue" | "gold" | "red";
  }[]>([]);
  const [messagesOpen, setMessagesOpen] = useState(false);
  const [docsOpen, setDocsOpen] = useState(false);
  const [portfolioDeadlines, setPortfolioDeadlines] = useState(() => mockDeadlines.map((d) => ({ ...d })));
  const [portfolioRules, setPortfolioRules] = useState(() => mockRules.map((r) => ({ ...r })));
  const [resolvedRuleIds, setResolvedRuleIds] = useState<string[]>([]);
  const [changedDeadlineIds, setChangedDeadlineIds] = useState<string[]>([]);
  const [reviewFocusRuleId, setReviewFocusRuleId] = useState<string | null>(null);
  const streamRef = useRef<HTMLDivElement | null>(null);
  const messageMenuRef = useRef<HTMLDivElement | null>(null);

  // Track recent visual contexts so the agent kernel knows what the CPA has
  // already seen when it decides what to render next.
  useEffect(() => {
    if (!view) return;
    const context = summarizeView(view, actions);
    setSeenVisualContexts((current) =>
      [context, ...current.filter((item) => item.summary !== context.summary)].slice(0, 8)
    );
  }, [view, actions]);

  // Bootstrap once — this is best-effort. If the backend is offline, the
  // frontend still renders fine because every section uses mockData.
  useEffect(() => {
    if (apiBootstrapped) return;
    setApiBootstrapped(true);
    void loadBackendOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBootstrapped]);

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
      current.map((message) => (message.id === messageId ? { ...message, text } : message))
    );
    scrollStream();
  }

  function showSectionNotice(text: string, tone: "green" | "blue" | "gold" | "red" = "blue") {
    setSectionNotice((current) => [{ id: id(), text, tone }, ...current].slice(0, 8));
  }

  function dismissSectionNotice(noticeId: string) {
    setSectionNotice((current) => current.filter((notice) => notice.id !== noticeId));
  }

  useEffect(() => {
    if (!messagesOpen) return;
    function onDocClick(event: MouseEvent) {
      if (!messageMenuRef.current) return;
      if (!messageMenuRef.current.contains(event.target as Node)) setMessagesOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMessagesOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [messagesOpen]);

  // Pop the drilldown overlay only when the resolved envelope adds
  // information beyond what the active section already shows.
  function maybeOpenDrilldown(envelope: ViewEnvelope | null) {
    if (!envelope) return;
    if (appMode !== "chat") return;
    if (SECTION_NATIVE_VIEWS.has(envelope.type)) return;
    setDrilldownOpen(true);
  }

  // ---------- Backend round-trips ----------

  async function loadBackendOverview() {
    setBusy(true);
    try {
      const result = await bootstrapToday({
        apiBase,
        tenantId,
        session: { ...session, current_view: view }
      });
      if (result.response.view) setView(result.response.view);
      setActions(result.response.actions || []);
      setSession(result.session);
      setBackendState("ready");
    } catch {
      // Backend not running is fine — sections still render from mockData.
      setBackendState("offline");
    } finally {
      setBusy(false);
    }
  }

  async function submit(value = input, userEcho?: string) {
    const cleaned = value.trim();
    if (!cleaned || busy) return;
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
          visual_context: view ? summarizeView(view, actions) : null,
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
            if (update.view) {
              setView(update.view);
              maybeOpenDrilldown(update.view);
            }
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
      append(
        "system",
        `The AI backend is unavailable. No records were changed. Please confirm FastAPI is running, then try again. ${String(error)}`
      );
    } finally {
      setBusy(false);
    }
  }

  async function runDirectAction(action: DirectAction, userEcho?: string) {
    if (busy) return;

    if (action.type === "agent_input" && action.text) {
      await submit(action.text, userEcho);
      return;
    }
    if (action.type !== "direct_execute") return;

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
      maybeOpenDrilldown(nextView);
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
          visual_context: view ? summarizeView(view, actions) : null,
          seen_visual_contexts: seenVisualContexts.slice(0, 6)
        },
        action
      });
      if (result.response.view) {
        setView(result.response.view);
        maybeOpenDrilldown(result.response.view);
      }
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

  // Sections dispatch plans through this callback (kept for backward-compat).
  // The section bodies no longer call dispatch automatically — they own their
  // own structured rendering — but a section may still call dispatch for an
  // explicit deep-dive into the chat envelope flow.
  const dispatchSectionPlan = useCallback(
    (plan: Record<string, unknown>, expectedView: string) => {
      void runDirectAction({
        type: "direct_execute",
        plan,
        expected_view: expectedView
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [session, view, actions, seenVisualContexts]
  );

  // Export prompt — routed through chat so the backend's export.export plan
  // path is the one source of truth, but the user got there via a button.
  function handleExport(scope: string, format: "csv" | "pdf") {
    showSectionNotice(
      `${format.toUpperCase()} export prepared for ${scope}. In this demo, the export stays inside the dashboard flow.`,
      "green"
    );
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  const quickActions = view ? buildQuickActions(view, actions) : [];
  const statusLabel =
    backendState === "ready"
      ? "Live backend"
      : backendState === "degraded"
        ? "Backend issue"
        : backendState === "offline"
          ? "Demo data"
          : "Connecting";

  const SectionComponent = sectionComponents[currentSection];
  const meta = sectionMeta[currentSection];
  const modeStatusTone =
    backendState === "ready"
      ? "green"
      : backendState === "degraded"
        ? "red"
        : backendState === "offline"
          ? "blue"
          : "gold";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          DueDate<em>HQ</em>
        </div>
        <div className="topbar-center">
          <SectionNav
            current={currentSection}
            onSelect={(section) => {
              setCurrentSection(section);
              if (section !== "review") setReviewFocusRuleId(null);
              setAppMode("dashboard");
              setDrilldownOpen(false);
            }}
          />
        </div>
        <div className="topbar-right">
          <button
            type="button"
            className={`topbar-ask-btn ${appMode === "chat" ? "active" : ""}`}
            onClick={() => setAppMode((current) => (current === "chat" ? "dashboard" : "chat"))}
          >
            Ask
          </button>
          <button
            type="button"
            className="topbar-ask-btn"
            onClick={() => setDocsOpen(true)}
          >
            Docs
          </button>
          <div className="tenant-name">Johnson CPA PLLC</div>
          <div className="message-shell" ref={messageMenuRef}>
            <button
              type="button"
              className="message-trigger"
              aria-label="Open page messages"
              onClick={() => setMessagesOpen((current) => !current)}
            >
              <span className="message-icon" aria-hidden="true">◔</span>
              {sectionNotice.length ? <span className="message-count">{sectionNotice.length}</span> : null}
            </button>
            {messagesOpen ? (
              <div className="message-menu">
                <div className="message-menu-head">
                  <strong>Page messages</strong>
                  <span>{sectionNotice.length} item{sectionNotice.length === 1 ? "" : "s"}</span>
                </div>
                {sectionNotice.length ? (
                  <ul className="message-list">
                    {sectionNotice.map((notice) => (
                      <li key={notice.id} className={`message-row ${notice.tone}`}>
                        <div className="message-row-copy">
                          <span className="message-row-label">Current page</span>
                          <p>{notice.text}</p>
                        </div>
                        <button
                          type="button"
                          className="ghost-btn"
                          onClick={() => dismissSectionNotice(notice.id)}
                        >
                          Dismiss
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="message-empty">No messages yet.</div>
                )}
              </div>
            ) : null}
          </div>
          <div className={`connection-pill ${backendState}`}>{statusLabel}</div>
          <div className="avatar">SJ</div>
        </div>
      </header>

      {appMode === "dashboard" ? (
        <main className="section-main">
          <section className="render-panel">
            <div className="surface-meta">
              <div>
                <div className="eyebrow">{meta.eyebrow}</div>
                <h1>{meta.title}</h1>
                <p className="surface-summary">{meta.subtitle}</p>
              </div>
            </div>
            <SectionComponent
              tenantId={tenantId}
              view={view ?? { type: "GuidanceCard", data: {}, selectable_items: [] }}
              busy={busy}
              dispatch={dispatchSectionPlan}
              openSection={(section, options) => {
                setCurrentSection(section);
                if (section === "review") {
                  setReviewFocusRuleId(options?.ruleId || null);
                } else {
                  setReviewFocusRuleId(null);
                }
                setAppMode("dashboard");
                setDrilldownOpen(false);
              }}
              onPrompt={() =>
                showSectionNotice(
                  "That action belongs to Chat mode. Use the Chat button in the top bar if you want to continue in the conversational workspace.",
                  "blue"
                )
              }
              onAction={() =>
                showSectionNotice(
                  "That action belongs to Chat mode. Use the Chat button in the top bar if you want to continue in the conversational workspace.",
                  "blue"
                )
              }
              onExport={handleExport}
              onNotify={showSectionNotice}
              deadlines={portfolioDeadlines}
              setDeadlines={setPortfolioDeadlines}
              rules={portfolioRules}
              setRules={setPortfolioRules}
              resolvedRuleIds={resolvedRuleIds}
              setResolvedRuleIds={setResolvedRuleIds}
              changedDeadlineIds={changedDeadlineIds}
              setChangedDeadlineIds={setChangedDeadlineIds}
              reviewFocusRuleId={reviewFocusRuleId}
            />
          </section>
        </main>
      ) : (
        <main className="chat-workspace-shell">
          <section className="workspace-stage">
            <div className="workspace-stage-head">
              <div>
                <div className="eyebrow">Current workspace</div>
                <h1>{view ? view.type : "Chat workspace"}</h1>
                <p className="surface-summary">
                  {view
                    ? "Structured work surfaces generated from the conversation live here."
                    : "Start a conversation to generate a work surface, client card, or next-step confirmation."}
                </p>
              </div>
              <div className="status-pills">
                <span className={`pill ${modeStatusTone}`}>{statusLabel}</span>
              </div>
            </div>
            <div className="workspace-stage-body">
              {view ? (
                <div className="workspace-surface-card">
                  <ViewRenderer
                    view={view}
                    onPrompt={(prompt) => void submit(prompt)}
                    onAction={(action, label) => void runDirectAction(action, label)}
                    tenantId={tenantId}
                  />
                </div>
              ) : (
                <section className="card workspace-empty">
                  <div className="eyebrow">No workspace yet</div>
                  <h2>Ask a question to generate the first work surface</h2>
                  <p>
                    Try opening a client, planning work for the next 30 days, or asking for a notice review.
                  </p>
                </section>
              )}
            </div>
          </section>

          <aside className="chat-panel" aria-label="Chat workspace">
            <div className="chat-header">
              <div className="chat-header-label">Conversation</div>
              <div className="chat-header-date">Sarah's work queue</div>
            </div>
            <div className="stream" ref={streamRef}>
              {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
            </div>
            {quickActions.length ? (
              <>
                <div className="quick-actions-label">Suggested next steps</div>
                <div className="quick-actions">
                  {quickActions.map((action) => (
                    <button
                      key={action.label}
                      className="quick-btn"
                      type="button"
                      onClick={() =>
                        action.action
                          ? void runDirectAction(action.action, action.label)
                          : void submit(action.prompt || action.label, action.label)
                      }
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              </>
            ) : null}
            <form className="composer" onSubmit={onSubmit}>
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask DueDateHQ what to do next"
              />
              <button type="submit" disabled={busy}>
                {busy ? "..." : "Send"}
              </button>
            </form>
          </aside>
        </main>
      )}

      {appMode === "chat" && drilldownOpen && view ? (
        <div
          className="drilldown-overlay"
          role="dialog"
          aria-modal="true"
          onClick={() => setDrilldownOpen(false)}
        >
          <div className="drilldown-panel" onClick={(event) => event.stopPropagation()}>
            <div className="drilldown-head">
              <div>
                <div className="eyebrow">From chat</div>
                <h2>{view.type}</h2>
              </div>
              <button
                type="button"
                className="chat-close"
                aria-label="Close detail"
                onClick={() => setDrilldownOpen(false)}
              >
                ×
              </button>
            </div>
            <div className="drilldown-body">
              <ViewRenderer
                view={view}
                onPrompt={(prompt) => void submit(prompt)}
                onAction={(action, label) => void runDirectAction(action, label)}
                tenantId={tenantId}
              />
            </div>
          </div>
        </div>
      ) : null}

      {docsOpen ? (
        <div
          className="docs-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="DueDateHQ docs"
          onClick={() => setDocsOpen(false)}
        >
          <section className="docs-panel" onClick={(event) => event.stopPropagation()}>
            <div className="docs-head">
              <div>
                <div className="eyebrow">Docs</div>
                <h2>DueDateHQ demo and CLI guide</h2>
                <p>
                  A compact operator guide for the current MVP: what to demo, what each screen means,
                  where AI participates, and which backend routes support the flow.
                </p>
              </div>
              <button type="button" className="chat-close" aria-label="Close docs" onClick={() => setDocsOpen(false)}>
                ×
              </button>
            </div>

            <div className="docs-grid">
              <article className="docs-card docs-wide">
                <span className="docs-kicker">Product frame</span>
                <h3>What DueDateHQ is</h3>
                <p>
                  DueDateHQ is a CPA practice-management dashboard for tax deadlines. It does not prepare or file returns.
                  It helps the CPA import a client portfolio, derive deadline work, monitor official rule changes,
                  decide what needs attention this week, and document follow-up actions.
                </p>
                <p>
                  The smallest operational unit is a work item: client, tax type, jurisdiction, due date,
                  status, assignee, source, reminders, blocker, extension state, and activity history.
                </p>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">5-minute demo</span>
                <h3>Run of show</h3>
                <ol>
                  <li><strong>Import:</strong> upload CSV, map columns, review rows, create or update clients.</li>
                  <li><strong>Weekly triage:</strong> open Work, check Work now / Blocked / Needs review / Archive.</li>
                  <li><strong>Rule change:</strong> open Review, inspect source and affected clients, apply or dismiss.</li>
                </ol>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">Screen logic</span>
                <h3>Where to look</h3>
                <ul>
                  <li><strong>Work</strong> is the Monday triage queue: active work, blocked items, review-driven work, and archive.</li>
                  <li><strong>Clients</strong> is the portfolio directory: profile, derived deadlines, blockers, reminders, and recent activity.</li>
                  <li><strong>Review</strong> is the official-change queue: source, diff, affected clients, apply/dismiss decision.</li>
                  <li><strong>Settings</strong> holds editable defaults and reminder channels, not operational status history.</li>
                </ul>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">State model</span>
                <h3>Work item flow</h3>
                <ul>
                  <li><strong>Active</strong> means the CPA can work on it now.</li>
                  <li><strong>Blocked</strong> means a client document, confirmation, or profile detail is missing.</li>
                  <li><strong>Needs review</strong> means a rule or notice needs a CPA decision before it changes work.</li>
                  <li><strong>Extension approved</strong> means an extension was filed and can be revoked in demo.</li>
                  <li><strong>Archived</strong> means the work was handled and removed from the active queue.</li>
                </ul>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">AI assist</span>
                <h3>Where AI participates</h3>
                <ul>
                  <li><strong>Import mapping:</strong> infer CSV fields and explain rows that need attention.</li>
                  <li><strong>Policy interpretation:</strong> summarize official source text and identify affected clients.</li>
                  <li><strong>Client follow-up:</strong> draft an email from the selected work item, blocker, contact, and due date.</li>
                </ul>
                <p>AI is intentionally lightweight in the UI: show it only at moments where it transforms messy input into structured work.</p>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">Backend demo APIs</span>
                <h3>Routes to verify</h3>
                <code>POST /import/preview</code>
                <code>POST /review/interpret/&lt;tenant_id&gt;</code>
                <code>GET /review/impact/&lt;tenant_id&gt;</code>
                <code>POST /clients/&lt;tenant_id&gt;/&lt;client_id&gt;/email/draft</code>
                <code>PATCH /settings/&lt;tenant_id&gt;/notification-routes/&lt;route_id&gt;</code>
              </article>

              <article className="docs-card docs-wide">
                <span className="docs-kicker">Local commands</span>
                <h3>Operator checklist</h3>
                <code>cd frontend && VITE_DUEDATEHQ_API_BASE=http://127.0.0.1:8000 npm run dev</code>
                <code>uv run --with fastapi --with uvicorn uvicorn duedatehq.http_api:create_fastapi_app --factory --reload --port 8000</code>
                <code>uv run python scripts/seed_small_demo.py</code>
                <code>uv run python -m duedatehq.cli import preview demo-data/due-datehq-demo-import.csv</code>
              </article>
            </div>

            <div className="docs-foot">
              Full repo docs: <code>docs/demo-operator-guide.md</code>, <code>docs/duedatehq-prd.md</code>, <code>docs/cli-reference.md</code>, and <code>handoff/redesign-v2-handoff.md</code>.
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
