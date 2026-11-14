const listEl = document.querySelector("#list");
const detailEl = document.querySelector("#detail");
const kpisEl = document.querySelector("#kpis");
const modeEl = document.querySelector("#mode");
const params = new URLSearchParams(location.search);
let selected = params.get("incident") || "";
let incidents = [];

function text(tag, value, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value == null || value === "" ? "—" : String(value);
  return node;
}

function kpi(label, value) {
  const box = document.createElement("div");
  box.className = "kpi";
  box.append(text("span", label), text("strong", value == null ? "—" : value));
  return box;
}

function renderKpis(incident) {
  const k = incident ? incident.kpis : {};
  kpisEl.replaceChildren(
    kpi("Time to first hypothesis", k.time_to_first_hypothesis_s == null ? "—" : `${k.time_to_first_hypothesis_s}s`),
    kpi("Time to root cause", k.time_to_root_cause_s == null ? "—" : `${k.time_to_root_cause_s}s`),
    kpi("Evidence", k.evidence_count ?? 0),
    kpi("Writes blocked", k.writes_blocked ?? 0),
  );
}

function renderList() {
  listEl.replaceChildren();
  if (!incidents.length) {
    listEl.append(text("p", "No incidents yet. Inject scenario 1 and wait for Alertmanager.", "empty"));
    return;
  }
  for (const incident of incidents) {
    const button = document.createElement("button");
    button.className = "incident" + (incident.id === selected ? " active" : "");
    button.append(text("b", incident.alertname || incident.id));
    const row = document.createElement("div");
    const pill = text("span", incident.status, "pill " + incident.status);
    row.append(pill, text("small", " " + incident.id));
    button.append(row);
    button.addEventListener("click", () => {
      selected = incident.id;
      render();
    });
    listEl.append(button);
  }
}

function linkList(items) {
  const wrap = document.createElement("div");
  wrap.className = "evidence";
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "card";
    const title = document.createElement("div");
    title.append(text("span", item.id || "", "id"), text("span", item.kind || ""));
    card.append(title, text("p", item.summary || ""));
    if (item.query) card.append(text("pre", item.query));
    if (item.blocking_pids && item.blocking_pids.length) {
      card.append(text("p", "blocking pids " + item.blocking_pids.join(", ")));
    }
    if (item.trace_id) card.append(text("p", "trace_id=" + item.trace_id));
    if (item.commit_sha) card.append(text("p", "sha=" + item.commit_sha));
    if (item.link) {
      const a = document.createElement("a");
      a.href = item.link;
      a.target = "_blank";
      a.rel = "noreferrer";
      a.textContent = "Open evidence";
      card.append(a);
    }
    wrap.append(card);
  }
  return wrap;
}

function renderDetail() {
  const incident = incidents.find((item) => item.id === selected) || incidents[0];
  if (!incident) {
    detailEl.replaceChildren(text("p", "Waiting for the first firing alert.", "empty"));
    renderKpis(null);
    return;
  }
  selected = incident.id;
  renderKpis(incident);
  detailEl.replaceChildren();
  const head = document.createElement("div");
  head.append(text("h2", incident.summary), text("span", incident.status, "pill " + incident.status));
  detailEl.append(head);

  if (incident.pending_step && incident.status === "awaiting_approval") {
    const panel = document.createElement("div");
    panel.className = "approval";
    const intent = params.get("intent");
    panel.append(
      text("h3", intent === "reject" ? "Reject this write?" : "Approve this write?"),
      text("p", `${incident.pending_step.title} · ${incident.pending_step.action}`),
      text("p", "The execution rail already blocked this write. It runs only after an approval record."),
    );
    const pg = (incident.evidence || []).filter((item) => String(item.kind || "").startsWith("pg"));
    if (pg.length) {
      panel.append(text("h3", "Postgres evidence"));
      for (const item of pg) {
        const line = `${item.id} ${item.kind}: ${item.summary || ""}`;
        panel.append(text("p", line));
      }
    }
    const actions = document.createElement("div");
    actions.className = "actions";
    const approve = document.createElement("button");
    approve.className = "primary";
    approve.textContent = intent === "approve" ? "Confirm approval" : "Approve";
    approve.addEventListener("click", () => decide(incident.id, true));
    const reject = document.createElement("button");
    reject.className = "ghost";
    reject.textContent = intent === "reject" ? "Confirm reject" : "Reject";
    reject.addEventListener("click", () => decide(incident.id, false));
    actions.append(approve, reject);
    panel.append(actions);
    detailEl.append(panel);
  }

  const hypothesis = document.createElement("div");
  hypothesis.className = "block";
  hypothesis.append(text("h3", "Hypothesis"), text("div", incident.hypothesis || "Not stated yet.", "hypothesis"));
  detailEl.append(hypothesis);

  const evidence = document.createElement("div");
  evidence.className = "block";
  evidence.append(text("h3", "Evidence"));
  evidence.append(incident.evidence.length ? linkList(incident.evidence) : text("p", "No evidence yet.", "empty"));
  detailEl.append(evidence);

  const links = document.createElement("div");
  links.className = "block";
  links.append(text("h3", "Links"));
  const row = document.createElement("p");
  for (const [label, href] of [["Grafana", incident.grafana_url], ["GitLab", incident.gitlab_url]]) {
    if (!href) continue;
    const a = document.createElement("a");
    a.href = href;
    a.target = "_blank";
    a.rel = "noreferrer";
    a.textContent = label;
    a.style.marginRight = "12px";
    row.append(a);
  }
  links.append(row);
  detailEl.append(links);

  const timeline = document.createElement("div");
  timeline.className = "block";
  timeline.append(text("h3", "Timeline"));
  const ul = document.createElement("ul");
  ul.className = "timeline";
  for (const event of incident.timeline) {
    const li = document.createElement("li");
    li.append(text("time", (event.at || "").slice(11, 19)), text("span", event.kind, "kind"), text("span", event.text));
    ul.append(li);
  }
  timeline.append(ul);
  detailEl.append(timeline);

  if (incident.postmortem) {
    const post = document.createElement("div");
    post.className = "block";
    post.append(text("h3", "Postmortem draft"), text("div", incident.postmortem, "postmortem"));
    detailEl.append(post);
  }
}

async function decide(id, approved) {
  await fetch(`/api/incidents/${id}/decision`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({approved, approver: "local operator"}),
  });
  await refresh();
}

async function refresh() {
  const response = await fetch("/api/incidents");
  const body = await response.json();
  incidents = body.incidents || [];
  if (!selected && incidents[0]) selected = incidents[0].id;
  renderList();
  renderDetail();
}

async function meta() {
  try {
    const body = await fetch("/api/meta").then((response) => response.json());
    modeEl.textContent = `${body.model} · ${body.nemo ? "NeMo on" : "NeMo off"} · read-only default`;
  } catch (error) {
    modeEl.textContent = "agent unreachable";
  }
}

function render() {
  renderList();
  renderDetail();
}

meta();
refresh();
setInterval(refresh, 2000);
