// App.tsx
// Slim shell for the DueDateHQ "traditional" frontend (codex/frontend-core-flow).
//
// Information architecture (per duedatehq-frontend-skill/SKILL.md):
//   - 5 top-level sections: Today / Calendar / Clients / Updates / Settings.
//   - Section body renders rich, structured UI from mockData (sections.tsx).
//   - Chat lives in a right-hand drawer (natural language only).
//   - When chat resolves to a ViewEnvelope (ClientCard, ConfirmCard, etc.),
//     App overlays a drilldown card on top of the active section.
//
// What this file is NOT:
//   - It is not where business logic lives — that's in the backend / cards.tsx.
//   - It does not invent new view types, plan types, or design tokens.

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { bootstrapToday, executeAction, streamChat } from "./apiClient";
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
  const [currentSection, setCurrentSection] = useState<SectionId>("today");
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
  const [chatOpen, setChatOpen] = useState(false);
  const [drilldownOpen, setDrilldownOpen] = useState(false);
  const [backendState, setBackendState] = useState<"connecting" | "ready" | "degraded" | "offline">("connecting");
  const streamRef = useRef<HTMLDivElement | null>(null);

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

  // Pop the drilldown overlay only when the resolved envelope adds
  // information beyond what the active section already shows.
  function maybeOpenDrilldown(envelope: ViewEnvelope | null) {
    if (!envelope) return;
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
    setChatOpen(true);
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
    void submit(`Generate a ${format.toUpperCase()} export for: ${scope}`, `Export ${scope}`);
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

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          DueDate<em>HQ</em>
        </div>
        <SectionNav current={currentSection} onSelect={setCurrentSection} />
        <div className="topbar-right">
          <button
            className={`chat-toggle ${chatOpen ? "active" : ""}`}
            type="button"
            onClick={() => setChatOpen((current) => !current)}
            aria-expanded={chatOpen}
            aria-label="Toggle chat drawer"
          >
            {chatOpen ? "Close chat" : "Ask DueDateHQ"}
          </button>
          <div className="tenant-name">Johnson CPA PLLC</div>
          <div className={`connection-pill ${backendState}`}>{statusLabel}</div>
          <div className="avatar">SJ</div>
        </div>
      </header>

      <main className={`section-main ${chatOpen ? "with-chat" : ""}`}>
        <section className="render-panel">
          <div className="surface-meta">
            <div>
              <div className="eyebrow">{meta.eyebrow}</div>
              <h1>{meta.title}</h1>
              <p className="surface-summary">{meta.subtitle}</p>
            </div>
            <div className="status-pills">
              <span
                className={`pill ${
                  backendState === "ready"
                    ? "green"
                    : backendState === "degraded"
                      ? "red"
                      : backendState === "offline"
                        ? "blue"
                        : "gold"
                }`}
              >
                {statusLabel}
              </span>
            </div>
          </div>
          <SectionComponent
            tenantId={tenantId}
            view={view ?? { type: "GuidanceCard", data: {}, selectable_items: [] }}
            busy={busy}
            dispatch={dispatchSectionPlan}
            onPrompt={(prompt) => void submit(prompt)}
            onAction={(action, label) => void runDirectAction(action, label)}
            onExport={handleExport}
          />
        </section>

        {chatOpen ? (
          <aside className="chat-drawer" aria-label="Chat drawer">
            <div className="chat-header">
              <div className="chat-header-label">Conversation</div>
              <div className="chat-header-date">Sarah's work queue</div>
              <button
                type="button"
                className="chat-close"
                aria-label="Close chat"
                onClick={() => setChatOpen(false)}
              >
                ×
              </button>
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
        ) : null}
      </main>

      {drilldownOpen && view ? (
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
    </div>
  );
}
