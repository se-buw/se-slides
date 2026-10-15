// "Open in VS Code" buttons and QR codes.
(function () {
  const KEY = "course.vscodeRoot";

  function storedRoot() {
    try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; }
  }

  function defaultRoot() {
    const m = document.querySelector('meta[name="course-vscode-root"]');
    return m ? m.content : "";
  }

  function root() {
    return storedRoot() || defaultRoot();
  }

  function askRoot() {
    const r = window.prompt(
      "Local folder of the course repository (e.g. C:/Users/you/course).\n" +
      "It is stored in this browser only.", root());
    if (r === null) return false;
    const clean = r.trim().replace(/\\/g, "/").replace(/\/+$/, "");
    try { localStorage.setItem(KEY, clean); } catch (e) { /* private mode */ }
    return clean !== "";
  }

  function vscodeUrl(file, line) {
    const r = root();
    const path = (r.startsWith("/") ? "" : "/") + r + "/" + file;
    return "vscode://file" + encodeURI(path) + ":" + line;
  }

  document.addEventListener("click", function (e) {
    const open = e.target.closest(".vscode-open");
    if (open) {
      e.preventDefault();
      if (!root() && !askRoot()) return;
      window.location.href = vscodeUrl(open.dataset.file, open.dataset.line);
      return;
    }
    if (e.target.closest(".vscode-root")) {
      e.preventDefault();
      askRoot();
    }
  });

  function renderQr() {
    if (typeof QRCode === "undefined") return;
    document.querySelectorAll(".qr[data-url]").forEach(function (el) {
      if (el.dataset.done) return;
      el.dataset.done = "1";
      const size = parseInt(el.dataset.size || "220", 10);
      new QRCode(el, { text: el.dataset.url, width: size, height: size, correctLevel: QRCode.CorrectLevel.M });
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderQr);
  } else {
    renderQr();
  }

  // Layout check: content must stay above the footer, listings must not be clipped.
  // The check always runs in the print view (the build's layout report reads it); outlines and
  // labels are drawn only in decks built with -ShowLayout (meta course-layout-marks).
  const FOOTER_SPACE = 44; // px of the 720 px slide height reserved for footer/slide number

  function marksOn() {
    return !!document.querySelector('meta[name="course-layout-marks"]');
  }

  function mark(el, section, text) {
    el.classList.add("course-overflow");
    if (!section.querySelector(".course-overflow-label")) {
      const label = document.createElement("div");
      label.className = "course-overflow-label";
      label.textContent = text;
      section.appendChild(label);
    }
  }

  // Returns the problems of one slide as texts; draws them if draw is true.
  function checkSlide(section, draw) {
    const problems = [];
    if (!section || section.classList.contains("stack")) return problems;
    function found(el, text) {
      if (problems.indexOf(text) < 0) problems.push(text);
      if (draw) mark(el, section, text);
    }
    const deck = window.Reveal;
    const height = deck.getConfig().height;
    const scale = deck.getScale ? deck.getScale() : 1;
    const top = section.getBoundingClientRect().top;
    let bottom = 0;
    section.querySelectorAll("h1, h2, p, li, pre, table, img, svg, .listing, .columns, .callout, .tip, .pitfall, .java25")
      .forEach(function (el) {
        if (el.closest(".notes, aside")) return;
        const r = el.getBoundingClientRect();
        if (r.height > 0) bottom = Math.max(bottom, (r.bottom - top) / scale);
      });
    if (bottom > height - FOOTER_SPACE) found(section, "content too long (" + Math.round(bottom) + " px)");
    // Quarto scrolls div.sourceCode, plain blocks scroll the pre: check every level
    section.querySelectorAll("div.sourceCode, pre, pre > code").forEach(function (el) {
      const box = el.closest("div.sourceCode") || el;
      if (el.scrollWidth > el.clientWidth + 2) found(box, "code line too wide");
      if (el.scrollHeight > el.clientHeight + 2) found(box, "listing clipped");
    });
    if (draw && problems.length) {
      console.warn("[course] " + problems.join(", ") + ": " + (section.querySelector("h2, h1") || {}).textContent);
    }
    return problems;
  }

  function whenReveal(fn) {
    if (window.Reveal && window.Reveal.isReady && window.Reveal.isReady()) fn();
    else if (window.Reveal && window.Reveal.on) window.Reveal.on("ready", fn);
    else setTimeout(function () { whenReveal(fn); }, 100);
  }

  // Way back to the list of all lectures: link in the bottom left corner and key H.
  // Decks live in lectures/ (website and Moodle bundle); the list is one level up.
  const HOME = "../index.html";
  whenReveal(function () {
    if (document.documentElement.classList.contains("print-pdf") || /print-pdf/.test(location.search)) return;
    const link = document.createElement("a");
    link.className = "course-home";
    link.href = HOME;
    link.title = "All lectures (H)";
    link.textContent = "☰ All lectures";
    document.querySelector(".reveal").appendChild(link);
    window.Reveal.addKeyBinding({ keyCode: 72, key: "H", description: "All lectures" },
      function () { window.location.href = HOME; });
  });

  // deck.html?slide=12 (slide box on the list of lectures): open the deck at slide 12 as numbered
  // in the corner. Reveal's #/h/v hash counts sections, not slides. The query is removed again,
  // so that reloading keeps the current slide.
  whenReveal(function () {
    const n = parseInt(new URLSearchParams(location.search).get("slide"), 10);
    if (!(n > 0)) return;
    history.replaceState(null, "", location.pathname + location.hash);
    const slides = window.Reveal.getSlides();
    const i = window.Reveal.getIndices(slides[Math.min(n, slides.length) - 1]);
    window.Reveal.slide(i.h, i.v);
  });

  function printView() {
    return document.documentElement.classList.contains("print-pdf") || /print-pdf/.test(location.search);
  }

  function deckName() {
    return decodeURIComponent(location.pathname.split("/").pop().replace(/\.html$/, ""));
  }

  // Slide log for lecture recordings: every slide change with the time, kept in this browser.
  // tools/video.ps1 matches it with the OBS recording (YouTube chapters, video links on the slides).
  // Shift+R saves it as slidelog-<date>.json. Not logged: print view, speaker view, embedded decks.
  const LOG = "course.slidelog";
  const LOG_DAYS = 14;
  const LOG_MAX = 20000; // entries; about 3 MB in the worst case, below the 5 MB of localStorage

  function readLog() {
    try { return JSON.parse(localStorage.getItem(LOG) || "[]"); } catch (e) { return []; }
  }

  function appendLog(entry) {
    const cutoff = Date.now() - LOG_DAYS * 864e5;
    const log = readLog().filter(function (e) { return e.t >= cutoff; });
    log.push(entry);
    try { localStorage.setItem(LOG, JSON.stringify(log.slice(-LOG_MAX))); } catch (e) { /* private mode, full */ }
  }

  function headingOf(slide) {
    const h = slide && slide.querySelector("h1, h2");
    return h ? h.textContent.trim() : "";
  }

  // the level-1 slide (# heading) a slide belongs to: Quarto puts all slides side by side
  function sectionOf(slide) {
    for (let s = slide; s; s = s.previousElementSibling) {
      if (s.classList && s.classList.contains("level1")) return s;
    }
    return null;
  }

  function logSlide(slide) {
    if (!slide) return;
    const section = sectionOf(slide);
    appendLog({
      d: deckName(), i: slide.id || "", ti: headingOf(slide),
      l: slide.classList.contains("level1") ? 1 : slide.classList.contains("level2") ? 2 : 0,
      s: section ? section.id : "", st: section ? headingOf(section) : "",
      t: Date.now(),
    });
  }

  whenReveal(function () {
    const deck = window.Reveal;
    if (printView() || window.self !== window.top || (deck.isSpeakerNotes && deck.isSpeakerNotes())) return;
    logSlide(deck.getCurrentSlide());
    deck.on("slidechanged", function (e) { logSlide(e.currentSlide); });
    // closing or reloading ends the visit of the current slide
    window.addEventListener("pagehide", function () { appendLog({ d: deckName(), ev: "away", t: Date.now() }); });
    window.addEventListener("pageshow", function (e) { if (e.persisted) logSlide(deck.getCurrentSlide()); });
  });

  // Shift+R: save the log (Reveal ignores key bindings with modifiers, so this is a plain listener)
  document.addEventListener("keydown", function (e) {
    if (!(e.key === "R" && e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey)) return;
    e.preventDefault();
    const blob = new Blob([JSON.stringify(readLog())], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "slidelog-" + new Date().toISOString().slice(0, 10) + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }, true);

  // "▶ Video" link and key Y: the lecture recording at the current slide. The times come from
  // lectures/<deck>.video.json (tools/video.ps1), embedded by se-slides.lua as #course-video.
  // A slide that was not shown in a recording links to the closest earlier one.
  // #course-video comes after Reveal.initialize in the page: wait for the whole document, too.
  function whenParsed(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }
  whenReveal(function () { whenParsed(videoLink); });
  function videoLink() {
    const deck = window.Reveal;
    const data = document.getElementById("course-video");
    if (!data || printView()) return;
    let videos = [];
    try { videos = JSON.parse(data.textContent).videos || []; } catch (e) { return; }
    if (!videos.length) return;
    function target(slide) {
      const slides = deck.getSlides();
      for (let i = slides.indexOf(slide); i >= 0; i--) {
        let best = null;
        videos.forEach(function (v) {
          const s = v.slides && v.slides[slides[i].id]; // [seconds, length of the visit]
          if (s && (!best || s[1] > best.d)) best = { id: v.id, t: s[0], d: s[1] };
        });
        if (best) return "https://youtu.be/" + encodeURIComponent(best.id) + "?t=" + best.t;
      }
      return "https://youtu.be/" + encodeURIComponent(videos[0].id);
    }
    const link = document.createElement("a");
    link.className = "course-video";
    link.title = "This slide in the lecture recording (Y)";
    link.textContent = "▶ Video";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    document.querySelector(".reveal").appendChild(link);
    function update() { link.href = target(deck.getCurrentSlide()); }
    update();
    deck.on("slidechanged", update);
    deck.addKeyBinding({ keyCode: 89, key: "Y", description: "Lecture recording at this slide" },
      function () { update(); window.open(link.href, "_blank", "noopener"); });
  }

  whenReveal(function () {
    const deck = window.Reveal;
    const printing = document.documentElement.classList.contains("print-pdf") || /print-pdf/.test(location.search);
    if (printing) {
      // wait for the PDF layout and diagrams
      setTimeout(function () {
        const problems = [];
        const pages = Array.from(document.querySelectorAll(".reveal .slides .pdf-page"));
        let count = 0;
        document.querySelectorAll(".reveal .slides section").forEach(function (s) {
          if (s.querySelector("section")) return;
          count++;
          // page number in the PDF: the print view wraps every slide in a .pdf-page
          const wrapper = s.closest(".pdf-page");
          const page = wrapper ? pages.indexOf(wrapper) + 1 : count;
          const h = s.querySelector("h2, h1");
          checkSlide(s, marksOn()).forEach(function (t) {
            problems.push({ page: page, problem: t, title: h ? h.textContent.trim() : "" });
          });
        });
        // read by the build (tools/build.ps1, layout report) from the DOM of the print view
        const report = document.createElement("div");
        report.id = "course-layout-report";
        report.hidden = true;
        report.textContent = JSON.stringify(problems);
        document.body.appendChild(report);
      }, 1500);
    } else {
      if (!marksOn()) return;
      setTimeout(function () { checkSlide(deck.getCurrentSlide(), true); }, 300);
      deck.on("slidechanged", function (e) { setTimeout(function () { checkSlide(e.currentSlide, true); }, 300); });
    }
  });
})();
