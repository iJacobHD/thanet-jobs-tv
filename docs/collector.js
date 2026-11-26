/* Thanet Jobs TV - collector.
   Runs inside Work Hub (jobs.service.gov.uk) from the "Collect Thanet jobs" bookmark.
   Reads the job search results near Margate, opens each Thanet advert and saves
   everything to one file for the board's updater. Read-only: it never changes anything on Work Hub. */
(async () => {
  if (window.__thanetCollecting) return;
  window.__thanetCollecting = true;
  const AUTO_DOWNLOAD = !window.__thanetNoDownload;
  const LOCATION = "Margate";               // search centre (10 miles covers all of Thanet)
  const MAX_PAGES = 40;
  const THANET = /Margate|Ramsgate|Broadstairs|Westgate|Birchington|Minster|Cliftonville|Westwood|Manston|St\.? Peter|Garlinge|Cliffsend|Monkton|Acol|St Nicholas|Thanet|\bCT(?:7|8|9|10|11|12)\b/i;

  // ---- progress box ----
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;z-index:2147483647;right:20px;bottom:20px;width:380px;background:#0c2340;color:#fff;" +
    "font:16px/1.4 Arial,sans-serif;padding:18px 20px;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.4)";
  box.innerHTML = '<b style="font-size:18px">Collecting Thanet jobs…</b><div id="tj-msg" style="margin-top:8px">Starting</div>' +
    '<div style="height:8px;background:rgba(255,255,255,.2);border-radius:9px;margin-top:10px"><i id="tj-bar" style="display:block;height:100%;width:0;background:#ffd400;border-radius:9px"></i></div>';
  document.body.appendChild(box);
  const msg = t => (box.querySelector("#tj-msg").textContent = t);
  const bar = p => (box.querySelector("#tj-bar").style.width = Math.round(p * 100) + "%");

  const P = new DOMParser();
  const get = async path => {
    for (let i = 0; i < 3; i++) {
      try { const r = await fetch(path, { credentials: "same-origin" }); if (r.ok) return await r.text(); } catch (e) {}
      await new Promise(r => setTimeout(r, 1500 * (i + 1)));
    }
    return null;
  };

  try {
    const dump = {}, want = [], seen = new Set();
    let total = null;
    // 1. search results
    for (let p = 1; p <= MAX_PAGES; p++) {
      const path = `/jobs/search?location=${LOCATION}&pageNumber=${p}`;
      const html = await get(path);
      if (!html) throw new Error("Could not load search page " + p);
      const d = P.parseFromString(html, "text/html");
      const cards = [...d.querySelectorAll('[data-testid^="searchResultCard-"]')];
      const counter = d.querySelector('[class*="counterDesktop"]');
      if (total === null) { const m = html.match(/of\s*<strong>\s*([\d,]+)\s*<\/strong>/); total = m ? +m[1].replace(/,/g, "") : null; }
      let fresh = 0;
      dump[path] = "<main>" + (counter ? counter.outerHTML : "") + cards.map(c => {
        const id = c.dataset.testid.split("-")[1];
        if (!seen.has(id)) {
          seen.add(id); fresh++;
          const loc = c.querySelector('[data-testid="searchResultCardEmployer"]');
          if (loc && THANET.test(loc.textContent)) want.push(id);
        }
        return `<div data-testid="${c.dataset.testid}"><a href="/jobs/${id}">x</a></div>`;
      }).join("") + "</main>";
      msg(`Reading search results: page ${p}${total ? " of " + Math.ceil(total / 10) : ""}`);
      bar(total ? Math.min(0.3, (p * 10 / total) * 0.3) : 0.1);
      if (!fresh || (total && seen.size >= total)) break;
    }

    // 2. each Thanet advert
    const strip = el => {
      el.querySelectorAll("svg,button,script,style").forEach(x => x.remove());
      el.querySelectorAll("*").forEach(x => [...x.attributes].forEach(a => { if (a.name !== "data-testid") x.removeAttribute(a.name); }));
      return el;
    };
    let done = 0;
    const one = async id => {
      const html = await get("/jobs/" + id);
      done++; msg(`Opening adverts: ${done} of ${want.length}`); bar(0.3 + 0.7 * done / want.length);
      if (!html) return;
      const d = P.parseFromString(html, "text/html");
      const m = d.querySelector("main") || d.body;
      const h = m.querySelector('[data-testid="pageHeading"]');
      const t = m.querySelector('[data-testid="jobSummaryTable"]');
      let s = "";
      for (const h2 of m.querySelectorAll("h2")) {
        const name = h2.textContent.trim();
        if (/related jobs/i.test(name)) break;
        const n = h2.nextElementSibling;
        if (!n) continue;
        const cls = n.classList.contains("rawHtmlContainer") ? "rawHtmlContainer" : "govuk-body";
        const txt = n.textContent.replace(/\s+/g, " ").slice(0, 6000).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
        s += `<h2>${name}</h2><div class="${cls}">${txt}</div>`;
      }
      dump["/jobs/" + id] = "<main>" + (h ? `<h1 data-testid="pageHeading">${h.textContent.replace(/[&<>]/g, "")}</h1>` : "") + (t ? strip(t).outerHTML : "") + s + "</main>";
    };
    // a few at a time, to be gentle on the site
    for (let i = 0; i < want.length; i += 4) await Promise.all(want.slice(i, i + 4).map(one));

    const out = JSON.stringify({ collected: new Date().toISOString(), searched: seen.size, thanet: want.length, pages: dump });
    window.__thanetDump = out;
    const name = `thanet-jobs-${new Date().toISOString().slice(0, 10)}.json`;
    if (AUTO_DOWNLOAD) {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([out], { type: "application/json" }));
      a.download = name; document.body.appendChild(a); a.click(); a.remove();
    }
    bar(1);
    box.innerHTML = `<b style="font-size:18px">✓ Done: ${want.length} Thanet adverts collected</b>
      <div style="margin-top:8px">Saved as <b>${name}</b> in your Downloads.<br>
      Next: <a href="https://github.com/iJacobHD/thanet-jobs-tv/upload/main/incoming" target="_blank" style="color:#ffd400;font-weight:bold">upload it here</a> and press <i>Commit changes</i>.
      The TV board and USB slides update about 5 minutes later.</div>
      <div style="margin-top:10px;text-align:right"><a href="#" style="color:#c3d1e3" onclick="this.closest('div').parentNode.remove();return false">close</a></div>`;
  } catch (e) {
    box.innerHTML = `<b>Something went wrong</b><div style="margin-top:8px">${String(e.message || e)}. Try again in a minute.</div>`;
  } finally {
    window.__thanetCollecting = false;
  }
})();
