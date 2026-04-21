import { useEffect, useMemo, useState } from "react";
import {
  calendarMonth,
  clientRecords,
  dashboardData,
  getClientById,
  getNoticeById,
  importDraft,
  navItems,
  notices,
  pagePrompts,
  rulesWorkspace
} from "./mockData";

const PAGE_META = {
  dashboard: {
    eyebrow: "Weekly Triage",
    title: "This week across your client portfolio",
    description:
      "A practice-management style home screen: open deadlines, waiting-on-info blockers, and notice review in one place."
  },
  clients: {
    eyebrow: "Clients",
    title: "Client portfolio",
    description:
      "A client list like TaxDome or Canopy, but tuned for filing readiness, risk, and next deadline instead of generic CRM fields."
  },
  client: {
    eyebrow: "Client Record",
    title: "Client detail",
    description:
      "A single-client workspace for obligations, status, annual filing profile, and next available actions."
  },
  import: {
    eyebrow: "Import & Mapping",
    title: "Normalize existing CPA data",
    description:
      "Start from the spreadsheet firms already use today, map fields into DueDateHQ, and only follow up on the missing pieces."
  },
  notices: {
    eyebrow: "Notice Review",
    title: "Official change review",
    description:
      "This is the product's distinctive surface: official source, affected clients, safe updates, and manual review in one workflow."
  },
  calendar: {
    eyebrow: "Calendar",
    title: "Monthly filing calendar",
    description:
      "A classic workload calendar for spotting busy weeks and quickly seeing what lands together."
  },
  rules: {
    eyebrow: "Rules & Templates",
    title: "Rules and reminder templates",
    description:
      "A lightweight configuration surface for the filing engine: rule templates, reminder cadence, and review queue."
  }
};

const INITIAL_MESSAGES = [
  {
    id: "m-1",
    role: "assistant",
    text:
      "I can help you navigate the product skeleton. Try asking for the dashboard, a client record, import review, or notice review."
  }
];

const WORKFLOW_GUIDES = {
  dashboard: {
    eyebrow: "Workflow guide",
    title: "How a CPA should use this dashboard",
    tip: "Start with Track, clear anything blocked in Waiting on info, then decide whether a Notice or Watchlist item should become real work.",
    steps: [
      { label: "1. Track", description: "Pick the active filing or review item that should move first this week." },
      { label: "2. Waiting on info", description: "Clear blockers so the queue stops being delayed by missing documents or confirmations." },
      { label: "3. Notice + Watchlist", description: "Decide whether policy changes or risky clients should become real tasks." }
    ]
  },
  import: {
    eyebrow: "Workflow guide",
    title: "How onboarding should flow",
    tip: "The goal is not to rebuild the CPA's world from scratch. Confirm what mapped correctly, fix only what is missing, then generate the first working dashboard.",
    steps: [
      { label: "1. Review mapping", description: "Check whether the spreadsheet columns landed in the right DueDateHQ fields." },
      { label: "2. Fill deadline-driving gaps", description: "Only fix the fields that change filings, jurisdictions, or reminder behavior." },
      { label: "3. Generate dashboard", description: "Once the profile is good enough, create the first weekly queue instead of asking for every possible detail." }
    ]
  },
  notice: {
    eyebrow: "Workflow guide",
    title: "How notice review should work",
    tip: "A notice only matters if the CPA can turn it into a decision. Read the source, inspect affected clients, then either archive it or create real work from it.",
    steps: [
      { label: "1. Verify the source", description: "Confirm this is an official update worth attention." },
      { label: "2. Inspect impacted clients", description: "See who was auto-updated and who still needs human review." },
      { label: "3. Decide the action", description: "Mark read, dismiss, or turn the notice into a work item for the team." }
    ]
  },
  client: {
    eyebrow: "Workflow guide",
    title: "How to work a single client record",
    tip: "Use this page to understand why the client is here, then act on the one deadline or blocker that matters most before returning to the portfolio view.",
    steps: [
      { label: "1. Read the profile", description: "Confirm the key filing facts and the account context." },
      { label: "2. Find the blocker or obligation", description: "Pick the deadline or missing input that is actually preventing progress." },
      { label: "3. Take one next action", description: "Complete it, remind later, adjust the date, or continue the outreach loop." }
    ]
  }
};

