import { Dispatch, ReactElement, SetStateAction, useEffect, useMemo, useState } from "react";
import type { ViewEnvelope } from "./types";
import {
  DownloadIcon,
  DirectActionHandler,
  FilterIcon,
  UploadIcon
} from "./coreUI";
import {
  mockChannels,
  mockClients,
  mockDeadlines,
  mockRules,
  mockSyncStatus,
  type MockClient,
  type MockDeadline,
  type MockRule
} from "./mockData";

export type SectionId = "work" | "clients" | "review" | "settings";

export type SectionDispatch = (
  plan: Record<string, unknown>,
  expectedView: string,
  echo: string
) => void;

export type SectionContext = {
  tenantId: string;
  view: ViewEnvelope;
  busy: boolean;
  dispatch: SectionDispatch;
  onPrompt: (prompt: string) => void;
  onAction: DirectActionHandler;
  onExport?: (scope: string, format: "csv" | "pdf") => void;
  onOpenClient?: (clientId: string) => void;
  onNavigate?: (section: SectionId) => void;
  onNotify?: (text: string, tone?: "green" | "blue" | "gold" | "red") => void;
  deadlines?: MockDeadline[];
  setDeadlines?: Dispatch<SetStateAction<MockDeadline[]>>;
  rules?: MockRule[];
  setRules?: Dispatch<SetStateAction<MockRule[]>>;
  resolvedRuleIds?: string[];
  setResolvedRuleIds?: Dispatch<SetStateAction<string[]>>;
  changedDeadlineIds?: string[];
  setChangedDeadlineIds?: Dispatch<SetStateAction<string[]>>;
  importLaunchToken?: number;
};

export const sectionMeta: Record<SectionId, { eyebrow: string; title: string; subtitle: string }> = {
  work: {
    eyebrow: "Work",
    title: "Work queue",
    subtitle: "This week's actionable deadlines, blockers, and rule-change alerts."
  },
  clients: {
    eyebrow: "Clients",
    title: "Client directory",
    subtitle: "Open a client profile or import a portfolio."
  },
  review: {
    eyebrow: "Review",
    title: "Official changes that need a decision",
    subtitle: "Review only the tax-rule changes that affect the current client portfolio."
  },
  settings: {
    eyebrow: "Settings",
    title: "Workspace settings",
    subtitle: "Tenant identity, reminders, and connected channels."
  }
};

const stateOptions = [
  "All",
  "CA",
  "TX",
  "NY",
  "NJ",
  "WA",
  "MN",
  "WI",
  "IL",
  "IN",
  "OH",
  "MI",
  "MA",
  "NH",
  "CO",
  "UT",
  "ID",
  "OR",
  "FL",
  "NV",
  "AZ",
  "Federal"
];

const taxTypeOptions = [
  "All",
  "Federal income",
  "State income",
  "Sales/Use",
  "Property",
  "Payroll (941)",
  "Franchise",
  "Excise",
  "PTE election"
];

function formatDaysRemaining(deadline: MockDeadline) {
  if (deadline.status === "completed") return "Filed";
  if (deadline.extension_status && deadline.extended_due_date) return `Extended -> ${deadline.extended_due_date}`;
  if (deadline.days_remaining < 0) return `Overdue by ${Math.abs(deadline.days_remaining)} days`;
  if (deadline.days_remaining === 0) return "Due today";
  if (deadline.days_remaining === 1) return "Due tomorrow";
  return `In ${deadline.days_remaining} days`;
}

function statusClass(deadline: MockDeadline) {
  if (deadline.status === "blocked") return "cb";
  if (deadline.status === "extension-filed" || deadline.status === "extension-approved") return "ci";
  return "ca";
}

function statusLabel(deadline: MockDeadline) {
  if (deadline.status === "blocked") return deadline.blocker_reason ? `Blocked - ${deadline.blocker_reason}` : "Blocked";
  if (deadline.status === "extension-approved") return "Extension approved";
  if (deadline.status === "extension-filed") return "Extension filed";
  return "Active";
}

function isThisWeek(deadline: MockDeadline) {
  return deadline.status !== "completed" && deadline.days_remaining >= 0 && deadline.days_remaining <= 7;
}

