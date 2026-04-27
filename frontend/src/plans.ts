// plans.ts
// Plan-factory helpers that build the cli_call plan envelopes the backend
// PlanExecutor accepts (see src/duedatehq/core/executor.py). Centralising the
// shapes avoids accidental drift between sections and keeps the contract
// auditable in one file.

export function todayPlan(tenantId: string): Record<string, unknown> {
  return {
    plan: [
      {
        step_id: "s1",
        type: "cli_call",
        cli_group: "today",
        cli_command: "today",
        args: { tenant_id: tenantId, limit: 5, enrich: true }
      }
    ],
    intent_label: "today",
    op_class: "read"
  };
}

export function clientListPlan(tenantId: string): Record<string, unknown> {
  return {
    plan: [
      {
        step_id: "s1",
        type: "cli_call",
        cli_group: "client",
        cli_command: "list",
        args: { tenant_id: tenantId }
      }
    ],
    intent_label: "client_list",
    op_class: "read"
  };
}

export function clientDeadlinesPlan(tenantId: string, clientId: string): Record<string, unknown> {
  return {
    plan: [
      {
        step_id: "s1",
        type: "cli_call",
        cli_group: "deadline",
        cli_command: "list",
        args: { tenant_id: tenantId, client_id: clientId }
      }
    ],
    intent_label: "client_deadline_list",
    op_class: "read"
  };
}

export function upcomingDeadlinesPlan(
  tenantId: string,
  withinDays: number,
  options: { jurisdiction?: string; clientId?: string; limit?: number } = {}
): Record<string, unknown> {
  const args: Record<string, unknown> = {
    tenant_id: tenantId,
    within_days: withinDays,
    status: "pending"
  };
  if (options.jurisdiction) args.jurisdiction = options.jurisdiction;
  if (options.clientId) args.client_id = options.clientId;
  if (options.limit) args.limit = options.limit;
  return {
    plan: [{ step_id: "s1", type: "cli_call", cli_group: "deadline", cli_command: "list", args }],
    intent_label: "upcoming_deadlines",
    op_class: "read"
  };
}

export function deadlineHistoryPlan(tenantId: string, deadlineId: string): Record<string, unknown> {
  return {
    plan: [
      {
        step_id: "s1",
        type: "cli_call",
        cli_group: "deadline",
        cli_command: "transitions",
        args: { tenant_id: tenantId, deadline_id: deadlineId }
      }
    ],
    intent_label: "deadline_history",
    op_class: "read"
  };
}

export function blockerListPlan(tenantId: string, options: { clientId?: string } = {}): Record<string, unknown> {
  const args: Record<string, unknown> = { tenant_id: tenantId, status: "open" };
  if (options.clientId) args.client_id = options.clientId;
  return {
    plan: [{ step_id: "s1", type: "cli_call", cli_group: "blocker", cli_command: "list", args }],
    intent_label: "blocker_list",
    op_class: "read"
  };
}

export function ruleReviewQueuePlan(): Record<string, unknown> {
  return {
    plan: [
      {
        step_id: "s1",
        type: "cli_call",
        cli_group: "rule",
        cli_command: "review-queue",
        args: {}
      }
    ],
    intent_label: "rule_review",
    op_class: "read"
  };
}

export function notifyPreviewPlan(tenantId: string, withinDays = 7): Record<string, unknown> {
  return {
    plan: [
      {
        step_id: "s1",
        type: "cli_call",
        cli_group: "notify",
        cli_command: "preview",
        args: { tenant_id: tenantId, within_days: withinDays }
      }
    ],
    intent_label: "notification_preview",
    op_class: "read"
  };
}
