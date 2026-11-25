"use strict";
const $ = (s, r = document) => r.querySelector(s);
const ICONS = {"Selfies":"🤳","People & Family":"👨‍👩‍👧","Food & Drinks":"🍜","Travel & Nature":"🏔️","Night Out":"🌙","Receipts & Tickets":"🧾"};
const SPECIALS = [
  {key: "picks", title: "Top Picks / Hero Shots", icon: "⭐", cls: "hero"},
  {key: "review", title: "Needs Review (Blurry & Duplicates)", icon: "🔍"},
  {key: "videos", title: "Videos", icon: "🎬"},
];
const MAX_THUMBS = 12;

const app = {
  info: null, job: null, awaitingStart: false, running: false,
  queue: [], pumping: false, tick: 0, flying: 0, total: 0, remaining: 0,
  stats: {checked: 0, sorted: 0, review: 0, receipts: 0, picks: 0, saved: 0},
  cards: {}, // key -> {el, grid, n, count}
};

/* ------------------------------------------------------------------ utils */
function toast(msg, ms = 3500) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, ms);
}
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ------------------------------------------------------------------ counters */
function setStat(key, value) {
  const el = $(`[data-stat="${key}"]`), dec = el.dataset.dec ? 1 : 0;
  const from = parseFloat(el.dataset.v || "0"); el.dataset.v = value;
  const t0 = performance.now();
  cancelAnimationFrame(el._raf);
  (function step(now) {
    const p = Math.min(1, (now - t0) / 450), e = 1 - Math.pow(1 - p, 3);
    el.textContent = (from + (value - from) * e).toLocaleString(undefined, {minimumFractionDigits: dec, maximumFractionDigits: dec});
    if (p < 1) el._raf = requestAnimationFrame(step);
  })(t0);
}
function bump(key, by = 1) {
  app.stats[key] += by;
  setStat(key, key === "saved" ? app.stats.saved / 1048576 : app.stats[key]);
}
function resetStats() { for (const k in app.stats) { app.stats[k] = 0; setStat(k, 0); } }

/* ------------------------------------------------------------------ cards */
function makeCard(key, title, icon, extra = "") {
  const el = document.createElement("div");
  el.className = `cat ${extra}`;
  el.innerHTML = `<div class="cat-head"><span><span class="ico">${icon}</span>${title}</span><span class="n">0</span></div><div class="grid"></div>`;
  el.tabIndex = 0; el.title = "Click to open this folder";
  el.onclick = () => openCard(key, title);
  el.onkeydown = e => { if (e.key === "Enter") openCard(key, title); };
  app.cards[key] = {el, key, title, grid: $(".grid", el), n: 0, count: $(".n", el)};
  return el;
}
function buildCards(categories) {
  app.cards = {};
  const list = $("#catList"); list.innerHTML = "";
  categories.forEach(c => list.append(makeCard(c, c, ICONS[c] || "✨")));
  const sp = $("#specialList"); sp.innerHTML = "";
  SPECIALS.forEach(s => sp.append(makeCard(s.key, s.title, s.icon, `special ${s.cls || ""}`)));
}
function clearCards() {
  for (const c of Object.values(app.cards)) { c.n = 0; c.count.textContent = 0; c.grid.innerHTML = ""; }
}

