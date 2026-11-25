"use strict";
/* Sorted-photo browsing: gallery modal, lightbox, day-by-day timeline, custom collage picker, tabs. */
const $$ = (s, r = document) => r.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const thumbUrl = it => `/api/library/${it.i}/thumb`;
const fileUrl = it => `/api/library/${it.i}/file`;
const NOT_SORTED = "Nothing is sorted on disk yet. Click “Start Sorting” (or “Apply Sort” in the preview) first.";

/* ------------------------------------------------------------------ data */
const Lib = {
  data: null,
  async load(force = true) {
    if (this.data && !force) return this.data;
    const r = await fetch("/api/library");
    const j = r.ok ? await r.json() : {empty: true};
    if (j.empty) { this.data = null; throw new Error(NOT_SORTED); }
    return (this.data = j);
  },
  clear() { this.data = null; },
};

/* ------------------------------------------------------------------ lightbox */
const Lightbox = (() => {
  let items = [], idx = 0;
  const root = () => $$("#lightbox");
  function open(list, i) { items = list; idx = i; root().hidden = false; render(); }
  function close() { root().hidden = true; $$("#lbStage").innerHTML = ""; }
  function render() {
    const it = items[idx], stage = $$("#lbStage");
    stage.innerHTML = it.kind === "video"
      ? `<video src="${fileUrl(it)}" controls autoplay></video>`
      : `<img src="${fileUrl(it)}" alt="${esc(it.name)}">`;
    $$("#lbName").textContent = it.name;
    $$("#lbMeta").textContent = `${idx + 1} / ${items.length} · ${it.category}${it.day ? " · " + it.day : ""}`;
    const multi = items.length > 1;
    $$("#lbPrev").style.visibility = $$("#lbNext").style.visibility = multi ? "visible" : "hidden";
    if (multi && items[(idx + 1) % items.length].kind === "image") new Image().src = fileUrl(items[(idx + 1) % items.length]);
  }
  const step = d => { idx = (idx + d + items.length) % items.length; render(); };
  function init() {
    $$("#lbPrev").onclick = () => step(-1);
    $$("#lbNext").onclick = () => step(1);
    $$("#lbClose").onclick = close;
    $$("#lbTab").onclick = () => window.open(fileUrl(items[idx]), "_blank", "noopener");
    $$("#lightbox").addEventListener("click", e => { if (e.target.id === "lbStage" || e.target.id === "lightbox") close(); });
  }
  return {open, close, step, init, isOpen: () => !root().hidden};
})();

/* ------------------------------------------------------------------ photo tiles */
function tile(it, sel) {
  const d = document.createElement("div");
  d.className = "ph" + (sel && sel.set.has(it.i) ? " on" : "");
  d.innerHTML = `<img loading="lazy" decoding="async" src="${thumbUrl(it)}" alt="${esc(it.name)}">` +
    (it.kind === "video" ? `<span class="vid">▶</span>` : "") +
    (sel && it.kind === "image" ? `<input type="checkbox" class="ck" aria-label="Select ${esc(it.name)}" ${sel.set.has(it.i) ? "checked" : ""}>` : "") +
    `<span class="ph-name">${esc(it.name)}</span>`;
  const ck = d.querySelector(".ck");
  if (ck) {
    ck.addEventListener("click", e => e.stopPropagation());
    ck.addEventListener("change", () => {
      if (ck.checked && sel.set.size >= 6) { ck.checked = false; return toast("You can pick up to 6 photos for a collage."); }
      ck.checked ? sel.set.add(it.i) : sel.set.delete(it.i);
      d.classList.toggle("on", ck.checked); sel.onChange();
    });
  }
  return d;
}

/* ------------------------------------------------------------------ collage bar + preview */
const LAYOUTS = [
  {k: "split", n: 2, t: "2-Photo Split"}, {k: "editorial", n: 3, t: "3-Photo Editorial"},
  {k: "polaroid", n: 4, t: "4-Photo Polaroid Grid"}, {k: "grid6", n: 6, t: "6-Photo Grid"},
];

