// App.tsx
// Slim shell for the DueDateHQ "traditional" frontend (codex/frontend-core-flow).
//
// Information architecture (per duedatehq-frontend-skill/SKILL.md):
//   - 4 top-level sections: Work / Clients / Review / Settings.
//   - Section body renders rich, structured UI from mockData (sections.tsx).
//   - Ask lives as a tool entry, not as a top-level destination.
//   - Ask opens a secretary conversation. Conversation stays in the dialog;
//     rendered work surfaces update the page result area.
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
  VisualContext,
  WorkspaceItem
} from "./types";
import { ViewRenderer } from "./cards";
import { id, MessageBubble } from "./coreUI";
import {
  appendBreadcrumb,
  buildQuickActions,
  buildWorkspaceSnapshot,
  humanIntentStatus,
  surfaceTitle,
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

export function App() {
  const [currentSection, setCurrentSection] = useState<SectionId>("work");
  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: id(), role: "system", text: "我在。你说要查什么，我把结果放到页面上。" }
  ]);
  const [view, setView] = useState<ViewEnvelope | null>(null);
  const [actions, setActions] = useState<ActionPlan[]>(initialActions);
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [displayLoading, setDisplayLoading] = useState<string | null>(null);
  const [expandedWorkspaceIds, setExpandedWorkspaceIds] = useState<string[]>([]);
  const [seenVisualContexts, setSeenVisualContexts] = useState<VisualContext[]>([]);
  const [input, setInput] = useState("");
  const [session, setSession] = useState<Record<string, unknown>>({
    tenant_id: tenantId,
    session_id: "frontend-validation-session",
    today: "2026-04-26"
  });
  const [busy, setBusy] = useState(false);
  const [apiBootstrapped, setApiBootstrapped] = useState(false);
  const [backendState, setBackendState] = useState<"connecting" | "ready" | "degraded" | "offline">("connecting");
  const [sectionNotice, setSectionNotice] = useState<{
    id: string;
    text: string;
    tone: "green" | "blue" | "gold" | "red";
  }[]>([]);
  const [messagesOpen, setMessagesOpen] = useState(false);
  const [portfolioDeadlines, setPortfolioDeadlines] = useState(() => mockDeadlines.map((d) => ({ ...d })));
  const [portfolioRules, setPortfolioRules] = useState(() => mockRules.map((r) => ({ ...r })));
  const [resolvedRuleIds, setResolvedRuleIds] = useState<string[]>([]);
  const [changedDeadlineIds, setChangedDeadlineIds] = useState<string[]>([]);
  const [importLaunchToken, setImportLaunchToken] = useState(0);
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

  function shouldInsertMaterial(envelope: ViewEnvelope | null) {
    if (!envelope) return false;
    return envelope.type !== "GuidanceCard";
  }

  function showResultOnPage(nextView: ViewEnvelope, nextActions: ActionPlan[]) {
    setView(nextView);
    setActions(nextActions);
  }

  function addWorkspace(
    nextView: ViewEnvelope,
    nextActions: ActionPlan[],
    options?: { summary?: string; highlight?: string[]; createdFrom?: string }
  ) {
    const workspace: WorkspaceItem = {
      id: id(),
      view: nextView,
      actions: nextActions,
      title: displayTitle(nextView),
      summary: options?.summary || displaySummary(nextView),
      highlight: options?.highlight || displayHighlight(nextView),
      createdFrom: options?.createdFrom || "这轮对话"
    };
    setWorkspaces((current) => [workspace, ...current].slice(0, 6));
    setExpandedWorkspaceIds([workspace.id]);
    setDisplayLoading(null);
  }

  function toggleWorkspace(workspaceId: string) {
    setExpandedWorkspaceIds((current) =>
      current.includes(workspaceId)
        ? current.filter((idValue) => idValue !== workspaceId)
        : [workspaceId, ...current]
    );
  }

  function workspacePrompt(workspace: WorkspaceItem, intent: "start" | "schedule" | "more") {
    if (intent === "start") return `先处理这个：${workspace.summary}`;
    if (intent === "schedule") return `把这个安排到日历：${workspace.summary}`;
    return `围绕这个结果继续说明：${workspace.summary}`;
  }

  function displayTitle(nextView: ViewEnvelope) {
    if (nextView.type === "RenderSpecSurface") {
      const spec = (nextView.data.render_spec || {}) as { title?: string };
      return spec.title || "整理出的材料";
    }
    return surfaceTitle(nextView);
  }

  function displaySummary(nextView: ViewEnvelope) {
    if (nextView.type === "ClientListCard") {
      const data = nextView.data as { total?: number; clients?: Array<{ name?: string }> };
      return `${data.total || 0} 个客户已经整理好。`;
    }
    if (nextView.type === "ListCard") {
      const data = nextView.data as { items?: Array<{ client_name?: string; tax_type?: string; due_date?: string }> };
      const first = data.items?.[0];
      return first
        ? `${data.items?.length || 0} 项任务，最近一项是 ${first.client_name || "当前客户"} 的 ${first.tax_type || "截止事项"}。`
        : "没有找到需要处理的截止事项。";
    }
    if (nextView.type === "RenderSpecSurface") {
      const spec = (nextView.data.render_spec || {}) as { intent_summary?: string };
      return spec.intent_summary || "我把当前判断依据整理好了。";
    }
    return "我把材料整理好了。";
  }

  function displayHighlight(nextView: ViewEnvelope) {
    const selectable = nextView.selectable_items || [];
    const first = selectable.find((item) => item.deadline_id || item.client_id || item.ref);
    if (first?.deadline_id) return [String(first.deadline_id)];
    if (first?.client_id) return [String(first.client_id)];
    if (first?.ref) return [String(first.ref)];
    return [];
  }

  function secretaryStepText(label?: string, detail?: string) {
    const normalized = `${label || ""} ${detail || ""}`.toLowerCase();
    if (normalized.includes("clientlistcard") || normalized.includes("client_list")) {
      return "我先查一下客户档案。";
    }
    if (normalized.includes("deadline") || normalized.includes("listcard")) {
      return "我先把相关截止事项排出来。";
    }
    if (normalized.includes("taxchangeradar") || normalized.includes("tax_change")) {
      return "我先看一下规则变化和受影响客户。";
    }
    if (normalized.includes("resolve_template")) return "我在选合适的展示方式。";
    if (normalized.includes("fetch_slot_data")) return "我在取需要的数据。";
    if (normalized.includes("dispatch_render")) return "我在把结果放到页面上。";
    if (normalized.includes("接收请求")) return "收到，我先看你要查什么。";
    if (normalized.includes("准备材料")) return "我准备把结果放到页面上。";
    return "我在处理。";
  }

  function renderReplyForView(nextView: ViewEnvelope, providedReply?: string) {
    if (nextView.type === "ClientListCard") {
      const data = nextView.data as { total?: number; clients?: Array<{ name?: string }> };
      const first = data.clients?.[0]?.name;
      return [
        `现在一共有 ${data.total || 0} 个客户。`,
        "我已经把左侧切到 Clients，客户目录就在那里。",
        first ? `你要先看 ${first}，还是继续筛选客户？` : "你要按州、税种，还是负责人继续筛选？"
      ].join("\n");
    }
    if (nextView.type === "ListCard") {
      const data = nextView.data as { items?: Array<{ client_name?: string; due_date?: string; tax_type?: string }> };
      const first = data.items?.[0];
      return [
        data.items?.length ? `我找到了 ${data.items.length} 项相关截止事项。` : "我没有找到匹配的截止事项。",
        "我已经把左侧切到 Work，本周分诊看板就在那里。",
        first
          ? `最近先看 ${first.client_name || "第一项"}${first.due_date ? ` ${first.due_date}` : ""}${first.tax_type ? ` 的 ${first.tax_type}` : ""}，要从这个开始吗？`
          : "要不要换一个客户或时间范围？"
      ].join("\n");
    }
    return providedReply || "我把对应页面放到左侧了。\n你先看摘要，再决定下一步。";
  }

  function viewFromRenderEvent(templateId: string, filledSlots: Record<string, unknown>): ViewEnvelope | null {
    const viewTypeByTemplate: Record<string, string> = {
      client_list: "ClientListCard",
      deadline_view: "ListCard",
      client_summary: "ClientCard",
      tax_change_radar: "TaxChangeRadarCard",
      generated_workspace: "RenderSpecSurface"
    };
    const viewType = viewTypeByTemplate[templateId];
    if (!viewType) return null;
    if (viewType === "ClientListCard") {
      return {
        type: viewType,
        data: { clients: filledSlots.clients || [], total: filledSlots.total || 0 },
        selectable_items: []
      };
    }
    if (viewType === "ListCard") {
      return {
        type: viewType,
        data: { title: "Deadlines", items: filledSlots.deadlines || [] },
        selectable_items: []
      };
    }
    return { type: viewType, data: { ...filledSlots }, selectable_items: [] };
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
    let renderedInTimeline = false;
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
          if (update.event === "agent_step") {
            const message = secretaryStepText(update.label, update.detail);
            if (thinkingMessageId) {
              replaceMessage(thinkingMessageId, message);
            } else {
              thinkingMessageId = append("status", message);
            }
            return;
          }
          if (update.event === "thinking") {
            thinkingMessageId = append("status", "我先理解一下。");
            return;
          }
          if (update.event === "intent_confirmed") {
            const message = update.intentLabel === "client_list"
              ? "这是客户数量问题，我去查客户列表。"
              : humanIntentStatus(update.intentLabel, update.planSource);
            if (thinkingMessageId) {
              replaceMessage(thinkingMessageId, message);
            } else {
              thinkingMessageId = append("status", message);
            }
          }
          if (update.event === "action_started" && update.actionType === "render") {
            const announce = secretaryStepText(update.template || update.announce);
            setDisplayLoading("我来拿一下。");
            if (thinkingMessageId) {
              replaceMessage(thinkingMessageId, announce);
            } else {
              thinkingMessageId = append("status", announce);
            }
          }
          if (update.event === "render_event") {
            const renderView = update.view || viewFromRenderEvent(update.templateId, update.filledSlots);
            if (renderView && shouldInsertMaterial(renderView)) {
              if (thinkingMessageId) {
                replaceMessage(thinkingMessageId, "结果已更新到页面。");
              }
              showResultOnPage(renderView, update.actions || []);
              addWorkspace(renderView, update.actions || [], {
                summary: update.summary || update.crossReference?.summary,
                highlight: update.highlight?.length ? update.highlight : update.crossReference?.highlight,
                createdFrom: cleaned
              });
              if (!streamedMessageId && update.crossReference?.reply) {
                streamedMessageId = append("system", update.crossReference.reply);
              }
              renderedInTimeline = true;
            }
          }
          if (update.event === "workspace_rendered" || update.event === "view_rendered") {
            if (renderedInTimeline) {
              setActions(update.actions || []);
              return;
            }
            if (update.view) {
              if (shouldInsertMaterial(update.view)) {
                if (thinkingMessageId) {
                  replaceMessage(thinkingMessageId, "结果已更新到页面。");
                }
                showResultOnPage(update.view, update.actions || []);
                addWorkspace(update.view, update.actions || [], { createdFrom: cleaned });
                const reply = renderReplyForView(update.view);
                if (streamedMessageId) {
                  replaceMessage(streamedMessageId, reply);
                } else {
                  streamedMessageId = append("system", reply);
                }
                renderedInTimeline = true;
              } else if (thinkingMessageId) {
                replaceMessage(thinkingMessageId, "我先确认你要看的方向。");
              }
            } else if (thinkingMessageId) {
              replaceMessage(thinkingMessageId, "我没抓准你的方向。");
            }
            if (!update.view || !shouldInsertMaterial(update.view)) setActions(update.actions || []);
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
        `后端现在没连上，没有改动任何数据。确认 FastAPI 在运行后再试一次。${String(error)}`
      );
    } finally {
      setBusy(false);
      setDisplayLoading(null);
    }
  }

  async function runDirectAction(action: DirectAction, userEcho?: string) {
    if (busy) return;

    if (action.type === "agent_input" && action.text) {
      await submit(action.text, userEcho);
      return;
    }
    if (action.type !== "direct_execute") return;
    setChatOpen(true);

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
      addWorkspace(nextView, [], { createdFrom: userEcho || "页面操作" });
      append("system", `好，我把 ${surfaceTitle(nextView)} 放到页面上。`);
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
      if (result.response.message) append("system", result.response.message);
      if (result.response.view) {
        setView(result.response.view);
        showResultOnPage(result.response.view, result.response.actions || []);
        addWorkspace(result.response.view, result.response.actions || [], { createdFrom: userEcho || "页面操作" });
      }
      setActions(result.response.actions || []);
      setSession(result.session);
      setBackendState("ready");
    } catch (error) {
      setBackendState("degraded");
      append("system", `这个动作没完成，也没有改动数据。${String(error)}`);
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

  function DisplayColumn() {
    if (!workspaces.length && displayLoading) {
      return (
        <div className="display-stack">
          <div className="display-loading-state">
            <span>{displayLoading}</span>
            <p>材料准备好后会放在这里。</p>
          </div>
        </div>
      );
    }

    return (
      <div className="display-stack">
        {displayLoading ? (
          <div className="display-loading-strip">
            <span>{displayLoading}</span>
          </div>
        ) : null}
        {workspaces.map((workspace, index) => {
          const expanded = expandedWorkspaceIds.includes(workspace.id);
          return (
            <article
              key={workspace.id}
              className={`display-workspace ${expanded ? "expanded" : "collapsed"}`}
            >
              <button
                type="button"
                className="display-workspace-head"
                onClick={() => toggleWorkspace(workspace.id)}
                aria-expanded={expanded}
              >
                <div>
                  <span className="display-origin">{index === 0 ? "刚拿到" : workspace.createdFrom}</span>
                  <h2>{workspace.title}</h2>
                  <p>{workspace.summary}</p>
                </div>
                <span className="display-toggle">{expanded ? "收起" : "展开"}</span>
              </button>
              {expanded ? (
                <>
                  {workspace.highlight.length ? (
                    <div className="display-cross-reference">
                      对话里提到的重点：{workspace.highlight.join(", ")}
                    </div>
                  ) : null}
                  <div className="display-workspace-body">
                    <ViewRenderer
                      view={workspace.view}
                      tenantId={tenantId}
                      onPrompt={(prompt) => void submit(prompt)}
                      onAction={(action, label) => void runDirectAction(action, label)}
                    />
                  </div>
                  <div className="display-actions">
                    <button type="button" onClick={() => void submit(workspacePrompt(workspace, "start"), "先处理这个")}>
                      先处理这个
                    </button>
                    <button type="button" onClick={() => void submit(workspacePrompt(workspace, "schedule"), "安排提醒")}>
                      安排提醒
                    </button>
                    <button type="button" onClick={() => void submit(workspacePrompt(workspace, "more"), "告诉我更多")}>
                      告诉我更多
                    </button>
                  </div>
                </>
              ) : null}
            </article>
          );
        })}
      </div>
    );
  }

  return (
    <div className={`app-shell ${chatOpen ? "chat-open" : ""}`}>
      <header className="topbar">
        <div className="brand">
          DueDate<em>HQ</em>
        </div>
        <div className="topbar-center">
          <SectionNav
            current={currentSection}
            pendingReviewCount={portfolioRules.filter((rule) => rule.status === "pending-review").length}
            onSelect={setCurrentSection}
          />
        </div>
        <div className="topbar-right">
          <button
            type="button"
            className={`topbar-ask-btn ${chatOpen ? "active" : ""}`}
            onClick={() => setChatOpen((current) => !current)}
          >
            Ask
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

      <main className="section-main">
        <section className="render-panel">
          <div className="surface-meta">
            <div>
              <div className="eyebrow">{meta.eyebrow}</div>
              <h1>{meta.title}</h1>
              <p className="surface-summary">{meta.subtitle}</p>
            </div>
          </div>
          {workspaces.length || displayLoading ? (
            <DisplayColumn />
          ) : (
            <SectionComponent
              tenantId={tenantId}
              view={view ?? { type: "GuidanceCard", data: {}, selectable_items: [] }}
              busy={busy}
              dispatch={dispatchSectionPlan}
              onPrompt={(prompt) => void submit(prompt)}
              onAction={(action, label) => void runDirectAction(action, label)}
              onExport={handleExport}
              onNotify={showSectionNotice}
              onNavigate={setCurrentSection}
              deadlines={portfolioDeadlines}
              setDeadlines={setPortfolioDeadlines}
              rules={portfolioRules}
              setRules={setPortfolioRules}
              resolvedRuleIds={resolvedRuleIds}
              setResolvedRuleIds={setResolvedRuleIds}
              changedDeadlineIds={changedDeadlineIds}
              setChangedDeadlineIds={setChangedDeadlineIds}
              importLaunchToken={importLaunchToken}
            />
          )}
        </section>
      </main>

      {chatOpen ? (
        <aside className="chat-panel secretary-panel" aria-label="Secretary conversation">
          <div className="chat-header">
            <div>
              <div className="chat-header-label">秘书台</div>
              <div className="chat-header-date">只在这里沟通</div>
            </div>
            <button
              type="button"
              className="chat-close"
              aria-label="Close conversation"
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
              <div className="quick-actions-label">下一步</div>
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
              placeholder="告诉我你要查什么"
            />
            <button type="submit" disabled={busy}>
              {busy ? "..." : "发送"}
            </button>
          </form>
        </aside>
      ) : null}
    </div>
  );
}
