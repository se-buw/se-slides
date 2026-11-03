// "Open in VS Code" buttons and QR codes.
(function () {
  // PDF export (tools/build.ps1): Reveal lays out the print view across several animation frames,
  // but headless Chrome with --virtual-time-budget prints without waiting for frames. Light decks
  // (no diagrams) then came out as one blank page. Timers run on virtual time, so the budget covers them.
  if (/HeadlessChrome/.test(navigator.userAgent) && /print-pdf/.test(location.search)) {
    window.requestAnimationFrame = function (cb) { return setTimeout(function () { cb(performance.now()); }, 16); };
    window.cancelAnimationFrame = function (id) { clearTimeout(id); };
  }

  // Generated lecture videos (tools/lecture-video): deck.html?video shows the slides without
  // navigation aids and cursor, and fragments appear without a transition (the video fades itself).
  const VIDEO = /[?&]video(&|=|$)/.test(location.search);
  if (VIDEO) {
    document.documentElement.classList.add("course-video-mode");
    const style = document.createElement("style");
    style.textContent =
      ".course-video-mode .reveal .controls, .course-video-mode .reveal .progress," +
      ".course-video-mode .code-copy-button { display: none !important; }" +
      // buttons, links and QR codes cannot be used in a video. The buttons go, so the file caption
      // of a listing gets the whole line (no "…"); file names in the text (a.vscode-open.code-link)
      // stay. QR codes leave their space (same layout as the slides).
      ".course-video-mode button.vscode-open, .course-video-mode button.vscode-root," +
      ".course-video-mode a.code-web { display: none !important; }" +
      ".course-video-mode .qr-box { visibility: hidden !important; }" +
      ".course-video-mode .reveal .slides section .fragment { transition: none !important; }" +
      ".course-video-mode, .course-video-mode * { cursor: none !important; }";
    document.head.appendChild(style);
  }

  // Dark mode (theme/se.scss). Without a choice the slides follow the system theme, in CSS alone.
  // A choice (key D, link in the corner) is stored like the one of Quarto's toggle on the list of
  // lectures, so both share it: "alternate" is dark, "default" light. PDF export and videos stay light.
  // This script runs in <head>, so the stored theme applies before the first paint.
  const SCHEME = "quarto-color-scheme";
  const ALWAYS_LIGHT = VIDEO || /print-pdf/.test(location.search);
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  function applyScheme() {
    let stored = null;
    try { stored = localStorage.getItem(SCHEME); } catch (e) { /* private mode */ }
    const html = document.documentElement;
    if (ALWAYS_LIGHT || stored === "default") html.dataset.theme = "light";
    else if (stored === "alternate") html.dataset.theme = "dark";
    else delete html.dataset.theme;
  }
  function isDark() {
    const theme = document.documentElement.dataset.theme;
    return theme ? theme === "dark" : systemDark.matches;
  }
  // The same theme as the system's is no choice: the slides follow the system again
  function setDark(dark) {
    try {
      if (dark === systemDark.matches) localStorage.removeItem(SCHEME);
      else localStorage.setItem(SCHEME, dark ? "alternate" : "default");
      applyScheme();
    } catch (e) {
      document.documentElement.dataset.theme = dark ? "dark" : "light"; // private mode: this page only
    }
  }
  applyScheme();
  // a choice made in another tab, e.g. on the list of lectures
  window.addEventListener("storage", function (e) { if (e.key === SCHEME) applyScheme(); });

  // Mermaid diagrams (Quarto renders them on load) size their label boxes with getBoundingClientRect,
  // which includes Reveal's scaling of the slides: at scale 0.94 (margin 0.06) every box came out 6 %
  // too small and labels ran over or were cut ("previous statemen"). Render them unscaled, then let
  // Reveal scale again. This listener is registered before Quarto's (script order), so it runs first.
  window.addEventListener("load", function () {
    if (!document.querySelector("pre.mermaid-js")) return sizeDiagrams();
    const unscaled = document.createElement("style");
    unscaled.textContent = ".reveal .slides { transform: none !important; zoom: 1 !important; }";
    document.head.appendChild(unscaled);
    let tries = 0;
    (function rescale() {
      // Quarto replaces each pre.mermaid-js by its SVG; give up after 10 s (a broken diagram)
      if (document.querySelector("pre.mermaid-js") && ++tries < 200) return setTimeout(rescale, 50);
      unscaled.remove();
      sizeDiagrams();
      if (window.Reveal && window.Reveal.layout) window.Reveal.layout();
    })();
  });

  // Diagrams (Mermaid, Graphviz) get the same text size everywhere, instead of the width of their
  // column: a small diagram was blown up to 74 px text, a wide one shrunk to 11 px. Both draw text
  // in the units of their viewBox; --diagram-w (se-slides.css) is the width at which the most used
  // text size becomes DIAGRAM_TEXT px. Narrower columns and the height limit shrink it further.
  const DIAGRAMS = ".reveal .cell-output-display svg, .reveal .mermaid svg, .reveal pre.mermaid-js + div svg";
  const DIAGRAM_TEXT = 24;      // px on the 1280x720 slide; body text is 34, code 20
  const DIAGRAM_TEXT_MIN = 20;  // smaller text is reported by the layout check (as for code)

  // The text size used for most characters, in viewBox units
  function diagramFont(svg) {
    const chars = {};
    svg.querySelectorAll("text, foreignObject span, foreignObject div, foreignObject p").forEach(function (el) {
      const text = el.textContent.trim();
      if (!text || (el.tagName.toLowerCase() !== "text" && el.children.length)) return;
      const size = Math.round(parseFloat(getComputedStyle(el).fontSize) * 10) / 10;
      if (size > 0) chars[size] = (chars[size] || 0) + text.length;
    });
    let best = 0;
    Object.keys(chars).forEach(function (s) { if (!best || chars[s] > chars[best]) best = s; });
    return +best;
  }

  function sizeDiagrams() {
    document.querySelectorAll(DIAGRAMS).forEach(function (svg) {
      const box = svg.viewBox && svg.viewBox.baseVal;
      const font = box && box.width && box.height && diagramFont(svg);
      if (!font) return;
      svg.dataset.courseFont = font;
      svg.style.setProperty("--diagram-w", (box.width * DIAGRAM_TEXT / font).toFixed(1) + "px");
      svg.style.setProperty("--diagram-ratio", (box.width / box.height).toFixed(4));
    });
    // the room on a slide needs its layout: all slides in the print view, else the slide shown
    whenReveal(function () {
      if (!printView()) return fitDiagrams(window.Reveal.getCurrentSlide());
      document.querySelectorAll(".reveal .slides section").forEach(function (s) {
        if (!s.querySelector("section")) fitDiagrams(s);
      });
    });
  }
  whenReveal(function () {
    window.Reveal.on("slidechanged", function (e) { fitDiagrams(e.currentSlide); });
  });

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

  function slideScale() {
    return window.Reveal.getScale ? window.Reveal.getScale() : 1;
  }

  // Lowest point of a slide's content, in px of the 720 px slide
  function contentBottom(section) {
    const scale = slideScale();
    const top = section.getBoundingClientRect().top;
    let bottom = 0;
    section.querySelectorAll("h1, h2, p, li, pre, table, img, svg, .listing, .columns, .callout, .tip, .pitfall, .java25")
      .forEach(function (el) {
        if (el.closest(".notes, aside")) return;
        const r = el.getBoundingClientRect();
        if (r.height > 0) bottom = Math.max(bottom, (r.bottom - top) / scale);
      });
    return bottom;
  }

  // Height limit of the diagrams of a shown slide (sizeDiagrams): their size at DIAGRAM_TEXT, as far
  // as the room above the footer allows. Diagrams one below the other share the shortage.
  function fitDiagrams(section) {
    if (!section) return;
    const svgs = Array.from(section.querySelectorAll(DIAGRAMS)).filter(function (svg) { return svg.dataset.courseFont; });
    if (!svgs.length) return;
    svgs.forEach(function (svg) {
      const box = svg.viewBox.baseVal;
      svg.style.setProperty("--diagram-max-h", (box.height * DIAGRAM_TEXT / +svg.dataset.courseFont).toFixed(1) + "px");
    });
    // 2 px below the limit: sizes round to fractions of a pixel
    const over = contentBottom(section) - (window.Reveal.getConfig().height - FOOTER_SPACE - 2);
    if (over <= 0) return;
    const scale = slideScale();
    const rects = svgs.map(function (svg) { return svg.getBoundingClientRect(); });
    const stacked = rects.some(function (a) {
      return rects.some(function (b) { return a !== b && (a.bottom <= b.top || b.bottom <= a.top); });
    });
    const share = stacked ? over / svgs.length : over;
    svgs.forEach(function (svg, i) {
      svg.style.setProperty("--diagram-max-h", Math.max(rects[i].height / scale - share, 40).toFixed(1) + "px");
    });
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
    const scale = slideScale();
    const bottom = contentBottom(section);
    if (bottom > height - FOOTER_SPACE) found(section, "content too long (" + Math.round(bottom) + " px)");
    // Quarto scrolls div.sourceCode, plain blocks scroll the pre: check every level
    section.querySelectorAll("div.sourceCode, pre, pre > code").forEach(function (el) {
      const box = el.closest("div.sourceCode") || el;
      if (el.scrollWidth > el.clientWidth + 2) found(box, "code line too wide");
      if (el.scrollHeight > el.clientHeight + 2) found(box, "listing clipped");
    });
    // a diagram that had to shrink below the minimum text size (sizeDiagrams)
    section.querySelectorAll(DIAGRAMS).forEach(function (svg) {
      const font = +svg.dataset.courseFont;
      const box = svg.viewBox && svg.viewBox.baseVal;
      const r = svg.getBoundingClientRect();
      if (!font || !box || !box.width || !r.width) return;
      const px = font * Math.min(r.width / box.width, r.height / box.height) / scale;
      if (px < DIAGRAM_TEXT_MIN - 0.5) found(svg, "diagram text " + Math.round(px) + " px");
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

  // Links in the bottom left corner, in one row (se-slides.css)
  function cornerLinks() {
    let row = document.querySelector(".reveal .course-links");
    if (!row) {
      row = document.createElement("div");
      row.className = "course-links";
      document.querySelector(".reveal").appendChild(row);
    }
    return row;
  }

  // Way back to the list of all lectures: link in the bottom left corner and key H.
  // Decks live in lectures/ (website and Moodle bundle); the list is one level up.
  // Next to it the switch between dark and light theme, key D.
  const HOME = "../index.html";
  whenReveal(function () {
    if (document.documentElement.classList.contains("print-pdf") || /print-pdf/.test(location.search) || VIDEO) return;
    const link = document.createElement("a");
    link.className = "course-home";
    link.href = HOME;
    link.title = "All lectures (H)";
    link.textContent = "☰ All lectures";
    cornerLinks().appendChild(link);
    window.Reveal.addKeyBinding({ keyCode: 72, key: "H", description: "All lectures" },
      function () { window.location.href = HOME; });

    const theme = document.createElement("a");
    theme.className = "course-theme";
    theme.href = "#";
    theme.title = "Dark or light theme (D)";
    function label() { theme.textContent = isDark() ? "◐ Light" : "◐ Dark"; }
    function toggle() { setDark(!isDark()); label(); }
    theme.addEventListener("click", function (e) { e.preventDefault(); toggle(); });
    cornerLinks().appendChild(theme);
    label();
    systemDark.addEventListener("change", label);
    window.addEventListener("storage", label);
    window.Reveal.addKeyBinding({ keyCode: 68, key: "D", description: "Dark or light theme" }, toggle);
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
    if (printView() || VIDEO || window.self !== window.top || (deck.isSpeakerNotes && deck.isSpeakerNotes())) return;
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
  // A slide that was not shown in a recording links to the closest earlier one. The lecture ends at the
  // last slide shown for MIN_SHOWN s: later slides (flipped to at the end, next week's) get no link.
  // #course-video comes after Reveal.initialize in the page: wait for the whole document, too.
  const MIN_SHOWN = 10;
  function whenParsed(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }
  whenReveal(function () { whenParsed(videoLink); });
  function videoLink() {
    const deck = window.Reveal;
    const data = document.getElementById("course-video");
    if (!data || printView() || VIDEO) return;
    let videos = [];
    try { videos = JSON.parse(data.textContent).videos || []; } catch (e) { return; }
    if (!videos.length) return;
    const slides = deck.getSlides();
    let end = -1;
    slides.forEach(function (s, i) {
      if (videos.some(function (v) { const t = v.slides && v.slides[s.id]; return t && t[1] >= MIN_SHOWN; })) end = i;
    });
    function target(slide) {
      const at = slides.indexOf(slide);
      if (at > end) return null;
      for (let i = at; i >= 0; i--) {
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
    // no "noreferrer": YouTube Studio then counts these views as External from the course site (the
    // origin only, not the deck); the lecture table keeps noreferrer so slide clicks stand apart
    link.rel = "noopener";
    cornerLinks().appendChild(link);
    function update() {
      const href = target(deck.getCurrentSlide());
      link.hidden = !href;
      if (href) link.href = href;
    }
    update();
    deck.on("slidechanged", update);
    deck.addKeyBinding({ keyCode: 89, key: "Y", description: "Lecture recording at this slide" },
      function () { update(); if (!link.hidden) window.open(link.href, "_blank", "noopener"); });
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
