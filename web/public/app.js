const ICONS = {
  plus: "M12 5v14M5 12h14",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  book: "M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1m0-15c3-2 6-2 9-1v15c-3-1-6-1-9 1z",
  briefcase: "M9 6V3h6v3M3 7h18v13H3zM3 12c6 3 12 3 18 0M10 13h4",
  people:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3a4 4 0 0 1 0 8m6 10v-2a4 4 0 0 0-3-3.87M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  calendar: "M8 2v4M16 2v4M3 10h18M3 4h18v17H3zM8 14h2M14 14h2",
  external: "M14 3h7v7M21 3l-9 9M10 3H3v18h18v-7",
  "arrow-up-right": "M7 17 17 7M7 7h10v10",
  "arrow-up": "M12 19V5m-6 6 6-6 6 6",
  message: "M21 15a4 4 0 0 1-4 4H7l-4 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z",
  info: "M12 11v6M12 7v.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  layers: "m12 3 10 6-10 6L2 9zm-9 12 9 6 9-6M3 12l9 6 9-6",
  link: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2",
  globe:
    "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0M2 12h20M12 2a18 18 0 0 1 0 20 18 18 0 0 1 0-20",
  compass: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0m-6-14-3 7-7 3 3-7z",
  menu: "M4 6h16M4 12h16M4 18h16",
  close: "m6 6 12 12M6 18 18 6",
  copy: "M9 9h12v12H9zM15 9V3H3v12h6",
  retry: "M3 10a9 9 0 1 1 2 9M3 3v7h7",
  stop: "M6 6h12v12H6z",
  check: "m5 12 4 4L19 6",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
};
const $ = (selector) => document.querySelector(selector);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [k, v] of Object.entries({
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "1.5",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
  }))
    svg.setAttribute(k, v);
  const p = document.createElementNS(svg.namespaceURI, "path");
  p.setAttribute("d", ICONS[name] || ICONS.message);
  svg.append(p);
  return svg;
}
document
  .querySelectorAll("[data-icon]")
  .forEach((n) => n.replaceChildren(icon(n.dataset.icon)));
const STORAGE = "codehub-assistant-v1";
let conversations = [];
try {
  const stored = JSON.parse(localStorage.getItem(STORAGE) || "[]");
  if (Array.isArray(stored))
    conversations = stored
      .filter(
        (c) =>
          typeof c.id === "string" &&
          Array.isArray(c.messages) &&
          c.messages.every(
            (m) =>
              ["user", "assistant"].includes(m.role) &&
              typeof m.content === "string",
          ),
      )
      .slice(0, 8);
} catch {}
const fresh = () => ({
  id: crypto.randomUUID(),
  kind: "",
  messages: [],
  title: "Νέα συνομιλία",
  updated: Date.now(),
});
let current = conversations[0] || fresh(),
  busy = false,
  controller = null,
  frame = null,
  forceScroll = false,
  toastTimer = null;
