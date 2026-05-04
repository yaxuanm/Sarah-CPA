// chatHelpers.ts
// Pure helpers used by the App shell to:
//   * project a ViewEnvelope into a VisualContext (so the agent kernel knows
//     what's currently on the right-hand pane).
//   * derive surface-meta strings (eyebrow / title / summary) for the
//     section header.
//   * pull the next-step quick actions out of the backend response.
//   * humanise the backend's intent_label thinking message.
// Kept framework-free so they're easy to unit-test or reuse from sections.

import type { ActionPlan, DirectAction, RenderSpec, TaskItem, ViewEnvelope, VisualContext } from "./types";

export type QuickAction = { label: string; prompt?: string; action?: DirectAction };

export function summarizeView(view: ViewEnvelope, actions: ActionPlan[]): VisualContext {
  const visibleActions = actions.map((action) => action.label).filter(Boolean);
  if (view.type === "ListCard") {
    const data = view.data as { headline?: string; title?: string; items?: TaskItem[] };
    const items = data.items || [];
    const clientNames = items.map((item, index) => item.client_name || `Item ${index + 1}`);
    return {
      view_type: view.type,
      headline: data.headline || data.title,
      visible_clients: clientNames,
      visible_deadlines: items.map(
        (item, index) =>
          `${clientNames[index]}: ${item.tax_type}, ${item.jurisdiction}, due ${item.due_date}, status ${item.status}`
      ),
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
      visible_deadlines: deadlines.map(
        (item) => `${item.tax_type}, ${item.jurisdiction}, due ${item.due_date}, status ${item.status}`
      ),
      visible_actions: visibleActions,
      summary: `${data.client_name || "Client"} detail; ${deadlines
        .map((item) => `${item.status}: ${item.missing || "no missing item"}`)
        .join("; ")}`
    };
  }
  if (view.type === "HistoryCard") {
    const data = view.data as {
      client_name?: string;
      tax_type?: string;
      due_date?: string;
      status?: string;
      source_url?: string;
    };
    return {
      view_type: view.type,
      headline: "Source and history",
      selected_client: data.client_name,
      visible_clients: data.client_name ? [data.client_name] : [],
      visible_deadlines: [
        `${data.tax_type || "deadline"}, due ${data.due_date || "unknown"}, status ${data.status || "unknown"}`
      ],
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
      visible_deadlines: (data.impacted_deadlines || []).map((item) =>
        [item.client_name, item.tax_type, item.due_date].filter(Boolean).join(" · ")
      ),
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

export function extractClientNames(text: string): string[] {
  const names = new Set<string>();
  for (const match of text.matchAll(
    /\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\s+(?:LLC|Inc|Corp|Dental|Manufacturing|Consulting))\b/g
  )) {
    names.add(match[1]);
  }
  return [...names];
}

export function surfaceTitle(view: ViewEnvelope): string {
  if (view.type === "ListCard") return (view.data as { title?: string }).title || "Deadline list";
  if (view.type === "ClientCard") return "Focused client";
  if (view.type === "ConfirmCard") return "Confirm change";
  if (view.type === "HistoryCard") return "Source and history";
  if (view.type === "GuidanceCard") return "Need context";
  if (view.type === "TaxChangeRadarCard") return "Tax change radar";
  if (view.type === "RenderSpecSurface") return "Next step";
  if (view.type === "ReminderPreviewCard") return "Reminder preview";
  if (view.type === "ClientListCard") return "Client directory";
  if (view.type === "ReviewQueueCard") return "Rule review queue";
  return "Work surface";
}

export function surfaceSummary(view: ViewEnvelope): string {
  if (view.type === "ListCard") {
    const data = view.data as { description?: string; items?: TaskItem[] };
    return data.description || `${data.items?.length || 0} deadline items ready for review.`;
  }
  if (view.type === "ClientCard") return "Review one client before you confirm or send outreach.";
  if (view.type === "ConfirmCard")
    return "This step writes back to the backend, so DueDateHQ asks for confirmation first.";
  if (view.type === "HistoryCard") return "Trace the source, due date, and status changes before you act.";
  if (view.type === "GuidanceCard")
    return "Use one of the suggested prompts so the workspace can stay constrained and actionable.";
  if (view.type === "TaxChangeRadarCard") return "Review external signals before they turn into active work.";
  if (view.type === "RenderSpecSurface") return "This is a generated work surface for an open-ended question.";
  if (view.type === "ReminderPreviewCard") return "Preview reminders that are about to be sent.";
  if (view.type === "ClientListCard") return "Pick a client to open their workspace.";
  if (view.type === "ReviewQueueCard") return "Review pending rule changes before approving them.";
  return "Review the current work surface.";
}

export function humanIntentStatus(intentLabel?: string, planSource?: string): string {
  const labels: Record<string, string> = {
    today: "I'll open today's work first.",
    context_advice: "I'll answer from the current workspace before changing the right side.",
    client_deadline_list: "I'll open the current client's active items first.",
    deadline_history: "I'll show the source and audit history first.",
    deadline_action_complete: "This writes back to the backend, so I'll ask for confirmation first.",
    notification_preview: "I'll show the next reminder set first.",
    upcoming_deadlines: "I'll open future deadlines first so you can narrow the scope.",
    completed_deadlines: "I'll show completed items first so you can review them.",
    ad_hoc_render_spec: "This request is open-ended, so the conversation needs one more concrete detail first."
  };
  const base = labels[intentLabel || ""] || "I'm organizing this request.";
  if (!planSource || planSource === "context_answer") return base;
  return base;
}

export function buildQuickActions(view: ViewEnvelope, actions: ActionPlan[]): QuickAction[] {
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

export function buildWorkspaceSnapshot(view: ViewEnvelope): Record<string, unknown> {
  const data = view.data || {};
  const workspaceType = workspaceTypeForView(view.type);
  const semanticId = String(
    data.client_id || data.client_name || data.deadline_id || data.title || data.headline || view.type
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

export function workspaceTypeForView(viewType: string): string {
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

export function appendBreadcrumb(current: unknown[], workspaceType: string): string[] {
  const breadcrumb = current.map((item) => String(item));
  if (!breadcrumb.length || breadcrumb[breadcrumb.length - 1] !== workspaceType) {
    breadcrumb.push(workspaceType);
  }
  return breadcrumb.slice(-8);
}
