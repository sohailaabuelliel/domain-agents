// Domain Agents UI — plain JS, no build step.
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const state = { domains: [], cur: null, history: {}, busy: false };
const SID = sessionStorage.getItem("sid") || (() => { const v = (crypto.randomUUID?.() || String(Math.random()).slice(2)); sessionStorage.setItem("sid", v); return v; })();
function renderMemory(prefs) {
  const el = $("#memory"); if (!el) return;
  el.innerHTML = prefs && prefs.length ? `<span class="mem-title">🧠 Remembered:</span> ` + prefs.map(p => `<span class="chip mem">${esc(p.label)}: ${esc(p.value)}</span>`).join("") + ` <button id="memclear" class="link">forget</button>` : "";
  $("#memclear")?.addEventListener("click", async () => { await fetch("/api/memory/" + SID, { method: "DELETE" }); renderMemory([]); });
}

// ---------- settings (key lives only in sessionStorage) ----------
const S = {
  get() { return JSON.parse(sessionStorage.getItem("llm") || '{"provider":"gemini"}'); },
  save() {
    const v = { provider: $("#provider").value, api_key: $("#apikey").value, model: $("#model").value, azure_endpoint: $("#endpoint").value };
    sessionStorage.setItem("llm", JSON.stringify(v)); S.dot();
  },
  load() { const v = S.get(); $("#provider").value = v.provider || "gemini"; $("#apikey").value = v.api_key || ""; $("#model").value = v.model || ""; $("#endpoint").value = v.azure_endpoint || ""; S.azure(); S.dot(); },
  azure() { $("#azureRow").classList.toggle("hidden", $("#provider").value !== "azure"); },
  dot() { $("#keyDot").className = "dot " + (S.get().api_key ? "on" : "off"); $("#keyDot").title = S.get().api_key ? "using your key" : "using the server's .env key (if any)"; },
};
$("#openSettings").onclick = () => $("#modal").classList.remove("hidden");
$("#closeSettings").onclick = () => { S.save(); $("#modal").classList.add("hidden"); };
$("#provider").onchange = () => { S.azure(); S.save(); };
["apikey", "model", "endpoint"].forEach(i => $("#" + i).oninput = S.save);
$("#testKey").onclick = async () => {
  S.save(); $("#testOut").textContent = "testing…";
  const r = await fetch("/api/test-key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(S.get()) }).then(r => r.json());
  $("#testOut").textContent = r.ok ? `✅ ${r.provider} · ${r.model}` : "❌ " + r.error;
};

// ---------- navigation ----------
function show(view) {
  document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
  $("#view-" + view).classList.remove("hidden");
  document.querySelectorAll(".nav").forEach(n => n.classList.remove("on"));
}
async function init() {
  S.load();
  state.domains = await fetch("/api/domains").then(r => r.json());
  $("#agents").innerHTML = state.domains.map(d => `<a class="nav" data-agent="${d.id}" style="--c:${d.accent}">${d.icon} ${esc(d.name)}<small>${d.documents} docs</small></a>`).join("");
  document.querySelectorAll("[data-agent]").forEach(a => a.onclick = () => openAgent(a.dataset.agent));
  document.querySelectorAll("[data-view]").forEach(a => a.onclick = () => { show(a.dataset.view); a.classList.add("on"); $("#head").innerHTML = `<h2>${a.textContent}</h2>`; document.documentElement.style.removeProperty("--c"); a.dataset.view === "checklist" ? loadChecklist() : loadDocs(); });
  openAgent(location.hash.slice(1) || state.domains[0].id);
}
function openAgent(id) {
  const d = state.domains.find(x => x.id === id) || state.domains[0]; state.cur = d; location.hash = d.id;
  show("chat"); document.querySelectorAll(".nav").forEach(n => n.classList.toggle("on", n.dataset.agent === d.id));
  document.body.style.setProperty("--c", d.accent);
  $("#head").innerHTML = `<h2>${d.icon} ${esc(d.name)}</h2><span class="tag">${d.documents} knowledge documents · tools: ${d.tools.join(", ")}</span>`;
  $("#info").innerHTML = `<b>${esc(d.use_case)}</b><ul>${d.tasks.map(t => `<li>${esc(t)}</li>`).join("")}</ul>
    <div class="muted" style="margin-top:6px">Refuses: ${d.blocked_intents.map(b => esc(b.id.replace(/_/g, " "))).join(" · ") || "—"} · “no evidence” below similarity ${d.min_score}</div>`;
  $("#examples").innerHTML = d.examples.map(e => `<span class="chip">${esc(e)}</span>`).join("");
  document.querySelectorAll(".chip").forEach(c => c.onclick = () => { $("#q").value = c.textContent; $("#q").focus(); });
  $("#msgs").innerHTML = ""; (state.history[d.id] || []).forEach(m => m.html && $("#msgs").insertAdjacentHTML("beforeend", m.html));
}

// ---------- chat ----------
const isAr = s => (s.match(/[\u0600-\u06FF]/g) || []).length > s.length * 0.3;
function traceLine(e) {
  if (e.type === "memory_learned") return `<div class="tl">🧠 <b>memory</b> learned: ${esc(e.items.join(" · "))}</div>`;
  const f = {
    guard_input: e => e.ok ? "✓ input guardrails passed" : `⛔ blocked by <b>${esc(e.rule)}</b>`,
    thought: e => `💭 ${esc(e.text).slice(0, 120)}`,
    action: e => `🔎 <b>${esc(e.tool)}</b> ${esc(JSON.stringify(e.args)).slice(0, 110)}`,
    observation: e => `📥 ${e.n_sources} sources collected so far`,
    coverage: e => `📏 best similarity ${e.best_similarity} vs threshold ${e.threshold}${e.unknown_terms?.length ? ` · unknown: ${esc(e.unknown_terms.join(", "))}` : ""} → ${e.covered ? "covered" : "<b>not covered</b>"}`,
    verify: e => `🧪 citation check #${e.attempt}: ${e.valid && !e.weak ? "ok" : "needs repair"} (grounding ${e.support})`,
    verify_pruned: e => `✂️ removed ${e.dropped} unverifiable statement(s)`,
    review: e => `🛡️ safety reviewer: ${e.approved ? "approved" : "flagged — " + esc((e.issues || []).join("; ")).slice(0, 120)}`,
    confidence: e => `📊 confidence ${e.score} (${e.level})`,
    error: e => `⚠️ ${esc(e.text)}`,
  }[e.type];
  return f ? `<div>${String(e.t).padStart(5)}s · ${f(e)}</div>` : "";
}
function cite(text, id) {
  return esc(text).replace(/\[(S\d+)\]/g, (_, s) => `<span class="cite" data-src="${id}-${s}">[${s}]</span>`);
}
function render(res, id, q) {
  const rtl = isAr(res.answer?.summary || res.message || q) ? "rtl" : "";
  let h = `<span class="status s-${res.status}">${{ answered: "Answered", refused: "Refused by guardrail", no_evidence: "No evidence found", error: "Error" }[res.status]}</span>`;
  if (res.status !== "answered") h += `<p class="${rtl}">${esc(res.message)}</p>`;
  else {
    const a = res.answer;
    h += `<div class="${rtl}"><div class="summary">${cite(a.summary, id)}</div>`;
    h += a.findings.map(f => `<div class="finding"><h4>${f.severity ? `<span class="sev ${f.severity}">${f.severity}</span>` : ""}${esc(f.title)}</h4>${cite(f.detail, id)}</div>`).join("");
    if (a.limitations) h += `<div class="lim"><b>Limitations:</b> ${esc(a.limitations)}</div>`;
    h += `</div>`;
  }
  const c = res.confidence;
  if (c && res.status === "answered") {
    const col = c.score >= .75 ? "var(--lo)" : c.score >= .5 ? "var(--mod)" : "var(--hi)";
    h += `<div class="conf"><div><b>Confidence ${Math.round(c.score * 100)}%</b> <span class="muted">${c.level}</span><div class="meter"><i style="width:${c.score * 100}%;background:${col}"></i></div></div>
      <div class="parts">${Object.entries(c.parts).map(([k, v]) => `<span>${k} ${v}</span>`).join("")}</div>
      ${res.review ? `<span class="rev ${res.review.approved ? "ok" : "bad"}">🛡️ reviewer ${res.review.approved ? "approved" : "flagged"}</span>` : ""}</div>`;
    if (c.reasons?.length) h += `<div class="muted">⚠ ${c.reasons.map(esc).join(" · ")}</div>`;
  }
  if (res.sources?.length) h += `<details><summary>${res.sources.length} source(s)</summary>${res.sources.map(s => `<div class="src" id="${id}-${s.id}"><b>[${s.id}]</b> ${esc(s.title)} › ${esc(s.section.slice(0, 80))} <span class="muted">· ${esc(s.doc_type)} · sim ${s.similarity}</span>${s.url ? ` <a href="${esc(s.url)}" target="_blank" rel="noopener">link</a>` : ""}<p>${esc(s.excerpt)}…</p></div>`).join("")}</details>`;
  if (res.status === "answered" && res.message) h += `<div class="disc">${esc(res.message)}</div>`;
  if (res.usage?.llm_calls) h += `<div class="muted" style="margin-top:6px">${res.elapsed}s · ${res.usage.llm_calls} model calls · ${res.usage.prompt_tokens + res.usage.output_tokens} tokens</div>`;
  return h;
}
$("#msgs").addEventListener("click", e => {
  const c = e.target.closest(".cite"); if (!c) return;
  const box = document.getElementById(c.dataset.src); if (!box) return;
  box.closest("details").open = true; box.scrollIntoView({ block: "center", behavior: "smooth" }); box.classList.add("flash"); setTimeout(() => box.classList.remove("flash"), 1600);
});
async function ask(question) {
  if (state.busy || !question.trim()) return; state.busy = true; $("#send").disabled = true;
  const d = state.cur, id = "m" + Date.now();
  const hist = state.history[d.id] ||= [];
  const userHtml = `<div class="msg user ${isAr(question) ? "rtl" : ""}">${esc(question)}</div>`;
  $("#msgs").insertAdjacentHTML("beforeend", userHtml + `<div class="msg bot" id="${id}"><div class="trace"></div></div>`);
  const box = document.getElementById(id), tr = box.querySelector(".trace"); box.scrollIntoView({ block: "end" });
  let result = null;
  try {
    const resp = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      domain: d.id, question, language: $("#lang").value, review: $("#review").checked, llm: S.get(), session_id: SID,
      history: hist.filter(m => m.role).map(m => ({ role: m.role, text: m.text })) }) });
    const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i; while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = /event: (\w+)/.exec(block)?.[1], data = JSON.parse(/data: (.*)/s.exec(block)?.[1] || "{}");
        if (ev === "trace") { tr.insertAdjacentHTML("beforeend", traceLine(data)); box.scrollIntoView({ block: "end" }); }
        if (ev === "result") { result = data; renderMemory(data.memory); }
        if (ev === "fatal") { result = { status: "error", message: data.message, sources: [], confidence: null }; if (data.code === "missing_key") $("#modal").classList.remove("hidden"); }
      }
    }
  } catch (err) { result = { status: "error", message: String(err), sources: [] }; }
  const body = render(result, id, question);
  box.innerHTML = body + `<details><summary>agent trace</summary><div class="trace">${tr.innerHTML}</div></details>`;
  hist.push({ role: "user", text: question, html: userHtml });
  hist.push({ role: "assistant", text: result.answer?.summary || result.message || "", html: `<div class="msg bot" id="${id}">${box.innerHTML}</div>` });
  state.busy = false; $("#send").disabled = false; $("#q").focus();
}
$("#form").onsubmit = e => { e.preventDefault(); const q = $("#q").value; $("#q").value = ""; ask(q); };
$("#q").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#form").requestSubmit(); } };

