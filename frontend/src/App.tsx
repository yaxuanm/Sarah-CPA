// App.tsx
// Slim shell for the DueDateHQ "traditional" frontend (codex/frontend-core-flow).
//
// Information architecture (per duedatehq-frontend-skill/SKILL.md):
//   - 5 top-level sections: Today / Calendar / Clients / Updates / Settings.
//   - Chat lives in a right-hand drawer (natural language only).
//   - Section body renders the most recent ViewEnvelope via <ViewRenderer>.
//
// State ownership:
//   - currentSection, view, actions, session, messages, busy, backendState
//     all live here so they survive section switches.
//   - Sections in sections.tsx dispatch plans via the `dispatch` callback;
//     this file resolves those plans against the backend executor through
//     `executeAction` and updates `view`.
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
  summarizeView,
  surfaceSummary,
  surfaceTitle
} from "./chatHelpers";
import {
  SectionId,
  SectionNav,
  sectionComponents,
  sectionMeta
} from "./sections";

const tenantId = import.meta.env.VITE_DUEDATEHQ_TENANT_ID || "2403c5e1-85ac-4593-86cc-02f8d97a8d92";
const apiBase = import.meta.env.VITE_DUEDATEHQ_API_BASE || "http://127.0.0.1:8000";

const initialView: ViewEnvelope = {
  type: "GuidanceCard",
  data: { message: "Opening today's work." },
  selectable_items: []
};
const initialActions: ActionPlan[] = [];

export function App() {
  const [currentSection, setCurrentSection] = useState<SectionId>("today");
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: id(), role: "status", text: String(initialView.data.message) }
  ]);
  const [view, setView] = useState<ViewEnvelope>(initialView);
  const [actions, setActions] = useState<ActionPlan[]>(initialActions);
  const [seenVisualContexts, setSeenVisualContexts] = useState<VisualContext[]>([
    summarizeView(initialView, initialActions)
  ]);
  const [input, setInput] = useState("");
  const [session, setSession] = useState<Record<string, unknown>>({
    tenant_id: tenantId,
    session_id: "frontend-validation-session",
    today: "2026-04-26"
  });
  const [busy, setBusy] = useState(false);
  const [apiBootstrapped, setApiBootstrapped] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [backendState, setBackendState] = useState<"connecting" | "ready" | "degraded">("connecting");
  const streamRef = useRef<HTMLDivElement | null>(null);

  // Track recent visual contexts so the agent kernel knows what the CPA has
  // already seen when it decides what to render next.
  useEffect(() => {
    const context = summarizeView(view, actions);
    setSeenVisualContexts((current) =>
      [context, ...current.filter((item) => item.summary !== context.summary)].slice(0, 8)
    );
  }, [view, actions]);

  // Bootstrap once.
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
      setMessages([
        { id: id(), role: "system", text: result.response.message || "Today's work is open." }
      ]);
    } catch (error) {
      setBackendState("degraded");
      append("system", `Couldn't load today's work from the backend. ${String(error)}`);
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

  // Sections dispatch plans through this callback. We turn the plan into a
  // direct_execute DirectAction so it routes through the same /action endpoint
  // the chat drawer uses. That keeps view-state transitions identical
  // regardless of who initiated them (section nav vs chat).
  const dispatchSectionPlan = useCallback(
    (plan: Record<string, unknown>, expectedView: string, _echo: string) => {
      void runDirectAction({
        type: "direct_execute",
        plan,
        expected_view: expectedView
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [session, view, actions, seenVisualContexts]
  );

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  const quickActions = buildQuickActions(view, actions);
  const statusLabel =
    backendState === "ready"
      ? "Live backend"
      : backendState === "degraded"
        ? "Backend issue"
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
              <h1>{currentSection === "today" ? surfaceTitle(view) : meta.title}</h1>
              <p className="surface-summary">
                {currentSection === "today" ? surfaceSummary(view) : meta.subtitle}
              </p>
            </div>
            <div className="status-pills">
              <span
                className={`pill ${
                  backendState === "ready" ? "green" : backendState === "degraded" ? "red" : "gold"
                }`}
              >
                {statusLabel}
              </span>
              <span className="pill blue">{view.type}</span>
            </div>
          </div>
          <SectionComponent
            tenantId={tenantId}
            view={view}
            busy={busy}
            dispatch={dispatchSectionPlan}
            onPrompt={(prompt) => void submit(prompt)}
            onAction={(action, label) => void runDirectAction(action, label)}
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
    </div>
  );
}
