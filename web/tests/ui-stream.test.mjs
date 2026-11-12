import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { webcrypto } from "node:crypto";
import vm from "node:vm";
import { parseHTML } from "linkedom";
import { citedSources, numberedCitations } from "../public/citations.js";

const html = await readFile(
  new URL("../public/index.html", import.meta.url),
  "utf8",
);
const script = (
  await readFile(new URL("../public/app.js", import.meta.url), "utf8")
).replace(
  'import { citedSources, numberedCitations } from "./citations.js";',
  "",
);
const tick = () => new Promise((resolve) => setImmediate(resolve));

async function preview(history = []) {
  const { document, HTMLElement } = parseHTML(html);
  HTMLElement.prototype.scrollIntoView = () => {};
  HTMLElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  let clipboard = null;
  // LinkeDOM does not implement the browser's select.value setter or layout metrics.
  Object.defineProperty(document.querySelector("#kind"), "value", {
    value: "",
    writable: true,
  });
  Object.defineProperty(document.querySelector("#advisor-hours"), "value", {
    value: "",
    writable: true,
  });
  const scroll = document.querySelector("#chat-scroll");
  let height = 600,
    position = 200,
    scrollWrites = 0;
  Object.defineProperties(scroll, {
    scrollHeight: { get: () => height },
    clientHeight: { get: () => 400 },
    scrollTop: {
      get: () => position,
      set: (value) => {
        position = Math.min(value, height - 400);
        scrollWrites++;
      },
    },
  });
  let stream;
  const requests = [];
  const frames = new Map();
  let frameId = 0;
  const context = vm.createContext({
    document,
    crypto: webcrypto,
    innerWidth: 1280,
    navigator: {
      clipboard: {
        writeText: async (text) => {
          clipboard = text;
        },
      },
    },
    localStorage: { getItem: () => JSON.stringify(history), setItem: () => {} },
    citedSources,
    numberedCitations,
    URL,
    AbortController,
    TextDecoder,
    Uint8Array,
    setTimeout: (...args) => {
      const timer = setTimeout(...args);
      timer.unref();
      return timer;
    },
    clearTimeout,
    requestAnimationFrame: (callback) => {
      frames.set(++frameId, callback);
      return frameId;
    },
    fetch: async (url, options) => {
      if (url === "/api/status")
        return Response.json({
          ready: true,
          answer_mode: "openai",
          documents: 167,
          features: ["learning-advisor", "course-comparison", "evidence-trace"],
        });
      requests.push(JSON.parse(options.body));
      return new Response(
        new ReadableStream({
          start(controller) {
            stream = controller;
          },
        }),
      );
    },
  });
  vm.runInContext(script, context);
  await tick();
  const flush = () => {
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach((callback) => callback());
  };
  const emit = async (event, data) => {
    stream.enqueue(
      new TextEncoder().encode(
        `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
      ),
    );
    await tick();
    flush();
  };
  return {
    document,
    context,
    flush,
    emit,
    scroll,
    setHeight: (value) => {
      height = value;
    },
    userScroll: (value) => {
      position = value;
    },
    writes: () => scrollWrites,
    finish: () => stream.close(),
    copied: () => clipboard,
    requests,
  };
}

test("stage/source/delta updates keep existing message and loading nodes mounted", async () => {
  const ui = await preview();
  const complete = vm.runInContext("send('Πώς επικοινωνώ;')", ui.context);
  ui.flush();
  const user = ui.document.querySelector(".message.user");
  const assistant = ui.document.querySelector(".message.assistant");
  const dots = assistant.querySelector(".typing-dots");
  const header = assistant.querySelector(".assistant-header");
  await ui.emit("stage", { stage: "searching" });
  await ui.emit("sources", {
    sources: [{ id: 1, title: "Contact", url: "https://codehub.gr/contact/" }],
  });
  await ui.emit("stage", { stage: "answering" });
  assert.equal(ui.document.querySelector(".message.user"), user);
  assert.equal(ui.document.querySelector(".message.assistant"), assistant);
  assert.equal(assistant.querySelector(".typing-dots"), dots);
  assert.equal(assistant.querySelector(".assistant-header"), header);
  assert.match(
    assistant.querySelector(".answer-status").textContent,
    /Συνθέτω/,
  );
  assert.equal(assistant.querySelector(".answer-status").hidden, false);
  await ui.emit("delta", { text: "Καλέστε " });
  await ui.emit("delta", { text: "**2114117481** [1]" });
  assert.equal(ui.document.querySelector(".message.assistant"), assistant);
  assert.equal(
    assistant.querySelector("strong:not(.assistant-header strong)")
      ?.textContent,
    "2114117481",
  );
  assert.equal(
    assistant.querySelector(".citation").href,
    "https://codehub.gr/contact/",
  );
  await ui.emit("done", { mode: "openai" });
  ui.finish();
  await complete;
  ui.flush();
  assert.equal(ui.document.querySelector(".message.assistant"), assistant);
  assert.equal(assistant.querySelector(".answer-status").hidden, true);
  assert.equal(assistant.querySelector(".answer-actions").hidden, false);
  assert.equal(ui.document.querySelectorAll(".message").length, 2);
});

test("stream follows the bottom but respects scrolling up, including completion", async () => {
  const ui = await preview();
  const complete = vm.runInContext(
    "send('Tell me about Code.Hub')",
    ui.context,
  );
  ui.flush();
  ui.setHeight(650);
  await ui.emit("delta", { text: "First part" });
  assert.equal(ui.scroll.scrollTop, 250);
  ui.userScroll(20);
  const before = ui.writes();
  ui.setHeight(1100);
  await ui.emit("delta", { text: " next part" });
  assert.equal(ui.scroll.scrollTop, 20);
  assert.equal(ui.writes(), before);
  await ui.emit("done", { mode: "openai" });
  ui.finish();
  await complete;
  ui.flush();
  assert.equal(ui.scroll.scrollTop, 20);
  assert.equal(ui.writes(), before);
});

test("retrieved candidates stay hidden until cited, including split streamed citations", async () => {
  const ui = await preview();
  const complete = vm.runInContext("send('Contact?')", ui.context);
  ui.flush();
  const sources = [1, 2, 3].map((id) => ({
    id,
    title: `Source ${id}`,
    url: `https://codehub.gr/${id}/`,
  }));
  await ui.emit("sources", { sources });
  assert.equal(ui.document.querySelectorAll(".source-card").length, 0);
  await ui.emit("delta", { text: "Phone number [" });
  assert.equal(ui.document.querySelectorAll(".source-card").length, 0);
  await ui.emit("delta", { text: "3]." });
  assert.equal(ui.document.querySelectorAll(".source-card").length, 1);
  assert.ok(ui.document.getElementById("source-1"));
  const card = ui.document.getElementById("source-1");
  assert.equal(
    card.querySelector(".source-link").href,
    "https://codehub.gr/3/",
  );
  await ui.emit("delta", { text: " More details." });
  assert.equal(ui.document.getElementById("source-1"), card);
  await ui.emit("sources", { sources: [sources[2]] });
  await ui.emit("done", { mode: "openai" });
  ui.finish();
  await complete;
  ui.flush();
  assert.equal(ui.document.querySelectorAll(".source-chip").length, 1);
  assert.equal(
    ui.document.querySelector(".source-chip").textContent,
    "1 · Source 3",
  );
});

