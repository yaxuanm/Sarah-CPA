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
  const [accountOpen, setAccountOpen] = useState(false);
  const [docsOpen, setDocsOpen] = useState(false);
  const [portfolioDeadlines, setPortfolioDeadlines] = useState(() => mockDeadlines.map((d) => ({ ...d })));
  const [portfolioRules, setPortfolioRules] = useState(() => mockRules.map((r) => ({ ...r })));
  const [resolvedRuleIds, setResolvedRuleIds] = useState<string[]>([]);
  const [changedDeadlineIds, setChangedDeadlineIds] = useState<string[]>([]);
  const [reviewFocusRuleId, setReviewFocusRuleId] = useState<string | null>(null);
  const streamRef = useRef<HTMLDivElement | null>(null);
  const messageMenuRef = useRef<HTMLDivElement | null>(null);
  const accountMenuRef = useRef<HTMLDivElement | null>(null);

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

  useEffect(() => {
    if (!accountOpen) return;
    function onDocClick(event: MouseEvent) {
      if (!accountMenuRef.current) return;
      if (!accountMenuRef.current.contains(event.target as Node)) setAccountOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setAccountOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [accountOpen]);

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
          <div className="account-menu-shell" ref={accountMenuRef}>
            <button
              type="button"
              className={`tenant-name account-trigger ${accountOpen ? "open" : ""}`}
              onClick={() => setAccountOpen((current) => !current)}
              aria-haspopup="menu"
              aria-expanded={accountOpen}
            >
              Johnson CPA PLLC
            </button>
            {accountOpen ? (
              <div className="account-menu" role="menu">
                <div className="account-menu-head">
                  <strong>Johnson CPA PLLC</strong>
                  <span>Signed in as Sarah Johnson</span>
                </div>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setCurrentSection("settings");
                    setAppMode("dashboard");
                    setDrilldownOpen(false);
                    setAccountOpen(false);
                  }}
                >
                  Workspace settings
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setDocsOpen(true);
                    setAccountOpen(false);
                  }}
                >
                  Product docs
                </button>
                <button type="button" role="menuitem" disabled>
                  Log out
                </button>
              </div>
            ) : null}
          </div>
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
                <h2>DueDateHQ product guide</h2>
                <p>
                  Learn how to import clients, review deadline work, handle official tax changes,
                  and keep your client portfolio current.
                </p>
              </div>
              <button type="button" className="chat-close" aria-label="Close docs" onClick={() => setDocsOpen(false)}>
                ×
              </button>
            </div>

            <div className="docs-grid">
              <article className="docs-card docs-wide">
                <span className="docs-kicker">Overview</span>
                <h3>What DueDateHQ helps you manage</h3>
                <p>
                  DueDateHQ keeps client tax deadlines, blockers, rule-change reviews, reminders,
                  extensions, and archived work in one operational dashboard.
                </p>
                <p>
                  It is designed for planning and triage. It helps you decide what should happen next,
                  but it does not prepare or file tax returns inside the product.
                </p>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">Ask</span>
                <h3>Use generated workspaces</h3>
                <ul>
                  <li>Click <strong>Ask</strong> when you want a focused workspace for a specific question or workflow.</li>
                  <li>Ask in plain language, such as “show blocked California clients” or “summarize what changed this week.”</li>
                  <li>The system renders a temporary workspace beside the conversation, instead of forcing every request into the fixed dashboard layout.</li>
                  <li>Use the main dashboard for source-of-truth work such as importing clients, editing work items, applying rule changes, and archiving.</li>
                </ul>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">Clients</span>
                <h3>Import clients</h3>
                <ol>
                  <li>Open <strong>Clients</strong>, then choose <strong>Import</strong>.</li>
                  <li>Upload a CSV exported from your existing client system.</li>
                  <li>Review column mapping and fix any fields that were mapped incorrectly.</li>
                  <li>Review the detected rows before anything is added or updated.</li>
                  <li>Finish import to create new clients or update matching clients in place.</li>
                </ol>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">Work</span>
                <h3>Use the work queue</h3>
                <ul>
                  <li><strong>Work now</strong> shows items that can be acted on immediately.</li>
                  <li><strong>Blocked</strong> shows items waiting on documents, confirmation, or profile details.</li>
                  <li><strong>Needs review</strong> shows work connected to an official change that still needs a CPA decision.</li>
                  <li><strong>Archive</strong> keeps completed or dismissed items out of the active queue.</li>
                </ul>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">Details</span>
                <h3>Open a work item</h3>
                <ul>
                  <li>Use <strong>Edit task</strong> to change the title, assignee, due date, priority, note, or blocker reason.</li>
                  <li>Use <strong>Actions</strong> to file or revoke an extension, mark the item blocked, resolve a blocker, or archive the item.</li>
                  <li>Use <strong>Client follow-up</strong> when the next step is asking the client for missing information.</li>
                  <li>Reminder and blocker panels show what is already scheduled and why the item may be stuck.</li>
                </ul>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">Review</span>
                <h3>Review official changes</h3>
                <ul>
                  <li>Open <strong>Review</strong> when an official rule or notice may affect your portfolio.</li>
                  <li>Open a row to inspect the source, the before/after change, and affected clients.</li>
                  <li>Choose <strong>Apply</strong> when the change should update related client work.</li>
                  <li>Choose <strong>Dismiss</strong> when the change does not apply to the current portfolio.</li>
                </ul>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">Clients</span>
                <h3>Read a client profile</h3>
                <ul>
                  <li>The profile summarizes entity type, state footprint, tax scope, contacts, and next due date.</li>
                  <li>The deadline calendar lists derived work for that client.</li>
                  <li>Client history shows recent imports, blockers, reminders, and changes that affected this client.</li>
                  <li>Export creates a CSV or PDF view for sharing outside the dashboard.</li>
                </ul>
              </article>

              <article className="docs-card">
                <span className="docs-kicker">Settings</span>
                <h3>Configure reminders</h3>
                <ul>
                  <li>Set the default reminder cadence for deadline work.</li>
                  <li>Connect email or messaging channels for CPA reminders.</li>
                  <li>Update firm defaults without changing individual client records.</li>
                  <li>Settings are for configuration, not for daily work history.</li>
                </ul>
              </article>

              <article className="docs-card docs-wide">
                <span className="docs-kicker">Glossary</span>
                <h3>Status terms</h3>
                <div className="docs-glossary">
                  <p><strong>Active</strong><span>The work can move forward now.</span></p>
                  <p><strong>Blocked</strong><span>Something is missing before work can continue.</span></p>
                  <p><strong>Needs review</strong><span>A CPA decision is required before the item changes state.</span></p>
                  <p><strong>Overdue</strong><span>The due date has passed and the item is still not archived.</span></p>
                  <p><strong>Extension approved</strong><span>An extension has been filed and the effective due date changed.</span></p>
                  <p><strong>Archived</strong><span>The item is handled and removed from active triage.</span></p>
                </div>
              </article>

              <article className="docs-card docs-wide docs-tech-card">
                <span className="docs-kicker">Technical reference</span>
                <h3>Local demo, CLI, and API</h3>
                <div className="docs-tech-grid">
                  <div>
                    <h4>Run locally</h4>
                    <code>cd frontend && VITE_DUEDATEHQ_API_BASE=http://127.0.0.1:8000 npm run dev</code>
                    <code>uv run --with fastapi --with uvicorn uvicorn duedatehq.http_api:create_fastapi_app --factory --reload --port 8000</code>
                    <code>uv run python scripts/seed_small_demo.py</code>
                  </div>
                  <div>
                    <h4>CLI</h4>
                    <code>uv run python -m duedatehq.cli --help</code>
                    <code>uv run python -m duedatehq.cli import preview demo-data/due-datehq-demo-import.csv</code>
                    <code>uv run python -m duedatehq.cli notify config add &lt;tenant_id&gt; --channel email --destination ops@example.com</code>
                  </div>
                  <div>
                    <h4>API routes</h4>
                    <code>POST /bootstrap/today</code>
                    <code>POST /import/preview</code>
                    <code>POST /review/interpret/&lt;tenant_id&gt;</code>
                    <code>GET /review/impact/&lt;tenant_id&gt;</code>
                    <code>POST /clients/&lt;tenant_id&gt;/&lt;client_id&gt;/email/draft</code>
                  </div>
                  <div>
                    <h4>AI behavior</h4>
                    <p>
                      AI assist uses Anthropic when <code>ANTHROPIC_API_KEY</code> or <code>CLAUDE_API_KEY</code> is configured.
                      Without credentials, the same endpoints return deterministic fallback output so the demo remains stable.
                    </p>
                    <p>Primary AI-backed surfaces are import mapping, policy interpretation, and client follow-up drafting.</p>
                  </div>
                </div>
              </article>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
