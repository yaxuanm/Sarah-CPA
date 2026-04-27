// cards.tsx
// View-envelope renderers. Each backend `view.type` (see
// src/duedatehq/core/response_generator.py) maps to one component here.
// ViewRenderer dispatches by type; UnknownView renders any unmapped envelope.
//
// Behavior is intentionally identical to the previous inline definitions in
// App.tsx — this file only reorganises code, it does not change rendered output
// or interaction contracts.

import type { ActionPlan, RenderBlock, RenderSpec, TaskItem, ViewEnvelope } from "./types";
import { validateRenderSpec } from "./renderSpec";
import { badgeClass, urgencyClass } from "./dashboardData";
import {
  DirectActionHandler,
  EyebrowHeader,
  Fact
} from "./coreUI";
import { deadlineHistoryPlan, todayPlan } from "./plans";

export function ViewRenderer({
  view,
  onPrompt,
  onAction,
  tenantId
}: {
  view: ViewEnvelope;
  onPrompt: (prompt: string) => void;
  onAction: DirectActionHandler;
  tenantId: string;
}) {
  if (view.type === "ListCard") return <ListCard view={view} onPrompt={onPrompt} onAction={onAction} />;
  if (view.type === "ClientCard")
    return <ClientCard view={view} onPrompt={onPrompt} onAction={onAction} tenantId={tenantId} />;
  if (view.type === "ConfirmCard") return <ConfirmCard view={view} onAction={onAction} />;
  if (view.type === "HistoryCard") return <HistoryCard view={view} />;
  if (view.type === "ReminderPreviewCard") return <ReminderPreviewCard view={view} />;
  if (view.type === "ClientListCard") return <ClientListCard view={view} onPrompt={onPrompt} />;
  if (view.type === "ReviewQueueCard") return <ReviewQueueCard view={view} />;
  if (view.type === "GuidanceCard") return <GuidanceCard view={view} onPrompt={onPrompt} />;
  if (view.type === "TaxChangeRadarCard") return <TaxChangeRadarCard view={view} onPrompt={onPrompt} />;
  if (view.type === "RenderSpecSurface") {
    return (
      <RenderSpecSurface
        spec={view.data.render_spec as RenderSpec}
        onPrompt={onPrompt}
        onAction={onAction}
      />
    );
  }
  return <UnknownView view={view} />;
}

export function ActionsBar({
  actions,
  onAction
}: {
  actions: ActionPlan[];
  onAction: DirectActionHandler;
}) {
  if (!actions.length) return null;
  return (
    <div className="action-bar action-bar-inline">
      {actions.slice(0, 3).map((action, index) => {
        const direct =
          action.action ||
          (action.plan
            ? {
                type: "direct_execute" as const,
                plan: action.plan
              }
            : null);
        return (
          <button
            key={`${action.label}-${index}`}
            className={index === 0 ? "primary" : "secondary"}
            onClick={() => {
              if (direct) {
                onAction(direct, action.label);
              }
            }}
            disabled={!direct}
          >
            {action.label}
          </button>
        );
      })}
    </div>
  );
}