/* ------------------------------------------------------------------ swirl cluster */
function buildSwirl(ids) {
  const sw = $("#swirl"); sw.innerHTML = "";
  sw.classList.remove("fast");
  const rings = [{r: 78, n: 6, dur: 40, dir: "normal"}, {r: 128, n: 10, dur: 55, dir: "reverse"},
                 {r: 178, n: 14, dur: 70, dir: "normal"}, {r: 214, n: 18, dur: 90, dir: "reverse"}];
  let i = 0;
  for (const rg of rings) {
    const ring = document.createElement("div");
    ring.className = "ring"; ring.style.setProperty("--dur", rg.dur + "s"); ring.style.setProperty("--dir", rg.dir);
    for (let k = 0; k < rg.n && i < ids.length; k++, i++) {
      const a = (360 / rg.n) * k, img = document.createElement("img");
      img.className = "sw"; img.decoding = "async"; img.src = `/api/thumb/${ids[i]}`; img.dataset.id = ids[i]; img.alt = "";
      const t = `rotate(${a}deg) translateX(${rg.r}px) rotate(${-a}deg)`;
      img.style.setProperty("--t", t); img.style.transform = t;
      img.style.setProperty("--dur", rg.dur + "s"); img.style.setProperty("--dir", rg.dir);
      ring.append(img);
    }
    sw.append(ring);
  }
  const core = document.createElement("div");
  core.className = "core"; core.id = "core"; sw.append(core);
  updateCore();
}
function updateCore(text) {
  const c = $("#core"); if (!c) return;
  c.innerHTML = text || (app.info && app.info.total ? `${app.remaining}<small>to sort</small>` : "📷");
}

/* ------------------------------------------------------------------ flying thumbnails */
function slotRect(card) {
  const g = card.grid.getBoundingClientRect(), idx = Math.min(card.n, MAX_THUMBS - 1);
  const cols = parseInt(getComputedStyle(card.grid).gridTemplateColumns.split(" ").length) || 6;
  const w = (g.width - 4 * (cols - 1)) / cols;
  return {x: g.left + (idx % cols) * (w + 4), y: g.top + Math.floor(idx / cols) * (w + 4), w};
}
function land(card, id) {
  card.n++; card.count.textContent = card.n;
  card.el.classList.add("pulse"); setTimeout(() => card.el.classList.remove("pulse"), 350);
  if (card.n <= MAX_THUMBS) {
    const img = new Image(); img.decoding = "async"; img.src = `/api/thumb/${id}`; img.alt = "";
    img.onclick = e => { e.stopPropagation(); openCard(card.key, card.title, id); };
    card.grid.append(img);
  }
}
function fly(id, key, {fast = false} = {}) {
  const card = app.cards[key];
  if (!card) return;
  const src = $(`.sw[data-id="${id}"]`);
  const stage = $("#swirl").getBoundingClientRect();
  const from = src ? src.getBoundingClientRect()
    : {left: stage.left + stage.width / 2 - 27 + (Math.random() - .5) * 60, top: stage.top + stage.height / 2 - 27 + (Math.random() - .5) * 60, width: 54};
  if (src) src.remove();
  if (fast && (app.tick % 12 || app.flying > 25)) return land(card, id);
  const to = slotRect(card);
  const f = new Image(); f.src = `/api/thumb/${id}`; f.className = "flyer";
  Object.assign(f.style, {left: from.left + "px", top: from.top + "px", width: from.width + "px", height: from.width + "px"});
  document.body.append(f); app.flying++;
  const dx = to.x - from.left, dy = to.y - from.top, s = to.w / from.width;
  f.animate([
    {transform: "translate(0,0) scale(1) rotate(0)", opacity: 1},
    {transform: `translate(${dx * .5}px,${dy * .5 - 60}px) scale(1.25) rotate(${(Math.random() - .5) * 40}deg)`, opacity: 1, offset: .45},
    {transform: `translate(${dx}px,${dy}px) scale(${s}) rotate(0)`, opacity: .95},
  ], {duration: 750, easing: "cubic-bezier(.4,.1,.2,1)", fill: "forwards"}).onfinish = () => { f.remove(); app.flying--; land(card, id); };
}

