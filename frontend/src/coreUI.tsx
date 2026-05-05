// coreUI.tsx
// Small, framework-agnostic primitives reused across cards and sections.
// Kept deliberately thin: any block that needs business logic belongs in
// cards.tsx or a section-specific file, not here.

import { ReactNode, useEffect, useRef, useState } from "react";
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

// FilterIcon — small inline SVG so we don't add an icon dep.
export function FilterIcon({ active }: { active?: boolean }) {
  return (
    <svg
      className={`filter-icon ${active ? "active" : ""}`}
      viewBox="0 0 16 16"
      width="14"
      height="14"
      aria-hidden="true"
    >
      <path
        d="M2 3.5h12M4 8h8M6.5 12.5h3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

// GitHub/Primer-inspired utility icons kept local so we do not add a new
// dependency just for a few lightweight toolbar glyphs.
export function UploadIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path
        d="M8 11V3.5M5.25 6.25 8 3.5l2.75 2.75M3 11.75v.75a.5.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5v-.75"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function DownloadIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path
        d="M8 3.5V11M5.25 8.25 8 11l2.75-2.75M3 11.75v.75a.5.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5v-.75"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function SaveIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path
        d="M4.25 2.75h7.5a.5.5 0 0 1 .5.5v10l-4.25-2.5-4.25 2.5v-10a.5.5 0 0 1 .5-.5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ChevronRightIcon() {
  return (
    <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
      <path
        d="m6 3.75 4 4-4 4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function WorkIcon() {
  return (
    <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
      <path
        d="M3.25 4.25h9.5a.5.5 0 0 1 .5.5v7.5a.5.5 0 0 1-.5.5h-9.5a.5.5 0 0 1-.5-.5v-7.5a.5.5 0 0 1 .5-.5Zm2-1.5h5.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function BlockedIcon() {
  return (
    <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
      <circle cx="8" cy="8" r="5.25" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M5.1 10.9 10.9 5.1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function ExtensionIcon() {
  return (
    <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
      <circle cx="8" cy="8" r="5.25" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 5.25v3.2l2.15 1.35" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ArchiveIcon() {
  return (
    <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
      <path
        d="M3.25 4.75h9.5M4.25 4.75v7.5a.5.5 0 0 0 .5.5h6.5a.5.5 0 0 0 .5-.5v-7.5M5.5 2.75h5l.75 2h-6.5l.75-2ZM6.25 7.25h3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export type FilterChipOption = { id: string; label: string };

export type FilterGroupSpec = {
  key: string;
  label: string;
  options: FilterChipOption[];
  selectedId: string;
  onSelect: (nextId: string) => void;
};

// FilterPopover — icon button that toggles a small popover with chip groups.
// Closes on outside click or Escape. Used by Today/Calendar/Clients sections.
export function FilterPopover({
  groups,
  activeCount,
  onClear
}: {
  groups: FilterGroupSpec[];
  activeCount: number;
  onClear?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(event: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="filter-popover-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`filter-trigger ${activeCount > 0 ? "active" : ""} ${open ? "open" : ""}`}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <FilterIcon active={activeCount > 0} />
        <span>Filter</span>
        {activeCount > 0 ? <span className="filter-count">{activeCount}</span> : null}
      </button>
      {open ? (
        <div className="filter-popover" role="dialog">
          <div className="filter-popover-head">
            <strong>Filter</strong>
            {onClear ? (
              <button type="button" className="link-btn" onClick={onClear}>
                Clear all
              </button>
            ) : null}
          </div>
          <div className="filter-popover-body">
            {groups.map((group) => (
              <div className="filter-group" key={group.key}>
                <span className="filter-label">{group.label}</span>
                <div className="filter-chips">
                  {group.options.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      className={`filter-chip ${option.id === group.selectedId ? "active" : ""}`}
                      onClick={() => group.onSelect(option.id)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="filter-popover-foot">
            <button type="button" className="primary" onClick={() => setOpen(false)}>
              Done
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// SearchInput — accessible inline search box with leading magnifier glyph.
export function SearchInput({
  value,
  onChange,
  placeholder
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="search-input">
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
        <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M10.4 10.4L13 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </label>
  );
}

// Toggle — accessible on/off switch used in Settings.
export function Toggle({
  checked,
  onChange,
  label
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`toggle ${checked ? "on" : "off"}`}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-knob" />
    </button>
  );
}

// SettingField — label + control row for Settings forms.
export function SettingField({
  label,
  hint,
  children
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="setting-field">
      <div className="setting-field-text">
        <span>{label}</span>
        {hint ? <small>{hint}</small> : null}
      </div>
      <div className="setting-field-control">{children}</div>
    </div>
  );
}

// IconButton — generic round icon button used in section headers (export, etc).
export function IconButton({
  icon,
  label,
  onClick,
  tone
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  tone?: "default" | "primary";
}) {
  return (
    <button
      type="button"
      className={`icon-btn ${tone === "primary" ? "primary" : ""}`}
      onClick={onClick}
      aria-label={label}
      title={label}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
