/* CountJar site script: theme, odometer, clipboard, charts, OTP input, builders. */
(function () {
  "use strict";

  // ---------- theme ----------
  const root = document.documentElement;
  window.cjTheme = {
    toggle() {
      const dark = !root.classList.contains("dark");
      root.classList.toggle("dark", dark);
      try { localStorage.setItem("cj-theme", dark ? "dark" : "light"); } catch (e) {}
      document.dispatchEvent(new CustomEvent("cj-theme"));
    },
  };

  // ---------- odometer ----------
  function odometer(el, value) {
    const text = Number(value || 0).toLocaleString("en-US");
    if (el.dataset.text === text) return;
    const prev = el.dataset.text || "";
    el.dataset.text = text;
    el.setAttribute("aria-label", text);
    if (prev.length !== text.length) {
      el.innerHTML = "";
      for (const ch of text) {
        if (/\d/.test(ch)) {
          const d = document.createElement("span");
          d.className = "odo-digit";
          d.setAttribute("aria-hidden", "true");
          const strip = document.createElement("span");
          strip.className = "odo-strip";
          for (let i = 0; i <= 9; i++) {
            const s = document.createElement("span");
            s.textContent = i;
            strip.appendChild(s);
          }
          d.appendChild(strip);
          el.appendChild(d);
        } else {
          const s = document.createElement("span");
          s.className = "odo-sep";
          s.setAttribute("aria-hidden", "true");
          s.textContent = ch;
          el.appendChild(s);
        }
      }
      // Let the browser lay out at 0 before sliding to the target digit.
      el.getBoundingClientRect();
    }
    const strips = el.querySelectorAll(".odo-strip");
    let i = 0;
    for (const ch of text) {
      if (/\d/.test(ch)) strips[i++].style.transform = `translateY(-${Number(ch)}em)`;
    }
  }
  window.cjOdometer = odometer;

  // ---------- helpers ----------
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

  window.cjToast = function (message, kind) {
    window.dispatchEvent(new CustomEvent("cj-toast", { detail: { message, kind: kind || "success" } }));
  };

  window.cjCopy = async function (text, label) {
    try {
      await navigator.clipboard.writeText(text);
      window.cjToast((label || "Copied") + " to clipboard");
    } catch (e) {
      window.cjToast("Couldn't copy. Select the text and copy it manually.", "error");
    }
  };

  const css = (name) => getComputedStyle(root).getPropertyValue(name).trim();

  // ---------- Alpine components ----------
  document.addEventListener("alpine:init", () => {
    const Alpine = window.Alpine;

    Alpine.data("toasts", () => ({
      items: [],
      add(e) {
        const id = Date.now() + Math.random();
        this.items.push({ id, ...e.detail });
        setTimeout(() => (this.items = this.items.filter((t) => t.id !== id)), 4200);
      },
    }));

    // Landing hero: the demo jar wired to the real API.
    Alpine.data("demoJar", (initial, base) => ({
      count: initial,
      busy: false,
      request: `GET ${base}/api/v2/demo/test-counter`,
      response: "",
      init() {
        odometer(this.$refs.odo, this.count);
        this.call("");
      },
      async call(action) {
        if (this.busy) return;
        this.busy = true;
        const path = `/api/v2/demo/test-counter${action ? "/" + action : ""}`;
        this.request = `GET ${base}${path}`;
        try {
          const r = await fetch(path);
          const data = await r.json();
          this.response = JSON.stringify(
            r.ok ? { name: data.name, count: data.count, updated_at: data.updated_at } : data, null, 2);
          if (r.ok) {
            this.count = data.count;
            odometer(this.$refs.odo, this.count);
          }
        } catch (e) {
          this.response = '{ "error": "network error" }';
        } finally {
          this.busy = false;
        }
      },
    }));

    // Big number on the counter page with quick actions.
    Alpine.data("counterLive", (initial, actionUrl) => ({
      count: initial,
      by: "",
      value: "",
      busy: false,
      init() { odometer(this.$refs.odo, this.count); },
      async act(action) {
        if (this.busy) return;
        if (action === "reset" && !confirm("Reset this counter? History is kept.")) return;
        this.busy = true;
        const body = new FormData();
        body.append("action", action);
        body.append("csrf_token", csrf());
        if (this.by) body.append("by", this.by);
        if (action === "set") body.append("value", this.value);
        try {
          const r = await fetch(actionUrl, { method: "POST", body, headers: { Accept: "application/json" } });
          const data = await r.json();
          if (!r.ok) throw new Error(data.error || "Something went wrong");
          this.count = data.count;
          odometer(this.$refs.odo, this.count);
        } catch (e) {
          window.cjToast(e.message, "error");
        } finally {
          this.busy = false;
        }
      },
    }));

    // History chart (Chart.js) with a range switcher.
    Alpine.data("historyChart", (url, kind) => ({
      range: "24h",
      chart: null,
      total: 0,
      init() {
        this.load();
        document.addEventListener("cj-theme", () => this.load());
      },
      async load() {
        const r = await fetch(`${url}?range=${this.range}`);
        if (!r.ok) return;
        const { series } = await r.json();
        this.total = series.reduce((a, p) => a + p.ups, 0);
        const hourly = this.range === "24h";
        const labels = series.map((p) => {
          const d = new Date(p.t);
          return hourly ? d.toLocaleTimeString([], { hour: "numeric" })
                        : d.toLocaleDateString([], { month: "short", day: "numeric" });
        });
        const honey = css("--honey"), coral = css("--coral"), muted = css("--muted"), line = css("--line");
        const datasets = [{
          label: kind === "count" ? "Increments" : "Events",
          data: series.map((p) => (kind === "count" ? p.ups : p.events)),
          backgroundColor: honey, borderRadius: 4, maxBarThickness: 22,
        }];
        if (kind === "count" && series.some((p) => p.downs)) {
          datasets.push({ label: "Decrements", data: series.map((p) => -p.downs),
                          backgroundColor: coral, borderRadius: 4, maxBarThickness: 22 });
        }
        const cfg = {
          type: "bar",
          data: { labels, datasets },
          options: {
            responsive: true, maintainAspectRatio: false, animation: { duration: 350 },
            plugins: { legend: { display: datasets.length > 1, labels: { color: muted, boxWidth: 10 } },
                       tooltip: { mode: "index", intersect: false } },
            scales: {
              x: { stacked: true, grid: { display: false }, ticks: { color: muted, maxTicksLimit: 8 } },
              y: { stacked: true, beginAtZero: true, grid: { color: line }, border: { display: false },
                   ticks: { color: muted, precision: 0 } },
            },
          },
        };
        if (this.chart) this.chart.destroy();
        this.chart = new window.Chart(this.$refs.canvas, cfg);
      },
      setRange(r) { this.range = r; this.load(); },
    }));

    // Six-box one-time code input with paste support.
    Alpine.data("otp", () => ({
      digits: ["", "", "", "", "", ""],
      get code() { return this.digits.join(""); },
      input(i, e) {
        const v = e.target.value.replace(/\D/g, "");
        if (v.length > 1) return this.fill(v);
        this.digits[i] = v;
        if (v && i < 5) this.$refs["d" + (i + 1)].focus();
        if (this.code.length === 6) this.$nextTick(() => this.$refs.form.requestSubmit());
      },
      back(i, e) {
        if (!this.digits[i] && i > 0) { this.$refs["d" + (i - 1)].focus(); e.preventDefault(); }
      },
      fill(v) {
        v.slice(0, 6).split("").forEach((c, j) => (this.digits[j] = c));
        this.$refs["d" + Math.min(v.length, 5)].focus();
        if (this.code.length === 6) this.$nextTick(() => this.$refs.form.requestSubmit());
      },
      paste(e) { this.fill((e.clipboardData.getData("text") || "").replace(/\D/g, "")); },
    }));

    // Resend timer on the OTP page.
    Alpine.data("countdown", (seconds) => ({
      left: seconds,
      init() { const t = setInterval(() => { if (--this.left <= 0) clearInterval(t); }, 1000); },
    }));

    // Embed + badge builder with live preview.
    Alpine.data("embedBuilder", (cfg) => ({
      ...cfg.defaults,
      tab: "widget",
      get attrs() {
        const a = [`data-workspace="${cfg.ws}"`, `data-counter="${cfg.name}"`, `data-type="${cfg.type}"`];
        if (this.theme !== "light") a.push(`data-theme="${this.theme}"`);
        if (this.label) a.push(`data-label="${this.label}"`);
        if (this.icon && cfg.type === "count" && this.icon !== "eye") a.push(`data-icon="${this.icon}"`);
        if (this.readonly) a.push(`data-readonly`);
        if (this.abbreviate) a.push(`data-abbreviate`);
        if (this.accent !== "#f2a90f") a.push(`data-accent="${this.accent}"`);
        if (cfg.type === "poll" && this.question) a.push(`data-question="${this.question}"`);
        return a;
      },
      get snippet() {
        return `<div class="countjar" ${this.attrs.join(" ")}></div>\n<script src="${cfg.base}/embed.js" async></script>`;
      },
      get badgeUrl() {
        const q = new URLSearchParams({ style: this.badgeStyle });
        if (this.badgeLabel) q.set("label", this.badgeLabel);
        if (this.badgeColor !== "amber") q.set("color", this.badgeColor);
        if (this.readonly) q.set("readonly", "1");
        if (this.abbreviate) q.set("abbreviate", "1");
        return `${cfg.base}/badge/${cfg.ws}/${cfg.name}.svg?${q}`;
      },
      get previewBadgeUrl() {
        // The preview never increments the real counter.
        const u = new URL(this.badgeUrl);
        u.searchParams.set("readonly", "1");
        return u.toString();
      },
      get markdown() { return `![${this.badgeLabel || "views"}](${this.badgeUrl})`; },
      get pixel() { return `<img src="${cfg.base}/p/${cfg.ws}/${cfg.name}.gif?campaign=launch" width="1" height="1" alt="">`; },
      init() {
        this.$watch("attrs", () => this.preview());
        this.$nextTick(() => this.preview());
      },
      preview() {
        const host = this.$refs.preview;
        if (!host || !window.CountJar) return;
        host.innerHTML = `<div class="countjar" ${this.attrs.join(" ")} data-readonly data-preview></div>`;
        window.CountJar.scan(host);
      },
    }));
  });
})();
