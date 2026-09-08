/* learn-german — single-page app. No framework, no build. */
(() => {
  "use strict";

  // ---------- config + helpers ------------------------------------------
  const qp = new URLSearchParams(location.search);
  if (qp.get("api")) { try { localStorage.setItem("lg_api", qp.get("api")); } catch {} }
  let API;
  try { API = localStorage.getItem("lg_api"); } catch {}
  API = API || location.origin;

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (s) => (s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const shortGloss = (s) => {
    const t = (s ?? "").split(";")[0].replace(/\s*\([^()]*\)\s*$/, "").trim();
    if (t.length >= 2 && t.length <= 60) return t;
    const c = (t || s || "").trim();
    return c.length > 60 ? c.slice(0, 60).replace(/[ ,]+$/, "") + "…" : c;
  };
  const pctOf = (n, d) => (d ? (100 * n / d) : 0);
  const day = (iso) => (iso || "").slice(0, 10);

  async function api(path, opts) {
    const r = await fetch(API + path, { headers: { "Content-Type": "application/json" }, ...opts });
    if (!r.ok) {
      let d;
      try { d = (await r.json()).detail; } catch {}
      if (Array.isArray(d)) d = d.map((x) => x.msg).join("; ");
      throw new Error(d || `${r.status} ${r.statusText}`);
    }
    return r.status === 204 ? null : r.json();
  }

  const ICON = {
    home: '<path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-6H10v6H4a1 1 0 0 1-1-1z"/>',
    cards: '<rect x="3" y="6" width="14" height="14" rx="2"/><path d="M8 3h10a2 2 0 0 1 2 2v10"/>',
    book: '<path d="M4 4h12a2 2 0 0 1 2 2v14H6a2 2 0 0 1-2-2z"/><path d="M4 4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2"/>',
    chart: '<path d="M4 20V4M4 20h16M8 16v-5M13 16V8M18 16v-9"/>',
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    chat: '<path d="M21 12a8 8 0 0 1-11.5 7.2L4 21l1.8-5.5A8 8 0 1 1 21 12z"/>',
    spark: '<path d="M12 3l1.9 4.7L18.5 9l-4.6 1.9L12 15l-1.9-4.1L5.5 9l4.6-1.3z"/><path d="M18 15l.9 2.2L21 18l-2.1.8L18 21l-.9-2.2L15 18l2.1-.8z"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
  };
  const svg = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n]}</svg>`;

  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  function toast(msg, kind = "") {
    let wrap = $(".toast-wrap");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.className = "toast-wrap";
      wrap.setAttribute("role", "status");
      wrap.setAttribute("aria-live", "polite");
      document.body.appendChild(wrap);
    }
    const t = document.createElement("div");
    t.className = "toast " + kind;
    t.textContent = msg;
    wrap.appendChild(t);
    setTimeout(() => {
      t.classList.add("out");
      setTimeout(() => t.remove(), 220);
    }, 3000);
  }

  // run an async action while showing a spinner on `btn` and disabling it
  async function withBusy(btn, fn) {
    if (btn) { btn.classList.add("is-loading"); btn.disabled = true; }
    try { return await fn(); }
    finally { if (btn) { btn.classList.remove("is-loading"); btn.disabled = false; } }
  }

  // animate a number in `el` from 0 -> n
  function countUp(el, n, { suffix = "", dur = 700 } = {}) {
    if (!el) return;
    if (reduceMotion || n === 0) { el.textContent = n + suffix; return; }
    const start = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(n * eased) + suffix;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // keep Tab focus inside `container` until `onClose`; Esc closes
  function trapFocus(container, onClose) {
    const sel = 'a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])';
    const first = () => $$(sel, container).filter((n) => n.offsetParent !== null);
    (first()[0] || container).focus?.();
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key !== "Tab") return;
      const f = first();
      if (!f.length) return;
      const i = f.indexOf(document.activeElement);
      if (e.shiftKey && (i <= 0)) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }

  // ---------- theme ---------------------------------------------------
  function applyTheme(v) {
    if (v === "light" || v === "dark") document.documentElement.dataset.theme = v;
    else delete document.documentElement.dataset.theme;
  }
  let theme = "system";
  try { theme = localStorage.getItem("lg_theme") || "system"; } catch {}
  applyTheme(theme);
  function setTheme(v) {
    theme = v;
    try { localStorage.setItem("lg_theme", v); } catch {}
    applyTheme(v);
  }

  // ---------- session ----------------------------------------------
  let sess = null;
  try { sess = JSON.parse(localStorage.getItem("lg_user") || "null"); } catch {}
  const saveSess = (s) => { sess = s; try { localStorage.setItem("lg_user", JSON.stringify(s)); } catch {} };
  const clearSess = () => { sess = null; try { localStorage.removeItem("lg_user"); } catch {} };
  const uid = () => sess.id;

  // ================================================================
  //  LOGIN GATE
  // ================================================================
  function renderGate() {
    document.body.innerHTML = `
      <div class="gate"><div class="box">
        <div class="brand"><span class="logo">LG</span><span><b>learn&#8209;german</b><small>vocabulary trainer</small></span></div>
        <div class="card">
          <div class="tabs">
            <button id="m-login" class="on">Log in</button>
            <button id="m-reg">Create account</button>
          </div>
          <label class="field"><span>Username</span>
            <input id="g-user" class="input" autocomplete="username" placeholder="e.g. demo" /></label>
          <label class="field"><span>Password</span>
            <input id="g-pass" class="input" type="password" autocomplete="current-password" placeholder="at least 4 characters" /></label>
          <label class="field" id="g-targetf" hidden><span>Learning German for</span>
            <select id="g-target" class="select">
              <option value="general">general</option><option value="work">work</option>
              <option value="travel">travel</option><option value="exam">exam</option>
            </select></label>
          <button class="btn block" id="g-go">Log in</button>
          <div id="g-msg" class="muted mt-3" aria-live="polite"></div>
          <div class="mini mt-3">Demo account — <b>demo</b> / <b>demo</b></div>
        </div>
      </div></div>`;
    let mode = "login";
    const set = (m) => {
      mode = m;
      $("#m-login").classList.toggle("on", m === "login");
      $("#m-reg").classList.toggle("on", m === "reg");
      $("#g-targetf").hidden = m !== "reg";
      $("#g-go").textContent = m === "login" ? "Log in" : "Create account";
      $("#g-msg").textContent = "";
    };
    $("#m-login").onclick = () => set("login");
    $("#m-reg").onclick = () => set("reg");
    async function go() {
      const username = $("#g-user").value.trim(), password = $("#g-pass").value;
      const msg = $("#g-msg");
      if (!username || !password) {
        msg.className = "err-text mt-3"; msg.textContent = "Enter a username and password.";
        return;
      }
      msg.className = "muted mt-3"; msg.textContent = "…";
      try {
        await withBusy($("#g-go"), async () => {
          const body = mode === "reg"
            ? { username, password, target: $("#g-target").value }
            : { username, password };
          const u = await api(
            mode === "reg" ? "/auth/register" : "/auth/login",
            { method: "POST", body: JSON.stringify(body) },
          );
          saveSess({ id: u.id, username: u.username, target: u.target });
        });
        location.hash = "#/";
        render();
      } catch (e) {
        msg.className = "err-text mt-3"; msg.textContent = e.message;
      }
    }
    $("#g-go").onclick = go;
    $("#g-pass").onkeydown = (e) => { if (e.key === "Enter") go(); };
    $("#g-user").focus();
  }

  // ================================================================
  //  VIEW: COACH  (natural language -> agent -> MCP tools)
  // ================================================================
  const SERVER_LABEL = { learning: "learning server", notes: "notes vault" };

  function viewCoach(root) {
    root.classList.add("narrow");
    root.innerHTML = `
      <div class="card">
        <p class="muted" style="margin:0 0 12px">
          Ask in plain English. The agent does <b>one</b> piece of language
          reasoning — turning your words into a time budget and topic — then
          calls <b>MCP tools</b> to compose the session. It never picks the
          words or the schedule itself.
        </p>
        <label class="field"><span>Your request</span>
          <textarea id="c-req" class="input" rows="3"
            style="resize:vertical;font:inherit">I have 10 minutes, German for work</textarea></label>
        <label class="field"><span>Mode</span>
          <div class="seg seg-full" id="c-mode">
            <button data-m="plan" class="on">Plan a session</button>
            <button data-m="converse">Converse (both servers)</button>
          </div>
        </label>
        <button class="btn block" id="c-go">Ask the coach</button>
        <div id="c-msg" class="mini mt-3" aria-live="polite">
          Try “20 minutes, travel vocab” or, in Converse mode, “set up a short
          session and note where I'm at”.</div>
      </div>
      <div id="c-out"></div>`;

    let mode = "plan";
    $$("#c-mode button").forEach((b) => (b.onclick = () => {
      mode = b.dataset.m;
      $$("#c-mode button").forEach((x) => x.classList.toggle("on", x === b));
    }));
    $("#c-go").onclick = () => withBusy($("#c-go"), run);
    $("#c-req").onkeydown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); $("#c-go").click(); }
    };

    async function run() {
      const request = $("#c-req").value.trim();
      const msg = $("#c-msg"), out = $("#c-out");
      if (request.length < 3) { msg.innerHTML = `<span class="err-text">Type a request first.</span>`; return; }
      msg.textContent = mode === "converse"
        ? "running the cross-server loop…" : "parsing intent and calling tools…";
      out.innerHTML = skeleton();
      try {
        const r = await api("/agent/plan", { method: "POST", body: JSON.stringify(
          { user_id: uid(), request, mode }) });
        msg.textContent = `Agent stopped: ${r.stopped} · ${r.turns} LLM turn${r.turns === 1 ? "" : "s"}.`;
        out.innerHTML = renderResult(r);
      } catch (e) {
        out.innerHTML = "";
        msg.innerHTML = `<span class="err-text">${esc(e.message)}</span>` +
          (String(e.message).includes("not configured")
            ? `<br><span class="muted">This deployment has no Anthropic API key set, so the agent loop is disabled. The deterministic study flow still works under <a href="#/study">Study</a>.</span>`
            : "");
      }
    }

    function renderResult(r) {
      const chips = [];
      const iv = r.intent || {};
      if (iv.minutes_available != null) chips.push(`${iv.minutes_available} min`);
      if (iv.topic) chips.push(esc(iv.topic));
      const servers = (r.servers_used || []).map((s) =>
        `<span class="pill">${esc(SERVER_LABEL[s] || s)}</span>`).join(" ");
      const steps = (r.tool_calls || []).map((t, i) =>
        `<li><span class="stepn">${i + 1}</span><code>${esc(t)}()</code></li>`).join("");
      const wordList = (title, ws) => !ws || !ws.length ? "" : `
        <div class="card-h" style="margin-top:14px"><h3>${title}</h3><span class="sp"></span><span class="muted">${ws.length}</span></div>
        <ul class="wl">${ws.map((w) =>
          `<li><b>${esc(w.article ? w.article + " " : "")}${esc(w.lemma)}</b>
           <span>${esc(shortGloss(w.translation_en || w.gloss || ""))}</span></li>`).join("")}</ul>`;

      return `
        <div class="card">
          ${r.reply ? `<p style="margin:0 0 10px;font-size:15px">${esc(r.reply)}</p>` : ""}
          ${chips.length ? `<div class="chips">${chips.map((c) => `<span class="pill">${c}</span>`).join(" ")}</div>` : ""}
          ${servers ? `<div class="chips mt-3"><span class="muted" style="margin-right:6px">servers used:</span>${servers}</div>` : ""}

          <div class="card-h" style="margin-top:16px"><h3>How it did it</h3><span class="sp"></span>
            <span class="muted">${(r.tool_calls || []).length} MCP tool call${(r.tool_calls || []).length === 1 ? "" : "s"}</span></div>
          ${steps ? `<ol class="steps">${steps}</ol>`
                  : `<p class="muted">No tools were called — the agent ${esc(r.stopped)}.</p>`}

          ${wordList("Review words", r.review_words)}
          ${wordList("New words", r.new_words)}

          ${r.session_id ? `<button class="btn block mt-3" id="c-open">Study this session</button>` : ""}
        </div>`;
    }

    root.addEventListener("click", (e) => {
      if (e.target && e.target.id === "c-open") location.hash = "#/study";
    });
  }

  // ================================================================
  //  APP SHELL
  // ================================================================
  const ROUTES = [
    { path: "/", name: "Home", icon: "home", view: viewHome },
    { path: "/study", name: "Study", icon: "cards", view: viewStudy },
    { path: "/coach", name: "Coach", icon: "spark", view: viewCoach },
    { path: "/practice", name: "Practice", icon: "chat", view: viewPractice },
    { path: "/browse", name: "Browse", icon: "book", view: viewBrowse },
    { path: "/progress", name: "Progress", icon: "chart", view: viewProgress },
    { path: "/settings", name: "Settings", icon: "gear", view: viewSettings },
  ];

  function renderShell() {
    document.body.innerHTML = `
      <div class="app">
        <aside class="sidebar">
          <div class="brand"><span class="logo">LG</span><span><b>learn&#8209;german</b><small>vocabulary trainer</small></span></div>
          <nav class="nav" id="nav" aria-label="Primary">${ROUTES.map((r) =>
            `<a href="#${r.path}" data-path="${r.path}">${svg(r.icon)}<span>${r.name}</span></a>`).join("")}</nav>
          <div class="spacer"></div>
          <button class="usercard" id="usercard">
            <span class="avatar" aria-hidden="true">${esc((sess.username || "?")[0])}</span>
            <span class="who"><b>${esc(sess.username)}</b><span>${esc(sess.target || "learner")}</span></span>
          </button>
        </aside>
        <main class="main" id="main">
          <div class="topbar"><h1 id="viewtitle">Home</h1></div>
          <div class="view" id="view"></div>
        </main>
      </div>`;
    $("#usercard").onclick = () => (location.hash = "#/settings");
    const main = $("#main");
    main.addEventListener("scroll", () => main.classList.toggle("scrolled", main.scrollTop > 4), { passive: true });
  }

  function skeleton() {
    return `<div class="card"><div class="skeleton" style="height:22px;width:40%"></div>
      <div class="skeleton mt-3" style="height:88px"></div></div>`;
  }

  function render() {
    if (!sess) return renderGate();
    if (!$(".app")) renderShell();
    const path = (location.hash.replace(/^#/, "") || "/").split("?")[0];
    const route = ROUTES.find((r) => r.path === path) || ROUTES[0];
    $$("#nav a").forEach((a) => {
      const on = a.dataset.path === route.path;
      a.classList.toggle("on", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.title = `${route.name} · learn-german`;
    $("#viewtitle").textContent = route.name;
    const v = $("#view");
    v.className = "view";
    $("#main")?.scrollTo({ top: 0 });
    v.innerHTML = skeleton();
    route.view(v);
  }

  window.addEventListener("hashchange", render);

  // ---------- keyboard shortcuts ----------
  const SHORTCUTS = [
    ["g h", "Home"], ["g s", "Study"], ["g p", "Practice"], ["g b", "Browse"],
    ["g d", "Progress (dashboard)"], ["g ,", "Settings"], ["?", "This help"],
  ];
  let gPending = false;
  addEventListener("keydown", (e) => {
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || !sess) return;
    if ($(".kbd-help")) { if (e.key === "Escape") $(".kbd-help").remove(); return; }
    if (e.key === "?") { e.preventDefault(); showShortcuts(); return; }
    if (e.key === "g") { gPending = true; setTimeout(() => (gPending = false), 900); return; }
    if (gPending) {
      const map = { h: "/", s: "/study", p: "/practice", b: "/browse", d: "/progress", ",": "/settings" };
      if (map[e.key]) { location.hash = "#" + map[e.key]; }
      gPending = false;
    }
  });
  function showShortcuts() {
    const el = document.createElement("div");
    el.className = "kbd-help";
    el.innerHTML = `<div class="box" role="dialog" aria-label="Keyboard shortcuts" tabindex="-1">
      <h3>Keyboard shortcuts</h3>
      <dl>${SHORTCUTS.map(([k, v]) =>
        `<dt>${v}</dt><dd>${k.split(" ").map((x) => `<kbd>${esc(x)}</kbd>`).join(" ")}</dd>`).join("")}</dl></div>`;
    const release = trapFocus($(".box", el), () => { release(); el.remove(); });
    el.addEventListener("click", (e) => { if (e.target === el) { release(); el.remove(); } });
    document.body.appendChild(el);
  }

  // ================================================================
  //  VIEW: HOME
  // ================================================================
  async function viewHome(root) {
    let d;
    try { d = await api(`/study/users/${uid()}/dashboard`); }
    catch (e) { root.innerHTML = errCard(e); return; }
    const acc = d.overall_accuracy == null ? "–" : Math.round(d.overall_accuracy * 100) + "%";
    const days = (d.daily_activity || []).slice(-14);
    const mx = Math.max(1, ...days.map((x) => x.reviews));
    const hour = new Date().getHours();
    const hi = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    const sess7 = (d.recent_sessions || []).slice(0, 4);
    root.innerHTML = `
      <div class="hero">
        <h2>${hi}, ${esc(sess.username)} 👋</h2>
        <p>${d.words_due_now
          ? `You have <b>${d.words_due_now}</b> word${d.words_due_now === 1 ? "" : "s"} due for review.`
          : "Nothing due right now — a good time to learn some new words."}</p>
        <button class="btn" id="h-start">${d.words_due_now ? "Review now" : "Learn new words"} →</button>
        <div class="hstats">
          <div><b><span data-n="${d.current_streak}">0</span>🔥</b><span>day streak</span></div>
          <div><b data-n="${d.words_known}">0</b><span>words known</span></div>
          <div><b>${acc}</b><span>accuracy</span></div>
        </div>
      </div>
      <div class="grid3 mt-4">
        <div class="stat"><b data-n="${d.total_reviews}">0</b><span>reviews</span></div>
        <div class="stat"><b data-n="${d.words_seen}">0</b><span>words seen</span></div>
        <div class="stat"><b>${esc(d.cefr_ceiling)}</b><span>CEFR ceiling</span></div>
      </div>
      <div class="card">
        <div class="card-h"><h3>Last 14 days</h3></div>
        <div class="spark">${days.map((x) => {
          const h = Math.round(pctOf(x.reviews, mx));
          const c = x.reviews ? Math.round(pctOf(x.correct, x.reviews)) : 0;
          return `<i style="height:${h}%" title="${x.date}: ${x.reviews} reviews, ${x.correct} correct"><b style="height:${c}%"></b></i>`;
        }).join("")}</div>
      </div>
      <div class="card">
        <div class="card-h"><h3>Jump back in</h3><span class="sp"></span><a href="#/progress">full progress →</a></div>
        ${sess7.length ? `<ul class="list">${sess7.map((s) =>
          `<li><span class="de">${day(s.started_at)}</span><span class="en2">${s.topic ? esc(s.topic) : "general"}</span>
           <span class="meta">${s.words_covered} words · ${s.minutes} min</span></li>`).join("")}</ul>`
          : `<div class="empty">${svg("cards")}<div>No sessions yet — start your first one.</div></div>`}
      </div>`;
    $$("[data-n]", root).forEach((el) => countUp(el, +el.dataset.n));
    $("#h-start").onclick = () => (location.hash = "#/study");
  }

  // ================================================================
  //  VIEW: STUDY  (swipe deck)
  // ================================================================
  function viewStudy(root) {
    root.classList.add("narrow");
    const deck = { q: [], qid: {}, i: 0, correct: 0, streak: 0, best: 0, sid: null, dir: "en",
                   mode: "swipe", revealed: false, busy: false, answered: 0, shownAt: 0 };

    root.innerHTML = `
      <div class="card" id="setup">
        <div class="row">
          <label class="field"><span>Minutes</span><input id="s-min" class="input" inputmode="numeric" value="10" /></label>
          <label class="field"><span>Topic</span><input id="s-topic" class="input" placeholder="any" /></label>
        </div>
        <div class="row">
          <label class="field"><span>Level</span><select id="s-level" class="select">
            <option value="">Auto (by progress)</option><option>A1</option><option>A2</option><option>B1</option><option>B2</option>
          </select></label>
          <label class="field"><span>Show first</span><select id="s-dir" class="select">
            <option value="en">EN → recall German</option><option value="de">DE → recall English</option>
          </select></label>
        </div>
        <label class="field"><span>Mode</span>
          <div class="seg seg-full" id="s-mode">
            <button data-m="swipe" class="on">Swipe (self-grade)</button>
            <button data-m="type">Type the answer</button>
          </div>
        </label>
        <button class="btn block" id="s-start">Start session</button>
        <div id="s-msg" class="muted mt-3" aria-live="polite"></div>
        <div id="s-hint" class="mini mt-3">Flip the card, then swipe <b>right</b> if you knew it, <b>left</b> if not. Arrow keys work too.</div>
      </div>
      <div id="deck" hidden>
        <div class="deckhead"><span id="d-count">1 / 1</span><span id="d-acc">0%</span></div>
        <div class="bar mb-2"><i class="known" id="d-fill" style="width:0%"></i></div>
        <div class="stage" id="d-stage"></div>
        <div class="rate locked" id="d-rate">
          <button class="btn ghost no" id="d-no">✗ Missed</button>
          <button class="btn ghost yes" id="d-yes">✓ Got it</button>
          <button class="btn flip" id="d-flip">Reveal answer</button>
        </div>
        <div id="d-type" hidden>
          <input id="d-input" class="input" autocomplete="off" autocapitalize="off" placeholder="type the translation" />
          <div id="d-fb"></div>
          <button class="btn block mt-3" id="d-go">Check</button>
        </div>
      </div>
      <div class="card" id="summary" hidden></div>`;

    let mode = "swipe";
    $$("#s-mode button").forEach((b) => (b.onclick = () => {
      mode = b.dataset.m;
      $$("#s-mode button").forEach((x) => x.classList.toggle("on", x === b));
      $("#s-hint").innerHTML = mode === "type"
        ? "Type the German (or English) translation and press Enter. You'll get feedback on <b>why</b> a miss happened."
        : "Flip the card, then swipe <b>right</b> if you knew it, <b>left</b> if not. Arrow keys work too.";
    }));

    $("#s-start").onclick = start;
    async function start() {
      $("#s-msg").textContent = "composing…"; $("#s-start").disabled = true;
      try {
        const dir = $("#s-dir").value;
        const s = await api("/study/sessions", { method: "POST", body: JSON.stringify({
          user_id: uid(),
          minutes_available: parseInt($("#s-min").value || "10", 10) || 10,
          topic: $("#s-topic").value.trim() || null,
          cefr_level: $("#s-level").value || null,
        }) });
        const words = [...s.review_words, ...s.new_words];
        if (!words.length) { $("#s-msg").textContent = "Nothing to study with those settings — try more minutes, another level, or a different topic."; return; }
        const qid = {};
        if (mode === "type") {
          const qs = await api("/study/quiz", { method: "POST", body: JSON.stringify({
            word_ids: words.map((w) => w.id), quiz_type: dir === "en" ? "en_to_de" : "de_to_en" }) });
          qs.forEach((x) => (qid[x.word_id] = x.question_id));
        }
        Object.assign(deck, { q: words, qid, i: 0, correct: 0, streak: 0, best: 0, answered: 0,
          sid: s.session_id, dir, mode, revealed: false, busy: false });
        $("#d-rate").hidden = mode === "type";
        $("#d-type").hidden = mode !== "type";
        $("#setup").hidden = true; $("#summary").hidden = true; $("#deck").hidden = false;
        renderCard(true);
      } catch (e) { $("#s-msg").innerHTML = `<span class="err-text">${esc(e.message)}</span>`; }
      finally { $("#s-start").disabled = false; }
    }

    const faceHTML = (w, back) => {
      const de = (deck.dir === "en") === back;
      if (de) {
        const art = w.article ? `<span class="art">${esc(w.article)}</span> ` : "";
        return `<div class="word">${art}${esc(w.lemma)}</div>`
          + (w.plural ? `<div class="sub">pl. ${esc(w.plural)}</div>` : "")
          + (w.ipa_or_audio_ref ? `<div class="ipa">/${esc(w.ipa_or_audio_ref)}/</div>` : "");
      }
      const brief = shortGloss(w.translation_en), full = (w.translation_en || "").trim();
      return `<div class="gloss">${esc(brief)}</div>` + (brief !== full ? `<div class="sub">${esc(full)}</div>` : "");
    };
    const sideLabel = (back) => ((deck.dir === "en") === back ? "German" : "English");

    function buildCard(w, top) {
      const c = document.createElement("div");
      c.className = "fcard " + (top ? "top" : "peek");
      c.innerHTML = `<span class="side">${sideLabel(false)}</span>
        <div class="tags"><span class="badge">${esc(w.cefr_level)}</span>${w.topic ? `<span class="badge topic">${esc(w.topic)}</span>` : ""}</div>
        <div class="face">${faceHTML(w, false)}</div>
        <span class="stamp yes">GOT IT</span><span class="stamp no">MISSED</span>
        <span class="revhint">tap to reveal</span>`;
      return c;
    }
    function renderCard(enter) {
      const w = deck.q[deck.i], nx = deck.q[deck.i + 1];
      deck.revealed = false;
      deck.busy = false;
      $("#d-count").textContent = `${deck.i + 1} / ${deck.q.length}`;
      $("#d-fill").style.width = pctOf(deck.i, deck.q.length) + "%";
      updAcc();
      const stage = $("#d-stage");
      stage.textContent = "";

      if (deck.mode === "type") {
        const top = buildCard(w, true);
        top.id = "d-top";
        top.style.cursor = "default";
        top.querySelector(".revhint")?.remove();
        top.querySelectorAll(".stamp").forEach((s) => s.remove());
        if (enter) top.classList.add("enter");
        stage.appendChild(top);
        $("#d-fb").innerHTML = "";
        $("#d-go").textContent = "Check";
        $("#d-go").disabled = false;
        const inp = $("#d-input");
        inp.value = ""; inp.disabled = false; inp.focus();
        deck.shownAt = performance.now();
        return;
      }

      $("#d-rate").classList.add("locked");
      $("#d-flip").textContent = "Reveal answer";
      if (nx) stage.appendChild(buildCard(nx, false));
      const top = buildCard(w, true);
      top.id = "d-top";
      if (enter) top.classList.add("enter");
      stage.appendChild(top);
      deck.shownAt = performance.now();
      wire(top);
    }
    const updAcc = () => { $("#d-acc").textContent = deck.answered ? `${Math.round(100 * deck.correct / deck.answered)}% correct` : "0%"; };
    function reveal() {
      if (deck.revealed || deck.busy) return;
      deck.revealed = true;
      const c = $("#d-top");
      c.querySelector(".side").textContent = sideLabel(true);
      c.querySelector(".face").innerHTML = faceHTML(deck.q[deck.i], true);
      c.querySelector(".revhint")?.remove();
      $("#d-rate").classList.remove("locked");
      $("#d-flip").textContent = "Rate it ↓";
      deck.shownAt = performance.now();
    }
    function wire(c) {
      let sx = 0, dx = 0, drag = false;
      const st = (yes) => c.querySelector(yes ? ".stamp.yes" : ".stamp.no");
      c.addEventListener("pointerdown", (e) => {
        if (deck.busy || !deck.revealed) return;
        drag = true; sx = e.clientX; dx = 0; c.style.transition = "none"; c.setPointerCapture(e.pointerId);
      });
      c.addEventListener("pointermove", (e) => {
        if (!drag) return;
        dx = e.clientX - sx;
        c.style.transform = `translateX(${dx}px) rotate(${dx / 18}deg)`;
        const p = Math.min(1, Math.abs(dx) / 120);
        st(true).style.opacity = dx > 0 ? p : 0;
        st(false).style.opacity = dx < 0 ? p : 0;
      });
      const end = () => {
        if (!drag) return;
        drag = false; c.style.transition = "";
        if (Math.abs(dx) > 110) fling(dx > 0);
        else { c.style.transform = ""; st(true).style.opacity = 0; st(false).style.opacity = 0; }
      };
      c.addEventListener("pointerup", end);
      c.addEventListener("pointercancel", end);
      c.addEventListener("click", () => { if (Math.abs(dx) <= 4 && !deck.revealed) reveal(); });
    }
    function fling(ok) {
      if (deck.busy) return;
      deck.busy = true;
      const c = $("#d-top");
      c.style.transform = `translateX(${ok ? innerWidth : -innerWidth}px) rotate(${ok ? 22 : -22}deg)`;
      c.style.opacity = "0";
      c.querySelector(ok ? ".stamp.yes" : ".stamp.no").style.opacity = 1;
      record(ok);
      setTimeout(() => {
        deck.busy = false;
        if (deck.i + 1 >= deck.q.length) finish();
        else { deck.i++; renderCard(true); }
      }, 240);
    }
    const rate = (ok) => { if (!deck.busy && deck.revealed) fling(ok); };
    $("#d-yes").onclick = () => rate(true);
    $("#d-no").onclick = () => rate(false);
    $("#d-flip").onclick = () => { if (!deck.revealed) reveal(); };
    async function record(ok) {
      deck.answered++;
      if (ok) { deck.correct++; deck.streak++; deck.best = Math.max(deck.best, deck.streak); } else deck.streak = 0;
      updAcc();
      const rt = Math.max(200, Math.min(600000, Math.round(performance.now() - deck.shownAt)));
      try {
        await api("/study/review", { method: "POST", body: JSON.stringify({
          user_id: uid(), word_id: deck.q[deck.i].id, correct: ok, response_time_ms: rt }) });
      } catch {}
    }
    async function finish() {
      $("#deck").hidden = true;
      let row = {};
      try { row = await api(`/study/sessions/${deck.sid}/finish`, { method: "POST", body: JSON.stringify({ words_covered: deck.answered }) }) || {}; } catch {}
      const n = deck.answered, p = n ? Math.round(100 * deck.correct / n) : 0;
      const rc = p >= 80 ? "var(--ok)" : p >= 50 ? "var(--accent)" : "var(--bad)";
      $("#summary").hidden = false;
      $("#summary").innerHTML = `
        <div class="ring" style="--p:${p};--rc:${rc}"><span id="ring-n">0%</span></div>
        <div class="sumcol">
          <div class="stat"><b>${deck.correct}/${n}</b><span>correct</span></div>
          <div class="stat"><b>${deck.best}</b><span>best streak</span></div>
          <div class="stat"><b>#${row.session_id ?? deck.sid ?? "–"}</b><span>session</span></div>
        </div>
        <button class="btn block" id="sum-again">New session</button>
        <button class="btn ghost block mt-2" id="sum-home">Back to home</button>`;
      countUp($("#ring-n"), p, { suffix: "%" });
      $("#sum-again").onclick = () => { $("#summary").hidden = true; $("#setup").hidden = false; };
      $("#sum-home").onclick = () => (location.hash = "#/");
      toast(`Session done — ${p}% correct`, p >= 50 ? "ok" : "");
    }

    // ---- typed-answer mode ----
    const advance = () => {
      if (deck.i + 1 >= deck.q.length) finish();
      else { deck.i++; renderCard(true); }
    };
    async function submitTyped() {
      if (deck.busy) return;
      const inp = $("#d-input");
      if ($("#d-go").textContent === "Next") return advance();
      const text = inp.value.trim();
      if (!text) return;
      deck.busy = true; $("#d-go").disabled = true; inp.disabled = true;
      let r;
      try {
        r = await api("/study/answers", { method: "POST", body: JSON.stringify({
          user_id: uid(), question_id: deck.qid[deck.q[deck.i].id], user_answer: text }) });
      } catch (e) {
        $("#d-fb").innerHTML = `<div class="fb bad">${esc(e.message)}</div>`;
        deck.busy = false; $("#d-go").disabled = false; inp.disabled = false; return;
      }
      deck.answered++;
      if (r.correct) { deck.correct++; deck.streak++; deck.best = Math.max(deck.best, deck.streak); }
      else deck.streak = 0;
      updAcc();
      $("#d-fb").innerHTML = r.correct
        ? `<div class="fb ok">✓ correct</div>`
        : `<div class="fb bad">✗ answer: <b>${esc(r.expected)}</b>`
          + (r.error_type ? ` <span class="echip">${esc(r.error_type.replace(/_/g, " "))}</span>` : "")
          + (r.feedback ? `<div class="fbnote">${esc(r.feedback)}</div>` : "") + `</div>`;
      $("#d-go").textContent = "Next"; $("#d-go").disabled = false;
      deck.busy = false;
    }
    $("#d-go").onclick = submitTyped;
    $("#d-input").addEventListener("keydown", (e) => { if (e.key === "Enter") submitTyped(); });
    const onKey = (e) => {
      if ($("#deck").hidden || deck.mode === "type") return;  // type mode: the input handles keys
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); if (!deck.revealed) reveal(); }
      else if (e.key === "ArrowRight") rate(true);
      else if (e.key === "ArrowLeft") rate(false);
    };
    document.addEventListener("keydown", onKey);
    // clean up the key listener when leaving the view
    window.addEventListener("hashchange", function off() {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("hashchange", off);
    });
  }

  // ================================================================
  //  VIEW: PRACTICE  (conversational roleplay)
  // ================================================================
  const SCENARIOS = {
    cafe: "Café — order food & drink",
    directions: "Directions — ask a stranger the way",
    shopping: "Shopping — buy clothes, ask size & price",
    smalltalk: "Small talk — chat about the weekend",
    doctor: "Doctor — describe your symptoms",
    hotel: "Hotel — check in, ask about breakfast",
  };

  function viewPractice(root) {
    root.classList.add("narrow");
    const S = { sid: null, scenario: "cafe", level: "", targets: [], used: new Set(),
                history: [], turns: 0, busy: false };

    root.innerHTML = `
      <div class="card" id="p-setup">
        <label class="field"><span>Scenario</span>
          <select id="p-scn" class="select">${Object.entries(SCENARIOS).map(([k, v]) =>
            `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
        <label class="field"><span>Length</span>
          <input id="p-min" class="input" inputmode="numeric" value="10" /></label>
        <button class="btn block" id="p-start">Start conversation</button>
        <div id="p-msg" class="muted mt-3" aria-live="polite"></div>
        <div class="mini mt-3">
          You'll chat in German with a tutor. It steers the conversation toward your
          due &amp; weak words — each one lights up when you use it correctly.</div>
      </div>
      <div id="p-live" hidden>
        <div class="card"><div class="targets-strip" id="p-targets"></div></div>
        <div class="card"><div class="chat" id="p-chat"></div>
          <div class="chat-input">
            <input id="p-in" class="input" placeholder="Antworte auf Deutsch…" autocomplete="off" />
            <button class="btn" id="p-send">Send</button>
          </div>
        </div>
        <button class="btn ghost block mt-3" id="p-end">End &amp; save</button>
      </div>
      <div class="card" id="p-summary" hidden></div>`;

    $("#p-start").onclick = startConv;
    async function startConv() {
      $("#p-msg").textContent = "starting…"; $("#p-start").disabled = true;
      try {
        const r = await api("/study/conversation", { method: "POST", body: JSON.stringify({
          user_id: uid(), scenario: $("#p-scn").value,
          minutes: parseInt($("#p-min").value || "10", 10) || 10 }) });
        Object.assign(S, { sid: r.session_id, scenario: $("#p-scn").value, level: r.level,
          targets: r.targets, used: new Set(), history: [], turns: 0 });
        renderTargets();
        $("#p-chat").innerHTML = "";
        addBubble("tutor", r.opener);
        S.history.push({ role: "assistant", content: r.opener });
        $("#p-setup").hidden = true; $("#p-summary").hidden = true; $("#p-live").hidden = false;
        $("#p-in").focus();
      } catch (e) { $("#p-msg").innerHTML = `<span class="err-text">${esc(e.message)}</span>`; }
      finally { $("#p-start").disabled = false; }
    }
    function renderTargets() {
      $("#p-targets").innerHTML = S.targets.map((w) =>
        `<span class="chip${S.used.has(w.id) ? " done" : ""}" data-id="${w.id}"
           title="${esc(w.translation_en)}">${w.article ? esc(w.article) + " " : ""}${esc(w.lemma)}</span>`).join("");
    }
    function addBubble(who, text) {
      const d = document.createElement("div");
      d.className = "msg " + who;
      d.textContent = text;
      $("#p-chat").appendChild(d);
      $("#p-chat").scrollTop = $("#p-chat").scrollHeight;
    }
    async function send() {
      if (S.busy) return;
      const text = $("#p-in").value.trim();
      if (!text) return;
      S.busy = true; $("#p-send").disabled = true; $("#p-in").value = ""; $("#p-in").disabled = true;
      addBubble("me", text);
      S.history.push({ role: "user", content: text });
      S.turns++;
      const typing = document.createElement("div");
      typing.className = "msg tutor typing"; typing.textContent = "…";
      $("#p-chat").appendChild(typing);
      try {
        const r = await api("/study/conversation/turn", { method: "POST", body: JSON.stringify({
          session_id: S.sid, user_id: uid(), scenario: S.scenario,
          target_word_ids: S.targets.map((w) => w.id),
          history: S.history.slice(0, -1), user_message: text }) });
        typing.remove();
        addBubble("tutor", r.reply);
        S.history.push({ role: "assistant", content: r.reply });
        if (!r.available) toast("Tutor offline — set ANTHROPIC_API_KEY to enable grading", "");
        let fresh = 0;
        r.used_word_ids.forEach((id) => { if (!S.used.has(id)) { S.used.add(id); fresh++; } });
        if (fresh) { renderTargets(); toast(`+${fresh} word${fresh === 1 ? "" : "s"} used ✓`, "ok"); }
      } catch (e) { typing.remove(); addBubble("tutor", "⚠ " + e.message); }
      finally { S.busy = false; $("#p-send").disabled = false; $("#p-in").disabled = false; $("#p-in").focus(); }
    }
    $("#p-send").onclick = send;
    $("#p-in").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });

    $("#p-end").onclick = async () => {
      let res = {};
      try {
        res = await api("/study/conversation/finish", { method: "POST", body: JSON.stringify({
          session_id: S.sid, user_id: uid(), used_word_ids: [...S.used], turns: S.turns }) }) || {};
      } catch {}
      $("#p-live").hidden = true; $("#p-summary").hidden = false;
      const usedWords = S.targets.filter((w) => S.used.has(w.id));
      $("#p-summary").innerHTML =
        `<h3 class="mb-2">Nice work</h3>
         <p class="muted mb-3">${S.turns} turns · practised
           <b>${res.words_practised ?? usedWords.length}</b> of ${S.targets.length} target words.</p>
         <div class="chips">${usedWords.map((w) =>
           `<span class="chip done">${w.article ? esc(w.article) + " " : ""}${esc(w.lemma)}</span>`).join("") || `<span class="chip">none this time</span>`}</div>
         <button class="btn block mt-4" id="p-again">New conversation</button>
         <button class="btn ghost block mt-2" id="p-home">Back to home</button>`;
      $("#p-again").onclick = () => { $("#p-summary").hidden = true; $("#p-setup").hidden = false; };
      $("#p-home").onclick = () => (location.hash = "#/");
    };
  }

  // ================================================================
  //  VIEW: BROWSE
  // ================================================================
  async function viewBrowse(root) {
    const st = { limit: 25, offset: 0, level: "", topic: "", q: "", total: 0 };
    root.innerHTML = `
      <div class="card">
        <div class="chips mb-3" id="b-levels"></div>
        <div class="row">
          <input id="b-q" class="input" type="search" placeholder="lemma starts with…" />
          <select id="b-topic" class="select"><option value="">All topics</option></select>
        </div>
      </div>
      <div class="tablewrap mt-4">
        <table><thead><tr><th>#</th><th>Word</th><th>Plural</th><th>English</th><th>Level</th><th>Topic</th></tr></thead>
        <tbody id="b-rows"></tbody></table>
      </div>
      <div class="pager"><button class="btn ghost sm" id="b-prev">‹ Prev</button><span id="b-range"></span><button class="btn ghost sm" id="b-next">Next ›</button></div>`;

    $("#b-levels").innerHTML = `<button class="chip on" data-lv="">All levels</button>`
      + ["A1", "A2", "B1", "B2"].map((l) => `<button class="chip" data-lv="${l}">${l}</button>`).join("");
    $$("#b-levels .chip").forEach((c) => c.onclick = () => {
      st.level = c.dataset.lv; st.offset = 0;
      $$("#b-levels .chip").forEach((x) => x.classList.toggle("on", x === c));
      load();
    });
    try {
      const t = await api("/topics");
      $("#b-topic").innerHTML = `<option value="">All topics</option>` + t.map((x) => `<option>${esc(x.topic)}</option>`).join("");
    } catch {}
    $("#b-topic").onchange = () => { st.topic = $("#b-topic").value; st.offset = 0; load(); };
    let deb;
    $("#b-q").oninput = () => { clearTimeout(deb); deb = setTimeout(() => { st.q = $("#b-q").value.trim(); st.offset = 0; load(); }, 220); };
    $("#b-prev").onclick = () => { st.offset = Math.max(0, st.offset - st.limit); load(); };
    $("#b-next").onclick = () => { st.offset += st.limit; load(); };

    async function load() {
      const p = new URLSearchParams({ limit: st.limit, offset: st.offset });
      if (st.level) p.set("cefr_level", st.level);
      if (st.topic) p.set("topic", st.topic);
      if (st.q) p.set("q", st.q);
      $("#b-rows").innerHTML = `<tr><td colspan="6"><div class="skeleton" style="height:120px"></div></td></tr>`;
      let d;
      try { d = await api("/words?" + p); }
      catch (e) { $("#b-rows").innerHTML = `<tr><td colspan="6" class="err-text">${esc(e.message)}</td></tr>`; return; }
      st.total = d.total;
      $("#b-rows").innerHTML = d.items.map((w) => `
        <tr class="click" data-id="${w.id}">
          <td class="rank">${w.frequency_rank}</td>
          <td>${w.article ? `<span class="art">${esc(w.article)}</span> ` : ""}<b>${esc(w.lemma)}</b></td>
          <td>${esc(w.plural) || "—"}</td>
          <td class="en" title="${esc(w.translation_en)}">${esc(shortGloss(w.translation_en))}</td>
          <td><span class="badge">${esc(w.cefr_level)}</span></td>
          <td>${esc(w.topic) || "—"}</td>
        </tr>`).join("") || `<tr><td colspan="6" class="empty">no matches</td></tr>`;
      $$("#b-rows tr.click").forEach((tr) => tr.onclick = () => openWord(tr.dataset.id));
      $("#b-range").textContent = st.total ? `${st.offset + 1}–${Math.min(st.offset + st.limit, st.total)} of ${st.total}` : "0";
      $("#b-prev").disabled = st.offset === 0;
      $("#b-next").disabled = st.offset + st.limit >= st.total;
    }
    async function openWord(id) {
      let w;
      try { w = await api(`/words/${id}`); } catch (e) { toast(e.message, "bad"); return; }
      const bg = document.createElement("div"); bg.className = "drawer-bg";
      const dr = document.createElement("div");
      dr.className = "drawer"; dr.setAttribute("role", "dialog"); dr.setAttribute("aria-label", w.lemma); dr.tabIndex = -1;
      dr.innerHTML = `
        <div class="drawer-top"><span class="badge">${esc(w.cefr_level)}</span>
          <button class="icon-btn" id="dr-x" aria-label="Close">${svg("x")}</button></div>
        <div class="big">${w.article ? `<span class="art">${esc(w.article)}</span> ` : ""}${esc(w.lemma)}</div>
        <div class="muted">${esc(w.translation_en)}</div>
        <dl class="kv">
          <dt>Plural</dt><dd>${esc(w.plural) || "—"}</dd>
          <dt>IPA</dt><dd>${w.ipa_or_audio_ref ? "/" + esc(w.ipa_or_audio_ref) + "/" : "—"}</dd>
          <dt>Topic</dt><dd>${esc(w.topic) || "—"}</dd>
          <dt>Frequency rank</dt><dd>#${w.frequency_rank}</dd>
        </dl>`;
      const release = trapFocus(dr, () => close());
      const prevFocus = document.activeElement;
      const close = () => { release(); bg.remove(); dr.remove(); prevFocus?.focus?.(); };
      bg.onclick = close;
      dr.querySelector("#dr-x").onclick = close;
      document.body.append(bg, dr);
    }
    load();
  }

  // ================================================================
  //  VIEW: PROGRESS  (dashboard)
  // ================================================================
  async function viewProgress(root) {
    let p;
    try { p = await api(`/study/users/${uid()}/dashboard`); }
    catch (e) { root.innerHTML = errCard(e); return; }
    const acc = p.overall_accuracy == null ? "–" : Math.round(p.overall_accuracy * 100) + "%";
    const days = p.daily_activity || [];
    const mx = Math.max(1, ...days.map((x) => x.reviews));
    const totR = days.reduce((s, x) => s + x.reviews, 0), totC = days.reduce((s, x) => s + x.correct, 0);
    const today = days.length ? days[days.length - 1].date : "";
    const bars = days.map((x) => {
      const h = Math.round(pctOf(x.reviews, mx)), c = x.reviews ? Math.round(pctOf(x.correct, x.reviews)) : 0;
      return `<i class="${x.date === today ? "today" : ""}" style="height:${h}%" title="${x.date}: ${x.reviews} reviews, ${x.correct} correct"><b style="height:${c}%"></b></i>`;
    }).join("");
    const lvl = (arr, sm) => (arr || []).filter((L) => L.total).map((L) => `
      <div class="lvlrow${sm ? " wide" : ""}"><span class="nm" title="${esc(L.level || L.topic)}">${esc(L.level || L.topic)}</span>
        <div class="bar" title="${L.known} known · ${L.seen} seen · ${L.total}">
          <i class="seen" style="width:0" data-w="${pctOf(L.seen, L.total)}%"></i><i class="known" style="width:0" data-w="${pctOf(L.known, L.total)}%"></i></div>
        <span class="num"><b>${L.seen}</b> / ${L.total}</span></div>`).join("");
    const m = p.maturity || { learning: 0, young: 0, mature: 0 };
    const mT = m.learning + m.young + m.mature;
    const fc = p.forecast || [];
    const fcMax = Math.max(1, ...fc.map((f) => f.count));
    const li = (arr) => (arr || []).length
      ? arr.map((w) => `<li><span class="de">${w.article ? esc(w.article) + " " : ""}${esc(w.lemma)}</span>
          <span class="en2" title="${esc(w.translation_en)}">${esc(shortGloss(w.translation_en))}</span></li>`).join("")
      : `<li class="en2">none</li>`;
    const sess = p.recent_sessions || [];
    root.innerHTML = `
      <div class="kpis">
        <div class="stat"><b><span data-n="${p.current_streak}">0</span>🔥</b><span>day streak</span><small>best ${p.best_streak}</small></div>
        <div class="stat"><b data-n="${p.total_reviews}">0</b><span>reviews</span><small>${p.words_seen} seen</small></div>
        <div class="stat"><b>${acc}</b><span>accuracy</span><small>${p.words_known} known</small></div>
        <div class="stat"><b data-n="${p.words_due_now}">0</b><span>due now</span><small>&nbsp;</small></div>
        <div class="stat"><b>${esc(p.cefr_ceiling)}</b><span>ceiling</span><small>target ${esc(p.target)}</small></div>
        <div class="stat"><b data-n="${sess.length}">0</b><span>sessions</span><small>recent</small></div>
      </div>
      <div class="card">
        <div class="card-h"><h3>Activity — last ${days.length} days</h3></div>
        <div class="spark">${bars}</div>
        <div class="sparkcap"><span>${days[0] ? days[0].date.slice(5) : ""}</span>
          <span>${totR} reviews · ${totR ? Math.round(100 * totC / totR) : 0}% correct</span><span>today</span></div>
      </div>
      <div class="card"><div class="card-h"><h3>Coverage by level</h3></div>${lvl(p.by_level)}
        <div class="legend"><span><i class="f"></i>seen</span><span><i></i>answered right ≥ once</span></div></div>
      ${mT ? `<div class="card"><div class="card-h"><h3>Word maturity</h3></div>
        <div class="stack"><i class="l" style="width:0" data-w="${pctOf(m.learning, mT)}%"></i><i class="y" style="width:0" data-w="${pctOf(m.young, mT)}%"></i><i class="m" style="width:0" data-w="${pctOf(m.mature, mT)}%"></i></div>
        <div class="legend"><span><i class="f"></i>learning ${m.learning}</span><span><i class="y"></i>young ${m.young}</span><span><i></i>mature ${m.mature}</span></div></div>` : ""}
      <div class="card"><div class="card-h"><h3>Upcoming reviews</h3></div><div class="fc">${
        fc.map((f) => `<div><b>${f.count}</b><div class="fb2 ${f.label === "overdue" ? "over" : ""}" style="height:${pctOf(f.count, fcMax)}%"></div><span>${esc(f.label)}</span></div>`).join("")
      }</div></div>
      ${lvl(p.by_topic, true) ? `<div class="card"><div class="card-h"><h3>Coverage by topic</h3></div>${lvl(p.by_topic, true)}</div>` : ""}
      ${sess.length ? `<div class="card"><div class="card-h"><h3>Recent sessions</h3></div><ul class="list">${
        sess.map((s) => `<li><span class="de">${day(s.started_at)}</span><span class="en2">${s.topic ? esc(s.topic) : "general"}</span><span class="meta">${s.words_covered} words · ${s.minutes} min</span></li>`).join("")
      }</ul></div>` : ""}
      <div class="card"><div class="card-h"><h3>Due for review</h3></div><ul class="list">${li(p.due_words)}</ul>
        <div class="card-h mt-3"><h3>Weakest words</h3></div><ul class="list">${li(p.weak_words)}</ul></div>`;

    $$("[data-n]", root).forEach((el) => countUp(el, +el.dataset.n));
    requestAnimationFrame(() => $$("[data-w]", root).forEach((el) => { el.style.width = el.dataset.w; }));
  }

  // ================================================================
  //  VIEW: SETTINGS
  // ================================================================
  function viewSettings(root) {
    root.classList.add("narrow");
    root.innerHTML = `
      <div class="card">
        <div class="card-h"><h3>Appearance</h3></div>
        <div class="seg" id="theme">
          <button data-v="system">System</button><button data-v="light">Light</button><button data-v="dark">Dark</button>
        </div>
      </div>
      <div class="card">
        <div class="card-h"><h3>Account</h3></div>
        <dl class="kv">
          <dt>Username</dt><dd>${esc(sess.username)}</dd>
          <dt>Target</dt><dd>${esc(sess.target || "—")}</dd>
          <dt>User id</dt><dd>#${sess.id}</dd>
        </dl>
        <button class="btn danger mt-3" id="set-logout">Log out</button>
      </div>
      <div class="card">
        <div class="card-h"><h3>Connection</h3></div>
        <label class="field"><span>API base URL</span><input class="input" id="set-api" value="${esc(API)}" /></label>
        <button class="btn ghost" id="set-api-save">Save &amp; reload</button>
      </div>
      <div class="card">
        <div class="card-h"><h3>About</h3></div>
        <div class="muted">learn-german — a deterministic spaced-repetition trainer with an
        agentic MCP layer. <a href="https://claude.com/claude-code" target="_blank" rel="noreferrer">built with Claude Code</a>.</div>
      </div>`;
    $$("#theme button").forEach((b) => {
      b.classList.toggle("on", b.dataset.v === theme);
      b.onclick = () => { setTheme(b.dataset.v); $$("#theme button").forEach((x) => x.classList.toggle("on", x === b)); };
    });
    $("#set-logout").onclick = () => { clearSess(); location.hash = "#/"; render(); };
    $("#set-api-save").onclick = () => {
      const v = $("#set-api").value.trim();
      try { v ? localStorage.setItem("lg_api", v) : localStorage.removeItem("lg_api"); } catch {}
      location.reload();
    };
  }

  // ---------- shared ------------------------------------------------
  function errCard(e) {
    return `<div class="card"><div class="empty">${svg("x")}<div>${esc(e.message)}</div>
      <button class="btn ghost sm mt-3" onclick="location.reload()">retry</button></div></div>`;
  }

  render();
})();
