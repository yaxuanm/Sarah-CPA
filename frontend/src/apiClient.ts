import type { ActionPlan, DirectAction, ViewEnvelope } from "./types";

export type StreamUpdate =
  | { event: "thinking"; message: string }
  | { event: "intent_confirmed"; intentLabel?: string; planSource?: string }
  | { event: "view_rendered"; view: ViewEnvelope | null; actions: ActionPlan[] }
  | { event: "feedback_recorded"; signal?: string }
  | { event: "message_delta"; delta: string }
  | { event: "done"; response?: { message?: string; view?: ViewEnvelope; actions?: ActionPlan[] }; session?: Record<string, unknown> };

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
  response: { message?: string; view?: ViewEnvelope; actions?: ActionPlan[] };
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
  response: { message?: string; view?: ViewEnvelope; actions?: ActionPlan[] };
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

function parseSseChunk(chunk: string): StreamUpdate | null {
  const event = chunk.match(/^event:\s*(.+)$/m)?.[1]?.trim();
  const rawData = chunk.match(/^data:\s*(.+)$/m)?.[1];
  if (!event || !rawData) return null;
  const data = JSON.parse(rawData);

  if (event === "thinking") return { event, message: data.message };
  if (event === "intent_confirmed") {
    return { event, intentLabel: data.intent_label, planSource: data.plan_source };
  }
  if (event === "view_rendered") return { event, view: data.view, actions: data.actions || [] };
  if (event === "feedback_recorded") return { event, signal: data.signal };
  if (event === "message_delta") return { event, delta: data.delta || "" };
  if (event === "done") return { event, response: data.response, session: data.session };
  return null;
}