function clientTags(client: MockClient) {
  if (client.risk_label === "high") return ["Q2 941 doc missing", "CA nexus review"];
  if (client.risk_label === "watch") return client.name.includes("Harbor")
    ? ["PTE decision pending", "Federal ext filed"]
    : ["TX notice - CA nexus"];
  if (client.states.length === 1) return ["Single-state", "Payroll current"];
  if (client.name.includes("Riverbend")) return ["Property: 3 counties"];
  if (client.name.includes("Atlas")) return ["IFTA extensions approved"];
  if (client.name.includes("Kestrel")) return ["Remote-first - PEO payroll"];
  if (client.name.includes("Maple")) return ["Two-clinic group"];
  if (client.name.includes("Glacier")) return ["E-commerce - Avalara"];
  return [client.applicable_taxes[0] || "Active profile"];
}

export function WorkSection({
  deadlines: deadlineStore,
  rules: ruleStore,
  onExport,
  onNotify,
  onNavigate,
  setDeadlines: setDeadlineStore
}: SectionContext) {
  const deadlines = deadlineStore ?? mockDeadlines;
  const rules = ruleStore ?? mockRules;
  const [filterOpen, setFilterOpen] = useState(false);
  const [stateFilter, setStateFilter] = useState("All");
  const [taxFilter, setTaxFilter] = useState("All");
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [selectedDeadlineId, setSelectedDeadlineId] = useState<string | null>(null);

  const visibleDeadlines = useMemo(
    () =>
      deadlines
        .filter((deadline) => {
          if (deadline.status === "completed") return archiveOpen;
          if (!archiveOpen && !isThisWeek(deadline)) return false;
          if (stateFilter !== "All" && deadline.jurisdiction !== stateFilter) return false;
          if (taxFilter !== "All" && deadline.tax_type !== taxFilter) return false;
          return true;
        })
        .sort((a, b) => a.days_remaining - b.days_remaining),
    [deadlines, stateFilter, taxFilter, archiveOpen]
  );

  const grouped = useMemo(() => {
    const groups = new Map<string, MockDeadline[]>();
    visibleDeadlines.forEach((deadline) => {
      const key = deadline.days_remaining <= 4 ? "Apr 27 - May 3" : deadline.due_label;
      groups.set(key, [...(groups.get(key) || []), deadline]);
    });
    return [...groups.entries()];
  }, [visibleDeadlines]);

  const selectedDeadline = selectedDeadlineId ? deadlines.find((deadline) => deadline.id === selectedDeadlineId) : null;
  const pendingRules = rules.filter((rule) => rule.status === "pending-review");
  const thisWeekCount = deadlines.filter(isThisWeek).length;
  const blockedCount = deadlines.filter((deadline) => deadline.status === "blocked").length;
  const nextThirty = deadlines.filter((deadline) => deadline.status !== "completed" && deadline.days_remaining >= 0 && deadline.days_remaining <= 30);

  function updateDeadline(deadlineId: string, updater: (deadline: MockDeadline) => MockDeadline) {
    setDeadlineStore?.((current) => current.map((deadline) => (deadline.id === deadlineId ? updater(deadline) : deadline)));
  }

  if (selectedDeadline) {
    return (
      <section className="ddh-work-detail">
        <button type="button" className="ddh-back-link" onClick={() => setSelectedDeadlineId(null)}>
          Back to work queue
        </button>
        <div className="detail-head">
          <div>
            <h2>{selectedDeadline.client_name} - {selectedDeadline.tax_type}</h2>
            <p>Inspect the source, reminders, blockers, and extension state for this item.</p>
          </div>
          <div className="detail-actions">
            <button
              type="button"
              className="ddh-btn"
              onClick={() => {
                updateDeadline(selectedDeadline.id, (deadline) => ({ ...deadline, status: "completed" }));
                setSelectedDeadlineId(null);
                onNotify?.(`${selectedDeadline.client_name} archived from the work queue.`, "blue");
              }}
            >
              Archive
            </button>
            <button
              type="button"
              className="ddh-btn ddh-btn-primary"
              onClick={() => {
                updateDeadline(selectedDeadline.id, (deadline) =>
                  deadline.status === "blocked"
                    ? { ...deadline, status: "pending", blocker_reason: null }
                    : { ...deadline, status: "blocked", blocker_reason: "Waiting on client" }
                );
                setSelectedDeadlineId(null);
              }}
            >
              {selectedDeadline.status === "blocked" ? "Resolve blocker" : "Mark blocked"}
            </button>
          </div>
        </div>

        <div className="detail-grid">
          <article className="detail-card">
            <div className="detail-card-lbl">Deadline</div>
            <div className="detail-bigtext">{selectedDeadline.tax_type} - {selectedDeadline.jurisdiction}</div>
            <div className="detail-date">{selectedDeadline.due_label} - {formatDaysRemaining(selectedDeadline)}</div>
            <div className="detail-fields">
              <div className="df"><span>Status</span><strong>{statusLabel(selectedDeadline)}</strong></div>
              <div className="df"><span>Assignee</span><strong>{selectedDeadline.assignee}</strong></div>
              <div className="df"><span>Source</span><strong>{selectedDeadline.source}</strong></div>
              <div className="df"><span>Extension</span><strong>{selectedDeadline.extended_due_date || "No extension"}</strong></div>
            </div>
          </article>
          <aside className="detail-right">
            <article className="detail-card">
              <div className="detail-card-lbl">Reminders</div>
              <h3>Queued reminder timeline</h3>
              <p>What is already scheduled for this deadline.</p>
              <div className="rem-item"><strong>Final-day push</strong><span>Email - scheduled</span><span>Apr 29, 8:00 AM</span></div>
            </article>
            <article className="detail-card">
              <div className="detail-card-lbl">Blocker</div>
              <h3>Blocking status</h3>
              <p>If this item is waiting on something, it will show here.</p>
              <div className="rem-item">
                <strong>{selectedDeadline.blocker_reason || "No blocker"}</strong>
                <span>{selectedDeadline.blocker_reason ? "Waiting on client to provide supporting information." : "This deadline is not blocked right now."}</span>
              </div>
            </article>
          </aside>
        </div>
      </section>
    );
  }

  return (
    <section className="ddh-work">
      <div className="ddh-summary">
        <SummaryCard label="This week" value={String(thisWeekCount)} sub="Actionable now" />
        <SummaryCard label="Blocked" value={String(blockedCount)} sub="Waiting on client" warn />
        <SummaryCard label="Rule changes" value={String(pendingRules.length)} sub="Need CPA decision" />
        <SummaryCard label="Next 30 days" value={String(nextThirty.length)} sub={`Across ${new Set(nextThirty.map((deadline) => deadline.client_id)).size} clients`} />
      </div>

      <div className="ddh-toolbar">
        <button type="button" className="ddh-btn" onClick={() => setFilterOpen((current) => !current)}>
          <FilterIcon /> Filter
        </button>
        <button type="button" className="ddh-btn" onClick={() => onExport?.("Work queue", "csv")}>
          <DownloadIcon /> Export
        </button>
        <button type="button" className="ddh-btn ddh-btn-sm ddh-archive-btn" onClick={() => setArchiveOpen((current) => !current)}>
          {archiveOpen ? "Back to active" : "View archive (1)"}
        </button>
        {filterOpen ? (
          <FilterPanel
            stateFilter={stateFilter}
            taxFilter={taxFilter}
            onState={setStateFilter}
            onTax={setTaxFilter}
            onClear={() => {
              setStateFilter("All");
              setTaxFilter("All");
            }}
            onDone={() => setFilterOpen(false)}
          />
        ) : null}
      </div>

      {grouped.map(([label, items], index) => (
        <div key={label} className="ddh-table">
          <div className="ddh-group">
            <span>{label}</span>
            <span>{index === 0 ? "This week - " : ""}{items.length} deadline{items.length === 1 ? "" : "s"}</span>
          </div>
          {index === 0 && pendingRules[0] ? (
            <div className="ddh-alert">
              <span className="ddh-alert-dot" />
              {pendingRules[0].source} - {pendingRules[0].title}. Affects {pendingRules[0].affected_count} clients.
              <button type="button" onClick={() => onNavigate?.("review")}>
                Review & apply
              </button>
            </div>
          ) : null}
          <div className="ddh-cols">
            <span>Client</span><span>Tax type</span><span>State</span><span>Status</span><span>Assignee</span><span />
          </div>
          {items.map((deadline) => (
            <button
              type="button"
              key={deadline.id}
              className={`ddh-row ${deadline.status === "blocked" ? "blocked" : ""}`}
              onClick={() => setSelectedDeadlineId(deadline.id)}
            >
              <span className="ddh-client">{deadline.client_name}</span>
              <span><span className="ddh-chip tax">{deadline.tax_type}</span></span>
              <span><span className="ddh-chip jurisdiction">{deadline.jurisdiction}</span></span>
              <span><span className={`ddh-chip ${statusClass(deadline)}`}>{statusLabel(deadline)}</span></span>
              <span className="ddh-assignee">{deadline.assignee}</span>
              <span className="ddh-link">Details</span>
            </button>
          ))}
        </div>
      ))}
    </section>
  );
}