function save() {
  current.updated = Date.now();
  if (current.messages.length) {
    conversations = [
      current,
      ...conversations.filter((c) => c.id !== current.id),
    ].slice(0, 8);
    try {
      localStorage.setItem(
        STORAGE,
        JSON.stringify(
          conversations.map((c) => ({ ...c, messages: c.messages.slice(-24) })),
        ),
      );
    } catch {}
  }
  renderRecent();
}
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("#toast").hidden = true), 2800);
}
function safeUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === "https:" &&
      ["codehub.gr", "www.codehub.gr"].includes(u.hostname) &&
      !u.username &&
      !u.password
      ? u.href
      : null;
  } catch {
    return null;
  }
}
function closeNav() {
  document.body.classList.remove("nav-open");
  $("#nav-toggle").setAttribute("aria-expanded", "false");
}
function setKind(kind) {
  current.kind = kind;
  $("#kind").value = kind;
  document
    .querySelectorAll(".topic")
    .forEach((b) => b.classList.toggle("active", b.dataset.kind === kind));
}
function renderRecent() {
  const root = $("#recent-list");
  root.replaceChildren();
  $("#recent-count").textContent = conversations.length;
  if (!conversations.length) {
    const p = el(
      "p",
      "recent-empty",
      "Η επόμενη ιδέα σου ξεκινά με μια ερώτηση.",
    );
    root.append(p);
    return;
  }
  for (const c of conversations) {
    const row = el("div", "recent-item");
    const b = el(
      "button",
      "recent-chat" + (c.id === current.id ? " selected" : ""),
      c.title,
    );
    b.title = c.title;
    b.onclick = () => {
      if (busy) controller?.abort();
      current = c;
      setKind(c.kind || "");
      renderMessages();
      renderSources(lastAssistant()?.sources || []);
      renderRecent();
      closeNav();
    };
    const d = el("button", "delete-chat");
    d.append(icon("trash"));
    d.setAttribute("aria-label", "Διαγραφή συνομιλίας: " + c.title);
    d.onclick = () => {
      if (busy && c.id === current.id) controller?.abort();
      conversations = conversations.filter((x) => x.id !== c.id);
      try {
        localStorage.setItem(STORAGE, JSON.stringify(conversations));
      } catch {}
      if (c.id === current.id) {
        current = fresh();
        setKind("");
        renderMessages();
        renderSources([]);
      }
      renderRecent();
    };
    row.append(b, d);
    root.append(row);
  }
}
function lastAssistant() {
  return [...current.messages].reverse().find((m) => m.role === "assistant");
}
function showSources(sources, id) {
  renderSources(sources);
  const panel = $("#source-panel");
  if (innerWidth <= 1000) panel.classList.add("mobile-visible");
  if (id) {
    const target = document.getElementById("source-" + id);
    target?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    target?.classList.add("highlight");
    setTimeout(() => target?.classList.remove("highlight"), 1600);
  }
}
function inline(parent, text, sources) {
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    parent.append(document.createTextNode(text.slice(cursor, match.index)));
    const v = match[0];
    if (v.startsWith("**")) parent.append(el("strong", "", v.slice(2, -2)));
    else if (v.startsWith("`")) parent.append(el("code", "", v.slice(1, -1)));
    else {
      const id = Number(v.slice(1, -1));
      const source = sources.find((s) => s.id === id);
      if (source && safeUrl(source.url)) {
        const a = el("a", "citation", String(id));
        a.href = safeUrl(source.url);
        a.title = source.title;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.onclick = (e) => {
          e.preventDefault();
          showSources(sources, id);
        };
        parent.append(a);
      } else parent.append(document.createTextNode(v));
    }
    cursor = match.index + v.length;
  }
  parent.append(document.createTextNode(text.slice(cursor)));
}
function markdown(target, text, sources) {
  target.replaceChildren();
  let list = null,
    para = null,
    code = null;
  for (const line of text.split("\n")) {
    if (line.startsWith("```")) {
      if (code) code = null;
      else {
        const pre = el("pre");
        code = el("code");
        pre.append(code);
        target.append(pre);
      }
      para = list = null;
      continue;
    }
    if (code) {
      code.textContent += line + "\n";
      continue;
    }
    if (!line.trim()) {
      list = para = null;
      continue;
    }
    const bullet = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)/);
    if (bullet) {
      if (!list) {
        list = el("ul");
        target.append(list);
      }
      const li = el("li");
      inline(li, bullet[1], sources);
      list.append(li);
      para = null;
    } else if (/^#{1,4}\s/.test(line)) {
      const h = el("h3");
      inline(h, line.replace(/^#{1,4}\s+/, ""), sources);
      target.append(h);
      para = list = null;
    } else {
      list = null;
      if (!para) {
        para = el("p");
        target.append(para);
      } else para.append(document.createElement("br"));
      inline(para, line, sources);
    }
  }
}
const messageViews = new Map();
function createMessageView(m) {
  const box = el("article", "message " + m.role);
  if (m.role === "user") {
    box.append(el("div", "user-bubble", m.content));
    return { box };
  }
  const header = el("div", "assistant-header"),
    avatar = el("span", "assistant-avatar"),
    mark = el("span", "small-mark"),
    mode = el("span", "", "Αναζήτηση πηγών");
  for (let n = 0; n < 3; n++) mark.append(el("i"));
  avatar.append(mark);
  header.append(avatar, el("strong", "", "CODE.HUB ASSISTANT"), mode);
  const body = el("div", "answer-body"),
    status = el("div", "answer-status"),
    dots = el("span", "typing-dots"),
    stage = el("span"),
    error = el("div", "error-note"),
    chips = el("div", "message-source-chips"),
    actions = el("div", "answer-actions");
  for (let n = 0; n < 3; n++) dots.append(el("i"));
  status.append(dots, stage);
  box.append(header, body, status, error, chips, actions);
  return { box, body, status, stage, mode, error, chips, actions };
}
function renderMessages() {
  const root = $("#messages");
  const visible = new Set(current.messages);
  for (const [message, view] of messageViews) {
    if (!visible.has(message)) {
      view.box.remove();
      messageViews.delete(message);
    }
  }
  $("#welcome").hidden = current.messages.length > 0;
  root.setAttribute("aria-live", busy ? "off" : "polite");
  for (let i = 0; i < current.messages.length; i++) {
    const m = current.messages[i];
    let view = messageViews.get(m);
    if (!view) {
      view = createMessageView(m);
      messageViews.set(m, view);
      root.append(view.box);
    }
    if (m.role === "user") continue;
    const last = i === current.messages.length - 1;
    const contentChanged =
      view.content !== m.content || view.sources !== m.sources;
    const footerChanged =
      contentChanged ||
      view.pending !== m.pending ||
      view.last !== last ||
      view.failure !== m.error;
    view.box.classList.toggle("pending", !!m.pending);
    view.mode.hidden = m.mode !== "sources" || !!m.pending;
    if (contentChanged) markdown(view.body, m.content, m.sources || []);
    view.status.hidden = !m.pending;
    const label =
      m.stage === "answering"
        ? "Συνθέτω την απάντηση…"
        : "Αναζητώ στο codehub.gr…";
    if (view.stage.textContent !== label) view.stage.textContent = label;
    view.error.hidden = !m.error;
    if (view.failure !== m.error) view.error.textContent = m.error || "";
    view.chips.hidden = !!m.pending || !m.sources?.length;
    view.actions.hidden = !!m.pending;
    if (footerChanged) {
      view.chips.replaceChildren();
      view.actions.replaceChildren();
    }
    if (footerChanged && m.sources?.length && !m.pending) {
      for (const s of m.sources.slice(0, 4)) {
        const b = el(
          "button",
          "source-chip",
          `${s.id} · ${s.title.split(" | ")[0]}`,
        );
        b.onclick = () => showSources(m.sources, s.id);
        view.chips.append(b);
      }
    }
    if (footerChanged && !m.pending) {
      if (m.content) {
        const copy = el("button");
        copy.append(icon("copy"), document.createTextNode("Αντιγραφή"));
        copy.onclick = async () => {
          try {
            await navigator.clipboard.writeText(m.content);
            toast("Η απάντηση αντιγράφηκε.");
          } catch {
            toast("Δεν ήταν δυνατή η αντιγραφή.");
          }
        };
        view.actions.append(copy);
      }
      if (i === current.messages.length - 1) {
        const retry = el("button");
        retry.append(
          icon("retry"),
          document.createTextNode(m.error ? "Δοκίμασε ξανά" : "Νέα απάντηση"),
        );
        retry.onclick = () => {
          if (busy) return;
          current.messages.pop();
          send(null, true);
        };
        view.actions.append(retry);
      }
    }
    Object.assign(view, {
      content: m.content,
      sources: m.sources,
      pending: m.pending,
      failure: m.error,
      last,
    });
  }
}
function renderSources(sources) {
  const valid = sources.filter(
    (s) =>
      Number.isInteger(s.id) && safeUrl(s.url) && typeof s.title === "string",
  );
  $("#source-empty").hidden = valid.length > 0;
  $("#source-results").hidden = !valid.length;
  $("#source-count").textContent = valid.length;
  const cards = $("#source-cards");
  cards.replaceChildren();
  for (const s of valid) {
    const article = el("article", "source-card");
    article.id = "source-" + s.id;
    const a = el("a", "source-link");
    a.href = safeUrl(s.url);
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.append(
      el("span", "source-number", String(s.id)),
      el("strong", "", s.title.split(" | ")[0]),
    );
    const domain = el("div", "source-domain");
    domain.append(el("span", "", "codehub.gr ↗"));
    if (s.fetched_at) {
      const date = new Date(s.fetched_at);
      if (!Number.isNaN(date.getTime()))
        domain.append(
          el(
            "span",
            "",
            new Intl.DateTimeFormat("el", {
              day: "numeric",
              month: "short",
              year: "numeric",
            }).format(date),
          ),
        );
    }
    article.append(a, domain);
    const details = el("details"),
      summary = el("summary", "", "Απόσπασμα πηγής");
    details.append(summary, el("p", "", s.text || ""));
    article.append(details);
    if (s.warnings?.length)
      article.append(
        el("p", "source-warning", "Στοιχεία προς επιβεβαίωση στην πηγή"),
      );
    cards.append(article);
  }
}
function schedule(follow = false) {
  forceScroll ||= follow;
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = null;
    const scroll = $("#chat-scroll");
    // Measure before updating content so growth doesn't look like user scrolling.
    const atBottom =
      forceScroll ||
      scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 80;
    forceScroll = false;
    renderMessages();
    if (atBottom) scroll.scrollTop = scroll.scrollHeight;
  });
}
function controls() {
  const b = $("#send");
  b.disabled = !busy && !$("#question").value.trim();
  b.setAttribute(
    "aria-label",
    busy ? "Διακοπή απάντησης" : "Αποστολή ερώτησης",
  );
  b.replaceChildren(icon(busy ? "stop" : "arrow-up"));
}
function historyPayload(messages) {
  let items = messages
    .filter((m) => m.content && !m.error)
    .map((m) => ({
      role: m.role,
      content: m.content.slice(0, m.role === "user" ? 1500 : 6000),
    }))
    .slice(-13);
  while (items.reduce((n, m) => n + m.content.length, 0) > 20000) items.shift();
  return items;
}
async function send(question, retry = false) {
  if (busy) {
    controller?.abort();
    return;
  }
  question = question ?? $("#question").value.trim();
  if (!retry && !question) return;
  if (!retry) {
    current.messages.push({ role: "user", content: question });
    current.title = current.messages
      .find((m) => m.role === "user")
      .content.slice(0, 38);
    $("#question").value = "";
    $("#question").style.height = "auto";
  }
  const payload = {
    messages: historyPayload(current.messages),
    kind: current.kind || null,
  };
  const responseMessage = {
    role: "assistant",
    content: "",
    sources: [],
    pending: true,
    stage: "searching",
    mode: null,
  };
  current.messages.push(responseMessage);
  const target = current;
  busy = true;
  controller = new AbortController();
  controls();
  save();
  renderSources([]);
  schedule(true);
  let finished = false;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail = "Δεν ήταν δυνατή η σύνδεση. Δοκίμασε ξανά.";
      try {
        const data = await response.json();
        if (typeof data.error === "string") detail = data.error;
      } catch {}
      throw new Error(detail);
    }
    if (!response.body)
      throw new Error("Δεν ήταν δυνατή η ανάγνωση της απάντησης.");
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer = (
        buffer + decoder.decode(value || new Uint8Array(), { stream: !done })
      ).replaceAll("\r\n", "\n");
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const name = block
          .split("\n")
          .find((l) => l.startsWith("event:"))
          ?.slice(6)
          .trim();
        const raw = block
          .split("\n")
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).trimStart())
          .join("\n");
        if (!raw) continue;
        let data;
        try {
          data = JSON.parse(raw);
        } catch {
          continue;
        }
        if (name === "stage") responseMessage.stage = data.stage;
        else if (name === "sources") {
          responseMessage.sources = Array.isArray(data.sources)
            ? data.sources
            : [];
          if (current.id === target.id) renderSources(responseMessage.sources);
        } else if (name === "delta" && typeof data.text === "string")
          responseMessage.content += data.text;
        else if (name === "done") {
          responseMessage.mode = data.mode;
          finished = true;
        } else if (name === "error") {
          responseMessage.error =
            data.message || "Δεν ολοκληρώθηκε η απάντηση.";
          finished = true;
        }
        if (current.id === target.id) schedule();
      }
      if (done) break;
    }
    if (!finished && !responseMessage.error)
      responseMessage.error =
        "Η σύνδεση διακόπηκε πριν ολοκληρωθεί η απάντηση.";
  } catch (error) {
    if (error.name !== "AbortError") responseMessage.error = error.message;
    else if (!responseMessage.content)
      responseMessage.content = "Η απάντηση διακόπηκε.";
  } finally {
    responseMessage.pending = false;
    busy = false;
    controller = null;
    controls();
    if (current.id === target.id) {
      save();
      controls();
      schedule();
    } else {
      try {
        localStorage.setItem(STORAGE, JSON.stringify(conversations));
      } catch {}
    }
    refreshStatus();
  }
}
async function refreshStatus() {
  try {
    const r = await fetch("/api/status", { cache: "no-store" });
    if (!r.ok) throw new Error();
    const s = await r.json();
    const status = $("#status");
    status.className = "status " + (s.ready ? "ready" : "error");
    status.querySelector("span").textContent = s.ready
      ? s.answer_mode === "openai"
        ? "Βασισμένο σε πηγές"
        : "Αναζήτηση πηγών"
      : "Η αναζήτηση δεν είναι διαθέσιμη";
    $("#mode-note").hidden = s.answer_mode === "openai";
    $("#corpus-label").textContent = s.ready
      ? `${s.documents} σελίδες · codehub.gr`
      : "Αναμονή σύνδεσης με τις πηγές";
  } catch {
    $("#status").className = "status error";
    $("#status span").textContent = "Αναμονή σύνδεσης";
  }
}
$("#chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  send();
});
$("#question").addEventListener("input", () => {
  const t = $("#question");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 130) + "px";
  controls();
});
$("#question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    if (!busy) send();
  }
});
$("#kind").addEventListener("change", (e) => {
  setKind(e.target.value);
  if (current.messages.length) save();
});
document.querySelectorAll(".topic").forEach(
  (b) =>
    (b.onclick = () => {
      setKind(b.dataset.kind);
      if (current.messages.length) save();
      closeNav();
      $("#question").focus();
    }),
);
document.querySelectorAll(".suggestion").forEach(
  (b) =>
    (b.onclick = () => {
      setKind("");
      send(b.dataset.question);
    }),
);
$("#new-chat").onclick = () => {
  if (busy) controller?.abort();
  current = fresh();
  setKind("");
  renderMessages();
  renderSources([]);
  renderRecent();
  closeNav();
  $("#question").focus();
};
$("#nav-toggle").onclick = () => {
  const open = document.body.classList.toggle("nav-open");
  $("#nav-toggle").setAttribute("aria-expanded", String(open));
};
$("#nav-scrim").onclick = closeNav;
$("#about-button").onclick = () => $("#about-dialog").showModal();
$(".dialog-close").onclick = () => $("#about-dialog").close();
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeNav();
    $("#source-panel").classList.remove("mobile-visible");
  }
});
const closeSources = el("button", "icon-button source-close");
closeSources.setAttribute("aria-label", "Κλείσιμο πηγών");
closeSources.append(icon("close"));
closeSources.onclick = () =>
  $("#source-panel").classList.remove("mobile-visible");
$("#source-panel").prepend(closeSources);
setKind(current.kind || "");
renderRecent();
renderMessages();
renderSources(lastAssistant()?.sources || []);
controls();
refreshStatus();