function CollageBar(host, getSelected, clear) {
  const el = document.createElement("div");
  el.className = "cbar"; el.hidden = true;
  el.innerHTML = `<span class="cnt"></span>
    <div class="lay">${LAYOUTS.map(l => `<button type="button" class="lbtn" data-k="${l.k}">${l.t}</button>`).join("")}</div>
    <input class="ctitle" maxlength="80" placeholder="Custom title or caption (optional)">
    <button class="btn primary small create" type="button">Create Collage</button>
    <button class="btn ghost small clr" type="button">Clear</button>`;
  host.append(el);
  let layout = "polaroid", manual = false, busy = false;
  const need = () => LAYOUTS.find(l => l.k === layout).n;
  function update() {
    const n = getSelected().length;
    el.hidden = n === 0;
    if (!manual) { const m = LAYOUTS.find(l => l.n === n); if (m) layout = m.k; }
    el.querySelectorAll(".lbtn").forEach(b => b.classList.toggle("on", b.dataset.k === layout));
    const ok = n === need();
    el.querySelector(".cnt").innerHTML = `<b>${n} photo${n === 1 ? "" : "s"} selected</b>` +
      (ok ? "" : `<small>this layout needs ${need()}</small>`);
    el.querySelector(".create").disabled = !ok || busy;
  }
  el.querySelectorAll(".lbtn").forEach(b => b.onclick = () => { layout = b.dataset.k; manual = true; update(); });
  el.querySelector(".clr").onclick = () => { manual = false; clear(); };
  el.querySelector(".create").onclick = async () => {
    busy = true; update(); el.querySelector(".create").textContent = "Creating…";
    try { await Collage.create(getSelected(), layout, el.querySelector(".ctitle").value); }
    catch (e) { toast(e.message, 6000); }
    busy = false; el.querySelector(".create").textContent = "Create Collage"; update();
  };
  return {update, el};
}

const Collage = (() => {
  let current = null;
  async function create(ids, layout, title) {
    const r = await fetch("/api/collage/custom", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({items: ids, layout, title})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || "Couldn't create the collage");
    current = j;
    $$("#cpTitle").textContent = j.title;
    $$("#cpImg").src = j.url + "?t=" + Date.now();
    $$("#cpDownload").href = j.url + "?download=1";
    $$("#cpSave").disabled = false; $$("#cpSave").textContent = "Save to Travel Book";
    $$("#cpreview").hidden = false;
  }
  function init() {
    $$("#cpClose").onclick = () => $$("#cpreview").hidden = true;
    $$("#cpSave").onclick = async () => {
      if (!current) return;
      const b = $$("#cpSave"); b.disabled = true; b.textContent = "Saving…";
      try {
        const r = await fetch("/api/book/add-custom", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name: current.name})});
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || "Couldn't save");
        b.textContent = "Saved ✓"; toast(j.already ? "Already in your Travel Book." : `Added to your Travel Book (page ${j.page + 1}).`);
      } catch (e) { b.disabled = false; b.textContent = "Save to Travel Book"; toast(e.message, 6000); }
    };
  }
  return {create, init};
})();