function SummaryCard({ label, value, sub, warn }: { label: string; value: string; sub: string; warn?: boolean }) {
  return (
    <article className={`ddh-summary-card ${warn ? "warn" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{sub}</small>
    </article>
  );
}

function FilterPanel({
  stateFilter,
  taxFilter,
  onState,
  onTax,
  onClear,
  onDone
}: {
  stateFilter: string;
  taxFilter: string;
  onState: (value: string) => void;
  onTax: (value: string) => void;
  onClear: () => void;
  onDone: () => void;
}) {
  return (
    <div className="ddh-filter-panel">
      <div className="ddh-filter-head">
        <strong>Filter</strong>
        <button type="button" onClick={onClear}>Clear all</button>
      </div>
      <FilterPills label="State" value={stateFilter} options={stateOptions} onSelect={onState} />
      <FilterPills label="Tax type" value={taxFilter} options={taxTypeOptions} onSelect={onTax} />
      <button type="button" className="ddh-btn ddh-btn-primary" onClick={onDone}>Done</button>
    </div>
  );
}

function FilterPills({ label, value, options, onSelect }: { label: string; value: string; options: string[]; onSelect: (value: string) => void }) {
  return (
    <>
      <div className="ddh-filter-label">{label}</div>
      <div className="ddh-filter-pills">
        {options.map((option) => (
          <button
            type="button"
            key={option}
            className={`ddh-filter-pill ${option === value ? "on" : ""}`}
            onClick={() => onSelect(option)}
          >
            {option}
          </button>
        ))}
      </div>
    </>
  );
}

type ImportStep = 1 | 2 | 3 | 4;

export function ClientsSection({ onExport, onNotify, importLaunchToken = 0 }: SectionContext) {
  const [importOpen, setImportOpen] = useState(false);
  const [importStep, setImportStep] = useState<ImportStep>(1);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);

  useEffect(() => {
    if (importLaunchToken) {
      setImportOpen(true);
      setImportStep(1);
    }
  }, [importLaunchToken]);

  function openImport() {
    setImportOpen(true);
    setImportStep(1);
  }

  function closeImport() {
    setImportOpen(false);
    setImportStep(1);
  }

  if (importOpen) {
    return (
      <ImportWizard
        step={importStep}
        onStep={setImportStep}
        onClose={closeImport}
        onDone={() => {
          onNotify?.("30 clients imported. Full-year deadline calendars generated.", "green");
          closeImport();
        }}
      />
    );
  }

  const selectedClient = selectedClientId ? mockClients.find((client) => client.id === selectedClientId) : null;
  if (selectedClient) {
    const clientDeadlines = mockDeadlines.filter((deadline) => deadline.client_id === selectedClient.id);
    return (
      <section className="ddh-work-detail">
        <button type="button" className="ddh-back-link" onClick={() => setSelectedClientId(null)}>
          Back to client directory
        </button>
        <div className="detail-head">
          <div>
            <h2>{selectedClient.name}</h2>
            <p>{selectedClient.entity_type} - {selectedClient.states.join(", ")} - {selectedClient.primary_contact_email}</p>
          </div>
          <div className="detail-actions">
            <button type="button" className="ddh-btn" onClick={() => onExport?.(`${selectedClient.name} profile`, "pdf")}>Export profile</button>
            <button type="button" className="ddh-btn ddh-btn-primary" onClick={() => onNotify?.(`Opened ${selectedClient.name} in the client workspace.`, "blue")}>Open workspace</button>
          </div>
        </div>
        <div className="detail-grid">
          <article className="detail-card">
            <div className="detail-card-lbl">Client profile</div>
            <div className="detail-bigtext">{selectedClient.primary_contact_name}</div>
            <div className="detail-date">{selectedClient.notes}</div>
            <div className="detail-fields">
              <div className="df"><span>Active</span><strong>{selectedClient.active_deadlines} deadlines</strong></div>
              <div className="df"><span>Blocked</span><strong>{selectedClient.blocked_deadlines} deadlines</strong></div>
              <div className="df"><span>Extensions</span><strong>{selectedClient.extensions_filed} filed</strong></div>
              <div className="df"><span>Tax types</span><strong>{selectedClient.applicable_taxes.join(", ")}</strong></div>
            </div>
          </article>
          <aside className="detail-right">
            <article className="detail-card">
              <div className="detail-card-lbl">Upcoming work</div>
              <h3>{clientDeadlines.length} portfolio deadlines</h3>
              <p>Active and archived records currently known for this client.</p>
              {clientDeadlines.slice(0, 4).map((deadline) => (
                <div className="rem-item" key={deadline.id}>
                  <strong>{deadline.tax_type} - {deadline.jurisdiction}</strong>
                  <span>{deadline.due_label} - {statusLabel(deadline)}</span>
                </div>
              ))}
            </article>
          </aside>
        </div>
      </section>
    );
  }

  return (
    <section>
      <div className="ddh-page-head">
        <div>
          <div className="ddh-eyebrow">Clients</div>
          <h1>Client directory</h1>
        </div>
        <div className="ddh-actions">
          <button type="button" className="ddh-btn">Filter</button>
          <button type="button" className="ddh-btn" onClick={() => onExport?.("Client directory", "pdf")}>Export</button>
          <button type="button" className="ddh-btn ddh-btn-primary" onClick={openImport}><UploadIcon /> Import</button>
        </div>
      </div>

      <div className="ddh-client-grid">
        {mockClients.slice(0, 9).map((client) => (
          <ClientTile key={client.id} client={client} onOpen={() => setSelectedClientId(client.id)} />
        ))}
      </div>
    </section>
  );
}

function ClientTile({ client, onOpen }: { client: MockClient; onOpen: () => void }) {
  const tags = clientTags(client);
  return (
    <article className={`ddh-client-card ${client.risk_label === "high" ? "high" : client.risk_label === "watch" ? "watch" : ""}`}>
      <h2>{client.name}</h2>
      <p>{client.entity_type} - {client.states.join(", ")}</p>
      <div className="ddh-client-tags">
        {tags.map((tag, index) => (
          <span key={tag} className={`ddh-client-tag ${client.risk_label === "high" && index === 0 ? "danger" : client.risk_label === "watch" ? "warn" : "neutral"}`}>
            {tag}
          </span>
        ))}
      </div>
      <div className="ddh-client-counts">
        <span><strong>{client.active_deadlines}</strong> active</span>
        <span><strong>{client.blocked_deadlines}</strong> blocked</span>
      </div>
      <div className="ddh-client-foot">
        <span>{client.primary_contact_name}</span>
        <button type="button" onClick={onOpen}>Details</button>
      </div>
    </article>
  );
}

function ImportWizard({
  step,
  onStep,
  onClose,
  onDone
}: {
  step: ImportStep;
  onStep: (step: ImportStep) => void;
  onClose: () => void;
  onDone: () => void;
}) {
  function next() {
    if (step < 4) onStep((step + 1) as ImportStep);
  }
  function back() {
    if (step > 1) onStep((step - 1) as ImportStep);
  }

  return (
    <section className="ddh-import">
      <div className="ddh-import-head">
        <div>
          <div className="ddh-eyebrow">Clients - Import</div>
          <h1>Bring a portfolio of clients into DueDateHQ</h1>
          <p>Upload a CSV, confirm how its columns map to our client fields, and review duplicate detection before anything is written.</p>
        </div>
        <button type="button" className="ddh-btn" onClick={onClose}>Cancel & back to clients</button>
      </div>
      <div className="ddh-stepper">
        {["Choose file", "Map columns", "Review rows", "Done"].map((label, index) => {
          const itemStep = (index + 1) as ImportStep;
          return (
            <div key={label} className="ddh-step">
              <span className={itemStep <= step ? "active" : ""}>{index + 1}</span>
              <strong className={itemStep <= step ? "active" : ""}>{label}</strong>
            </div>
          );
        })}
      </div>
      <div className="ddh-import-body">
        {step === 1 ? <ImportStepOne onNext={next} /> : null}
        {step === 2 ? <ImportStepTwo onBack={back} onNext={next} /> : null}
        {step === 3 ? <ImportStepThree onBack={back} onNext={next} /> : null}
        {step === 4 ? <ImportStepDone onDone={onDone} /> : null}
      </div>
    </section>
  );
}

function ImportStepOne({ onNext }: { onNext: () => void }) {
  return (
    <>
      <button type="button" className="ddh-upload-area" onClick={onNext}>
        <span className="ddh-upload-icon">↑</span>
        <strong>Drop your CSV here, or click to browse</strong>
        <small>clients_taxdome_export.csv - 847 bytes - 31 rows detected</small>
        <span className="ddh-source-tags">
          {["TaxDome", "Drake", "Karbon", "QuickBooks", "Custom CSV"].map((source) => <em key={source}>{source}</em>)}
        </span>
      </button>
      <div className="ddh-step-foot"><button type="button" className="ddh-btn ddh-btn-primary" onClick={onNext}>Continue</button></div>
    </>
  );
}

function ImportStepTwo({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const rows = [
    ["client_name", "Northwind Services LLC", "Client name", "Auto-matched"],
    ["ein", "47-2938471", "EIN / Tax ID", "Auto-matched"],
    ["entity_type", "LLC", "Entity type", "Auto-matched"],
    ["primary_state", "CA", "Primary state", "Auto-matched"],
    ["additional_states", "TX, NV", "Additional states", "Auto-matched"],
    ["tax_types_csv", "Federal income, 941", "Tax types", "Auto-matched"],
    ["assigned_preparer", "Maya Chen", "Assignee", "Auto-matched"],
    ["misc_notes", "Payroll heavy, 3 states", "Skip column", "Review needed"]
  ];
  return (
    <>
      <p className="ddh-import-note">AI detected 7 of 8 fields automatically. Review the mapping before continuing.</p>
      <table className="ddh-map-table">
        <thead><tr><th>CSV column</th><th>Sample value</th><th>Field</th><th>Confidence</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]}>
              <td><code>{row[0]}</code></td>
              <td>{row[1]}</td>
              <td><select defaultValue={row[2]}><option>{row[2]}</option><option>Notes</option><option>Skip column</option></select></td>
              <td><span className={row[3] === "Review needed" ? "review" : "auto"}>{row[3]}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="ddh-step-foot"><button type="button" className="ddh-btn" onClick={onBack}>Back</button><button type="button" className="ddh-btn ddh-btn-primary" onClick={onNext}>Continue</button></div>
    </>
  );
}

function ImportStepThree({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const rows = [
    ["Northwind Services LLC", "LLC", "CA, TX, NV", "Federal, 941, Sales/Use", "Maya Chen", "Ready"],
    ["Harbor Studio Partners", "Partnership", "NY, NJ", "Federal, PTE election", "Evan Malik", "Ready"],
    ["Sierra Wholesale Inc.", "C-Corp", "TX, CA, AZ", "Federal, State, Sales/Use", "Daniel Ortega", "Ready"],
    ["Pinecone Dental P.C.", "Prof Corp", "WA", "Federal, State, 941", "Dr. Lila Park", "Ready"],
    ["Greenway Consulting LLC", "-", "CO", "Federal, State", "Owen Patel", "Entity type missing"]
  ];
  return (
    <>
      <p className="ddh-import-note">30 rows parsed - 0 duplicates detected - 1 row needs attention</p>
      <table className="ddh-review-table">
        <thead><tr><th>Client</th><th>Entity</th><th>States</th><th>Tax types</th><th>Assignee</th><th>Status</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]} className={row[5] !== "Ready" ? "warn" : ""}>
              {row.map((cell, index) => <td key={index}><span className={index === 5 ? (cell === "Ready" ? "auto" : "review") : ""}>{cell}</span></td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="ddh-step-foot"><button type="button" className="ddh-btn" onClick={onBack}>Back</button><button type="button" className="ddh-btn ddh-btn-primary" onClick={onNext}>Import 30 clients</button></div>
    </>
  );
}

function ImportStepDone({ onDone }: { onDone: () => void }) {
  return (
    <div className="ddh-import-done">
      <div>✓</div>
      <h2>30 clients imported</h2>
      <p>Full-year deadline calendars generated. 1 client needs entity type before deadlines can be assigned.</p>
      <button type="button" className="ddh-btn ddh-btn-primary" onClick={onDone}>Go to client directory</button>
    </div>
  );
}

export function ReviewSection({
  rules: ruleStore,
  setRules,
  setResolvedRuleIds,
  deadlines: deadlineStore,
  setDeadlines,
  setChangedDeadlineIds,
  onNotify
}: SectionContext) {
  const rules = ruleStore ?? mockRules;
  const pendingRules = rules.filter((rule) => rule.status === "pending-review");
  const autoApplied = rules.filter((rule) => rule.status === "auto-applied");

  function applyRule(ruleId: string) {
    const changedIds: string[] = [];
    setRules?.((current) => current.map((rule) => rule.id === ruleId ? { ...rule, status: "auto-applied" } : rule));
    setDeadlines?.((current) =>
      current.map((deadline) => {
        if (deadline.notice_rule_id !== ruleId) return deadline;
        changedIds.push(deadline.id);
        return { ...deadline, notice_rule_id: undefined, due_label: "May 30", due_date: "2026-05-30", days_remaining: 34 };
      })
    );
    setResolvedRuleIds?.((current) => current.includes(ruleId) ? current : [...current, ruleId]);
    setChangedDeadlineIds?.((current) => [...new Set([...current, ...changedIds])]);
    onNotify?.("Rule applied to affected clients.", "green");
  }

  function dismissRule(ruleId: string) {
    setRules?.((current) => current.map((rule) => rule.id === ruleId ? { ...rule, status: "dismissed" } : rule));
    setResolvedRuleIds?.((current) => current.includes(ruleId) ? current : [...current, ruleId]);
    onNotify?.("Rule dismissed for this portfolio.", "gold");
  }

  return (
    <section>
      <div className="ddh-page-head review-head">
        <div>
          <div className="ddh-eyebrow">Review</div>
          <h1>Official changes that need a decision</h1>
          <p>Review only the tax-rule changes that affect the current client portfolio.</p>
        </div>
      </div>
      <div className="ddh-review-info">
        <div>
          <strong>{pendingRules.length} official changes need review</strong>
          <span>{mockSyncStatus.rules_auto_applied_today} auto-applied today - {mockSyncStatus.source_count} sources healthy</span>
        </div>
        <div>
          Last full sync <strong>{mockSyncStatus.last_full_sync}</strong> - Next sync <strong>{mockSyncStatus.next_scheduled_sync}</strong>
          <em>Healthy</em>
        </div>
      </div>
      <div className="ddh-review-label">
        <strong>Review queue</strong>
        <span>Open a row for source, diff, and affected clients.</span>
      </div>
      {pendingRules.map((rule) => (
        <ReviewRule key={rule.id} rule={rule} deadlines={deadlineStore ?? mockDeadlines} onApply={applyRule} onDismiss={dismissRule} />
      ))}
      {autoApplied.length ? <div className="ddh-section-divider">Auto-applied today</div> : null}
      {autoApplied.map((rule) => (
        <ReviewRule key={rule.id} rule={rule} deadlines={deadlineStore ?? mockDeadlines} auto onApply={applyRule} onDismiss={dismissRule} />
      ))}
    </section>
  );
}

function ReviewRule({
  rule,
  deadlines,
  auto,
  onApply,
  onDismiss
}: {
  rule: MockRule;
  deadlines: MockDeadline[];
  auto?: boolean;
  onApply: (id: string) => void;
  onDismiss: (id: string) => void;
}) {
  const affected = rule.affected_count || deadlines.filter((deadline) => deadline.notice_rule_id === rule.id).length;
  return (
    <article className={`ddh-rule ${auto ? "auto" : ""}`}>
      <div className="ddh-rule-top">
        <div>
          <h2>{rule.title}</h2>
          <p>{rule.jurisdiction} - {rule.source} - detected {new Date(rule.detected_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</p>
        </div>
        <span>{auto ? "Auto-applied" : "Pending review"}</span>
      </div>
      <p>{rule.summary}</p>
      <div className="ddh-rule-tags">
        <span>Affects <strong>{affected} client{affected === 1 ? "" : "s"}</strong></span>
        <span><strong>Change</strong> {rule.diff_before} to {rule.diff_after}</span>
      </div>
      <div className="ddh-rule-foot">
        <button type="button">Official source</button>
        <div>
          {auto ? (
            <>
              <button type="button" className="ddh-btn ddh-btn-sm">View changes</button>
              <button type="button" className="ddh-btn ddh-btn-sm">Undo</button>
            </>
          ) : (
            <>
              <button type="button" className="ddh-btn">Review details</button>
              <button type="button" className="ddh-btn" onClick={() => onDismiss(rule.id)}>Dismiss</button>
              <button type="button" className="ddh-btn ddh-btn-primary" onClick={() => onApply(rule.id)}>Apply to {affected} client{affected === 1 ? "" : "s"}</button>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

export function SettingsSection({ tenantId, onNotify }: SectionContext) {
  const [displayName, setDisplayName] = useState("Johnson CPA PLLC");
  const [timeZone, setTimeZone] = useState("America/Los_Angeles");
  const [fiscalYear, setFiscalYear] = useState("Calendar (Jan - Dec)");
  const [channels, setChannels] = useState(() => mockChannels.slice(0, 3).map((channel) => ({ ...channel })));

  function saveSettings() {
    onNotify?.("Workspace settings saved for this session.", "green");
  }

  return (
    <section>
      <div className="ddh-page-head"><div><div className="ddh-eyebrow">Settings</div><h1>Workspace settings</h1></div></div>
      <SettingsCard label="Workspace" title="Tenant identity" subtitle="Display name, time zone, and fiscal year shown across the app.">
        <SettingRow label="Display name" sub="Shown in the topbar and on exports." value={displayName} onChange={setDisplayName} />
        <SettingRow label="Time zone" sub="Used for reminder send times." value={timeZone} onChange={setTimeZone} />
        <SettingRow label="Fiscal year" sub="Used to bucket extensions and YTD totals." value={fiscalYear} onChange={setFiscalYear} />
        <SettingRow label="Tenant ID" sub="Sent on every backend request - read only." value={tenantId} mono />
        <div className="ddh-settings-foot"><span>Anchored today: Apr 26, 2026</span><button type="button" className="ddh-btn ddh-btn-primary" onClick={saveSettings}>Save changes</button></div>
      </SettingsCard>
      <SettingsCard label="Notifications" title="Reminder channels" subtitle="Toggle which channels carry the 30/14/7/1 stepped reminders.">
        {channels.map((channel) => (
          <div key={channel.id} className="ddh-setting-row">
            <div><strong>{channel.label}</strong><span>{channel.description}</span></div>
            <button
              type="button"
              className={`ddh-channel-toggle ${channel.enabled ? "enabled" : ""}`}
              onClick={() =>
                setChannels((current) =>
                  current.map((item) => item.id === channel.id ? { ...item, enabled: !item.enabled } : item)
                )
              }
            >
              {channel.enabled ? "Enabled" : "Not connected"}
            </button>
          </div>
        ))}
      </SettingsCard>
    </section>
  );
}

function SettingsCard({ label, title, subtitle, children }: { label: string; title: string; subtitle: string; children: ReactElement | ReactElement[] }) {
  return (
    <article className="ddh-settings-card">
      <div className="ddh-eyebrow">{label}</div>
      <h2>{title}</h2>
      <p>{subtitle}</p>
      {children}
    </article>
  );
}

function SettingRow({
  label,
  sub,
  value,
  mono,
  onChange
}: {
  label: string;
  sub: string;
  value: string;
  mono?: boolean;
  onChange?: (value: string) => void;
}) {
  return (
    <div className="ddh-setting-row">
      <div><strong>{label}</strong><span>{sub}</span></div>
      <input
        className={mono ? "mono" : ""}
        value={value}
        readOnly={!onChange}
        onChange={(event) => onChange?.(event.target.value)}
      />
    </div>
  );
}

export const sectionOrder: SectionId[] = ["work", "clients", "review", "settings"];

export function SectionNav({
  current,
  onSelect,
  pendingReviewCount
}: {
  current: SectionId;
  onSelect: (id: SectionId) => void;
  pendingReviewCount: number;
}) {
  return (
    <nav className="section-nav">
      {sectionOrder.map((id) => (
        <button
          key={id}
          type="button"
          className={`section-nav-btn ${id === current ? "active" : ""}`}
          onClick={() => onSelect(id)}
        >
          {sectionMeta[id].eyebrow}
          {id === "review" && pendingReviewCount ? <span className="tab-badge">{pendingReviewCount}</span> : null}
        </button>
      ))}
    </nav>
  );
}

export const sectionComponents: Record<SectionId, (ctx: SectionContext) => ReactElement> = {
  work: WorkSection,
  clients: ClientsSection,
  review: ReviewSection,
  settings: SettingsSection
};