function ListCard({
  view,
  onPrompt,
  onAction
}: {
  view: ViewEnvelope;
  onPrompt: (prompt: string) => void;
  onAction: DirectActionHandler;
}) {
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
      <EyebrowHeader
        eyebrow={data.title || "Deadline list"}
        title={items.length ? data.headline || "Review the matching deadlines" : "No matching work"}
        subtitle={data.description}
        pillLabel={`${data.total ?? items.length} ${data.status_label || "items"}`}
        pillTone="red"
      />
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

function ClientCard({
  view,
  onPrompt,
  onAction,
  tenantId
}: {
  view: ViewEnvelope;
  onPrompt: (prompt: string) => void;
  onAction: DirectActionHandler;
  tenantId: string;
}) {
  const data = view.data as {
    client_name?: string;
    entity_type?: string;
    registered_states?: string[];
    deadlines?: TaskItem[];
  };
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
              <strong>
                {item.tax_type} · {item.jurisdiction}
              </strong>
              <span>
                {item.due_date} · {item.status}
              </span>
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
                  plan: deadlineHistoryPlan(tenantId, deadline.deadline_id)
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
                plan: todayPlan(tenantId)
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

function ConfirmCard({
  view,
  onAction
}: {
  view: ViewEnvelope;
  onAction: DirectActionHandler;
}) {
  const data = view.data as {
    description?: string;
    due_date?: string;
    consequence?: string;
    options?: Array<{ label: string; style?: string; plan?: Record<string, unknown> | null }>;
  };
  return (
    <article className="card confirm-card">
      <EyebrowHeader
        eyebrow="Confirm before changing records"
        title={data.description || "Confirm action"}
        pillLabel={data.due_date || "pending"}
        pillTone="gold"
      />
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
      <EyebrowHeader
        eyebrow="Source and audit trail"
        title={data.client_name || "Current item"}
        pillLabel={data.status || "record"}
        pillTone="blue"
      />
      <div className="fact-grid">
        <Fact label="Tax type" value={data.tax_type || "Unknown"} />
        <Fact label="Due" value={data.due_date || "Unknown"} />
        <Fact label="Source" value={data.source_url || "No source URL"} />
      </div>
      <div className="timeline">
        {(data.transitions || []).map((transition, index) => (
          <div className="timeline-row" key={index}>
            <span>{transition.at || transition.created_at || "event"}</span>
            <p>
              {transition.note ||
                `${transition.from_status || "previous"} → ${transition.to_status || "current"}`}
            </p>
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
      <EyebrowHeader eyebrow="Reminder preview" title={`${data.total || 0} reminders ready`} />
      <div className="list">
        {(data.reminders || []).map((reminder, index) => (
          <div className="plain-row" key={index}>
            <strong>{reminder.client_name}</strong>
            <span>
              {reminder.tax_type} · due {reminder.due_date}
            </span>
          </div>
        ))}
      </div>
    </article>
  );
}

function ClientListCard({
  view,
  onPrompt
}: {
  view: ViewEnvelope;
  onPrompt: (prompt: string) => void;
}) {
  const data = view.data as {
    clients?: Array<{
      client_id: string;
      name: string;
      entity_type?: string;
      registered_states?: string[];
    }>;
    total?: number;
  };
  return (
    <article className="card">
      <EyebrowHeader eyebrow="Clients" title={`${data.total || 0} clients`} />
      <div className="list">
        {(data.clients || []).map((client) => (
          <button
            className="task-row"
            key={client.client_id}
            onClick={() => onPrompt(`focus ${client.name}`)}
          >
            <div>
              <strong>{client.name}</strong>
              <span>
                {client.entity_type || "Entity"} · {(client.registered_states || []).join(", ")}
              </span>
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
      <EyebrowHeader eyebrow="Rule review" title={`${data.total || 0} items need review`} />
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

function TaxChangeRadarCard({
  view,
  onPrompt
}: {
  view: ViewEnvelope;
  onPrompt: (prompt: string) => void;
}) {
  const data = view.data as {
    title?: string;
    primary_question?: string;
    data_boundary_notice?: string;
    metrics?: Array<{ label: string; value: string; tone?: "red" | "green" | "blue" | "gold" }>;
    rule_signals?: Array<{ title: string; detail?: string; source?: string }>;
    impacted_deadlines?: Array<{
      client_name: string;
      tax_type: string;
      jurisdiction: string;
      due_date: string;
      status: string;
    }>;
  };
  return (
    <article className="card radar-card">
      <EyebrowHeader
        eyebrow="Tax change radar"
        title={data.title || "This month's tax change radar"}
        subtitle={data.primary_question}
      />
      {data.data_boundary_notice ? (
        <section className="boundary-note">
          <strong>Data boundary</strong>
          <p>{data.data_boundary_notice}</p>
        </section>
      ) : null}
      <section className="fact-grid">
        {(data.metrics || []).map((metric) => (
          <Fact key={metric.label} label={metric.label} value={metric.value} tone={metric.tone} />
        ))}
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
            <button
              className="task-row"
              key={`${item.client_name}-${item.tax_type}-${index}`}
              onClick={() => onPrompt(`Open ${item.client_name}`)}
            >
              <div>
                <strong>{item.client_name}</strong>
                <span>
                  {item.tax_type} · {item.jurisdiction}
                </span>
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

function GuidanceCard({
  view,
  onPrompt
}: {
  view: ViewEnvelope;
  onPrompt: (prompt: string) => void;
}) {
  const data = view.data as {
    title?: string;
    eyebrow?: string;
    message?: string;
    options?: string[];
    context_options?: Array<Record<string, string>>;
  };
  return (
    <article className="card guidance-card">
      <EyebrowHeader
        eyebrow={data.eyebrow || "Need one more bit of context"}
        title={data.title || "Choose the item first"}
      />
      <p className="consequence">
        {data.message || "I need a little more context before changing the work surface."}
      </p>
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

function RenderSpecSurface({
  spec,
  onPrompt,
  onAction
}: {
  spec: RenderSpec;
  onPrompt: (prompt: string) => void;
  onAction: DirectActionHandler;
}) {
  const validation = validateRenderSpec(spec);
  if (!validation.ok) {
    return (
      <article className="card">
        <EyebrowHeader eyebrow="Render spec rejected" title="This surface did not pass validation" />
        <p className="consequence">{validation.errors.join(" ")}</p>
      </article>
    );
  }
  return (
    <article className="card spec-card">
      <EyebrowHeader
        eyebrow={spec.surface_kind || "Rendered for this question"}
        title={spec.title}
      />
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

function RenderBlockView({
  block,
  onPrompt,
  onAction
}: {
  block: RenderBlock;
  onPrompt: (prompt: string) => void;
  onAction: DirectActionHandler;
}) {
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
        {block.facts.map((fact) => (
          <Fact key={fact.label} label={fact.label} value={fact.value} tone={fact.tone} />
        ))}
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
          <p key={source.label}>
            <strong>{source.label}</strong> {source.detail}
          </p>
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
      <h3>{(block as { title?: string }).title || ""}</h3>
      <p>{(block as { body?: string }).body || ""}</p>
    </section>
  );
}

function UnknownView({ view }: { view: ViewEnvelope }) {
  return (
    <article className="card">
      <EyebrowHeader eyebrow="Unknown view" title={view.type} />
      <pre className="json-preview">{JSON.stringify(view.data, null, 2)}</pre>
    </article>
  );
}