function App() {
  const [activePage, setActivePage] = useState("dashboard");
  const [selectedClientId, setSelectedClientId] = useState("cl-001");
  const [selectedNoticeId, setSelectedNoticeId] = useState("notice-001");
  const [clientsData, setClientsData] = useState(clientRecords);
  const [journeyBanner, setJourneyBanner] = useState({
    title: "Start with the core workflow",
    body: "Import data, generate the weekly dashboard, then move through Track, Waiting on info, Notice, and Client Detail."
  });
  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [inputValue, setInputValue] = useState("");

  const selectedClient = useMemo(
    () => clientsData.find((client) => client.client_id === selectedClientId) || clientsData[0],
    [clientsData, selectedClientId]
  );
  const selectedNotice = useMemo(() => getNoticeById(selectedNoticeId), [selectedNoticeId]);
  const pageKey = activePage === "client" ? "client" : activePage;
  const meta = PAGE_META[pageKey];
  const currentGuide = WORKFLOW_GUIDES[pageKey];
  const prompts = pagePrompts[pageKey] || pagePrompts.dashboard;

  function pushMessage(role, text) {
    setMessages((current) => [
      ...current,
      { id: `m-${current.length + 1}`, role, text }
    ]);
  }

  function goToPage(page) {
    setActivePage(page);
  }

  function openClient(clientId) {
    setSelectedClientId(clientId);
    setActivePage("client");
    const client = clientsData.find((item) => item.client_id === clientId);
    if (client) {
      setJourneyBanner({
        title: `Now working ${client.client_name}`,
        body: "Read the client context first, then act on one obligation or blocker before returning to the portfolio."
      });
    }
  }

  function openNotice(noticeId) {
    setSelectedNoticeId(noticeId);
    setActivePage("notices");
    const notice = getNoticeById(noticeId);
    if (notice) {
      setJourneyBanner({
        title: `Now reviewing ${notice.title}`,
        body: "Verify the source, inspect impacted clients, then either mark it read, dismiss it, or turn it into a task."
      });
    }
  }

  function applyClientDeadlineUpdate(clientId, deadlineId, updater) {
    setClientsData((current) =>
      current.map((client) =>
        client.client_id !== clientId
          ? client
          : {
              ...client,
              deadlines: client.deadlines.map((deadline) =>
                deadline.deadline_id === deadlineId ? updater(deadline) : deadline
              )
            }
      )
    );
  }

  function reportJourney(title, body) {
    setJourneyBanner({ title, body });
  }

  function generateDashboardFromImport() {
    setActivePage("dashboard");
    setJourneyBanner({
      title: "Dashboard generated from imported data",
      body: "Start in Track, then clear Waiting on info. If a notice matters, convert it into a task instead of leaving it as a passive update."
    });
    pushMessage("assistant", "The dashboard is ready. Start by reviewing Track, then move to Waiting on info.");
  }

  function handlePromptSubmit(prompt) {
    const trimmed = prompt.trim();
    if (!trimmed) return;

    pushMessage("user", trimmed);
    setInputValue("");

    const lower = trimmed.toLowerCase();

    if (lower.includes("dashboard") || lower.includes("today") || lower.includes("week")) {
      setActivePage("dashboard");
      pushMessage("assistant", "Opened the weekly triage dashboard.");
      return;
    }

    if (lower.includes("client") || lower.includes("portfolio")) {
      setActivePage("clients");
      pushMessage("assistant", "Opened the client portfolio.");
      return;
    }

    if (lower.includes("harbor")) {
      openClient("cl-002");
      pushMessage("assistant", "Opened Harbor Studio Partners.");
      return;
    }

    if (lower.includes("northwind")) {
      openClient("cl-001");
      pushMessage("assistant", "Opened Northwind Services LLC.");
      return;
    }

    if (lower.includes("sierra")) {
      openClient("cl-003");
      pushMessage("assistant", "Opened Sierra Wholesale Inc.");
      return;
    }

    if (lower.includes("import") || lower.includes("mapping") || lower.includes("spreadsheet")) {
      setActivePage("import");
      pushMessage("assistant", "Opened the import and mapping workflow.");
      return;
    }

    if (lower.includes("notice") || lower.includes("changed") || lower.includes("review")) {
      setActivePage("notices");
      pushMessage("assistant", "Opened the official notice review workspace.");
      return;
    }

    if (lower.includes("calendar") || lower.includes("month")) {
      setActivePage("calendar");
      pushMessage("assistant", "Opened the monthly filing calendar.");
      return;
    }

    if (lower.includes("rule") || lower.includes("template") || lower.includes("reminder")) {
      setActivePage("rules");
      pushMessage("assistant", "Opened the rules and templates page.");
      return;
    }

    pushMessage(
      "assistant",
      "I can open the dashboard, clients, import, notices, calendar, or rules pages."
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand-card">
          <div className="brand-dot" />
          <div>
            <div className="brand-name">DueDateHQ</div>
            <p>Deadline intelligence for CPA teams</p>
          </div>
        </div>

        <nav className="nav-list">
          {navItems.map((item) => {
            const isActive =
              activePage === item.id || (activePage === "client" && item.id === "clients");
            return (
              <button
                key={item.id}
                type="button"
                className={`nav-item ${isActive ? "active" : ""}`}
                onClick={() => goToPage(item.id)}
              >
                {item.label}
              </button>
            );
          })}
        </nav>

        <section className="sidebar-card">
          <div className="sidebar-label">Core flow</div>
          <p>
            Import data, fill missing fields, generate the weekly queue, open a client, and decide the next action.
          </p>
        </section>
      </aside>

      <div className="app-frame">
        <header className="topbar">
          <div>
            <div className="eyebrow">{meta.eyebrow}</div>
            <h1>{meta.title}</h1>
            <p>{meta.description}</p>
          </div>
          <div className="topbar-actions">
            {currentGuide ? <HelpMenu guide={currentGuide} /> : null}
            <button type="button" className="button button-secondary" onClick={() => goToPage("import")}>
              Open import
            </button>
            <button type="button" className="button button-primary" onClick={() => goToPage("notices")}>
              Review notices
            </button>
          </div>
        </header>

        <section className="card journey-banner">
          <div>
            <div className="panel-label">Next step</div>
            <h3>{journeyBanner.title}</h3>
            <p>{journeyBanner.body}</p>
          </div>
        </section>

        <div className="content-grid">
          <main className="workspace-panel">
            <MainContent
              activePage={activePage}
              clients={clientsData}
              selectedClient={selectedClient}
              selectedNotice={selectedNotice}
              onOpenClient={openClient}
              onOpenNotice={openNotice}
              onGenerateDashboard={generateDashboardFromImport}
              onClientDeadlineUpdate={applyClientDeadlineUpdate}
              onJourneyEvent={reportJourney}
            />
          </main>

          <aside className="assistant-panel">
            <section className="panel-card">
              <div className="panel-label">AI Assistant</div>
              <h3>How AI fits here</h3>
              <p>{assistantSummary(activePage, selectedClient, selectedNotice)}</p>
            </section>

            <section className="panel-card">
              <div className="panel-label">Suggested prompts</div>
              <div className="prompt-list">
                {prompts.map((prompt) => (
                  <button key={prompt} type="button" className="prompt-chip" onClick={() => handlePromptSubmit(prompt)}>
                    {prompt}
                  </button>
                ))}
              </div>
            </section>

            <section className="panel-card">
              <div className="panel-label">Conversation</div>
              <div className="message-list">
                {messages.map((message) => (
                  <article key={message.id} className={`message ${message.role}`}>
                    <strong>{message.role === "assistant" ? "DueDateHQ" : "You"}</strong>
                    <p>{message.text}</p>
                  </article>
                ))}
              </div>
            </section>
          </aside>
        </div>

        <footer className="composer-panel">
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              handlePromptSubmit(inputValue);
            }}
          >
            <textarea
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              placeholder="Ask to open a page or inspect a client. Example: open Harbor Studio Partners"
            />
            <button className="button button-primary" type="submit">
              Send
            </button>
          </form>
        </footer>
      </div>
    </div>
  );
}

function MainContent({
  activePage,
  clients,
  selectedClient,
  selectedNotice,
  onOpenClient,
  onOpenNotice,
  onGenerateDashboard,
  onClientDeadlineUpdate,
  onJourneyEvent
}) {
  if (activePage === "dashboard") {
    return <DashboardPage onOpenClient={onOpenClient} onOpenNotice={onOpenNotice} onJourneyEvent={onJourneyEvent} />;
  }

  if (activePage === "clients") {
    return <ClientsPage clients={clients} onOpenClient={onOpenClient} />;
  }

  if (activePage === "client") {
    return <ClientDetailPage client={selectedClient} onDeadlineUpdate={onClientDeadlineUpdate} onJourneyEvent={onJourneyEvent} />;
  }

  if (activePage === "import") {
    return <ImportPage onGenerateDashboard={onGenerateDashboard} onJourneyEvent={onJourneyEvent} />;
  }

  if (activePage === "notices") {
    return <NoticesPage selectedNotice={selectedNotice} onOpenClient={onOpenClient} onOpenNotice={onOpenNotice} onJourneyEvent={onJourneyEvent} />;
  }

  if (activePage === "calendar") {
    return <CalendarPage />;
  }

  return <RulesPage />;
}

