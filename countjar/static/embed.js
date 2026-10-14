/*! CountJar embed — https://countjar docs at /docs/widgets
 *  <div class="countjar" data-workspace="acme" data-counter="visits"></div>
 *  <script src="https://YOUR-COUNTJAR/embed.js" async></script>
 */
(function () {
  "use strict";
  if (window.CountJar && window.CountJar.scan) return;

  var script = document.currentScript;
  var BASE = script && script.src ? new URL(script.src).origin : location.origin;

  var ICONS = {
    eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    heart: '<path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.8 4.5c2.2 0 3.6 1.2 5.2 3 1.6-1.8 3-3 5.2-3 3.8 0 5.9 3.9 4.4 7.3C19.5 16.4 12 21 12 21Z"/>',
    star: '<path d="m12 2.8 2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.6l-5.8 3.1 1.1-6.5-4.7-4.6 6.5-.9L12 2.8Z"/>',
    fire: '<path d="M12 22c4.4 0 7-3 7-7 0-4.5-3.5-6.8-4.5-11-2.5 2-3.5 4.5-3.5 6.5C9.5 9 9 7.5 9 6c-2.5 2-4 5.2-4 8.5C5 19 7.6 22 12 22Z"/>',
    download: '<path d="M12 3v12m0 0-5-5m5 5 5-5M4 21h16"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.3-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18.5 14.8c1.7.7 2.8 2.4 3 5.2"/>',
    thumbs: '<path d="M7 10v11H3V10h4Zm0 0 4.5-7.5c1.7 0 2.9 1.5 2.5 3.1L13.3 9H19a2 2 0 0 1 2 2.3l-1.3 7.5A2.6 2.6 0 0 1 17.2 21H7"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/>',
  };

  var THEMES = {
    light: { bg: "#ffffff", fg: "#1a1d3a", muted: "#5b6285", line: "#d4dbe8", soft: "#eef2f8" },
    dark: { bg: "#171b36", fg: "#e8eaf6", muted: "#9aa0c3", line: "#2a2f55", soft: "#0f1226" },
    glass: { bg: "rgba(255,255,255,.14)", fg: "inherit", muted: "currentColor", line: "rgba(255,255,255,.28)", soft: "rgba(255,255,255,.1)" },
  };

  function icon(name, fill) {
    return '<svg viewBox="0 0 24 24" width="16" height="16" fill="' + (fill ? "currentColor" : "none") +
      '" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      (ICONS[name] || ICONS.eye) + "</svg>";
  }

  function fmt(n, abbreviate) {
    n = Number(n) || 0;
    if (!abbreviate) return n.toLocaleString("en-US");
    var units = [[1e9, "B"], [1e6, "M"], [1e3, "k"]];
    for (var i = 0; i < units.length; i++) {
      if (Math.abs(n) >= units[i][0]) return (n / units[i][0]).toFixed(1).replace(/\.0$/, "") + units[i][1];
    }
    return String(n);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function api(ws, name, action, params) {
    var url = BASE + "/api/v2/" + encodeURIComponent(ws) + "/" + encodeURIComponent(name) +
      (action ? "/" + action : "");
    var q = new URLSearchParams(params || {}).toString();
    return fetch(url + (q ? "?" + q : ""), { credentials: "omit" }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error((d.error && d.error.message) || "CountJar error");
        return d;
      });
    });
  }

  function remember(key, val) {
    try {
      if (val === undefined) return localStorage.getItem("countjar:" + key);
      localStorage.setItem("countjar:" + key, val);
    } catch (e) { return null; }
  }

  function animate(el, to, opts) {
    if (opts.noAnim || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.textContent = fmt(to, opts.abbreviate);
      return;
    }
    var start = performance.now(), dur = Math.min(1600, 400 + String(to).length * 120);
    function step(t) {
      var p = Math.min(1, (t - start) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(Math.round(to * e), opts.abbreviate);
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function styles(o) {
    var t = THEMES[o.theme] || THEMES.light;
    var bg = o.bg || t.bg, fg = o.color || t.fg, accent = o.accent || "#f2a90f";
    return "<style>" +
      ":host{all:initial;display:inline-block;font:500 14px/1.3 ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;color:" + fg + "}" +
      ".w{display:inline-flex;flex-direction:column;gap:8px;background:" + bg + ";color:" + fg + ";border:1px solid " + t.line + ";border-radius:14px;padding:8px 12px;" + (o.theme === "glass" ? "backdrop-filter:blur(10px);" : "") + "}" +
      ".row{display:inline-flex;align-items:center;gap:8px}" +
      ".ic{color:" + accent + ";display:inline-flex}" +
      ".n{font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.01em}" +
      ".l{color:" + t.muted + ";opacity:.85}" +
      "button{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:6px;border-radius:10px;padding:6px 10px;border:1px solid " + t.line + ";background:" + t.soft + ";color:inherit;font-weight:600;transition:transform .15s}" +
      "button:hover{border-color:" + accent + "}button:focus-visible{outline:2px solid " + accent + ";outline-offset:2px}" +
      "button:active{transform:scale(.96)}button[disabled]{cursor:default;opacity:.85}" +
      "button.on{background:" + accent + ";border-color:" + accent + ";color:#1a1d3a}" +
      ".q{font-weight:600}" +
      ".bar{height:8px;border-radius:99px;background:" + t.soft + ";overflow:hidden;min-width:160px}" +
      ".bar i{display:block;height:100%;background:" + accent + ";transition:width .6s ease}" +
      ".res{display:grid;grid-template-columns:auto 1fr auto;gap:6px 10px;align-items:center;font-size:13px}" +
      ".stars button{padding:4px;border:0;background:none;color:" + t.muted + "}.stars button.on,.stars button.hv{color:" + accent + "}" +
      ".by{font-size:11px;color:" + t.muted + ";text-decoration:none;opacity:.7}.by:hover{opacity:1}" +
      "@keyframes pop{50%{transform:scale(1.3)}}.pop{animation:pop .35s ease}" +
      "</style>";
  }

  function opts(el) {
    var d = el.dataset;
    var has = function (k) { return d[k] !== undefined && d[k] !== "false"; };
    return {
      ws: d.workspace, name: d.counter, type: d.type || "count",
      theme: d.theme || "light", icon: d.icon, label: d.label,
      readonly: has("readonly"), abbreviate: has("abbreviate"), hideZero: has("hideZero"),
      noAnim: has("noAnim"), noLink: has("noLink"), preview: has("preview"),
      color: d.color, bg: d.bg, accent: d.accent, window: d.window,
      question: d.question || "Was this helpful?", start: Number(d.start || 0),
    };
  }

  function credit(o) {
    return o.noLink ? "" : '<a class="by" href="' + BASE + '/" target="_blank" rel="noopener">CountJar</a>';
  }

  function renderCount(root, el, o) {
    var params = o.window ? { window: o.window } : {};
    var req = o.readonly ? api(o.ws, o.name, "", params) : api(o.ws, o.name, "up", params);
    return req.then(function (d) {
      var value = (o.window && d.window ? d.window.count : d.count) + o.start;
      if (o.hideZero && !value) { el.style.display = "none"; return; }
      root.innerHTML += '<div class="w"><span class="row"><span class="ic">' + icon(o.icon || "eye") +
        '</span><span class="n">0</span>' + (o.label ? '<span class="l">' + esc(o.label) + "</span>" : "") +
        "</span>" + credit(o) + "</div>";
      animate(root.querySelector(".n"), value, o);
    });
  }

  function renderLike(root, el, o) {
    var key = "like:" + o.ws + "/" + o.name;
    return api(o.ws, o.name).then(function (d) {
      var liked = remember(key) === "1";
      root.innerHTML += '<div class="w"><span class="row"><button type="button" aria-pressed="' + liked + '" class="' +
        (liked ? "on" : "") + '">' + icon("heart", liked) + '<span class="n">' + fmt(d.count + o.start, o.abbreviate) +
        "</span>" + (o.label ? '<span class="l">' + esc(o.label) + "</span>" : "") + "</button></span>" + credit(o) + "</div>";
      var btn = root.querySelector("button");
      if (o.readonly || o.preview) { btn.disabled = true; return; }
      btn.addEventListener("click", function () {
        if (remember(key) === "1") return;
        remember(key, "1");
        btn.classList.add("on", "pop");
        btn.setAttribute("aria-pressed", "true");
        btn.querySelector("svg").setAttribute("fill", "currentColor");
        var n = btn.querySelector(".n");
        n.textContent = fmt(d.count + o.start + 1, o.abbreviate);
        api(o.ws, o.name, "like").then(function (r) { n.textContent = fmt(r.count + o.start, o.abbreviate); })
          .catch(function () {});
      });
    });
  }

  function pollResults(d) {
    var total = d.yes + d.no, y = total ? Math.round(100 * d.yes / total) : 0;
    return '<div class="res"><span>Yes</span><span class="bar"><i style="width:' + y + '%"></i></span><span>' + y +
      '%</span><span>No</span><span class="bar"><i style="width:' + (total ? 100 - y : 0) + '%"></i></span><span>' +
      (total ? 100 - y : 0) + '%</span></div><span class="l">' + fmt(total) + " vote" + (total === 1 ? "" : "s") + "</span>";
  }

  function renderPoll(root, el, o) {
    var key = "vote:" + o.ws + "/" + o.name;
    return api(o.ws, o.name).then(function (d) {
      var voted = remember(key);
      var body = voted || o.readonly ? pollResults(d)
        : '<span class="row"><button type="button" data-c="yes">' + icon("thumbs") + 'Yes</button><button type="button" data-c="no">No</button></span>';
      root.innerHTML += '<div class="w"><span class="q">' + esc(o.question) + '</span><div class="body">' + body + "</div>" + credit(o) + "</div>";
      if (voted || o.readonly || o.preview) return;
      root.querySelectorAll("button").forEach(function (b) {
        b.addEventListener("click", function () {
          remember(key, b.dataset.c);
          api(o.ws, o.name, "vote", { choice: b.dataset.c }).then(function (r) {
            root.querySelector(".body").innerHTML = pollResults(r);
          }).catch(function () {});
        });
      });
    });
  }

  function renderRating(root, el, o) {
    var key = "rate:" + o.ws + "/" + o.name;
    return api(o.ws, o.name).then(function (d) {
      var mine = Number(remember(key) || 0);
      var shown = mine || Math.round(d.average);
      var stars = "";
      for (var i = 1; i <= 5; i++) {
        stars += '<button type="button" aria-label="' + i + ' star' + (i > 1 ? "s" : "") + '" data-v="' + i + '" class="' +
          (i <= shown ? "on" : "") + '">' + icon("star", i <= shown) + "</button>";
      }
      root.innerHTML += '<div class="w"><span class="row"><span class="stars row">' + stars + '</span><span class="n">' +
        (d.average || 0).toFixed(1) + '</span><span class="l">(' + fmt(d.ratings) + ")</span></span>" + credit(o) + "</div>";
      if (mine || o.readonly || o.preview) {
        root.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
        return;
      }
      var btns = root.querySelectorAll("button");
      btns.forEach(function (b) {
        b.addEventListener("mouseenter", function () {
          btns.forEach(function (x) { x.classList.toggle("hv", Number(x.dataset.v) <= Number(b.dataset.v)); });
        });
        b.addEventListener("click", function () {
          remember(key, b.dataset.v);
          api(o.ws, o.name, "rate", { value: b.dataset.v }).then(function (r) {
            btns.forEach(function (x) {
              var on = Number(x.dataset.v) <= Number(b.dataset.v);
              x.classList.toggle("on", on); x.disabled = true;
              x.querySelector("svg").setAttribute("fill", on ? "currentColor" : "none");
            });
            root.querySelector(".n").textContent = r.average.toFixed(1);
            root.querySelector(".l").textContent = "(" + fmt(r.ratings) + ")";
          }).catch(function () {});
        });
      });
      root.querySelector(".stars").addEventListener("mouseleave", function () {
        btns.forEach(function (x) { x.classList.remove("hv"); });
      });
    });
  }

  var RENDER = { count: renderCount, like: renderLike, poll: renderPoll, rating: renderRating };

  function mount(el) {
    if (el.__countjar) return;
    el.__countjar = true;
    var o = opts(el);
    if (!o.ws || !o.name) return;
    var root = el.shadowRoot || el.attachShadow({ mode: "open" });
    root.innerHTML = styles(o);
    (RENDER[o.type] || renderCount)(root, el, o).catch(function (e) {
      root.innerHTML += '<span class="w l" title="' + esc(e.message) + '">—</span>';
    });
  }

  function scan(scope) {
    (scope || document).querySelectorAll(".countjar").forEach(mount);
  }

  window.CountJar = { scan: scan, version: "2.0.0" };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { scan(); });
  else scan();
})();
