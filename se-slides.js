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
  // Decks live in lectures/ (website) or html/ (Moodle bundle); the list is one level up.
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
