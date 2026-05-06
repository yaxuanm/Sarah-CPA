import type { ActionPlan, DirectAction, ViewEnvelope } from "./types";

export type BackendResponse = {
  message?: string;
  view?: ViewEnvelope;
  actions?: ActionPlan[];
  workspace_update?: Record<string, unknown>;
  next_step?: Record<string, unknown>;
  suggested_actions?: ActionPlan[];
};

export type StreamUpdate =
  | { event: "thinking"; message: string }
  | { event: "intent_confirmed"; intentLabel?: string; planSource?: string }
  | { event: "workspace_rendered"; view: ViewEnvelope | null; actions: ActionPlan[] }
  | { event: "view_rendered"; view: ViewEnvelope | null; actions: ActionPlan[] }
  | { event: "feedback_recorded"; signal?: string }
  | { event: "message_delta"; delta: string }
  | { event: "done"; response?: BackendResponse; session?: Record<string, unknown> };

export async function streamChat(params: {
  apiBase: string;
  userInput: string;
  tenantId: string;
  session: Record<string, unknown>;
  onUpdate: (update: StreamUpdate) => void;
}): Promise<Record<string, unknown>> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_input: params.userInput,
      tenant_id: params.tenantId,
      session: params.session
    })
  });

  if (!response.ok || !response.body) {
    throw new Error(`Backend stream failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let nextSession = params.session;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const update = parseSseChunk(chunk);
      if (!update) continue;
      params.onUpdate(update);
      if (update.event === "done" && update.session) {
        nextSession = update.session;
      }
    }
  }

  return nextSession;
}

export async function bootstrapToday(params: {
  apiBase: string;
  tenantId: string;
  session: Record<string, unknown>;
}): Promise<{
  response: BackendResponse;
  session: Record<string, unknown>;
}> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/bootstrap/today`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_id: params.tenantId,
      session: params.session
    })
  });

  if (!response.ok) {
    throw new Error(`Bootstrap failed: ${response.status}`);
  }

  return response.json();
}

export async function executeAction(params: {
  apiBase: string;
  tenantId: string;
  session: Record<string, unknown>;
  action: DirectAction;
}): Promise<{
  response: BackendResponse;
  session: Record<string, unknown>;
}> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_id: params.tenantId,
      session: params.session,
      action: params.action
    })
  });

  if (!response.ok) {
    throw new Error(`Action failed: ${response.status}`);
  }

  return response.json();
}

export type SourceStatusItem = {
  source_key: string;
  label: string;
  default_url: string;
  sync_supported: boolean;
  latest_fetch_run?: {
    fetch_run_id: string;
    source_key: string;
    source_url: string;
    status: string;
    fetched_at: string;
  } | null;
};

export type SourceSyncResult = {
  source_key: string;
  source_url: string;
  fetched_at: string;
  fetch_run?: {
    fetch_run_id: string;
    source_key: string;
    status: string;
    fetched_at: string;
  };
  result?: {
    status: string;
    review_id?: string;
  };
};

export type DashboardPayload = {
  today: unknown[];
  active_work: unknown[];
  waiting_on_info: unknown[];
  client_count: number;
  open_task_count: number;
  open_blocker_count: number;
};

export type NotificationPreview = {
  routes: Array<{ channel: string; destination: string; enabled: boolean }>;
  reminders: Array<{
    reminder_id: string;
    client_id: string;
    deadline_id: string;
    reminder_day: string;
    scheduled_at: string;
    status: string;
  }>;
  deliveries: Array<{
    delivery_id: string;
    channel: string;
    destination: string;
    subject: string;
    status: string;
    sent_at?: string | null;
  }>;
};

export type ImportPreview = {
  source_name: string;
  source_kind: string;
  imported_rows: number;
  summary: string;
  mappings: Array<{
    target_field: string;
    source_column: string;
    confidence: number;
    status: string;
  }>;
  missing_fields: string[];
  extra_columns: string[];
  sample_rows: string[][];
  ready_to_generate: boolean;
  required_mappings: number;
  resolved_required_mappings: number;
};

export type ImportApplyBackendResult = {
  source_name: string;
  created_clients: Array<{ client_id: string; name: string }>;
  created_blockers: Array<{ blocker_id: string; title: string }>;
  created_tasks: Array<{ task_id: string; title: string }>;
  skipped_rows: Array<{ row_number: number; client_name?: string | null; reason: string }>;
  dashboard: DashboardPayload;
};

export type ImportAiMappingProposal = {
  summary: string;
  ai_used: boolean;
  changes: Array<{
    header: string;
    next_value: string;
    note: string;
    custom_field?: {
      id: string;
      label: string;
      type: "text" | "date" | "single_select";
    };
  }>;
};

export type FollowupDraft = {
  subject: string;
  body: string;
  rationale?: string;
  ai_used: boolean;
};

