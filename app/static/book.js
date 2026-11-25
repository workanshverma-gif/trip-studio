"use strict";
/* Interactive Travel Book: StPageFlip viewer + live search over per-page tags. */
const Book = (() => {
  const q = s => document.querySelector(s);
  let data = null, pf = null, matches = [], cur = -1, resizeT, searchT;

  function open() {
    q("#book").hidden = false; document.body.style.overflow = "hidden";
    showBuilding("Designing your collages…", 0);
    fetch("/api/book/build", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"})
      .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.statusText); return j; })
      .then(j => { if (j.ready) load(); })
      .catch(e => { close(); toast(e.message, 6000); });
  }
  // StPageFlip.destroy() removes its container from the DOM, so always recreate #flip afterwards.
  function destroyFlip() {
    if (pf) { try { pf.destroy(); } catch {} pf = null; }
    let host = q("#flip");
    if (!host) {
      host = document.createElement("div"); host.id = "flip";
      q(".book-stage").insertBefore(host, q("#bookBuilding"));
    }
    host.innerHTML = "";
    return host;
  }
  function close() {
    destroyFlip();
    q("#book").hidden = true; document.body.style.overflow = "";
    if (window.onBookClosed) window.onBookClosed();
  }
  function showBuilding(msg, pct) {
    q("#bookBuilding").hidden = false; q("#buildMsg").textContent = msg; q("#buildBar").value = pct;
  }
  function onEvent(ev) {
    if (q("#book").hidden) return;
    if (ev.type === "book_progress") showBuilding(`Designing page ${ev.done} of ${ev.total}…`, ev.done / ev.total * 100);
    else if (ev.type === "book_done") load();
    else if (ev.type === "book_error") { close(); toast("Couldn't build the book: " + ev.message, 8000); }
  }

  async function load() {
    try { data = await (await fetch("/api/book")).json(); } catch { return toast("Couldn't load the book"); }
    q("#bookTitle").textContent = data.title; q("#bookRange").textContent = `${data.date_range} · ${data.stats}`;
    q("#bookBuilding").hidden = true;
    render(0);
  }

  function sizes() {
    const vw = innerWidth, vh = innerHeight;
    let h = Math.max(320, vh - 210), w = h * 1080 / 1920;
    if (vw < 760) { w = Math.min(vw - 32, (vh - 210) * 1080 / 1920); h = w * 1920 / 1080; }
    else if (w * 2 > vw - 60) { w = (vw - 60) / 2; h = w * 1920 / 1080; }
    return {w: Math.floor(w), h: Math.floor(h)};
  }

  function render(startPage) {
    const host = destroyFlip();
    const last = data.pages.length - 1, {w, h} = sizes();
    data.pages.forEach((p, i) => {
      const d = document.createElement("div");
      d.className = "pg"; d.dataset.density = (i === 0 || i === last) ? "hard" : "soft";
      d.innerHTML = `<img src="/api/book/page/${i}" alt="${p.title}" draggable="false"><button class="dl" type="button">⬇ Download This Collage</button>`;
      const b = d.querySelector(".dl");
      ["mousedown", "touchstart", "pointerdown", "mouseup", "touchend"].forEach(t => b.addEventListener(t, e => e.stopPropagation()));
      b.addEventListener("click", e => {
        e.stopPropagation();
        const a = document.createElement("a"); a.href = `/api/book/page/${i}?download=1`; a.download = ""; document.body.append(a); a.click(); a.remove();
      });
      host.append(d);
    });
    pf = new St.PageFlip(host, {width: w, height: h, size: "fixed", showCover: true, maxShadowOpacity: .45, flippingTime: 750,
      usePortrait: true, startPage, mobileScrollSupport: false, swipeDistance: 25, showPageCorners: true, autoSize: false});
    pf.loadFromHTML(host.querySelectorAll(".pg"));
    pf.on("flip", updateInfo);
    updateInfo();
    runSearch(false);
  }
  function updateInfo() {
    if (!pf) return;
    const i = pf.getCurrentPageIndex(), n = data.pages.length;
    q("#pageInfo").textContent = i === 0 ? `Cover · ${n} pages` : `Page ${i + 1} of ${n}`;
  }

  /* ---- search: phrase-start match at word boundary ("day 2" must not hit "day 21") */
  function matcher(text) {
    const t = text.trim().toLowerCase();
    if (!t) return null;
    const re = new RegExp("(^|[^a-z0-9])" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + (/\d$/.test(t) ? "($|[^0-9])" : ""));
    return page => page.search.some(s => re.test(s));
  }
  function runSearch(jump = true) {
    const m = matcher(q("#bookSearch").value), chips = q("#matchChips"), info = q("#searchInfo");
    matches = []; cur = -1; chips.innerHTML = "";
    if (!m) { info.textContent = ""; return; }
    data.pages.forEach((p, i) => { if (p.kind === "collage" && m(p)) matches.push(i); });
    info.textContent = matches.length ? `${matches.length} page${matches.length > 1 ? "s" : ""}` : "No matches";
    matches.forEach(i => {
      const b = document.createElement("button"); b.className = "chip";
      b.textContent = `p.${i + 1} · ${data.pages[i].title}`; b.onclick = () => goto(i); chips.append(b);
    });
    if (matches.length && jump) goto(matches[0]);
  }
  function goto(i) { cur = matches.indexOf(i); if (pf) pf.flip(i); }
  function nextMatch() {
    if (!matches.length) return;
    cur = (cur + 1) % matches.length; pf.flip(matches[cur]);
  }

  function init() {
    q("#btnBookClose").onclick = close;
    q("#bookPrev").onclick = () => pf && pf.flipPrev();
    q("#bookNext").onclick = () => pf && pf.flipNext();
    q("#btnPdf").onclick = () => toast("Preparing your PDF… it will download in a few seconds.", 5000);
    const s = q("#bookSearch");
    s.addEventListener("input", () => { clearTimeout(searchT); searchT = setTimeout(runSearch, 220); });
    s.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); nextMatch(); } if (e.key === "Escape") { s.value = ""; runSearch(false); s.blur(); e.stopPropagation(); } });
    document.addEventListener("keydown", e => {
      if (q("#book").hidden || !pf || document.activeElement === s) return;
      if (e.key === "ArrowRight") pf.flipNext();
      else if (e.key === "ArrowLeft") pf.flipPrev();
      else if (e.key === "Escape") close();
      else if (e.key === "/") { e.preventDefault(); s.focus(); }
    });
    addEventListener("resize", () => {
      clearTimeout(resizeT);
      resizeT = setTimeout(() => { if (pf && data && !q("#book").hidden) render(pf.getCurrentPageIndex()); }, 300);
    });
  }
  return {open, onEvent, init};
})();
