export type MessageRole = "system" | "user" | "status";

export type ChatMessage = {
  id: string;
  role: MessageRole;
  text: string;
};

export type ViewEnvelope = {
  type: string;
  data: Record<string, unknown>;
  selectable_items?: Array<Record<string, unknown>>;
};

export type VisualContext = {
  view_type: string;
  headline?: string;
  selected_client?: string;
  visible_clients: string[];
  visible_deadlines: string[];
  visible_actions: string[];
  summary: string;
};

export type ActionPlan = {
  label: string;
  plan?: Record<string, unknown> | null;
};

export type TaskItem = {
  deadline_id: string;
  client_id: string;
  client_name: string;
  tax_type: string;
  jurisdiction: string;
  due_date: string;
  status: string;
  days_remaining: number;
  risk?: string;
  missing?: string;
};

export type RenderBlock =
  | {
      type: "decision_brief";
      title: string;
      body: string;
    }
  | {
      type: "fact_strip";
      facts: Array<{ label: string; value: string; tone?: "red" | "green" | "blue" | "gold" }>;
    }
  | {
      type: "action_draft";
      label: string;
      body: string;
      note?: string;
    }
  | {
      type: "source_list";
      sources: Array<{ label: string; detail: string }>;
    }
  | {
      type: "choice_set";
      question: string;
      choices: Array<{ label: string; intent: string; style?: "primary" | "secondary" }>;
    }
  | {
      type: "empty_state";
      title: string;
      body: string;
    };

export type RenderSpec = {
  version: "0.1";
  surface: "work_card";
  title: string;
  intent_summary: string;
  blocks: RenderBlock[];
};
