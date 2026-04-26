import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { bootstrapToday, executeAction, streamChat } from "./apiClient";
import { validateRenderSpec } from "./renderSpec";
import type { ActionPlan, ChatMessage, DirectAction, RenderBlock, RenderSpec, TaskItem, ViewEnvelope, VisualContext } from "./types";

const tenantId = import.meta.env.VITE_DUEDATEHQ_TENANT_ID || "2403c5e1-85ac-4593-86cc-02f8d97a8d92";
const apiBase = import.meta.env.VITE_DUEDATEHQ_API_BASE || "http://127.0.0.1:8000";
const initialView: ViewEnvelope = {
  type: "GuidanceCard",
  data: {
    message: "正在打开今天的待办。"
  },
  selectable_items: []
};
const initialActions: ActionPlan[] = [];

function id(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export function App() {
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
    today: "2025-05-15"
  });
  const [busy, setBusy] = useState(false);
  const [apiBootstrapped, setApiBootstrapped] = useState(false);
  const streamRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const context = summarizeView(view, actions);
    setSeenVisualContexts((current) => [
      context,
      ...current.filter((item) => item.summary !== context.summary)
    ].slice(0, 8));
  }, [view, actions]);

  useEffect(() => {
    if (apiBootstrapped) return;
    setApiBootstrapped(true);
    void loadBackendOverview();
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

  async function submit(value = input) {
    const cleaned = value.trim();
    if (!cleaned || busy) return;
    setInput("");
    append("user", cleaned);

    setBusy(true);
    let streamedMessageId: string | null = null;
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
          if (update.event === "thinking") return;
          if (update.event === "intent_confirmed") {
            append("status", humanIntentStatus(update.intentLabel, update.planSource));
          }
          if (update.event === "view_rendered") {
            if (update.view) setView(update.view);
            setActions(update.actions || []);
          }
          if (update.event === "feedback_recorded") {
            if (update.signal === "correction") {
              append("status", "我会记住这次纠正，避免下次再这样理解。");
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
    } catch (error) {
      append("system", `AI 后端暂时不可用，我没有改动任何数据。请确认 FastAPI 已启动后再试。${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runDirectAction(action: DirectAction) {
    if (busy) return;
    if (action.type === "agent_input" && action.text) {
      await submit(action.text);
      return;
    }
    if (action.type !== "direct_execute") return;

    if (action.view_data && action.expected_view) {
      const nextView = {
        type: action.expected_view,
        data: action.view_data,
        selectable_items: action.selectable_items || []
      };
      setView(nextView);
      setActions([]);
      setSession((current) => ({
        ...current,
        current_view: nextView,
        selectable_items: nextView.selectable_items,
        current_actions: []
      }));
      append("status", "已打开。");
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
      if (result.response.message) append("system", result.response.message);
    } catch (error) {
      append("system", `这个按钮暂时执行失败，我没有改动任何数据。${String(error)}`);
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
      setMessages([{ id: id(), role: "system", text: result.response.message || "今天的待办已打开。" }]);
    } catch (error) {
      append("system", `后端待办加载失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  const quickActions = buildQuickActions(view, actions);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">DueDate<em>HQ</em></div>
        <div className="topbar-right">
          <div className="tenant-name">Johnson CPA PLLC</div>
          <div className="connection-pill">AI backend</div>
          <div className="avatar">SJ</div>
        </div>
      </header>

      <main className="workspace">
        <aside className="conv-panel">
          <div className="conv-header">
            <div className="conv-header-label">Interaction lab</div>
            <div className="conv-header-date">Sarah's morning queue</div>
          </div>
          <div className="stream" ref={streamRef}>
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </div>
          <div className="quick-actions">
            {quickActions.map((action) => (
              <button
                key={action.label}
                className="quick-btn"
                onClick={() => action.action ? void runDirectAction(action.action) : void submit(action.prompt || action.label)}
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
            <button type="submit" disabled={busy}>{busy ? "..." : "go"}</button>
          </form>
        </aside>

        <section className="render-panel">
          <div className="surface-meta">
            <div>
              <div className="eyebrow">Rendered from need</div>
              <h1>{surfaceTitle(view)}</h1>
            </div>
            <div className="status-pills">
              <span className="pill gold">AI backend</span>
              <span className="pill blue">{view.type}</span>
            </div>
          </div>
          <ViewRenderer view={view} onPrompt={(prompt) => void submit(prompt)} onAction={(action) => void runDirectAction(action)} />
        </section>
      </main>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`msg ${isUser ? "user" : ""} ${message.role === "status" ? "status" : ""}`}>
      <div className={`msg-badge ${isUser ? "usr" : "sys"}`}>{isUser ? "SJ" : "DH"}</div>
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

function ViewRenderer({ view, onPrompt, onAction }: { view: ViewEnvelope; onPrompt: (prompt: string) => void; onAction: (action: DirectAction) => void }) {
  if (view.type === "ListCard") return <ListCard view={view} onPrompt={onPrompt} onAction={onAction} />;
  if (view.type === "ClientCard") return <ClientCard view={view} onPrompt={onPrompt} onAction={onAction} />;
  if (view.type === "ConfirmCard") return <ConfirmCard view={view} onPrompt={onPrompt} />;
  if (view.type === "HistoryCard") return <HistoryCard view={view} />;
  if (view.type === "ReminderPreviewCard") return <ReminderPreviewCard view={view} />;
  if (view.type === "ClientListCard") return <ClientListCard view={view} onPrompt={onPrompt} />;
  if (view.type === "ReviewQueueCard") return <ReviewQueueCard view={view} />;
  if (view.type === "GuidanceCard") return <GuidanceCard view={view} onPrompt={onPrompt} />;
  if (view.type === "RenderSpecSurface") return <RenderSpecSurface spec={view.data.render_spec as RenderSpec} onPrompt={onPrompt} />;
  return <UnknownView view={view} />;
}

function ListCard({ view, onPrompt, onAction }: { view: ViewEnvelope; onPrompt: (prompt: string) => void; onAction: (action: DirectAction) => void }) {
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
          return (
          <button
            className="task-row"
            key={item.deadline_id || `${clientName}-${index}`}
            onClick={() => {
              const action = view.selectable_items?.[index]?.action;
              if (action) {
                onAction(action);
                return;
              }
              onPrompt(`打开第 ${index + 1} 条`);
            }}
            aria-label={`Open ${clientName}`}
            title={`Open ${clientName}`}
          >
            <div>
              <strong>{clientName}</strong>
              <span>{detail || "Deadline item"}</span>
            </div>
            <div className="task-right">
              <span className={item.days_remaining <= 0 ? "due hot" : "due"}>{item.due_date}</span>
              <span>{item.status}</span>
            </div>
          </button>
          );
        })}
      </div>
    </article>
  );
}

function ClientCard({ view, onPrompt, onAction }: { view: ViewEnvelope; onPrompt: (prompt: string) => void; onAction: (action: DirectAction) => void }) {
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
            onAction({
              type: "direct_execute",
              expected_view: "RenderSpecSurface",
              plan: {
                special: "render_spec_needed",
                intent_label: "client_request_draft",
                op_class: "read",
                message: "我根据当前选中的客户和事项生成请求草稿。",
                user_input: `prepare request for ${clientName}`
              }
            })
          }
        >
          Prepare request
        </button>
        <button className="secondary" onClick={() => onPrompt("show source")}>Show source</button>
        <button className="secondary" onClick={() => onPrompt("back to today")}>Back to today</button>
      </div>
    </article>
  );
}

function ConfirmCard({ view, onPrompt }: { view: ViewEnvelope; onPrompt: (prompt: string) => void }) {
  const data = view.data as { description?: string; due_date?: string; consequence?: string; options?: Array<{ label: string; style?: string }> };
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
            onClick={() => onPrompt(option.style === "primary" ? "confirm" : "cancel")}
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

function GuidanceCard({ view, onPrompt }: { view: ViewEnvelope; onPrompt: (prompt: string) => void }) {
  const data = view.data as {
    message?: string;
    options?: string[];
    context_options?: Array<Record<string, string>>;
  };
  return (
    <article className="card guidance-card">
      <div className="card-header">
        <div>
          <div className="eyebrow">Need one more bit of context</div>
          <h2>Choose the item first</h2>
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
        {(data.options?.length ? data.options : ["查看今天的待处理事项"]).map((option) => (
          <button key={option} className="secondary" onClick={() => onPrompt(option)}>
            {option}
          </button>
        ))}
      </div>
    </article>
  );
}

function RenderSpecSurface({ spec, onPrompt }: { spec: RenderSpec; onPrompt: (prompt: string) => void }) {
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
          <div className="eyebrow">Suggested next step</div>
          <h2>{spec.title}</h2>
        </div>
      </div>
      <p className="spec-summary">{spec.intent_summary}</p>
      <div className="spec-blocks">
        {spec.blocks.map((block, index) => (
          <RenderBlockView key={index} block={block} onPrompt={onPrompt} />
        ))}
      </div>
    </article>
  );
}

function RenderBlockView({ block, onPrompt }: { block: RenderBlock; onPrompt: (prompt: string) => void }) {
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
              onClick={() => onPrompt(choice.intent)}
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
    return (data.options?.length ? data.options : ["查看今天的待处理事项"]).slice(0, 3).map((option) => ({
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
        prompt: choice.intent
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
  if (view.type === "RenderSpecSurface") return "Next step";
  return "Work surface";
}

function humanIntentStatus(intentLabel?: string, planSource?: string): string {
  const labels: Record<string, string> = {
    today: "我会先打开今天需要处理的事项。",
    context_advice: "我会根据当前页面直接回答，右侧先保持不变。",
    client_deadline_list: "我会先打开这个客户的当前事项。",
    deadline_history: "我会先查这件事的来源和变更记录。",
    deadline_action_complete: "这是写入操作，我会先请你确认。",
    notification_preview: "我会先显示接下来需要提醒的客户。",
    upcoming_deadlines: "我会打开所有未来待处理截止事项，并给你筛选追问。",
    completed_deadlines: "我会打开已经处理完成的事项，方便核对。",
    ad_hoc_render_spec: "这个需求比较开放，我先把它整理成可推进的工作面。"
  };
  const base = labels[intentLabel || ""] || "我正在整理这个需求。";
  if (!planSource || planSource === "context_answer") return base;
  return base;
}