/* ------------------------------------------------------------------ event queue */
function enqueue(ev) { app.queue.push(ev); if (!app.pumping) pump(); }
async function pump() {
  app.pumping = true;
  while (app.queue.length) {
    const ev = app.queue.shift();
    const fast = app.queue.length > 60;
    $("#swirl").classList.toggle("fast", app.running);
    handle(ev, fast);
    await sleep(fast ? 1 : ev.type === "file" || ev.type === "pick" ? 85 : 0);
    if (fast && ++app.tick % 25 === 0) await sleep(0);   // let the browser paint during big folders
  }
  app.pumping = false;
}
function handle(ev, fast) {
  if (ev.type === "start") {
    if (!app.awaitingStart) return;
    app.awaitingStart = false; app.job = ev.job; app.total = ev.total; app.remaining = ev.total;
    buildCards(ev.categories); updateCore();
    $("#stageLabel").textContent = ev.dry ? "Previewing — nothing will be moved…" : "Sorting your photos…";
    return;
  }
  if (ev.type.startsWith("book_")) return Book.onEvent(ev);
  if (ev.job !== app.job) return;
  if (ev.type === "status") {
    $("#stageLabel").textContent = ev.message;
  } else if (ev.type === "file") {
    bump("checked"); app.remaining--; updateCore();
    $("#progressBar").style.width = (app.stats.checked / app.total * 100) + "%";
    let key;
    if (ev.kind === "video") key = "videos";
    else if (ev.bucket === "Needs Review") { key = "review"; bump("review"); bump("saved", ev.size); }
    else { key = ev.category; bump("sorted"); if (key === "Receipts & Tickets") bump("receipts"); }
    fly(ev.id, key, {fast});
  } else if (ev.type === "pick") {
    bump("picks"); fly(ev.id, "picks", {fast});
  } else if (ev.type === "done") {
    finish(ev);
  } else if (ev.type === "error") {
    app.running = false; refreshButtons(); toast("Something went wrong: " + ev.message, 8000);
  }
}
async function finish(ev) {
  await sleep(900);
  app.running = false; $("#swirl").classList.remove("fast");
  $("#progressBar").style.width = "100%"; updateCore("✓");
  $("#stageLabel").textContent = ev.dry ? "Preview complete — no files were touched." : "Done!";
  const s = app.stats;
  if (ev.dry) {
    $("#modalSub").textContent = `${ev.total} files analysed in ${ev.seconds}s. Nothing has been copied or moved yet — files will be ${$("#optCopy").checked ? "copied" : "moved"} into "Sorted_Trip_Studio" inside your folder.`;
    $("#planList").innerHTML = ev.plan.map(([f, n]) => `<div class="row"><span>${f.replace(/[&<>]/g, "")}</span><b>${n}</b></div>`).join("");
    $("#modal").hidden = false;
    try { app.info = await api("/api/state"); } catch {}
    refreshButtons();
    return;
  }
  $("#sumTitle").textContent = ev.dry ? "Preview ready" : "All sorted!";
  $("#sumText").textContent = `${s.checked} files checked in ${ev.seconds}s · ${s.sorted} photos sorted · ${s.review} need review · ${ev.videos} videos · ${s.picks} top picks · ${(s.saved / 1048576).toFixed(1)} MB flagged.` +
    (ev.copy ? " Your originals were left untouched." : " Files were moved — Undo puts them back.") + " Saved to Sorted_Trip_Studio.";
  $("#summary").hidden = false;
  confetti();
  try { app.info = await api("/api/state"); } catch {}
  refreshButtons();
  Lib.clear(); Timeline.refresh();
}

/* ------------------------------------------------------------------ confetti */
function confetti() {
  const cv = $("#confetti"), ctx = cv.getContext("2d");
  cv.width = innerWidth; cv.height = innerHeight;
  const stage = $("#stage").getBoundingClientRect();
  const colors = ["#E0703A", "#F2B544", "#2E9E5B", "#4F8FD9", "#D9577E", "#8B6FD6"];
  const ps = Array.from({length: 160}, () => {
    const a = Math.random() * Math.PI * 2, v = 6 + Math.random() * 12;
    return {x: stage.left + stage.width / 2, y: stage.top + stage.height / 2, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 5,
            w: 6 + Math.random() * 6, h: 4 + Math.random() * 6, r: Math.random() * 6, vr: (Math.random() - .5) * .4,
            c: colors[Math.random() * colors.length | 0], life: 1};
  });
  (function frame() {
    ctx.clearRect(0, 0, cv.width, cv.height);
    let alive = false;
    for (const p of ps) {
      p.vy += .35; p.vx *= .99; p.x += p.vx; p.y += p.vy; p.r += p.vr; p.life -= .006;
      if (p.life <= 0 || p.y > cv.height + 20) continue;
      alive = true; ctx.save(); ctx.globalAlpha = Math.min(1, p.life * 2);
      ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.c; ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); ctx.restore();
    }
    if (alive) requestAnimationFrame(frame); else ctx.clearRect(0, 0, cv.width, cv.height);
  })();
}