test("saved out-of-order citations match sequential chips, panel links and copied text", async () => {
  const sources = [1, 2, 3, 4, 5].map((id) => ({
    id,
    title: `Source ${id}`,
    url: `https://codehub.gr/${id}/`,
  }));
  const raw = "Training [2]. Skills [5]. Contact [1].";
  const ui = await preview([
    {
      id: "numbering",
      title: "Training",
      messages: [
        { role: "user", content: "Training?" },
        { role: "assistant", content: raw, sources, mode: "openai" },
      ],
    },
  ]);
  const links = [...ui.document.querySelectorAll(".citation")];
  assert.deepEqual(
    links.map((link) => link.textContent),
    ["1", "2", "3"],
  );
  assert.deepEqual(
    links.map((link) => link.href),
    ["https://codehub.gr/2/", "https://codehub.gr/5/", "https://codehub.gr/1/"],
  );
  const chips = [...ui.document.querySelectorAll(".source-chip")];
  assert.deepEqual(
    chips.map((chip) => chip.textContent),
    ["1 · Source 2", "2 · Source 5", "3 · Source 1"],
  );
  chips[1].onclick();
  const selected = ui.document.getElementById("source-2");
  assert.equal(
    selected.querySelector(".source-link").href,
    "https://codehub.gr/5/",
  );
  assert.equal(selected.classList.contains("highlight"), true);
  await ui.document.querySelector(".answer-actions button").onclick();
  assert.equal(ui.copied(), "Training [1]. Skills [2]. Contact [3].");
  assert.equal(
    vm.runInContext("current.messages.at(-1).content", ui.context),
    raw,
  );
});

