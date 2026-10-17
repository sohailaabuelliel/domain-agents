// Domain Agents UI — plain JS, no build step.
// Everything the old UI showed is still shown: agent info, tasks, refusals, threshold, examples, memory,
// live trace, status, summary, findings + severity, limitations, confidence (+ parts, reasons, reviewer),
// sources (title, section, type, similarity, link, excerpt), disclaimer, usage stats, checklist, docs.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const state = { domains: [], cur: null, history: {}, busy: false, view: "chat", doc: null, checklist: null, docsList: null, models: {} };
const SID = sessionStorage.getItem("sid") || (() => { const v = crypto.randomUUID?.() || String(Math.random()).slice(2); sessionStorage.setItem("sid", v); return v; })();
const ICONS = ["pharma", "medical", "finance", "marketing", "hospitality"];
const icon = d => ICONS.includes(d.id) ? `/static/icons/${d.id}.png` : "/static/icons/logo.png";
const PROVIDERS = { gemini: "Google Gemini", openai: "OpenAI", azure: "Azure OpenAI" };
const isAr = s => (String(s || "").match(/[\u0600-\u06FF]/g) || []).length > String(s || "").length * 0.3;

// ---------- i18n (UI chrome only; docs, answers and knowledge keep their own language) ----------
let UI = localStorage.getItem("uiLang") || "en";
function t(key, vars = {}) {
  const s = (I18N[UI] && I18N[UI][key]) ?? I18N.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
}
const INTENT = {
  en: { individual_dosing: "individual dosing", diagnosis: "diagnosis", self_harm_misuse: "self-harm / misuse", individual_treatment: "individual treatment", self_harm: "self-harm",
        investment_advice: "investment advice", price_prediction: "price prediction", guaranteed_results: "guaranteed results", deceptive_tactics: "deceptive tactics",
        fake_engagement: "fake engagement", fake_reviews: "fake reviews", guest_privacy: "guest privacy", guest_privacy_roomnumber: "guest room numbers" },
  ar: { individual_dosing: "جرعة لشخص بعينه", diagnosis: "التشخيص", self_harm_misuse: "إيذاء النفس / سوء الاستخدام", individual_treatment: "علاج لشخص بعينه", self_harm: "إيذاء النفس",
        investment_advice: "نصائح استثمارية", price_prediction: "توقّع الأسعار", guaranteed_results: "وعود بنتائج مضمونة", deceptive_tactics: "أساليب مضلِّلة",
        fake_engagement: "تفاعل مزيّف", fake_reviews: "تقييمات مزيّفة", guest_privacy: "خصوصية الضيوف", guest_privacy_roomnumber: "أرقام غرف الضيوف" },
};
const intent = id => INTENT[UI][id] || INTENT.en[id] || id.replace(/_/g, " ");
const dn = d => (UI === "ar" && d.ar?.name) || d.name;
const duse = d => (UI === "ar" && d.ar?.use_case) || d.use_case;
const dtasks = d => (UI === "ar" && d.ar?.tasks?.length ? d.ar.tasks : d.tasks);
const ddisc = d => (UI === "ar" && d.ar?.disclaimer) || d.disclaimer;

function applyLang() {
  document.documentElement.lang = UI;
  document.documentElement.dir = UI === "ar" ? "rtl" : "ltr";
  $$("[data-i18n]").forEach(el => el.textContent = t(el.dataset.i18n));
  $$("[data-i18n-ph]").forEach(el => el.placeholder = t(el.dataset.i18nPh));
  $$("[data-i18n-title]").forEach(el => el.title = t(el.dataset.i18nTitle));
  $$("[data-ui-lang]").forEach(b => b.classList.toggle("on", b.dataset.uiLang === UI));
  renderAgentNav(); S.pill(); S.dot();
  if (state.view === "chat" && state.cur) { renderAgentHead(); rerenderMsgs(); }
  else if (state.view === "checklist") renderChecklist();
  else if (state.view === "docs") { setHead("docs"); renderDocsNav(); }
  if (!$("#modal").classList.contains("hidden")) S.renderModels();
}
$$("[data-ui-lang]").forEach(b => b.onclick = () => { UI = b.dataset.uiLang; localStorage.setItem("uiLang", UI); applyLang(); });