/* ------------------------------------------------------------------ folder / buttons */
function refreshButtons() {
  const has = app.info && app.info.folder && app.info.total > 0;
  $("#btnSelect").disabled = app.running;
  $("#btnDry").disabled = $("#btnStart").disabled = !has || app.running;
  $("#btnUndo").disabled = !(app.info && app.info.can_undo) || app.running;
  $("#btnBookTop").disabled = $("#btnUndo").disabled;
}
function applyFolder(info) {
  app.info = info; app.remaining = info.total;
  $("#folderName").textContent = info.name || "…";
  $("#folderMeta").textContent = info.folder
    ? `${info.images.toLocaleString()} photos · ${info.videos.toLocaleString()} videos found${info.total ? "" : " — nothing to sort here"}`
    : "Choose a folder of photos to begin.";
  $("#stageLabel").textContent = info.total ? "Ready — preview first, or start sorting" : "Pick a folder to see your photos swirl here";
  $("#summary").hidden = true; $("#progressBar").style.width = "0";
  resetStats(); buildCards(app.info.categories || app.baseCats); buildSwirl(info.ids || []);
  refreshButtons(); Lib.clear(); Timeline.refresh();
}
async function selectFolder(path) {
  try {
    const r = await api("/api/select-folder", path ? {path} : {});
    if (r.cancelled) return;
    if (r.dialog_failed) {
      const p = prompt("The folder picker isn't available here. Paste the full folder path:");
      return p ? selectFolder(p) : null;
    }
    applyFolder(r);
  } catch (e) { toast(e.message, 6000); }
}
async function startSort(dry) {
  if (app.running) return;
  try {
    app.running = true; app.awaitingStart = true; app.queue = [];
    resetStats(); clearCards(); $("#summary").hidden = true; $("#progressBar").style.width = "0";
    buildSwirl(app.info.ids);
    refreshButtons();
    await api("/api/sort", {dry, timeline: $("#optTimeline").checked, timeline_mode: $("#optTimeline").checked, custom: $("#optCustom").value, copy: $("#optCopy").checked, filter: $("#optFilter").checked});
  } catch (e) {
    app.running = false; app.awaitingStart = false; refreshButtons(); toast(e.message, 6000);
  }
}
async function undo() {
  if (!confirm("Move all sorted files back to where they were?")) return;
  try {
    const r = await api("/api/undo", {});
    toast(`Restored ${r.restored} files.`);
    applyFolder(r);
  } catch (e) { toast(e.message, 6000); }
}

/* ------------------------------------------------------------------ init */
async function init() {
  $("#btnSelect").onclick = () => selectFolder();
  $("#folderName").onclick = () => { if (!app.running) { const p = prompt("Type or paste a folder path:"); if (p) selectFolder(p); } };
  $("#btnDry").onclick = () => startSort(true);
  $("#btnStart").onclick = () => startSort(false);
  $("#btnUndo").onclick = undo;
  $("#btnModalCancel").onclick = () => $("#modal").hidden = true;
  $("#btnApply").onclick = () => { $("#modal").hidden = true; startSort(false); };
  $("#btnSumClose").onclick = () => $("#summary").hidden = true;
  $("#btnBook").onclick = () => { $("#summary").hidden = true; Book.open(); };
  $("#btnBookTop").onclick = () => Book.open();
  Book.init(); initLibraryUI();

  const st = await api("/api/state");
  app.baseCats = st.categories;
  applyFolder(st.folder ? st : {...st, name: null, folder: null});
  const es = new EventSource(`/api/stream?after=${st.last_event}`);
  es.onmessage = m => enqueue(JSON.parse(m.data));
}
init().catch(e => toast("Could not reach the local server: " + e.message, 8000));
