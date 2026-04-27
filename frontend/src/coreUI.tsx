// coreUI.tsx
// Small, framework-agnostic primitives reused across cards and sections.
// Kept deliberately thin: any block that needs business logic belongs in
// cards.tsx or a section-specific file, not here.

import { ReactNode } from "react";
import type { ChatMessage, DirectAction } from "./types";

export type DirectActionHandler = (action: DirectAction, userEcho?: string) => void;

export function id(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export function describeDirectAction(action: DirectAction): string {
  if (action.command === "confirm_pending") return "Confirm this change";
  if (action.command === "cancel_pending") return "Cancel";
  if (action.expected_view === "ListCard") return "Back to today's work";
  if (action.expected_view === "ClientCard") return "Open this client";
  if (action.expected_view === "HistoryCard") return "Show source";
  if (action.expected_view === "ConfirmCard") return "Review before writing";
  if (action.expected_view === "RenderSpecSurface") return "Continue";
  return "Run this action";
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const isThinking =
    message.role === "status" &&
    (/^opening/i.test(message.text) ||
      /^the next workspace/i.test(message.text) ||
      /^connecting/i.test(message.text));
  return (
    <div
      className={`msg ${isUser ? "user" : ""} ${message.role === "status" ? "status" : ""} ${
        isThinking ? "thinking" : ""
      }`}
    >
      <div className={`msg-badge ${isUser ? "usr" : "sys"}`}>{isThinking ? "" : isUser ? "SJ" : "DH"}</div>
      <div className="msg-bubble">
        <MarkdownText text={message.text} />
      </div>
    </div>
  );
}

export function MarkdownText({ text }: { text: string }) {
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

export function normalizeMarkdownLines(text: string) {
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

export function renderInlineMarkdown(text: string) {
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

export function Fact({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className={`fact ${tone || ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function EyebrowHeader({
  eyebrow,
  title,
  subtitle,
  pillLabel,
  pillTone
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
  pillLabel?: string;
  pillTone?: "red" | "gold" | "blue" | "green";
}) {
  return (
    <div className="card-header">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
        {subtitle ? <p className="card-description">{subtitle}</p> : null}
      </div>
      {pillLabel ? <span className={`pill ${pillTone || "blue"}`}>{pillLabel}</span> : null}
    </div>
  );
}

export function EmptyStateRow({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{body}</span>
    </div>
  );
}
