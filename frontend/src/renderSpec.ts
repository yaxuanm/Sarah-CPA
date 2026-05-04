import type { RenderBlock, RenderSpec } from "./types";

const ALLOWED_BLOCKS = new Set<RenderBlock["type"]>([
  "decision_brief",
  "fact_strip",
  "action_draft",
  "source_list",
  "choice_set",
  "empty_state"
]);

export function buildClientRequestDraft(clientName: string, missingItem: string, dueDate: string): RenderSpec {
  return {
    version: "0.1",
    surface: "work_card",
    title: `${clientName} client request`,
    intent_summary: `Prepare the outbound request for ${clientName}.`,
    blocks: [
      {
        type: "decision_brief",
        title: "Ready to send outside DueDateHQ",
        body: `The return cannot move forward until ${missingItem} arrives. This draft asks for exactly that item and mentions the ${dueDate} deadline.`
      },
      {
        type: "action_draft",
        label: "Send this message to the client",
        body: `Hi,\n\nWe are preparing your upcoming filing and still need ${missingItem}. Please send it over when you can so we can keep the ${dueDate} deadline on track.\n\nThank you,\nSarah`,
        note: "DueDateHQ prepared the message only. Send it through your normal email or client portal, then come back and record it as sent."
      },
      {
        type: "choice_set",
        question: "After you send it, record the work here.",
        choices: [
          { label: "Record as sent", intent: "mark sent", style: "primary" },
          { label: "Adjust wording", intent: "revise", style: "secondary" },
          { label: "Back to today", intent: "today", style: "secondary" }
        ]
      }
    ]
  };
}

export function validateRenderSpec(spec: RenderSpec): { ok: boolean; errors: string[] } {
  const errors: string[] = [];

  if (spec.version !== "0.1") errors.push("Unsupported spec version.");
  if (spec.surface !== "work_card") errors.push("Unsupported surface.");
  if (!spec.title.trim()) errors.push("Missing title.");
  if (!spec.intent_summary.trim()) errors.push("Missing intent summary.");
  if (!spec.blocks.length) errors.push("Spec must include at least one block.");

  for (const block of spec.blocks) {
    if (!ALLOWED_BLOCKS.has(block.type)) {
      errors.push(`Unsupported block type: ${block.type}`);
    }
    if (block.type === "choice_set" && block.choices.length === 0) {
      errors.push("Choice set must include at least one choice.");
    }
  }

  return { ok: errors.length === 0, errors };
}