/* ------------------------------------------------------------------ gallery modal (a category / folder) */
const Gallery = (() => {
  const sel = {set: new Set(), onChange: () => bar && bar.update()};
  let bar = null, items = [], folderReq = {};
  const selected = () => [...sel.set];
  function render() {
    const g = $$("#galGrid"); g.innerHTML = "";
    const frag = document.createDocumentFragment();
    items.forEach((it, k) => { const t = tile(it, sel); t.onclick = () => Lightbox.open(items, k); frag.append(t); });
    g.append(frag);
    bar.update();
  }
  function open({title, items: list, folder}) {
    items = list; folderReq = folder || {}; sel.set.clear();
    $$("#galTitle").textContent = title;
    $$("#galCount").textContent = `${list.length} item${list.length === 1 ? "" : "s"} · click a photo to view it full size, tick boxes to build a collage`;
    $$("#gallery").hidden = false; document.body.style.overflow = "hidden";
    render();
  }
  function close() { $$("#gallery").hidden = true; document.body.style.overflow = ""; sel.set.clear(); }
  async function openCategory(cat, title, fid) {
    if (app.running) return toast("Still sorting — you can browse the folders as soon as it finishes.");
    let lib;
    try { lib = await Lib.load(true); } catch (e) { return toast(e.message, 6000); }
    const list = lib.items.filter(it => it.category === cat);
    if (!list.length) return toast("Nothing in this folder yet.");
    open({title, items: list, folder: {category: cat}});
    if (fid != null) { const k = list.findIndex(it => it.fid === fid); if (k >= 0) Lightbox.open(list, k); }
  }
  async function openFolderOnDisk(req) {
    try {
      const r = await fetch("/api/open-folder", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(req)});
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || "Couldn't open the folder");
      toast("Opened: " + j.opened, 4000);
    } catch (e) { toast(e.message, 6000); }
  }
  function init() {
    bar = CollageBar($$("#galBarHost"), selected, () => { sel.set.clear(); render(); });
    $$("#galClose").onclick = close;
    $$("#galOpenFolder").onclick = () => openFolderOnDisk(folderReq);
    $$("#gallery").addEventListener("click", e => { if (e.target.id === "gallery") close(); });
  }
  return {init, open, close, openCategory, openFolderOnDisk, isOpen: () => !$$("#gallery").hidden};
})();

/* ------------------------------------------------------------------ day-by-day timeline (dashboard) */
const Timeline = (() => {
  const parse = d => { const m = /^Day (\d+) - (\d{4}-\d{2}-\d{2})$/.exec(d); return m ? {n: +m[1], date: m[2]} : {n: 9999, date: d}; };
  async function refresh() {
    const box = $$("#timelineView");
    let lib;
    try { lib = await Lib.load(true); } catch { box.hidden = true; return; }
    if (!lib.timeline) { box.hidden = true; return; }
    const days = new Map();
    lib.items.filter(it => it.day && it.category !== "Top Picks").forEach(it => {
      if (!days.has(it.day)) days.set(it.day, []);
      days.get(it.day).push(it);
    });
    if (!days.size) { box.hidden = true; return; }
    const order = [...days.keys()].sort((a, b) => parse(a).n - parse(b).n);
    $$("#tlSummary").textContent = `${order.length} day${order.length === 1 ? "" : "s"} · click a day to expand it`;
    const host = $$("#tlDays"); host.innerHTML = "";
    order.forEach((day, k) => {
      const list = days.get(day), p = parse(day), sec = document.createElement("div");
      sec.className = "tl-day" + (k === 0 ? " open" : "");
      sec.innerHTML = `<div class="tl-dh" role="button" tabindex="0"><span class="dn">Day ${p.n}</span><span class="dd">${esc(p.date)}</span>
        <span class="muted">${list.length} item${list.length === 1 ? "" : "s"}</span><span class="sp"></span>
        <button class="btn small ghost tl-folder" type="button">Open folder</button><span class="chev">▾</span></div>
        <div class="tl-body"><div class="pgrid sm"></div></div>`;
      let built = false;
      const build = () => {
        if (built) return; built = true;
        const grid = sec.querySelector(".pgrid"), shown = list.slice(0, 18);
        shown.forEach((it, i) => { const t = tile(it, null); t.onclick = () => Lightbox.open(list, i); grid.append(t); });
        if (list.length > shown.length) {
          const more = document.createElement("button");
          more.className = "btn small more"; more.textContent = `View all ${list.length}`;
          more.onclick = () => Gallery.open({title: `${day}`, items: list, folder: {day}});
          grid.append(more);
        }
      };
      const head = sec.querySelector(".tl-dh");
      const toggle = () => { sec.classList.toggle("open"); if (sec.classList.contains("open")) build(); };
      head.onclick = toggle;
      head.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
      sec.querySelector(".tl-folder").onclick = e => { e.stopPropagation(); Gallery.openFolderOnDisk({day}); };
      host.append(sec);
      if (k === 0) build();
    });
    box.hidden = false;
  }
  return {refresh, hide: () => { $$("#timelineView").hidden = true; }};
})();