export async function fetchSourceStatus(params: { apiBase: string }): Promise<{ sources: SourceStatusItem[] }> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/sources/status`);

  if (!response.ok) {
    throw new Error(`Source status failed: ${response.status}`);
  }

  return response.json();
}

export async function previewImportCsv(params: {
  apiBase: string;
  sourceName: string;
  csvText: string;
}): Promise<{ preview: ImportPreview }> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/import/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_name: params.sourceName,
      csv_text: params.csvText
    })
  });

  if (!response.ok) {
    throw new Error(`Import preview failed: ${response.status}`);
  }

  return response.json();
}

export async function applyImportCsv(params: {
  apiBase: string;
  tenantId: string;
  sourceName: string;
  csvText: string;
  taxYear?: number;
}): Promise<{ result: ImportApplyBackendResult }> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/import/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_id: params.tenantId,
      source_name: params.sourceName,
      csv_text: params.csvText,
      tax_year: params.taxYear || 2026,
      actor: "frontend-demo"
    })
  });

  if (!response.ok) {
    throw new Error(`Import apply failed: ${response.status}`);
  }

  return response.json();
}

export async function proposeImportMapping(params: {
  apiBase: string;
  prompt: string;
  headers: string[];
  targetFields: Array<{ key: string; label: string; required?: boolean; aliases: string[] }>;
  customFields: Array<{ id: string; label: string; type: string }>;
}): Promise<{ proposal: ImportAiMappingProposal }> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/ai/import-mapping`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt: params.prompt,
      headers: params.headers,
      target_fields: params.targetFields,
      custom_fields: params.customFields
    })
  });

  if (!response.ok) {
    throw new Error(`Import AI mapping failed: ${response.status}`);
  }

  return response.json();
}

export async function draftFollowup(params: {
  apiBase: string;
  workItem: Record<string, unknown>;
  previousBody?: string;
}): Promise<{ draft: FollowupDraft }> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/ai/followup-draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      work_item: params.workItem,
      previous_body: params.previousBody || ""
    })
  });

  if (!response.ok) {
    throw new Error(`Follow-up draft failed: ${response.status}`);
  }

  return response.json();
}

export async function syncOfficialSources(params: {
  apiBase: string;
  states?: string[];
}): Promise<{ results: SourceSyncResult[] }> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/sources/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ states: params.states || ["CA", "TX", "NY"] })
  });

  if (!response.ok) {
    throw new Error(`Source sync failed: ${response.status}`);
  }

  return response.json();
}

export async function fetchDashboardPayload(params: {
  apiBase: string;
  tenantId: string;
  limit?: number;
}): Promise<{ payload: DashboardPayload }> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/dashboard/payload`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_id: params.tenantId,
      limit: params.limit || 5
    })
  });

  if (!response.ok) {
    throw new Error(`Dashboard payload failed: ${response.status}`);
  }

  return response.json();
}

export async function previewNotifications(params: {
  apiBase: string;
  tenantId: string;
  withinDays?: number;
}): Promise<NotificationPreview> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/notifications/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_id: params.tenantId,
      within_days: params.withinDays || 14
    })
  });

  if (!response.ok) {
    throw new Error(`Notification preview failed: ${response.status}`);
  }

  return response.json();
}

export async function sendPendingNotifications(params: {
  apiBase: string;
  tenantId: string;
  triggerDue?: boolean;
}): Promise<{ sent: number; deliveries: NotificationPreview["deliveries"] }> {
  const response = await fetch(`${params.apiBase.replace(/\/$/, "")}/notifications/send-pending`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_id: params.tenantId,
      trigger_due: params.triggerDue ?? true,
      at: "2100-01-01T00:00:00+00:00",
      actor: "frontend-demo"
    })
  });

  if (!response.ok) {
    throw new Error(`Notification send failed: ${response.status}`);
  }

  return response.json();
}

function parseSseChunk(chunk: string): StreamUpdate | null {
  const event = chunk.match(/^event:\s*(.+)$/m)?.[1]?.trim();
  const rawData = chunk.match(/^data:\s*(.+)$/m)?.[1];
  if (!event || !rawData) return null;
  const data = JSON.parse(rawData);

  if (event === "thinking") return { event, message: data.message };
  if (event === "intent_confirmed") {
    return { event, intentLabel: data.intent_label, planSource: data.plan_source };
  }
  if (event === "workspace_rendered") return { event, view: data.view, actions: data.actions || [] };
  if (event === "view_rendered") return { event, view: data.view, actions: data.actions || [] };
  if (event === "feedback_recorded") return { event, signal: data.signal };
  if (event === "message_delta") return { event, delta: data.delta || "" };
  if (event === "done") return { event, response: data.response, session: data.session };
  return null;
}