test("saved conversations show every cited source, including the fifth, and hide uncited candidates", async () => {
  const sources = [1, 2, 3, 4, 5, 6].map((id) => ({
    id,
    title: `Source ${id}`,
    url: `https://codehub.gr/${id}/`,
  }));
  const ui = await preview([
    {
      id: "saved-chat",
      title: "Saved",
      messages: [
        { role: "user", content: "Contact?" },
        {
          role: "assistant",
          content: "Training options [1] [2] [3] [4] [5].",
          sources,
          mode: "openai",
        },
      ],
    },
  ]);
  assert.equal(ui.document.querySelectorAll(".source-card").length, 5);
  assert.ok(ui.document.getElementById("source-5"));
  assert.equal(ui.document.getElementById("source-6"), null);
  const chips = [...ui.document.querySelectorAll(".source-chip")];
  assert.equal(chips.length, 5);
  assert.equal(chips[4].textContent, "5 · Source 5");
});

for (const kind of ["job", "course"])
  test(`more ${kind} button sends the next offset with its pinned snapshot`, async () => {
    const ui = await preview();
    const first = vm.runInContext(
      "send('Ποιες είναι οι καριέρες;')",
      ui.context,
    );
    ui.flush();
    const source = {
      id: 1,
      title: "Role",
      url: "https://codehub.gr/job/role/",
    };
    await ui.emit("sources", { sources: [source] });
    await ui.emit("delta", { text: "Θέσεις **1–10** από **11**. Role [1]" });
    const next = { kind, offset: 10, snapshot_id: "a".repeat(64) };
    await ui.emit("done", { mode: `${kind}-list`, next_listing: next });
    ui.finish();
    await first;
    ui.flush();
    const more = ui.document.querySelector(".next-jobs");
    assert.ok(more);
    assert.equal(
      more.textContent,
      kind === "job" ? "Περισσότερες θέσεις" : "Περισσότερα μαθήματα",
    );
    const second = more.onclick();
    ui.flush();
    assert.deepEqual(ui.requests.at(-1).listing, next);
    await ui.emit("sources", { sources: [source] });
    await ui.emit("delta", { text: "Θέσεις **11–11** από **11**. Role [1]" });
    await ui.emit("done", { mode: `${kind}-list`, next_listing: null });
    ui.finish();
    await second;
    ui.flush();
    const replies = ui.document.querySelectorAll(".message.assistant");
    assert.equal(replies[replies.length - 1].querySelector(".next-jobs"), null);
  });

test("answer links are clickable for Code.Hub only and markup remains inert", async () => {
  const ui = await preview([
    {
      id: "links",
      title: "Links",
      messages: [
        {
          role: "assistant",
          mode: "openai",
          sources: [],
          content:
            "[Επικοινωνία](https://codehub.gr/contact/) [External](https://evil.test/) <img src=x onerror=alert(1)> [Bad](javascript:alert(1))",
        },
      ],
    },
  ]);
  const body = ui.document.querySelector(".message.assistant .message-body");
  const links = ui.document.querySelectorAll(".answer-link");
  assert.equal(links.length, 1);
  assert.equal(links[0].getAttribute("href"), "https://codehub.gr/contact/");
  assert.equal(
    ui.document.querySelectorAll(".message.assistant img").length,
    0,
  );
  assert.ok(
    ui.document
      .querySelector(".message.assistant")
      .textContent.includes("External"),
  );
});