// ---------- settings (key lives only in sessionStorage) ----------
const S = {
  get() { return Object.assign({ provider: "gemini", api_key: "", model: "", azure_endpoint: "" }, JSON.parse(sessionStorage.getItem("llm") || "{}")); },
  set(patch) { sessionStorage.setItem("llm", JSON.stringify(Object.assign(S.get(), patch))); S.dot(); S.pill(); },
  load() {
    const v = S.get();
    $("#apikey").value = v.api_key; $("#endpoint").value = v.azure_endpoint;
    S.seg(v.provider); S.dot(); S.pill();
  },
  seg(p) {
    $$("#providerSeg button").forEach(b => { const on = b.dataset.p === p; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
    $("#azureRow").classList.toggle("hidden", p !== "azure");
  },
  dot() { const k = !!S.get().api_key; $("#keyDot").className = "dot " + (k ? "on" : "off"); $("#keyDot").title = t(k ? "key.yours" : "key.server"); },
  pill() {
    const v = S.get();
    $("#mpProvider").textContent = PROVIDERS[v.provider] || v.provider;
    $("#mpModel").textContent = v.model || (state.models[S.cacheKey()]?.default) || t("set.default");
  },
  cacheKey() { const v = S.get(); return [v.provider, v.api_key, v.azure_endpoint].join("|"); },
  timer: null, req: 0,
  async fetchModels(force = false) {
    const v = S.get(), key = S.cacheKey();
    if (!force && state.models[key]?.ok) return S.renderModels();
    if (v.provider === "azure" && !v.azure_endpoint) { state.models[key] = { ok: false, need: true, models: [] }; return S.renderModels(); }
    const my = ++S.req;
    state.models[key] = { loading: true, models: [] }; S.renderModels();
    let r;
    try { r = await fetch("/api/models", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }).then(x => x.json()); }
    catch (e) { r = { ok: false, error: String(e), models: [] }; }
    if (my !== S.req) return;
    if (!r.ok && /No API key|needs an endpoint/i.test(r.error || "")) r.need = true;
    state.models[key] = r; S.renderModels(); S.pill();
  },
  renderModels() {
    const v = S.get(), m = state.models[S.cacheKey()] || {}, sel = $("#modelSel"), st = $("#modelStatus");
    $("#modelSpin").classList.toggle("hidden", !m.loading);
    sel.disabled = !!m.loading;
    const list = m.models || [];
    const chosen = v.model || m.default || "";
    const custom = chosen && !list.includes(chosen) && !(m.loading);
    let opts = "";
    if (m.loading) opts = `<option>${esc(t("set.loading", { p: PROVIDERS[v.provider] }))}</option>`;
    else {
      if (!list.length) opts += `<option value="">${esc(t("set.default"))}${m.default ? " · " + esc(m.default) : ""}</option>`;
      opts += list.map(x => `<option value="${esc(x)}">${esc(x)}${x === m.default ? "   (" + esc(t("set.default")) + ")" : ""}</option>`).join("");
      opts += `<option value="__custom">${esc(t("set.custom"))}</option>`;
    }
    sel.innerHTML = opts;
    if (!m.loading) {
      if (list.includes(chosen)) sel.value = chosen;
      else if (custom) sel.value = "__custom";
      else sel.value = list.length ? (list.includes(m.default) ? m.default : list[0]) : "";
    }
    $("#modelCustom").classList.toggle("hidden", sel.value !== "__custom");
    if (sel.value === "__custom") $("#modelCustom").value = v.model;
    st.className = "f-hint" + (m.ok ? " ok" : (m.error && !m.need ? " err" : ""));
    st.textContent = m.loading ? "" : m.ok ? t("set.found", { n: list.length }) : m.need ? t("set.needKey") : m.error ? t("set.failed", { e: m.error }) : "";
    if (!m.loading && sel.value !== "__custom" && sel.value !== v.model) S.set({ model: sel.value });
  },
  open() { S.load(); $("#modal").classList.remove("hidden"); $("#testOut").textContent = ""; $("#testOut").className = "test-out"; S.fetchModels(); },
  close() { $("#modal").classList.add("hidden"); },
};
$("#openSettings").onclick = S.open;
$("#stopServer").onclick = async () => {
  if (!confirm(t("stop.confirm"))) return;
  try {
    const r = await fetch("/api/shutdown", { method: "POST" });
    if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || r.statusText); return; }
  } catch (e) { /* the server may close the connection while stopping */ }
  const d = document.createElement("div");
  d.className = "stopped";
  d.innerHTML = `<div><h2>${t("stop.done")}</h2><p>${t("stop.close")}</p><p>${t("stop.again")}</p></div>`;
  document.body.appendChild(d);
};
$("#closeSettings").onclick = $("#xSettings").onclick = S.close;
$("#modal").addEventListener("mousedown", e => { if (e.target.id === "modal") S.close(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") { S.close(); closeSide(); } });
$$("#providerSeg button").forEach(b => b.onclick = () => { S.set({ provider: b.dataset.p, model: "" }); S.seg(b.dataset.p); S.fetchModels(); });
const debounced = () => { clearTimeout(S.timer); S.timer = setTimeout(() => S.fetchModels(), 600); };
$("#apikey").oninput = () => { S.set({ api_key: $("#apikey").value.trim(), model: "" }); debounced(); };
$("#endpoint").oninput = () => { S.set({ azure_endpoint: $("#endpoint").value.trim() }); debounced(); };
$("#refreshModels").onclick = () => S.fetchModels(true);
$("#modelSel").onchange = () => {
  const v = $("#modelSel").value;
  $("#modelCustom").classList.toggle("hidden", v !== "__custom");
  if (v === "__custom") { $("#modelCustom").value = ""; $("#modelCustom").focus(); } else S.set({ model: v });
};
$("#modelCustom").oninput = () => S.set({ model: $("#modelCustom").value.trim() });
$("#testKey").onclick = async () => {
  const out = $("#testOut"); out.className = "test-out"; out.textContent = t("set.testing");
  let r;
  try { r = await fetch("/api/test-key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(S.get()) }).then(x => x.json()); }
  catch (e) { r = { ok: false, error: String(e) }; }
  out.className = "test-out " + (r.ok ? "ok" : "err");
  out.textContent = r.ok ? `✓ ${PROVIDERS[r.provider] || r.provider} · ${r.model}` : "✕ " + r.error;
};

// ---------- layout helpers ----------
const closeSide = () => { $("#side").classList.remove("open"); $("#scrim").classList.remove("open"); };
$("#menuBtn").onclick = () => { $("#side").classList.add("open"); $("#scrim").classList.add("open"); };
$("#scrim").onclick = closeSide;
function show(view) {
  state.view = view;
  $$(".view").forEach(v => v.classList.add("hidden"));
  $("#view-" + view).classList.remove("hidden");
  $$(".nav").forEach(n => n.classList.toggle("on", view === "chat" ? n.dataset.agent === state.cur?.id : n.dataset.view === view));
  closeSide();
}
function setAccent(c) {
  const r = document.documentElement.style;
  r.setProperty("--c", c); r.setProperty("--c-soft", `color-mix(in srgb, ${c} 12%, white)`);
}
function setHead(view) {
  if (view === "chat") return renderAgentHead();
  const ico = view === "docs" ? "nav.docs" : "nav.checklist";
  $("#head").innerHTML = `<div><h1>${esc(t(ico))}</h1><div class="sub">${esc(view === "docs" ? t("docs.sub") : t("ck.sub"))}</div></div>`;
}

// ---------- agents ----------
function renderAgentNav() {
  $("#agents").innerHTML = state.domains.map(d => `<a class="nav ${state.view === "chat" && state.cur?.id === d.id ? "on" : ""}" data-agent="${d.id}" href="#${d.id}" style="--c:${d.accent}">
    <img class="agent-ico" src="${icon(d)}" alt="" width="32" height="32"><span class="nav-text"><b>${esc(dn(d))}</b><small>${esc(t("agent.docs", { n: d.documents }))}</small></span></a>`).join("");
}
function renderAgentHead() {
  const d = state.cur;
  $("#head").innerHTML = `<img class="top-ico" src="${icon(d)}" alt="" width="38" height="38"><div style="min-width:0">
    <h1>${esc(dn(d))}</h1><div class="sub"><span>${esc(t("agent.knowledge", { n: d.documents }))}</span><span class="sep"></span>
    <span class="hide-sm">${esc(t("agent.tools"))}:</span>${d.tools.map(x => `<span class="pill tool">${esc(x)}</span>`).join("")}</div></div>`;
  const has = (state.history[d.id] || []).length > 0;
  const info = $("#info"); const tag = has ? "details" : "div";
  if (info.tagName.toLowerCase() !== tag) { const n = document.createElement(tag); n.id = "info"; n.className = "info"; info.replaceWith(n); }
  $("#info").innerHTML = (has ? `<summary><img src="${icon(d)}" alt="" width="20" height="20">${esc(t("agent.about"))}</summary>` : "") + `<p class="info-lead">${esc(duse(d))}</p>
    <div class="info-grid">
      <div><h4>${esc(t("agent.canDo"))}</h4><ul class="tasks">${dtasks(d).map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div><h4>${esc(t("agent.refuses"))}</h4><div class="refuse">${d.blocked_intents.map(b => `<span class="pill no">${esc(intent(b.id))}</span>`).join("") || "—"}</div></div>
    </div>
    <div class="info-foot"><span class="k">${esc(t("agent.threshold", { v: d.min_score }))}</span></div>
    ${ddisc(d) ? `<div class="disclaimer" dir="auto">${esc(ddisc(d))}</div>` : ""}`;
  $("#examples").innerHTML = d.examples.map(e => `<button type="button" class="chip" dir="auto" title="${esc(e)}">${esc(e)}</button>`).join("");
  $$("#examples .chip").forEach(c => c.onclick = () => { $("#q").value = c.title; autosize(); $("#q").focus(); });
}
function openAgent(id) {
  const d = state.domains.find(x => x.id === id) || state.domains[0];
  state.cur = d; if (location.hash.slice(1) !== d.id) history.replaceState(null, "", "#" + d.id);
  setAccent(d.accent); show("chat"); renderAgentHead(); rerenderMsgs();
  $("#chatScroll").scrollTop = 0;
}

// ---------- memory ----------
function renderMemory(prefs) {
  state.memory = prefs || [];
  const el = $("#memory");
  el.innerHTML = state.memory.length ? `<span>${esc(t("mem.title"))}:</span>` + state.memory.map(p => `<span class="mem-chip" dir="auto">${esc(p.label)}: ${esc(p.value)}</span>`).join("") + `<button id="memclear" type="button" class="link-btn">${esc(t("mem.forget"))}</button>` : "";
  $("#memclear")?.addEventListener("click", async () => { await fetch("/api/memory/" + SID, { method: "DELETE" }); renderMemory([]); });
}

// ---------- trace ----------
const TI = { guard_input: "◆", thought: "…", action: "→", observation: "↳", coverage: "≈", verify: "✓", verify_pruned: "✂", review: "◈", confidence: "%", error: "!", memory_learned: "＋" };
function traceLine(e) {
  const f = {
    memory_learned: e => `<b>${esc(t("tr.memory"))}</b>: ${esc((e.items || []).join(" · "))}`,
    guard_input: e => e.ok ? esc(t("tr.guardOk")) : `${esc(t("tr.guardBad"))} <b>${esc(e.rule)}</b>`,
    thought: e => esc(String(e.text || "").slice(0, 160)),
    action: e => `<b>${esc(e.tool)}</b> ${esc(JSON.stringify(e.args)).slice(0, 140)}`,
    observation: e => esc(t("tr.sources", { n: e.n_sources })),
    coverage: e => `${esc(t("tr.best", { b: e.best_similarity, t: e.threshold }))}${e.unknown_terms?.length ? ` · ${esc(t("tr.unknown"))}: ${esc(e.unknown_terms.join(", "))}` : ""} → ${e.covered ? esc(t("tr.covered")) : `<b>${esc(t("tr.notCovered"))}</b>`}`,
    verify: e => `${esc(t("tr.verify", { a: e.attempt }))}: ${e.valid && !e.weak ? esc(t("tr.ok")) : esc(t("tr.repair"))} (${esc(t("tr.grounding"))} ${e.support})`,
    verify_pruned: e => esc(t("tr.pruned", { n: e.dropped })),
    review: e => `${esc(t("tr.review"))}: ${e.approved ? esc(t("tr.approved")) : esc(t("tr.flagged")) + " — " + esc((e.issues || []).join("; ")).slice(0, 140)}`,
    confidence: e => esc(t("tr.conf", { s: e.score, l: t("res.level." + e.level) })),
    error: e => esc(e.text),
  }[e.type];
  if (!f) return "";
  return `<div class="tl"><span class="tt">${e.t != null ? esc(e.t) + "s" : ""}</span><span class="ti">${TI[e.type] || "·"}</span><span>${f(e)}</span></div>`;
}

// ---------- answer rendering ----------
const cite = (text, id) => esc(text).replace(/\[(S\d+)\]/g, (_, s) => `<span class="cite" role="button" tabindex="0" data-src="${id}-${s}">${s}</span>`);
const SHIELD = `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5l6 2.3v4.6c0 3.9-2.6 6.6-6 8.1-3.4-1.5-6-4.2-6-8.1V4.8z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>`;
function renderResult(res, id, q, trace) {
  const dir = isAr(res.answer?.summary || res.message || q) ? "rtl" : "ltr";
  let h = `<div class="res-head"><span class="status s-${res.status}">${esc(t("st." + res.status))}</span>`;
  if (res.review) h += `<span class="rev ${res.review.approved ? "ok" : "bad"}">${SHIELD}${esc(t(res.review.approved ? "res.reviewOk" : "res.reviewBad"))}</span>`;
  h += `</div>`;
  if (res.status !== "answered") h += `<p class="res-msg" dir="${dir}">${esc(res.message)}</p>`;
  else {
    const a = res.answer;
    h += `<div dir="${dir}"><div class="summary">${cite(a.summary, id)}</div>`;
    if (a.findings?.length) h += `<div class="findings">${a.findings.map(f => `<div class="finding ${esc(f.severity || "")}"><h4>${f.severity ? `<span class="sev ${esc(f.severity)}">${esc(f.severity)}</span>` : ""}${esc(f.title)}</h4><p>${cite(f.detail, id)}</p></div>`).join("")}</div>`;
    if (a.limitations) h += `<div class="lim"><b>${esc(t("res.limitations"))}:</b> ${cite(a.limitations, id)}</div>`;
    h += `</div>`;
  }
  const c = res.confidence;
  if (c && res.status === "answered") {
    const col = c.score >= .75 ? "var(--ok)" : c.score >= .5 ? "#d98a00" : "var(--bad)";
    h += `<div class="conf"><div class="conf-score" style="color:${col}">${Math.round(c.score * 100)}%<small>${esc(t("res.confidence"))} · ${esc(t("res.level." + c.level))}</small></div>
      <div class="meter"><i style="width:${c.score * 100}%;background:${col}"></i></div>
      <div class="parts">${Object.entries(c.parts || {}).map(([k, v]) => `<span>${esc(t("res.part." + k))} <b>${esc(v)}</b></span>`).join("")}</div>
      ${c.reasons?.length ? `<div class="reasons" dir="auto">${c.reasons.map(r => `<span>⚠ ${esc(r)}</span>`).join("")}</div>` : ""}</div>`;
  }
  if (res.status === "answered" && res.message) h += `<div class="disc" dir="auto">${esc(res.message)}</div>`;
  if (res.sources?.length) h += `<details class="fold src-fold"><summary>${esc(t("res.sources", { n: res.sources.length }))}</summary><div class="fold-body">${res.sources.map(s => `
    <div class="src" id="${id}-${esc(s.id)}" dir="ltr"><div class="src-head"><span class="src-id">[${esc(s.id)}]</span><span class="src-title">${esc(s.title)}</span>${s.section ? `<span class="src-sec">› ${esc(String(s.section).slice(0, 90))}</span>` : ""}</div>
    <div class="src-meta"><span>${esc(s.doc_type)}</span><span>${esc(t("res.sim"))} ${esc(s.similarity)}</span>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(t("res.link"))} ↗</a>` : ""}</div>
    <p>${esc(s.excerpt)}…</p></div>`).join("")}</div></details>`;
  if (trace?.length) h += `<details class="fold"><summary>${esc(t("res.trace"))}</summary><div class="fold-body"><div class="trace">${trace.map(traceLine).join("")}</div></div></details>`;
  if (res.usage?.llm_calls) h += `<div class="stats">${esc(t("res.stats", { s: res.elapsed, c: res.usage.llm_calls, t: (res.usage.prompt_tokens || 0) + (res.usage.output_tokens || 0) }))}</div>`;
  return h;
}
const userBubble = q => `<div class="msg user" dir="auto">${esc(q)}</div>`;
function rerenderMsgs() {
  const hist = state.history[state.cur.id] || [];
  $("#msgs").innerHTML = hist.map(m => userBubble(m.q) + `<div class="msg bot" id="${m.id}">${renderResult(m.result, m.id, m.q, m.trace)}</div>`).join("");
}
function jumpToSource(el) {
  const box = document.getElementById(el.dataset.src); if (!box) return;
  box.closest("details").open = true; box.scrollIntoView({ block: "center", behavior: "smooth" });
  box.classList.add("flash"); setTimeout(() => box.classList.remove("flash"), 1600);
}
$("#msgs").addEventListener("click", e => { const c = e.target.closest(".cite"); if (c) jumpToSource(c); });
$("#msgs").addEventListener("keydown", e => { const c = e.target.closest(".cite"); if (c && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); jumpToSource(c); } });

// ---------- ask ----------
const scrollDown = () => { const s = $("#chatScroll"); s.scrollTop = s.scrollHeight; };
async function ask(question) {
  if (state.busy || !question.trim()) return;
  state.busy = true; $("#send").disabled = true;
  const d = state.cur, id = "m" + Date.now(), hist = state.history[d.id] ||= [];
  $("#msgs").insertAdjacentHTML("beforeend", userBubble(question) + `<div class="msg bot" id="${id}"><div class="working"><span class="spin"></span>${esc(t("chat.thinking"))}</div><div class="trace live-trace"></div></div>`);
  const box = document.getElementById(id), tr = box.querySelector(".trace"); scrollDown();
  const trace = []; let result = null;
  try {
    const resp = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      domain: d.id, question, language: $("#lang").value, review: $("#review").checked, llm: S.get(), session_id: SID,
      history: hist.flatMap(m => [{ role: "user", text: m.q }, { role: "assistant", text: m.result.answer?.summary || m.result.message || "" }]) }) });
    const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i; while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = /event: (\w+)/.exec(block)?.[1], data = JSON.parse(/data: (.*)/s.exec(block)?.[1] || "{}");
        if (ev === "trace") { trace.push(data); tr.insertAdjacentHTML("beforeend", traceLine(data)); scrollDown(); }
        if (ev === "result") { result = data; renderMemory(data.memory); }
        if (ev === "fatal") { result = { status: "error", message: data.message, sources: [], confidence: null }; if (data.code === "missing_key") S.open(); }
      }
    }
  } catch (err) { result = { status: "error", message: String(err), sources: [] }; }
  result ||= { status: "error", message: "No response from the server.", sources: [] };
  hist.push({ id, q: question, result, trace });
  if (state.cur.id === d.id) { box.innerHTML = renderResult(result, id, question, trace); if (hist.length === 1) renderAgentHead(); }
  state.busy = false; $("#send").disabled = false; $("#q").focus();
}
const autosize = () => { const q = $("#q"); q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 180) + "px"; };
$("#q").addEventListener("input", autosize);
$("#form").onsubmit = e => { e.preventDefault(); const q = $("#q").value; $("#q").value = ""; autosize(); ask(q); };
$("#q").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#form").requestSubmit(); } };

// ---------- checklist ----------
async function loadChecklist() {
  show("checklist"); setAccent("#0f766e"); setHead("checklist");
  if (history.state !== "ck") history.replaceState(null, "", "#checklist");
  state.checklist ||= await fetch("/api/checklist").then(r => r.json());
  renderChecklist();
}
function renderChecklist() {
  setHead("checklist");
  const c = state.checklist; if (!c) return;
  const all = c.groups.flatMap(g => g.items), n = all.length;
  const done = all.filter(i => i.status === "done").length, part = all.filter(i => i.status === "partial").length, todo = n - done - part;
  const lab = s => t({ done: "ck.done", partial: "ck.partial", todo: "ck.todo" }[s] || s);
  $("#checklist").innerHTML = `<div class="prog"><div class="prog-num">${done}<small>/${n}</small></div><div class="prog-main">
      <div class="bar"><i style="width:${done / n * 100}%;background:var(--ok)"></i><i style="width:${part / n * 100}%;background:#e0a43c"></i></div>
      <div class="prog-legend"><span><i style="background:var(--ok)"></i>${done} ${esc(t("ck.done"))}</span><span><i style="background:#e0a43c"></i>${part} ${esc(t("ck.partial"))}</span><span><i style="background:var(--line-2)"></i>${todo} ${esc(t("ck.todo"))}</span></div></div></div>` +
    c.groups.map(g => {
      const gd = g.items.filter(i => i.status === "done").length;
      return `<div class="grp"><h3><span dir="auto">${esc(g.title)}</span><small>${esc(t("ck.of", { d: gd, n: g.items.length }))}</small></h3>${g.items.map(i => `
        <div class="it"><span class="badge b-${esc(i.status)}">${esc(lab(i.status))}</span><div style="min-width:0"><div class="it-text" dir="auto">${esc(i.text)}</div>
        <div class="it-meta"><code>${esc(i.where)}</code>${i.doc ? `<a data-doc="${esc(i.doc.split("/").pop())}">${esc(i.doc)} ↗</a>` : ""}</div></div></div>`).join("")}</div>`;
    }).join("");
  $$("#checklist [data-doc]").forEach(a => a.onclick = () => loadDocs(a.dataset.doc));
}

// ---------- docs (always English; Mermaid diagrams rendered) ----------
let mermaidReady = null;
function loadMermaid() {
  return mermaidReady ||= new Promise((ok, bad) => {
    const s = document.createElement("script"); s.src = "/static/vendor/mermaid.min.js";
    s.onload = () => { mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", fontFamily: "Plex, system-ui, sans-serif",
      themeVariables: { primaryColor: "#e3f1ef", primaryBorderColor: "#0f766e", primaryTextColor: "#1d2321", lineColor: "#76807c", secondaryColor: "#fbf0d9", tertiaryColor: "#faf9f7", fontSize: "14px" },
      flowchart: { htmlLabels: true, curve: "basis", useMaxWidth: false } }); ok(window.mermaid); };
    s.onerror = bad; document.head.appendChild(s);
  });
}
function mdToHtml(src) {
  const r = new marked.Renderer();
  const baseCode = r.code.bind(r);
  r.code = tok => (tok.lang || "").trim() === "mermaid" ? `<div class="mermaid-box"><div class="mm-tools"><button type="button" data-mm="full">⤢ ${esc(t("docs.full"))}</button></div><div class="mermaid-scroll"><pre class="mermaid">${esc(tok.text)}</pre></div></div>` : baseCode(tok);
  return marked.parse(src, { renderer: r, gfm: true });
}
function fixDocLinks(root) {
  root.querySelectorAll("a[href]").forEach(a => {
    const h = a.getAttribute("href");
    if (/^https?:/.test(h)) { a.target = "_blank"; a.rel = "noopener"; return; }
    if (/^#/.test(h)) return;
    const file = h.split("/").pop();
    if (/\.md$/i.test(file)) { a.href = "#docs/" + file; a.onclick = e => { e.preventDefault(); loadDocs(file); }; }
    else if (/checklist\.yaml$/.test(file)) { a.href = "#checklist"; a.onclick = e => { e.preventDefault(); loadChecklist(); }; }
    else if (/^media\//.test(h)) { a.href = "/docs-media/" + h.slice(6); a.target = "_blank"; }
  });
  root.querySelectorAll("img[src^='media/']").forEach(i => i.src = "/docs-media/" + i.getAttribute("src").slice(6));
}
function renderDocsNav() {
  if (!state.docsList) return;
  $("#docsNav").innerHTML = `<h4>${esc(t("nav.docs"))}</h4>` + state.docsList.map(d => `<a data-f="${esc(d.file)}" class="${d.file === state.doc ? "on" : ""}" lang="en">${esc(d.title)}</a>`).join("");
  $$("#docsNav a").forEach(a => a.onclick = () => loadDocs(a.dataset.f));
}
async function loadDocs(file) {
  show("docs"); setAccent("#0f766e"); setHead("docs");
  state.docsList ||= await fetch("/api/docs").then(r => r.json());
  file ||= state.doc || state.docsList[0]?.file;
  state.doc = file; history.replaceState(null, "", "#docs/" + file); renderDocsNav();
  const body = $("#docBody");
  body.innerHTML = `<div class="doc-loading"><span class="spin"></span>${esc(t("docs.loading"))}</div>`;
  const md = (await fetch("/api/docs/" + encodeURIComponent(file)).then(r => r.json())).markdown || "";
  if (state.doc !== file) return;
  body.innerHTML = mdToHtml(md); fixDocLinks(body); $("#view-docs").scrollTop = 0;
  const diagrams = body.querySelectorAll("pre.mermaid");
  if (diagrams.length) {
    let m; try { m = await loadMermaid(); } catch (e) { console.error(e); return; }
    for (const [i, pre] of [...diagrams].entries()) {
      try {
        const { svg } = await m.render(`mm-${Date.now()}-${i}`, pre.textContent);
        if (state.doc !== file) return;
        pre.outerHTML = svg;
      } catch (e) { pre.closest(".mermaid-box").classList.add("err"); console.warn("mermaid", e); }
    }
    fitDiagrams(body);
  }
}

// readable size: shrink a wide diagram to the column, but never below 80% of its natural size (then scroll)
function fitDiagrams(root) {
  root.querySelectorAll(".mermaid-box svg").forEach(svg => {
    const vb = svg.viewBox.baseVal, natural = vb && vb.width ? vb.width : svg.getBBox().width;
    const avail = svg.closest(".mermaid-scroll").clientWidth - 36;
    const w = Math.max(Math.min(natural, avail), natural * 0.62);  // ≥ ~9px text; full screen shows 100%
    svg.style.width = w + "px"; svg.style.maxWidth = "none"; svg.removeAttribute("height");
  });
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-mm=full]"); if (b) {
    const svg = b.closest(".mermaid-box").querySelector("svg"); if (!svg) return;
    const ov = document.createElement("div"); ov.className = "mm-full";
    ov.innerHTML = `<button type="button" class="mm-close">✕ ${esc(t("docs.close"))}</button><div class="mm-full-in"></div>`;
    const c = svg.cloneNode(true); c.style.width = (svg.viewBox.baseVal.width || 1200) + "px";
    ov.querySelector(".mm-full-in").appendChild(c); document.body.appendChild(ov);
    ov.addEventListener("click", ev => { if (ev.target === ov || ev.target.closest(".mm-close")) ov.remove(); });
    return;
  }
});
window.addEventListener("resize", () => state.view === "docs" && fitDiagrams($("#docBody")));

// ---------- boot ----------
$$("[data-view]").forEach(a => a.onclick = e => { e.preventDefault(); a.dataset.view === "checklist" ? loadChecklist() : loadDocs(); });
$("#agents").addEventListener("click", e => { const a = e.target.closest("[data-agent]"); if (a) { e.preventDefault(); openAgent(a.dataset.agent); } });
function route() {
  const h = decodeURIComponent(location.hash.slice(1));
  if (h === "checklist") return loadChecklist();
  if (h.startsWith("docs")) return loadDocs(h.split("/")[1]);
  openAgent(h || state.domains[0].id);
}
window.addEventListener("hashchange", () => state.domains.length && route());
async function init() {
  S.load();
  state.domains = await fetch("/api/domains").then(r => r.json());
  applyLang();
  route();
  // ask the provider for the default model name once so the sidebar pill is accurate
  S.fetchModels();
}
init();