/* ------------------------------------------------------------------ custom collage tab */
const CollageTab = (() => {
  const sel = {set: new Set(), onChange: () => bar && bar.update()};
  let bar = null, lib = null, shown = [], runId = null;
  const selected = () => [...sel.set];
  function draw() {
    const v = $$("#ccSource").value, g = $$("#ccGrid");
    const [kind, val] = v.split("|");
    const pool = lib.items.filter(it => it.kind === "image" && (kind === "all" ? !["Top Picks", "Needs Review"].includes(it.category)
      : kind === "cat" ? it.category === val : it.day === val));
    shown = pool; g.innerHTML = "";
    const frag = document.createDocumentFragment();
    pool.forEach((it, k) => { const t = tile(it, sel); t.onclick = () => Lightbox.open(pool, k); frag.append(t); });
    g.append(frag);
    $$("#ccEmpty").hidden = pool.length > 0;
    if (!pool.length) $$("#ccEmpty").textContent = "No photos in this folder.";
    bar.update();
  }
  async function show() {
    if (!bar) bar = CollageBar($$("#ccBarHost"), selected, () => { sel.set.clear(); draw(); });
    try { lib = await Lib.load(true); } catch {
      lib = null; $$("#ccGrid").innerHTML = ""; $$("#ccSource").innerHTML = "";
      $$("#ccEmpty").hidden = false; $$("#ccEmpty").textContent = NOT_SORTED; bar.update(); return;
    }
    const cats = [...new Set(lib.items.filter(i => i.kind === "image").map(i => i.category))];
    const days = lib.timeline ? [...new Set(lib.items.map(i => i.day).filter(Boolean))] : [];
    const prev = $$("#ccSource").value;
    $$("#ccSource").innerHTML = `<option value="all|">All sorted photos</option>` +
      `<optgroup label="Folders">${cats.map(c => `<option value="cat|${esc(c)}">${esc(c)}</option>`).join("")}</optgroup>` +
      (days.length ? `<optgroup label="Days">${days.map(d => `<option value="day|${esc(d)}">${esc(d)}</option>`).join("")}</optgroup>` : "");
    if ([...$$("#ccSource").options].some(o => o.value === prev)) $$("#ccSource").value = prev;
    if (runId !== lib.run_id) { sel.set.clear(); runId = lib.run_id; }   // indices belong to one sort run
    draw();
  }
  function init() { $$("#ccSource").onchange = () => lib && draw(); }
  return {show, init, hideBar: () => bar && (bar.el.hidden = true), update: () => bar && bar.update()};
})();

/* ------------------------------------------------------------------ tabs */
const Nav = (() => {
  let view = "dashboard";
  function mark(t) { document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === t)); }
  function go(t) {
    if (t === "book") { mark("book"); return Book.open(); }
    view = t; mark(t);
    $$("#viewDashboard").hidden = t !== "dashboard";
    $$("#viewCollage").hidden = t !== "collage";
    if (t === "collage") CollageTab.show(); else { CollageTab.hideBar(); Timeline.refresh(); }
    scrollTo(0, 0);
  }
  function init() {
    document.querySelectorAll(".tab").forEach(b => b.onclick = () => go(b.dataset.tab));
    window.onBookClosed = () => mark(view);
  }
  return {go, init};
})();

/* ------------------------------------------------------------------ cards on the dashboard */
const CARD_CATEGORY = {picks: "Top Picks", review: "Needs Review", videos: "Videos"};
function openCard(key, title, fid) { Gallery.openCategory(CARD_CATEGORY[key] || key, title, fid); }

document.addEventListener("keydown", e => {
  if (Lightbox.isOpen()) {
    e.stopPropagation();
    if (e.key === "ArrowRight") Lightbox.step(1); else if (e.key === "ArrowLeft") Lightbox.step(-1);
    else if (e.key === "Escape") Lightbox.close();
  } else if (!$$("#cpreview").hidden) { if (e.key === "Escape") $$("#cpreview").hidden = true; }
  else if (Gallery.isOpen() && e.key === "Escape") Gallery.close();
}, true);

function initLibraryUI() { Lightbox.init(); Gallery.init(); Collage.init(); CollageTab.init(); Nav.init(); }