test("advisor collects declared profile and hours before requesting recommendations", async () => {
  const ui = await preview();
  ui.document.querySelector("#advisor-start").click();
  assert.ok(ui.document.querySelector("#advisor-dialog").hasAttribute("open"));
  ui.document.querySelector("#advisor-goal").value = "Build RAG with Python";
  ui.document.querySelector("#advisor-next").click();
  assert.equal(
    ui.document.querySelector("#advisor-step-profile").hidden,
    false,
  );
  ui.document.querySelector("#advisor-background").value =
    "I know Python and SQL";
  ui.document.querySelector("#advisor-hours").value = "24";
  ui.document.querySelector("#advisor-form").onsubmit({ preventDefault() {} });
  await tick();
  ui.flush();
  assert.equal(ui.requests[0].advisor.max_hours, 24);
  assert.equal(ui.requests[0].advisor.background, "I know Python and SQL");
  assert.equal(ui.requests[0].kind, "course");
  assert.ok(!ui.document.querySelector("#advisor-dialog").hasAttribute("open"));
  ui.finish();
  await tick();
});

test("course cards select two pinned sources and send an exact comparison action", async () => {
  const ui = await preview();
  vm.runInContext('send("Suggest RAG courses")', ui.context);
  await tick();
  ui.flush();
  const snapshot = "a".repeat(64);
  const courses = ["rag", "python"].map((name, i) => ({
    id: i + 1,
    title: name,
    url: `https://codehub.gr/course/${name}/`,
    text: "Course evidence",
    categories: ["course"],
    hours: i ? 88 : 24,
    level: "Intermediate",
  }));
  await ui.emit("sources", { sources: courses });
  await ui.emit("delta", { text: "Courses [1][2]." });
  await ui.emit("learning", {
    snapshot_id: snapshot,
    cards: courses,
    comparison: null,
    trace: { consulted: 4, cited: 2, query: "RAG courses", total_ms: 1000 },
  });
  await ui.emit("done", { mode: "openai" });
  ui.finish();
  await tick();
  ui.flush();
  assert.equal(ui.document.querySelectorAll(".course-card").length, 2);
  assert.match(
    ui.document.querySelector(".evidence-story").textContent,
    /4.*2/,
  );
  for (const b of ui.document.querySelectorAll("[data-course-select]"))
    b.click();
  assert.equal(ui.document.querySelector("#compare-tray").hidden, false);
  ui.document.querySelector("#compare-tray .learning-primary").click();
  await tick();
  assert.deepEqual(
    ui.requests[1].explore.urls,
    courses.map((c) => c.url),
  );
  assert.equal(ui.requests[1].explore.snapshot_id, snapshot);
  assert.equal(ui.requests[1].explore.type, "compare");
  await ui.emit("sources", { sources: courses });
  await ui.emit("delta", { text: "**_RAG_** [1] versus Python [2]." });
  await ui.emit("learning", {
    snapshot_id: snapshot,
    cards: courses,
    comparison: courses.map((c) => ({
      ...c,
      required_prerequisites: "Python fundamentals",
      beneficial_prerequisites: "Git",
    })),
    trace: { consulted: 2, cited: 2, query: "Compare", total_ms: 500 },
  });
  await ui.emit("done", { mode: "openai" });
  ui.finish();
  await tick();
  ui.flush();
  const table = ui.document.querySelector(".course-comparison");
  assert.ok(table);
  assert.match(table.textContent, /24/);
  assert.match(table.textContent, /88/);
  assert.match(table.textContent, /Python fundamentals/);
  assert.match(table.textContent, /Git/);
  assert.equal(ui.document.querySelector("strong em").textContent, "RAG");
});