function DashboardPage({ onOpenClient, onOpenNotice, onJourneyEvent }) {
  const [activeLane, setActiveLane] = useState("track");
  const [triageQueue, setTriageQueue] = useState(dashboardData.triage_queue);
  const [waitingItems, setWaitingItems] = useState(dashboardData.waiting_on_info);
  const [noticeItems, setNoticeItems] = useState(
    dashboardData.notice_watchlist.map((item, index) => ({
      ...item,
      read: index > 0
    }))
  );
  const [watchItems, setWatchItems] = useState(dashboardData.client_watchlist);
  const [actionMessage, setActionMessage] = useState(
    "Pick a lane on the dashboard. Each item now has a CPA action path instead of being a static card."
  );
  const [selectedIds, setSelectedIds] = useState({
    track: dashboardData.triage_queue[0]?.deadline_id || null,
    waiting: dashboardData.waiting_on_info[0]?.client_id || null,
    notices: dashboardData.notice_watchlist[0]?.notice_id || null,
    watchlist: dashboardData.client_watchlist[0]?.client_id || null
  });

  const laneConfig = useMemo(
    () => ({
      track: {
        items: triageQueue,
        itemKey: "deadline_id"
      },
      waiting: {
        items: waitingItems,
        itemKey: "client_id"
      },
      notices: {
        items: noticeItems,
        itemKey: "notice_id"
      },
      watchlist: {
        items: watchItems,
        itemKey: "client_id"
      }
    }),
    [noticeItems, triageQueue, waitingItems, watchItems]
  );

  const dashboardStats = [
    { label: "Track", value: `${triageQueue.length}`, tone: "neutral" },
    { label: "Need review", value: `${noticeItems.filter((item) => !item.read).length}`, tone: "review" },
    { label: "Waiting on info", value: `${waitingItems.length}`, tone: "critical" },
    { label: "Watchlist", value: `${watchItems.length}`, tone: "success" }
  ];

  const currentLane = laneConfig[activeLane];
  const currentMeta = dashboardData.section_meta[activeLane];
  const currentItem = currentLane.items.find((item) => item[currentLane.itemKey] === selectedIds[activeLane]) || currentLane.items[0];

  function selectLane(lane) {
    setActiveLane(lane);
  }

  function selectItem(lane, id) {
    setActiveLane(lane);
    setSelectedIds((current) => ({ ...current, [lane]: id }));
  }

  function replaceLaneSelection(lane, nextItems, itemKey) {
    setSelectedIds((current) => ({
      ...current,
      [lane]: nextItems.some((item) => item[itemKey] === current[lane]) ? current[lane] : nextItems[0]?.[itemKey] || null
    }));
  }

  function handleTrackAction(action) {
    if (!currentItem) return;

    if (action === "complete") {
      const nextItems = triageQueue.filter((item) => item.deadline_id !== currentItem.deadline_id);
      setTriageQueue(nextItems);
      replaceLaneSelection("track", nextItems, "deadline_id");
      setActionMessage(`Marked ${currentItem.task} as done. It is removed from this week's active track queue.`);
      onJourneyEvent("Track item completed", "Move to the next deadline in Track, or switch to Waiting on info if the queue is blocked.");
      return;
    }

    const nextItems = triageQueue.map((item) =>
      item.deadline_id === currentItem.deadline_id
        ? { ...item, status: "Remind later", priority: "Upcoming", due_date: "Apr 28" }
        : item
    );
    setTriageQueue(nextItems);
    setActionMessage(`Snoozed ${currentItem.task}. It stays visible, but no longer sits at the top of the queue.`);
    onJourneyEvent("Track item snoozed", "The item is still in the system, but you can now focus on another priority in this week's queue.");
  }

  function handleWaitingAction(action) {
    if (!currentItem) return;

    if (action === "received") {
      const nextItems = waitingItems.filter((item) => item.client_id !== currentItem.client_id);
      setWaitingItems(nextItems);
      replaceLaneSelection("waiting", nextItems, "client_id");
      setActionMessage(`Marked the missing info as received for ${currentItem.client_name}. The blocker is cleared from the waiting queue.`);
      onJourneyEvent("Blocker cleared", "Return to Track for active work, or open the client if you want to continue from the account view.");
      return;
    }

    setActionMessage(`Prepared the next outreach step for ${currentItem.client_name}. This is where a later AI flow can draft the message.`);
    onJourneyEvent("Outreach prepared", "The next move is to send the follow-up, then return when the missing information is received.");
  }

  function handleNoticeAction(action) {
    if (!currentItem) return;

    if (action === "read") {
      const nextItems = noticeItems.map((item) =>
        item.notice_id === currentItem.notice_id ? { ...item, read: true } : item
      );
      setNoticeItems(nextItems);
      setActionMessage(`Marked ${currentItem.title} as read. It stays on the notice queue until you either create work from it or remove it.`);
      onJourneyEvent("Notice acknowledged", "If this notice still matters, create a task from it. Otherwise you can safely dismiss it from the queue.");
      return;
    }

    if (action === "delete") {
      const nextItems = noticeItems.filter((item) => item.notice_id !== currentItem.notice_id);
      setNoticeItems(nextItems);
      replaceLaneSelection("notices", nextItems, "notice_id");
      setActionMessage(`Removed ${currentItem.title} from the notice queue.`);
      onJourneyEvent("Notice dismissed", "This update no longer needs attention. Move to another notice or go back to Track.");
      return;
    }

    const fullNotice = getNoticeById(currentItem.notice_id);
    const impactedClient = fullNotice.affected_clients.find((client) => !client.auto_updated) || fullNotice.affected_clients[0];
    if (!impactedClient) return;
    const newTask = {
      deadline_id: `task-${currentItem.notice_id}`,
      client_id: impactedClient.client_id,
      client_name: impactedClient.client_name,
      task: currentItem.title,
      due_date: impactedClient.new_date,
      status: "Created from notice",
      priority: "Review"
    };
    setTriageQueue((current) => [newTask, ...current]);
    setSelectedIds((current) => ({ ...current, track: newTask.deadline_id }));
    setActiveLane("track");
    setNoticeItems((current) =>
      current.map((item) => (item.notice_id === currentItem.notice_id ? { ...item, read: true } : item))
    );
    setActionMessage(`Created a trackable work item from ${currentItem.title} and moved you back to Track.`);
    onJourneyEvent("Task created from notice", "The next step is to open the impacted client or continue in Track where the new work item now belongs.");
  }

  function handleWatchlistAction(action) {
    if (!currentItem) return;

    if (action === "dismiss") {
      const nextItems = watchItems.filter((item) => item.client_id !== currentItem.client_id);
      setWatchItems(nextItems);
      replaceLaneSelection("watchlist", nextItems, "client_id");
      setActionMessage(`Removed ${currentItem.client_name} from the watchlist.`);
      onJourneyEvent("Watchlist item removed", "This account no longer needs special attention. Check other watchlist items or go back to Track.");
      return;
    }

    const newTask = {
      deadline_id: `watch-${currentItem.client_id}`,
      client_id: currentItem.client_id,
      client_name: currentItem.client_name,
      task: currentItem.headline,
      due_date: "Review this week",
      status: "Escalated from watchlist",
      priority: "Review"
    };
    setTriageQueue((current) => [newTask, ...current]);
    setSelectedIds((current) => ({ ...current, track: newTask.deadline_id }));
    setActiveLane("track");
    setActionMessage(`Escalated ${currentItem.client_name} from Watchlist into the active Track queue.`);
    onJourneyEvent("Watchlist item escalated", "This client now belongs in the active work queue. Review it in Track and decide the next concrete action.");
  }

  function renderLaneRow(lane, item) {
    if (lane === "track") {
      return (
        <button
          key={item.deadline_id}
          type="button"
          className={`table-row ${currentItem?.deadline_id === item.deadline_id ? "selected" : ""}`}
          onClick={() => selectItem("track", item.deadline_id)}
        >
          <div>
            <strong>{item.task}</strong>
            <span>
              {item.client_name} · due {item.due_date}
            </span>
          </div>
          <div className="row-meta">
            <span className={`mini-badge ${toneFromPriority(item.priority)}`}>{item.priority}</span>
            <span>{item.status}</span>
          </div>
        </button>
      );
    }

    if (lane === "waiting") {
      return (
        <button
          key={item.client_id}
          type="button"
          className={`table-row ${currentItem?.client_id === item.client_id ? "selected" : ""}`}
          onClick={() => selectItem("waiting", item.client_id)}
        >
          <div>
            <strong>{item.client_name}</strong>
            <span>{item.reason}</span>
          </div>
          <span className="mini-badge critical">Blocked</span>
        </button>
      );
    }

    if (lane === "notices") {
      return (
        <button
          key={item.notice_id}
          type="button"
          className={`table-row ${currentItem?.notice_id === item.notice_id ? "selected" : ""}`}
          onClick={() => selectItem("notices", item.notice_id)}
        >
          <div>
            <strong>{item.title}</strong>
            <span>{item.summary}</span>
          </div>
          <div className="row-meta">
            <span className={`mini-badge ${item.read ? "neutral" : "review"}`}>{item.read ? "Read" : "Review"}</span>
          </div>
        </button>
      );
    }

    return (
      <button
        key={item.client_id}
        type="button"
        className={`table-row ${currentItem?.client_id === item.client_id ? "selected" : ""}`}
        onClick={() => selectItem("watchlist", item.client_id)}
      >
        <div>
          <strong>{item.client_name}</strong>
          <span>{item.headline}</span>
        </div>
        <span className={`mini-badge ${toneFromRisk(item.risk_label)}`}>{item.risk_label}</span>
      </button>
    );
  }

  function renderInspector() {
    if (activeLane === "track" && currentItem) {
      return (
        <>
          <div className="inspector-block">
            <span className="panel-label">Selected item</span>
            <h4>{currentItem.task}</h4>
            <p>{currentItem.client_name} needs movement before {currentItem.due_date}. This row is here because it directly affects this week's filing queue.</p>
          </div>
          <div className="detail-grid">
            <InfoBlock label="Client" value={currentItem.client_name} />
            <InfoBlock label="Priority" value={currentItem.priority} />
            <InfoBlock label="Current status" value={currentItem.status} />
            <InfoBlock label="Due date" value={currentItem.due_date} />
          </div>
          <div className="inspector-actions">
            <button type="button" className="button button-primary" onClick={() => onOpenClient(currentItem.client_id)}>
              Open client
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleTrackAction("snooze")}>
              Remind later
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleTrackAction("complete")}>
              Mark done
            </button>
          </div>
        </>
      );
    }

    if (activeLane === "waiting" && currentItem) {
      return (
        <>
          <div className="inspector-block">
            <span className="panel-label">Blocked work</span>
            <h4>{currentItem.client_name}</h4>
            <p>{currentItem.reason}</p>
          </div>
          <div className="detail-grid">
            <InfoBlock label="Waiting on" value={currentItem.requested_from} />
            <InfoBlock label="Impact" value="Blocks deadline progress" />
          </div>
          <div className="callout-card">
            <span className="panel-label">Next step</span>
            <p>{currentItem.next_step}</p>
          </div>
          <div className="inspector-actions">
            <button type="button" className="button button-primary" onClick={() => onOpenClient(currentItem.client_id)}>
              Open client
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleWaitingAction("draft")}>
              Draft outreach
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleWaitingAction("received")}>
              Mark received
            </button>
          </div>
        </>
      );
    }

    if (activeLane === "notices" && currentItem) {
      return (
        <>
          <div className="inspector-block">
            <span className="panel-label">Selected notice</span>
            <h4>{currentItem.title}</h4>
            <p>{currentItem.summary}</p>
          </div>
          <div className="detail-grid">
            <InfoBlock label="Affected clients" value={`${currentItem.affected_count}`} />
            <InfoBlock label="Handling mode" value={currentItem.read ? "Read by CPA" : "Needs CPA review"} />
          </div>
          <div className="callout-card">
            <span className="panel-label">Next step</span>
            <p>{currentItem.next_step}</p>
          </div>
          <div className="inspector-actions">
            <button type="button" className="button button-primary" onClick={() => onOpenNotice(currentItem.notice_id)}>
              Open notice
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleNoticeAction("read")}>
              Mark read
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleNoticeAction("create-task")}>
              Create task
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleNoticeAction("delete")}>
              Delete
            </button>
          </div>
        </>
      );
    }

    if (currentItem) {
      return (
        <>
          <div className="inspector-block">
            <span className="panel-label">Watch item</span>
            <h4>{currentItem.client_name}</h4>
            <p>{currentItem.headline}</p>
          </div>
          <div className="callout-card">
            <span className="panel-label">Why it matters</span>
            <p>{currentItem.why_it_matters}</p>
          </div>
          <div className="callout-card">
            <span className="panel-label">Next step</span>
            <p>{currentItem.next_step}</p>
          </div>
          <div className="inspector-actions">
            <button type="button" className="button button-primary" onClick={() => onOpenClient(currentItem.client_id)}>
              Open client
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleWatchlistAction("escalate")}>
              Create task
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleWatchlistAction("dismiss")}>
              Remove
            </button>
          </div>
        </>
      );
    }

    return null;
  }

  return (
    <div className="stack">
      <section className="card">
        <div className="stats-grid">
          {dashboardStats.map((stat) => (
            <article key={stat.label} className="stat-card">
              <span className="stat-label">{stat.label}</span>
              <strong>{stat.value}</strong>
              <span className={`mini-badge ${stat.tone}`}>{stat.tone === "review" ? "Needs review" : stat.tone}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="section-head">
          <div>
            <div className="panel-label">Weekly workspace</div>
            <h3>Cross-state triage dashboard</h3>
          </div>
          <span className="soft-chip">Hover the ? icon for guidance, then use the decision panel to act.</span>
        </div>
        <div className="dashboard-lanes">
          {[
            { key: "track", count: triageQueue.length },
            { key: "waiting", count: waitingItems.length },
            { key: "notices", count: noticeItems.length },
            { key: "watchlist", count: watchItems.length }
          ].map((lane) => {
            const meta = dashboardData.section_meta[lane.key];
            const isActive = activeLane === lane.key;
            return (
              <div key={lane.key} className={`lane-card ${isActive ? "active" : ""}`}>
                <button type="button" className="lane-main" onClick={() => selectLane(lane.key)}>
                  <span className="panel-label">{meta.label}</span>
                  <strong>{lane.count}</strong>
                  <p>{meta.helper}</p>
                </button>
                <div className="tooltip-wrap">
                  <button type="button" className="help-icon" aria-label={`Explain ${meta.label}`}>
                    ?
                  </button>
                  <div className="lane-help-popover">
                    <strong>{meta.title}</strong>
                    <p>{meta.description}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <div className="split-grid dashboard-detail-grid">
        <section className="card">
          <div className="section-head">
            <div>
              <div className="panel-label">{currentMeta.label}</div>
              <h3>{currentMeta.title}</h3>
            </div>
            <div className="tooltip-wrap">
              <button type="button" className="help-icon help-icon-inline" aria-label={`Explain ${currentMeta.label}`}>
                ?
              </button>
              <div className="lane-help-popover lane-help-popover-inline">
                <strong>{currentMeta.title}</strong>
                <p>{currentMeta.description}</p>
              </div>
            </div>
          </div>
          {currentLane.items.length ? (
            <div className="table-list">
              {currentLane.items.map((item) => renderLaneRow(activeLane, item))}
            </div>
          ) : (
            <EmptyState
              title={`No items left in ${currentMeta.label}`}
              body="That is a good sign. Move to another lane, or go back to the dashboard later when more work is generated."
            />
          )}
        </section>

        <section className="card inspector-card">
          <div className="section-head">
            <div>
              <div className="panel-label">Why this matters</div>
              <h3>Decision panel</h3>
            </div>
          </div>
          <div className="callout-card callout-banner">
            <span className="panel-label">CPA action</span>
            <p>{actionMessage}</p>
          </div>
          {currentLane.items.length ? (
            renderInspector()
          ) : (
            <EmptyState
              title="Nothing to process here"
              body="When this lane is empty, the CPA can move on to another lane or return after new items are created."
            />
          )}
        </section>
      </div>
    </div>
  );
}

function ClientsPage({ clients, onOpenClient }) {
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <div className="panel-label">Portfolio</div>
          <h3>All clients</h3>
        </div>
        <div className="chip-row">
          <span className="soft-chip">Needs follow-up</span>
          <span className="soft-chip">Ready</span>
          <span className="soft-chip">High risk</span>
        </div>
      </div>
      <div className="table-list">
        {clients.map((client) => (
          <button key={client.client_id} type="button" className="table-row client-row" onClick={() => onOpenClient(client.client_id)}>
            <div>
              <strong>{client.client_name}</strong>
              <span>
                {client.entity_type} · {client.registered_states.join(", ")}
              </span>
            </div>
            <div className="row-meta">
              <span>{client.next_deadline}</span>
              <span className={`mini-badge ${toneFromRisk(client.risk_label)}`}>{client.risk_label}</span>
              <span>{client.intake_status}</span>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

function ClientDetailPage({ client, onDeadlineUpdate, onJourneyEvent }) {
  const [selectedDeadlineId, setSelectedDeadlineId] = useState(client.deadlines[0]?.deadline_id || null);
  const [detailMessage, setDetailMessage] = useState(
    "Pick the one obligation that matters most, then take one clear action before you go back to the dashboard."
  );

  const selectedDeadline =
    client.deadlines.find((deadline) => deadline.deadline_id === selectedDeadlineId) || client.deadlines[0];

  useEffect(() => {
    setSelectedDeadlineId(client.deadlines[0]?.deadline_id || null);
  }, [client.client_id]);

  function handleDeadlineAction(action) {
    if (!selectedDeadline) return;

    if (action === "complete") {
      onDeadlineUpdate(client.client_id, selectedDeadline.deadline_id, (deadline) => ({
        ...deadline,
        status: "Completed",
        available_actions: []
      }));
      setDetailMessage(`${selectedDeadline.tax_type} was marked done. The client record now shows this obligation as completed.`);
      onJourneyEvent("Client task completed", "Check whether this client still has another open obligation, or return to the portfolio to keep triaging.");
      return;
    }

    if (action === "snooze") {
      onDeadlineUpdate(client.client_id, selectedDeadline.deadline_id, (deadline) => ({
        ...deadline,
        status: "Remind later",
        due_date: "2026-04-28",
        days_remaining: 10
      }));
      setDetailMessage(`${selectedDeadline.tax_type} was snoozed. The due date was moved later in the mock workflow so the CPA can focus elsewhere first.`);
      onJourneyEvent("Client task snoozed", "This item has been pushed back. Either handle another obligation on this client or return to the dashboard.");
      return;
    }

    if (action === "override") {
      onDeadlineUpdate(client.client_id, selectedDeadline.deadline_id, (deadline) => ({
        ...deadline,
        status: "Adjusted by CPA",
        due_date: "2026-05-01",
        days_remaining: 13
      }));
      setDetailMessage(`${selectedDeadline.tax_type} was adjusted by the CPA. This simulates a due-date override from the client workspace.`);
      onJourneyEvent("Due date adjusted", "The record now reflects the CPA override. Review whether any other reminders or blockers still need attention.");
      return;
    }

    onDeadlineUpdate(client.client_id, selectedDeadline.deadline_id, (deadline) => ({
      ...deadline,
      status: "Marked not needed",
      available_actions: []
    }));
    setDetailMessage(`${selectedDeadline.tax_type} was marked not needed for this client.`);
    onJourneyEvent("Obligation waived", "This obligation is no longer active. Either move to the next open item on this client or go back to the dashboard.");
  }

  return (
    <div className="stack">
      <section className="card hero-card">
        <div>
          <div className="panel-label">Client record</div>
          <h3>{client.client_name}</h3>
          <p>{client.portfolio_note}</p>
        </div>
        <div className="chip-row">
          <span className="soft-chip">{client.entity_type}</span>
          <span className="soft-chip">{client.registered_states.join(", ")}</span>
          <span className="soft-chip">{client.intake_status}</span>
        </div>
      </section>

      <div className="split-grid">
        <section className="card">
          <div className="section-head">
            <div>
              <div className="panel-label">Profile</div>
              <h3>Annual filing profile</h3>
            </div>
          </div>
          <div className="detail-grid">
            <InfoBlock label="Home jurisdiction" value={client.home_jurisdiction} />
            <InfoBlock label="Primary contact" value={client.contact_name} />
            <InfoBlock label="Preferred channel" value={client.preferred_channel} />
            <InfoBlock label="Extension status" value={client.annual_profile.extension_status} />
          </div>
        </section>

        <section className="card">
          <div className="section-head">
            <div>
              <div className="panel-label">Activity</div>
              <h3>Recent timeline</h3>
            </div>
          </div>
          <div className="timeline-list">
            {client.activity.map((item) => (
              <article key={item} className="timeline-item">
                {item}
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="section-head">
          <div>
            <div className="panel-label">Deadlines</div>
            <h3>Open obligations</h3>
          </div>
          <span className="soft-chip">Pick one obligation, then choose the next action.</span>
        </div>
        <div className="split-grid detail-action-grid">
          <div className="table-list">
            {client.deadlines.map((deadline) => (
              <button
                key={deadline.deadline_id}
                type="button"
                className={`table-row ${selectedDeadline?.deadline_id === deadline.deadline_id ? "selected" : ""}`}
                onClick={() => setSelectedDeadlineId(deadline.deadline_id)}
              >
                <div>
                  <strong>
                    {deadline.tax_type} · {deadline.jurisdiction}
                  </strong>
                  <span>
                    Due {deadline.due_date} · {deadline.status}
                  </span>
                </div>
                <div className="row-meta row-meta-actions">
                  <span>{deadline.days_remaining} days left</span>
                  <span className="soft-chip action-chip">{deadline.available_actions.length || 0} actions</span>
                </div>
              </button>
            ))}
          </div>

          <div className="callout-card decision-stack">
            <span className="panel-label">Next action</span>
            <h4>
              {selectedDeadline?.tax_type} · {selectedDeadline?.jurisdiction}
            </h4>
            <p>{detailMessage}</p>
            <div className="detail-grid">
              <InfoBlock label="Current status" value={selectedDeadline?.status || "—"} />
              <InfoBlock label="Due date" value={selectedDeadline?.due_date || "—"} />
            </div>
            <div className="inspector-actions">
              {(selectedDeadline?.available_actions || []).map((action) => (
                <button key={action} type="button" className="button button-secondary" onClick={() => handleDeadlineAction(action)}>
                  {actionLabel(action)}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function ImportPage({ onGenerateDashboard, onJourneyEvent }) {
  const [mappings, setMappings] = useState(importDraft.mappings);
  const [missingItems, setMissingItems] = useState(
    importDraft.missing_fields.map((label, index) => ({
      id: `missing-${index + 1}`,
      label,
      resolved: false
    }))
  );
  const [selectedMissingId, setSelectedMissingId] = useState(`missing-1`);
  const [importMessage, setImportMessage] = useState(
    "Review mappings first, then clear the missing fields that actually affect deadline generation."
  );

  const selectedMissing =
    missingItems.find((item) => item.id === selectedMissingId) || missingItems[0] || null;
  const resolvedCount = missingItems.filter((item) => item.resolved).length;
  const readiness = resolvedCount >= 2 ? "Ready to generate dashboard" : "Needs a bit more cleanup";

  function confirmMapping(targetField) {
    setMappings((current) =>
      current.map((mapping) =>
        mapping.target_field === targetField ? { ...mapping, status: "Confirmed" } : mapping
      )
    );
    setImportMessage(`${targetField} was confirmed. Keep going until the deadline-driving fields look reliable.`);
    onJourneyEvent("Mapping confirmed", "Confirm the remaining fields that affect filings, then resolve the most important missing information.");
  }

  function resolveMissing(action) {
    if (!selectedMissing) return;

    if (action === "later") {
      setImportMessage(`${selectedMissing.label} can wait for follow-up. You can still generate the dashboard if the critical fields are covered.`);
      onJourneyEvent("Follow-up deferred", "You can leave this for later if it does not change the filing logic. Keep moving toward dashboard generation.");
      return;
    }

    setMissingItems((current) =>
      current.map((item) => (item.id === selectedMissing.id ? { ...item, resolved: true } : item))
    );
    setImportMessage(`${selectedMissing.label} was marked resolved. The import flow is closer to being usable for weekly triage.`);
    onJourneyEvent("Missing field resolved", "Keep clearing the critical missing fields. Once enough are resolved, generate the first dashboard.");
  }

  return (
    <div className="stack">
      <section className="card import-status-card">
        <div>
          <div className="panel-label">Import readiness</div>
          <h3>{readiness}</h3>
          <p className="body-copy">{importMessage}</p>
        </div>
        <div className="progress-cluster">
          <div className="progress-bar">
            <span style={{ width: `${(resolvedCount / missingItems.length) * 100}%` }} />
          </div>
          <span className="soft-chip">
            {resolvedCount}/{missingItems.length} missing fields handled
          </span>
        </div>
      </section>

      <section className="card hero-card">
        <div>
          <div className="panel-label">Import source</div>
          <h3>{importDraft.source_name}</h3>
          <p>{importDraft.summary}</p>
        </div>
        <div className="chip-row">
          <span className="soft-chip">{importDraft.source_kind}</span>
          <span className="soft-chip">{importDraft.imported_rows} imported rows</span>
        </div>
      </section>

      <div className="split-grid">
        <section className="card">
          <div className="section-head">
            <div>
              <div className="panel-label">Mapping</div>
              <h3>Detected fields</h3>
            </div>
            <span className="soft-chip">Confirm anything that changes filing logic.</span>
          </div>
          <div className="table-list">
            {mappings.map((mapping) => (
              <article key={mapping.target_field} className="table-row static">
                <div>
                  <strong>{mapping.target_field}</strong>
                  <span>{mapping.source_column || "No source column found"}</span>
                </div>
                <div className="row-meta">
                  <span>{mapping.confidence ? `${Math.round(mapping.confidence * 100)}%` : "—"}</span>
                  <span className={`mini-badge ${mapping.status === "Mapped" || mapping.status === "Confirmed" ? "success" : "review"}`}>
                    {mapping.status}
                  </span>
                  {mapping.status !== "Confirmed" ? (
                    <button type="button" className="button button-secondary button-small" onClick={() => confirmMapping(mapping.target_field)}>
                      Confirm
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="card">
          <div className="section-head">
            <div>
              <div className="panel-label">Follow-up</div>
              <h3>Missing information</h3>
            </div>
            <span className="soft-chip">Select one item and decide whether to resolve now or later.</span>
          </div>
          <div className="table-list">
            {missingItems.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`table-row ${selectedMissing?.id === item.id ? "selected" : ""}`}
                onClick={() => setSelectedMissingId(item.id)}
              >
                <div>
                  <strong>{item.label}</strong>
                  <span>Good AI opportunity: draft the question, but leave the final confirmation to the CPA.</span>
                </div>
                <span className={`mini-badge ${item.resolved ? "success" : "review"}`}>{item.resolved ? "Resolved" : "Ask CPA"}</span>
              </button>
            ))}
          </div>

          <div className="callout-card decision-stack top-gap">
            <span className="panel-label">Selected follow-up</span>
            <h4>{selectedMissing?.label || "No missing field selected"}</h4>
            <p>Resolve it now if it directly affects jurisdictions, entity type, extension handling, or reminder logic. Otherwise, leave it for follow-up.</p>
            <div className="inspector-actions">
              <button type="button" className="button button-secondary" onClick={() => resolveMissing("resolve")} disabled={!selectedMissing || selectedMissing.resolved}>
                Mark resolved
              </button>
              <button type="button" className="button button-secondary" onClick={() => resolveMissing("later")} disabled={!selectedMissing}>
                Ask later
              </button>
            </div>
          </div>
        </section>
      </div>

      <section className="card">
        <div className="section-head">
          <div>
            <div className="panel-label">Source preview</div>
            <h3>Imported sample rows</h3>
          </div>
          <button
            type="button"
            className="button button-primary"
            onClick={onGenerateDashboard}
            disabled={resolvedCount < 2}
          >
            Generate dashboard
          </button>
        </div>
        <div className="simple-table">
          <div className="simple-table-row header">
            <span>Client name</span>
            <span>Entity</span>
            <span>State footprint</span>
            <span>Payroll states</span>
          </div>
          {importDraft.sample_rows.map((row) => (
            <div key={row[0]} className="simple-table-row">
              {row.map((cell) => (
                <span key={`${row[0]}-${cell}`}>{cell}</span>
              ))}
            </div>
          ))}
        </div>
        <div className="chip-row top-gap">
          {importDraft.extra_columns.map((column) => (
            <span key={column} className="soft-chip">
              Extra column: {column}
            </span>
          ))}
        </div>
      </section>
    </div>
  );
}

function NoticesPage({ selectedNotice, onOpenClient, onOpenNotice, onJourneyEvent }) {
  const [noticeQueue, setNoticeQueue] = useState(notices);
  const [selectedNoticeId, setSelectedNoticeId] = useState(selectedNotice.notice_id);
  const [noticeMessage, setNoticeMessage] = useState(
    "Open a notice, validate the source, then decide whether it should be read, dismissed, or turned into real work."
  );

  useEffect(() => {
    setSelectedNoticeId(selectedNotice.notice_id);
  }, [selectedNotice.notice_id]);

  const currentNotice =
    noticeQueue.find((notice) => notice.notice_id === selectedNoticeId) || noticeQueue[0];

  function selectNotice(noticeId) {
    setSelectedNoticeId(noticeId);
    onOpenNotice(noticeId);
  }

  function advanceSelection(nextQueue) {
    if (nextQueue.some((notice) => notice.notice_id === selectedNoticeId)) return;
    const nextNoticeId = nextQueue[0]?.notice_id;
    if (nextNoticeId) {
      setSelectedNoticeId(nextNoticeId);
      onOpenNotice(nextNoticeId);
    }
  }

  function handleNoticeWorkflow(action) {
    if (!currentNotice) return;

    if (action === "read") {
      const nextQueue = noticeQueue.map((notice) =>
        notice.notice_id === currentNotice.notice_id ? { ...notice, status: "Read" } : notice
      );
      setNoticeQueue(nextQueue);
      setNoticeMessage(`${currentNotice.title} was marked as read. It stays visible until the CPA either creates work from it or dismisses it.`);
      onJourneyEvent("Notice marked read", "If the notice still requires action, create a task from it. Otherwise dismiss it to keep the queue clean.");
      return;
    }

    if (action === "dismiss") {
      const nextQueue = noticeQueue.filter((notice) => notice.notice_id !== currentNotice.notice_id);
      setNoticeQueue(nextQueue);
      advanceSelection(nextQueue);
      setNoticeMessage(`${currentNotice.title} was dismissed from the queue.`);
      onJourneyEvent("Notice dismissed", "This update no longer needs attention. Move to the next notice or go back to Track.");
      return;
    }

    const nextQueue = noticeQueue.map((notice) =>
      notice.notice_id === currentNotice.notice_id ? { ...notice, status: "Task created" } : notice
    );
    setNoticeQueue(nextQueue);
    setNoticeMessage(`${currentNotice.title} now needs follow-up work. The next step is to open an impacted client and continue from there.`);
    onJourneyEvent("Notice converted into work", "Open one impacted client now, or go back to Dashboard where this should be treated as active work.");
  }

  return (
    <div className="stack">
      <div className="split-grid notice-grid">
        <section className="card">
          <div className="section-head">
            <div>
              <div className="panel-label">Queue</div>
              <h3>Official notices</h3>
            </div>
            <span className="soft-chip">Open one notice, then decide whether it deserves action.</span>
          </div>
          {noticeQueue.length ? (
            <div className="table-list">
              {noticeQueue.map((notice) => (
                <button
                  key={notice.notice_id}
                  type="button"
                  className={`table-row ${currentNotice?.notice_id === notice.notice_id ? "selected" : ""}`}
                  onClick={() => selectNotice(notice.notice_id)}
                >
                  <div>
                    <strong>{notice.title}</strong>
                    <span>{notice.source_label}</span>
                  </div>
                  <span className={`mini-badge ${notice.status === "Needs review" ? "review" : notice.status === "Task created" ? "success" : "neutral"}`}>
                    {notice.status}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No notices in the queue"
              body="Once the CPA reads or dismisses all active notices, this queue becomes quiet until a new official update arrives."
            />
          )}
        </section>

        <section className="card">
          <div className="section-head">
            <div>
              <div className="panel-label">Selected notice</div>
              <h3>{currentNotice?.title || "No notice selected"}</h3>
            </div>
            {currentNotice ? <a href={currentNotice.source_url}>Open source</a> : null}
          </div>
          <p className="body-copy">{currentNotice?.summary || "No notice selected."}</p>
          <div className="callout-card callout-banner">
            <span className="panel-label">CPA action</span>
            <p>{noticeMessage}</p>
          </div>
          <div className="inspector-actions top-gap">
            <button type="button" className="button button-secondary" onClick={() => handleNoticeWorkflow("read")} disabled={!currentNotice}>
              Mark read
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleNoticeWorkflow("create-task")} disabled={!currentNotice}>
              Create task
            </button>
            <button type="button" className="button button-secondary" onClick={() => handleNoticeWorkflow("dismiss")} disabled={!currentNotice}>
              Dismiss
            </button>
          </div>
          <div className="callout-card top-gap">
            <span className="panel-label">How to decide</span>
            <p>If the source is official and the impacted clients really need work, create a task. If the update is already absorbed or irrelevant, dismiss it. If you only want to acknowledge it for now, mark it read.</p>
          </div>
          {(currentNotice?.affected_clients || []).length ? (
            <div className="table-list">
              {(currentNotice?.affected_clients || []).map((client) => (
                <button key={`${client.client_name}-${client.old_date}`} type="button" className="table-row" onClick={() => onOpenClient(client.client_id)}>
                  <div>
                    <strong>{client.client_name}</strong>
                    <span>
                      {client.old_date} → {client.new_date}
                    </span>
                  </div>
                  <span className={`mini-badge ${client.auto_updated ? "success" : "review"}`}>
                    {client.auto_updated ? "Auto-updated" : "Needs review"}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No impacted clients"
              body="This notice currently has no client impact listed, so the CPA can safely leave it as read or dismiss it."
            />
          )}
        </section>
      </div>
    </div>
  );
}

function EmptyState({ title, body }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

function HelpMenu({ guide }) {
  return (
    <div className="help-menu">
      <button type="button" className="button button-secondary help-trigger">
        Help
      </button>
      <div className="help-panel">
        <div className="panel-label">{guide.eyebrow}</div>
        <h3>{guide.title}</h3>
        <p>{guide.tip}</p>
        <div className="help-step-list">
          {guide.steps.map((step) => (
            <article key={step.label} className="help-step">
              <strong>{step.label}</strong>
              <p>{step.description}</p>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}

function CalendarPage() {
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <div className="panel-label">Month view</div>
          <h3>{calendarMonth.label}</h3>
        </div>
      </div>
      <div className="calendar-grid">
        {calendarMonth.days.map((day) => (
          <article key={day.date} className="calendar-card">
            <strong>{day.date}</strong>
            {day.items.length ? (
              day.items.map((item) => <span key={item}>{item}</span>)
            ) : (
              <span className="muted">No due items</span>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function RulesPage() {
  return (
    <div className="stack">
      <section className="card">
        <div className="section-head">
          <div>
            <div className="panel-label">Templates</div>
            <h3>Rule templates</h3>
          </div>
        </div>
        <div className="table-list">
          {rulesWorkspace.rule_templates.map((rule) => (
            <article key={rule.name} className="table-row static">
              <div>
                <strong>{rule.name}</strong>
                <span>{rule.scope}</span>
              </div>
              <span className={`mini-badge ${rule.status === "Active" ? "success" : "neutral"}`}>{rule.status}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="section-head">
          <div>
            <div className="panel-label">Review queue</div>
            <h3>Items still needing judgment</h3>
          </div>
        </div>
        <div className="table-list">
          {rulesWorkspace.review_queue.map((item) => (
            <article key={item} className="table-row static">
              <div>
                <strong>{item}</strong>
                <span>This is where a later AI workflow can assist, but not silently decide.</span>
              </div>
              <span className="mini-badge review">Review</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function InfoBlock({ label, value }) {
  return (
    <article className="info-block">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function assistantSummary(activePage, selectedClient, selectedNotice) {
  if (activePage === "import") {
    return "AI can help map columns, draft follow-up questions, and summarize what is still missing before deadlines are generated.";
  }
  if (activePage === "notices") {
    return `AI can summarize ${selectedNotice.source_label} updates and suggest impacted clients, but the CPA should still approve risky changes.`;
  }
  if (activePage === "client") {
    return `AI can prepare a handoff summary for ${selectedClient.client_name}, explain blockers, and draft next-step outreach.`;
  }
  if (activePage === "rules") {
    return "AI can help cluster review-queue items, detect duplicate rules, and propose safer reminder defaults.";
  }
  if (activePage === "calendar") {
    return "AI can summarize workload spikes, find overloaded weeks, and suggest what should move earlier.";
  }
  return "AI should sit beside the normal product workflow: explain priorities, open the right workspace, and reduce manual triage.";
}

function toneFromPriority(priority) {
  if (priority === "Critical") return "critical";
  if (priority === "Review") return "review";
  return "neutral";
}

function toneFromRisk(risk) {
  if (risk === "High") return "critical";
  if (risk === "Watch") return "review";
  return "success";
}

function actionLabel(action) {
  return {
    complete: "Mark done",
    snooze: "Remind later",
    override: "Adjust due date",
    waive: "Mark not needed"
  }[action] || action;
}

export default App;