// ---------- checklist ----------
async function loadChecklist() {
  const c = await fetch("/api/checklist").then(r => r.json());
  const all = c.groups.flatMap(g => g.items), done = all.filter(i => i.status === "done").length, part = all.filter(i => i.status === "partial").length;
  $("#checklist").innerHTML = `<div class="prog"><b>${done}/${all.length} done</b> · ${part} partial · ${all.length - done - part} to do<div class="bar"><i style="width:${(done + part / 2) / all.length * 100}%"></i></div></div>` +
    c.groups.map(g => `<div class="grp"><h3>${esc(g.title)}</h3>${g.items.map(i => `<div class="it"><span class="badge b-${i.status}">${i.status}</span><div>${esc(i.text)}<div class="muted"><code>${esc(i.where)}</code> ${i.doc ? `· <a data-doc="${esc(i.doc.split("/").pop())}">${esc(i.doc)}</a>` : ""}</div></div></div>`).join("")}</div>`).join("");
  document.querySelectorAll("[data-doc]").forEach(a => a.onclick = () => { show("docs"); loadDocs(a.dataset.doc); });
}

// ---------- docs ----------
function md(src) {
  const blocks = []; src = src.replace(/```(\w*)\n([\s\S]*?)```/g, (_, l, c) => (blocks.push(`<pre><code>${esc(c)}</code></pre>`), `\u0000${blocks.length - 1}\u0000`));
  const inline = t => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const lines = src.split("\n"), out = []; let list = false, tbl = [];
  const flush = () => { if (list) { out.push("</ul>"); list = false; } if (tbl.length) { const rows = tbl.filter(r => !/^\|[\s:|-]+\|$/.test(r)).map(r => r.slice(1, -1).split("|").map(x => inline(x.trim()))); out.push("<table>" + rows.map((r, i) => `<tr>${r.map(c => `<${i ? "td" : "th"}>${c}</${i ? "td" : "th"}>`).join("")}</tr>`).join("") + "</table>"); tbl = []; } };
  for (const l of lines) {
    let m;
    if (/^\|.*\|$/.test(l)) { if (list) flush(); tbl.push(l); continue; } else if (tbl.length) flush();
    if ((m = /^(#{1,3}) (.*)/.exec(l))) { flush(); out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); }
    else if ((m = /^\s*[-*] (.*)/.exec(l))) { if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${inline(m[1])}</li>`); }
    else if (/^\u0000\d+\u0000$/.test(l.trim())) { flush(); out.push(l.trim()); }
    else if (!l.trim()) flush(); else { flush(); out.push(`<p>${inline(l)}</p>`); }
  }
  flush(); return out.join("\n").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[i]);
}
async function loadDocs(file) {
  const list = await fetch("/api/docs").then(r => r.json());
  file ||= list[0]?.file;
  $("#docsNav").innerHTML = list.map(d => `<a data-f="${d.file}" class="${d.file === file ? "on" : ""}">${esc(d.title)}</a>`).join("");
  document.querySelectorAll("#docsNav a").forEach(a => a.onclick = () => loadDocs(a.dataset.f));
  if (file) $("#docBody").innerHTML = md((await fetch("/api/docs/" + file).then(r => r.json())).markdown);
}
init();
