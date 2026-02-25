/* FD Docs UI - no build, no dependencies. ASCII only. */

(function () {
  "use strict";

  var nav = [];
  var current = null;

  function qs(id) { return document.getElementById(id); }

  function toast(msg) {
    var el = document.createElement("div");
    el.className = "toast";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function () { el.classList.add("show"); }, 20);
    setTimeout(function () {
      el.classList.remove("show");
      setTimeout(function () { el.remove(); }, 200);
    }, 1400);
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderInline(s) {
    // code
    s = s.replace(/`([^`]+)`/g, function (_, m) {
      return "<code>" + escapeHtml(m) + "</code>";
    });
    // links [text](path)
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, text, href) {
      var safe = href.replace(/"/g, "%22");
      return "<a href=\"" + safe + "\" target=\"_blank\" rel=\"noopener\">" + escapeHtml(text) + "</a>";
    });
    // bold **x**
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // italics *x*
    s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    return s;
  }

  function mdToHtml(md) {
    var lines = md.replace(/\r\n/g, "\n").split("\n");
    var out = [];
    var inCode = false;
    var inUl = false;

    function closeUl() {
      if (inUl) {
        out.push("</ul>");
        inUl = false;
      }
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      if (line.trim().startsWith("```")) {
        if (!inCode) {
          closeUl();
          inCode = true;
          out.push("<pre><code>");
        } else {
          inCode = false;
          out.push("</code></pre>");
        }
        continue;
      }

      if (inCode) {
        out.push(escapeHtml(line) + "\n");
        continue;
      }

      if (line.startsWith("# ")) {
        closeUl();
        out.push("<h1>" + renderInline(escapeHtml(line.slice(2))) + "</h1>");
        continue;
      }
      if (line.startsWith("## ")) {
        closeUl();
        out.push("<h2>" + renderInline(escapeHtml(line.slice(3))) + "</h2>");
        continue;
      }
      if (line.startsWith("### ")) {
        closeUl();
        out.push("<h3>" + renderInline(escapeHtml(line.slice(4))) + "</h3>");
        continue;
      }

      if (line.startsWith("- ")) {
        if (!inUl) {
          closeUl();
          inUl = true;
          out.push("<ul>");
        }
        out.push("<li>" + renderInline(escapeHtml(line.slice(2))) + "</li>");
        continue;
      } else {
        closeUl();
      }

      if (line.trim() === "") {
        out.push("");
        continue;
      }

      out.push("<p>" + renderInline(escapeHtml(line)) + "</p>");
    }

    closeUl();
    if (inCode) {
      // Close if file ended mid-code; treat as closed.
      out.push("</code></pre>");
    }

    return out.join("\n");
  }

  function setActiveNav(id) {
    var items = document.querySelectorAll("#navList a");
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("active", items[i].dataset.id === id);
    }
  }

  function pageUrlHash(id) {
    return "#page=" + encodeURIComponent(id);
  }

  function readHashPageId() {
    var h = (location.hash || "").replace(/^#/, "");
    if (!h) return null;
    var parts = h.split("&");
    for (var i = 0; i < parts.length; i++) {
      var kv = parts[i].split("=");
      if (kv.length === 2 && kv[0] === "page") return decodeURIComponent(kv[1]);
    }
    return null;
  }

  function loadPageById(id) {
    var page = null;
    for (var i = 0; i < nav.length; i++) {
      if (nav[i].id === id) page = nav[i];
    }
    if (!page) page = nav[0];

    current = page;

    setActiveNav(page.id);
    qs("pageTitle").textContent = page.title;
    qs("pageMeta").textContent = "Source: " + page.path;

    fetch(page.path, { cache: "no-store" })
      .then(function (r) { return r.text(); })
      .then(function (txt) {
        qs("renderTarget").innerHTML = mdToHtml(txt);
      })
      .catch(function (err) {
        qs("renderTarget").innerHTML = "<p>Failed to load: " + escapeHtml(String(err)) + "</p>";
      });
  }

  function buildNav() {
    var ul = qs("navList");
    ul.innerHTML = "";
    for (var i = 0; i < nav.length; i++) {
      (function (page) {
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.href = pageUrlHash(page.id);
        a.textContent = page.title;
        a.dataset.id = page.id;
        a.addEventListener("click", function (e) {
          e.preventDefault();
          location.hash = pageUrlHash(page.id);
        });
        li.appendChild(a);
        ul.appendChild(li);
      })(nav[i]);
    }
  }

  function copyText(s) {
    return navigator.clipboard.writeText(s).then(function () {
      toast("Copied");
    }, function () {
      toast("Copy failed");
    });
  }

  function initActions() {
    qs("copyLinkBtn").addEventListener("click", function () {
      if (!current) return;
      var url = location.href.split("#")[0] + pageUrlHash(current.id);
      copyText(url);
    });

    qs("copyRawBtn").addEventListener("click", function () {
      if (!current) return;
      fetch(current.path, { cache: "no-store" })
        .then(function (r) { return r.text(); })
        .then(function (txt) { return copyText(txt); })
        .catch(function () { toast("Copy failed"); });
    });
  }

  function init() {
    initActions();
    fetch("nav.json", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        nav = j;
        buildNav();
        var requested = readHashPageId();
        loadPageById(requested || (nav[0] && nav[0].id) || "start");
      })
      .catch(function (err) {
        qs("renderTarget").innerHTML = "<p>Failed to load nav.json: " + escapeHtml(String(err)) + "</p>";
      });

    window.addEventListener("hashchange", function () {
      var requested = readHashPageId();
      if (requested) loadPageById(requested);
    });
  }

  init();
})();
