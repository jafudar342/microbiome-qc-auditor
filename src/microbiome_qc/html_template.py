"""Self-contained HTML report template.

All dynamic values are supplied as escaped JSON and inserted into the DOM with
``textContent``; the template itself contains no sample-derived markup.
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>Microbiome QC Audit Report</title>
<style>
:root {
  --bg: #f2f6fb;
  --surface: #ffffff;
  --surface-soft: #f8fafc;
  --ink: #172033;
  --muted: #5a6a80;
  --line: #dce4ee;
  --accent: #2457d6;
  --accent-deep: #163a91;
  --pass: #147a4d;
  --pass-bg: #e6f6ed;
  --warn: #8a5a00;
  --warn-bg: #fff4d4;
  --fail: #b42318;
  --fail-bg: #fde8e6;
  --neutral: #526174;
  --neutral-bg: #edf1f6;
  --shadow: 0 12px 32px rgba(23, 32, 51, 0.08);
  --radius: 16px;
}
* { box-sizing: border-box; }
html { color-scheme: light; }
body {
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  background:
    radial-gradient(900px 380px at 10% -10%, rgba(36, 87, 214, 0.18), transparent 65%),
    radial-gradient(700px 320px at 100% 0%, rgba(20, 122, 77, 0.12), transparent 60%),
    var(--bg);
  color: var(--ink);
  line-height: 1.5;
  min-height: 100vh;
}
button, input, select { font: inherit; }
button { cursor: pointer; }
.hero {
  background: linear-gradient(122deg, #10254f 0%, #183f88 54%, #1b5d78 100%);
  color: #fff;
  padding: 38px 0 46px;
}
.shell { width: min(1320px, calc(100% - 40px)); margin: 0 auto; }
.brand { display: flex; align-items: center; gap: 14px; }
.brand-mark {
  width: 46px; height: 46px; border-radius: 13px;
  display: grid; place-items: center;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.24);
  font-weight: 800; letter-spacing: 0.04em; font-size: 0.92rem;
  backdrop-filter: blur(8px);
}
.eyebrow { text-transform: uppercase; letter-spacing: 0.13em; font-size: 0.7rem; font-weight: 700; color: rgba(255, 255, 255, 0.68); margin: 0 0 3px; }
h1 { margin: 0; font-size: clamp(1.7rem, 3vw, 2.35rem); letter-spacing: -0.025em; }
.hero p.lede { margin: 7px 0 0; color: rgba(255, 255, 255, 0.78); max-width: 760px; font-size: 0.96rem; }
.hero-meta { margin-top: 22px; display: flex; flex-wrap: wrap; gap: 8px 22px; font-size: 0.82rem; color: rgba(255, 255, 255, 0.72); }
.hero-meta strong { color: #fff; font-weight: 600; }
.path-line { margin-top: 10px; font-size: 0.78rem; color: rgba(255, 255, 255, 0.58); overflow-wrap: anywhere; }
.page { padding: 28px 0 60px; }
.cards { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 14px; margin-top: -58px; }
.card {
  background: var(--surface); border: 1px solid rgba(220, 228, 238, 0.9);
  border-radius: var(--radius); padding: 18px 18px 16px; box-shadow: var(--shadow);
  position: relative; overflow: hidden;
}
.card::after { content: ""; position: absolute; inset: 0 auto auto 0; height: 4px; width: 100%; background: var(--accent); opacity: 0.8; }
.card.pass::after { background: var(--pass); }
.card.warn::after { background: var(--warn); }
.card.fail::after { background: var(--fail); }
.card.neutral::after { background: #7d8ca1; }
.card .value { display: block; font-size: 1.95rem; font-weight: 750; letter-spacing: -0.03em; line-height: 1.15; }
.card .label { color: var(--muted); font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.075em; font-weight: 700; margin-top: 3px; }
.card .hint { color: var(--muted); font-size: 0.73rem; margin-top: 8px; }
.banner { margin-top: 20px; border-radius: 13px; padding: 13px 16px; border: 1px solid var(--line); background: var(--surface); font-size: 0.9rem; }
.banner.fail { border-color: #f2c3bd; background: #fff6f5; color: #7d1b12; }
.banner.warn { border-color: #efd89b; background: #fffaeb; color: #6b4600; }
.banner.pass { border-color: #bfe5cf; background: #f3fbf6; color: #0e5d3b; }
.panel { margin-top: 20px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.panel-head { padding: 20px 22px 0; display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; flex-wrap: wrap; }
.panel h2 { margin: 0; font-size: 1.08rem; letter-spacing: -0.01em; }
.panel h3 { margin: 20px 0 8px; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
.panel .sub { color: var(--muted); font-size: 0.82rem; margin: 4px 0 0; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 16px 22px; border-bottom: 1px solid var(--line); background: var(--surface-soft); }
.search { flex: 1 1 300px; position: relative; }
.search input {
  width: 100%; border: 1px solid #cbd6e3; background: #fff; border-radius: 10px;
  padding: 10px 13px; color: var(--ink); outline: none;
}
.search input:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(36, 87, 214, 0.13); }
select { border: 1px solid #cbd6e3; background: #fff; border-radius: 10px; padding: 9px 30px 9px 11px; color: var(--ink); }
label.filter-label { display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: 0.82rem; }
.check input { accent-color: var(--accent); }
.count { margin-left: auto; color: var(--muted); font-size: 0.8rem; white-space: nowrap; }
.table-wrap { width: 100%; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.84rem; }
th {
  text-align: left; padding: 11px 14px; background: var(--surface-soft); color: var(--muted);
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.07em; border-bottom: 1px solid var(--line);
  white-space: nowrap; position: sticky; top: 0; z-index: 1;
}
td { padding: 13px 14px; border-bottom: 1px solid #edf1f6; vertical-align: top; }
tbody tr { transition: background 120ms ease; }
tbody tr.clickable { cursor: pointer; }
tbody tr.clickable:hover { background: #f7faff; }
tbody tr:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.sample-name { font-weight: 700; overflow-wrap: anywhere; min-width: 150px; }
.small { color: var(--muted); font-size: 0.76rem; }
.badge {
  display: inline-flex; align-items: center; border-radius: 999px; padding: 3px 9px;
  font-size: 0.68rem; font-weight: 800; letter-spacing: 0.045em; white-space: nowrap;
  border: 1px solid transparent;
}
.badge.pass { color: var(--pass); background: var(--pass-bg); border-color: #bde3cc; }
.badge.warn { color: var(--warn); background: var(--warn-bg); border-color: #eed48c; }
.badge.fail { color: var(--fail); background: var(--fail-bg); border-color: #f1beb8; }
.badge.neutral { color: var(--neutral); background: var(--neutral-bg); border-color: #d7dfe9; }
.problems-cell { min-width: 220px; max-width: 380px; }
.problems-cell .text { color: #44536a; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.link-button { border: 1px solid #cbd6e3; background: #fff; color: var(--accent); border-radius: 8px; padding: 5px 9px; font-size: 0.74rem; font-weight: 700; white-space: nowrap; }
.link-button:hover { border-color: var(--accent); background: #f4f7ff; }
.empty { padding: 32px 22px; text-align: center; color: var(--muted); font-size: 0.88rem; }
.note-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 28px; padding: 4px 22px 22px; }
.note-block ul, .plain-list { margin: 0; padding-left: 20px; }
.note-block li, .plain-list li { margin: 6px 0; color: #38465a; font-size: 0.82rem; overflow-wrap: anywhere; }
.empty-note { margin: 0 0 12px; color: var(--muted); font-size: 0.82rem; font-style: italic; }
.muted { color: var(--muted); }
.callout { margin: 0 22px 22px; padding: 12px 14px; background: #f7f9fc; border-left: 3px solid #9aa9bd; border-radius: 4px; color: #45546a; font-size: 0.8rem; }
footer { margin-top: 30px; padding-top: 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 0.76rem; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
dialog.sample-dialog {
  border: none; padding: 0; border-radius: 18px; width: min(980px, calc(100vw - 32px));
  max-height: min(88vh, 980px); background: var(--surface); color: var(--ink);
  box-shadow: 0 26px 80px rgba(8, 19, 41, 0.32); overflow: hidden;
}
dialog.sample-dialog::backdrop { background: rgba(10, 20, 38, 0.56); backdrop-filter: blur(2px); }
.dialog-shell { display: flex; flex-direction: column; max-height: min(88vh, 980px); }
.dialog-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding: 20px 24px; border-bottom: 1px solid var(--line); background: var(--surface-soft); }
.dialog-head h2 { margin: 2px 0 0; font-size: 1.25rem; letter-spacing: -0.02em; overflow-wrap: anywhere; }
.close-button { border: 1px solid #cbd6e3; background: #fff; border-radius: 9px; padding: 7px 13px; font-weight: 650; color: var(--ink); }
.close-button:hover { border-color: var(--accent); color: var(--accent); }
.dialog-content { padding: 22px 24px 28px; overflow-y: auto; }
.detail-status-row { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; margin-bottom: 18px; }
.detail-section { border-top: 1px solid var(--line); padding-top: 18px; margin-top: 20px; }
.detail-section:first-child { border-top: none; padding-top: 0; margin-top: 0; }
.detail-section h3 { margin: 0 0 10px; font-size: 1rem; }
.detail-section h4 { margin: 16px 0 7px; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
.detail-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.mini-card { border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: #fcfdff; }
.mini-card-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
.mini-card h4 { margin: 0; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
.filename { font-size: 0.78rem; overflow-wrap: anywhere; color: #37465b; margin: 3px 0; }
.stat-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 10px 0 0; }
.stat { background: var(--surface-soft); border-radius: 8px; padding: 7px 8px; }
.stat dt { color: var(--muted); font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.05em; margin: 0; }
.stat dd { margin: 1px 0 0; font-weight: 700; font-size: 0.86rem; }
.detail-table { width: 100%; font-size: 0.77rem; margin-top: 8px; table-layout: fixed; }
.detail-table th, .detail-table td { padding: 8px 9px; position: static; overflow-wrap: anywhere; }
.detail-table th { background: var(--surface-soft); white-space: normal; }
.note-text { margin: 6px 0; color: #3f4e63; font-size: 0.8rem; }
.detail-list { margin: 6px 0; padding-left: 20px; }
.detail-list li { margin: 4px 0; font-size: 0.8rem; overflow-wrap: anywhere; }
.dialog-close-hint { color: var(--muted); font-size: 0.72rem; margin-top: 14px; }
[hidden] { display: none !important; }
@media (max-width: 1080px) {
  .cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1180px) {
  .table-wrap table th:nth-child(8), .table-wrap table td:nth-child(8) { display: none; }
}
@media (max-width: 1000px) {
  .table-wrap table th:nth-child(6), .table-wrap table td:nth-child(6) { display: none; }
}
@media (max-width: 900px) {
  .table-wrap table th:nth-child(3), .table-wrap table td:nth-child(3),
  .table-wrap table th:nth-child(4), .table-wrap table td:nth-child(4) { display: none; }
}
@media (max-width: 720px) {
  .shell { width: min(100% - 24px, 1320px); }
  .hero { padding: 28px 0 46px; }
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .card { padding: 15px; }
  .card .value { font-size: 1.55rem; }
  .panel-head, .toolbar { padding-left: 15px; padding-right: 15px; }
  .note-grid, .detail-columns { grid-template-columns: 1fr; }
  .count { margin-left: 0; }
  .dialog-content { padding: 18px 16px 24px; }
  .dialog-head { padding: 16px; }
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  table { font-size: 0.8rem; }
  th { padding: 10px; }
  td { padding: 11px 10px; }
  .sample-name { min-width: 130px; }
}
@media (max-width: 640px) {
  .table-wrap table th:nth-child(2), .table-wrap table td:nth-child(2) { display: none; }
  .table-wrap table th, .table-wrap table td { padding-left: 8px; padding-right: 8px; }
}
@media print {
  body { background: #fff; }
  .hero { background: #fff; color: #000; padding: 10px 0 20px; }
  .hero p.lede, .hero-meta, .path-line { color: #333; }
  .cards { margin-top: 0; }
  .toolbar, .link-button { display: none; }
  .panel { box-shadow: none; break-inside: avoid; }
  dialog.sample-dialog { display: none; }
}
</style>
</head>
<body>
<header class="hero">
  <div class="shell">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">MQ</div>
      <div>
        <p class="eyebrow">Offline quality-control report</p>
        <h1>Microbiome QC Audit</h1>
      </div>
    </div>
    <p class="lede">Paired-end FASTQ integrity, read-pair consistency, and FastQC module statuses. This report is a data-quality audit, not a biological or clinical interpretation.</p>
    <div class="hero-meta" id="hero-meta"></div>
    <div class="path-line" id="hero-paths"></div>
  </div>
</header>

<main class="shell page">
  <section class="cards" id="summary-cards" aria-label="Audit summary"></section>
  <div id="status-banner" class="banner" role="status"></div>

  <section class="panel" aria-labelledby="samples-heading">
    <div class="panel-head">
      <div>
        <h2 id="samples-heading">Sample results</h2>
        <p class="sub">Select a sample for full statistics, pairing evidence, and FastQC module results.</p>
      </div>
    </div>
    <div class="toolbar">
      <label class="search">
        <input id="search-input" type="search" placeholder="Search sample, file, or problem" aria-label="Search samples by identifier, filename, or problem">
      </label>
      <label class="filter-label">Status
        <select id="status-filter" aria-label="Filter by QC classification">
          <option value="ALL">All</option>
          <option value="PASS">PASS</option>
          <option value="WARN">WARN</option>
          <option value="FAIL">FAIL</option>
        </select>
      </label>
      <label class="filter-label check"><input id="fastqc-filter" type="checkbox"> FastQC incomplete</label>
      <span class="count" id="result-count" aria-live="polite"></span>
    </div>
    <div class="table-wrap">
      <table aria-describedby="samples-heading">
        <thead>
          <tr>
            <th scope="col">Sample</th>
            <th scope="col">Reads R1 / R2</th>
            <th scope="col">Mean length</th>
            <th scope="col">GC %</th>
            <th scope="col">Pairing</th>
            <th scope="col">FastQC</th>
            <th scope="col">Classification</th>
            <th scope="col">Problems</th>
            <th scope="col">Details</th>
          </tr>
        </thead>
        <tbody id="sample-body"></tbody>
      </table>
    </div>
    <p id="no-results" class="empty" hidden>No samples match the current filters.</p>
  </section>

  <section class="panel" aria-labelledby="evidence-heading">
    <div class="panel-head">
      <div>
        <h2 id="evidence-heading">Evidence availability and warnings</h2>
        <p class="sub">Missing evidence is shown explicitly and is never substituted with a PASS result.</p>
      </div>
    </div>
    <div class="note-grid">
      <div class="note-block"><h3>Missing FastQC reports</h3><div id="missing-reports"></div></div>
      <div class="note-block"><h3>Orphaned reads</h3><div id="orphan-reads"></div></div>
      <div class="note-block"><h3>Ambiguous samples</h3><div id="ambiguous-samples"></div></div>
      <div class="note-block"><h3>Ignored or unrecognized files</h3><div id="ignored-files"></div></div>
    </div>
    <div class="note-grid">
      <div class="note-block"><h3>Global warnings</h3><ul class="plain-list" id="warnings-list"></ul></div>
      <div class="note-block"><h3>Audit limitations</h3><ul class="plain-list" id="limitations-list"></ul></div>
    </div>
    <p class="callout" id="scope-callout"></p>
  </section>

  <footer>
    <span>Generated offline by Microbiome QC Auditor <span id="footer-version"></span>. All assets are embedded in this file.</span>
    <span id="footer-time"></span>
  </footer>
</main>

<dialog class="sample-dialog" id="sample-dialog" aria-labelledby="dialog-title">
  <div class="dialog-shell">
    <div class="dialog-head">
      <div>
        <p class="eyebrow" style="color:var(--muted);">Sample detail</p>
        <h2 id="dialog-title"></h2>
      </div>
      <button class="close-button" id="dialog-close" type="button">Close</button>
    </div>
    <div class="dialog-content" id="dialog-content"></div>
  </div>
</dialog>

<noscript><div class="shell" style="padding:20px;color:#7d1b12;background:#fff3f2;">JavaScript is required to display this interactive report. The CSV and JSON artifacts contain the same audit data.</div></noscript>

<script type="application/json" id="audit-data">__AUDIT_DATA__</script>
<script>
(function () {
  "use strict";

  var data;
  try {
    data = JSON.parse(document.getElementById("audit-data").textContent);
  } catch (error) {
    document.getElementById("status-banner").className = "banner fail";
    document.getElementById("status-banner").textContent = "The embedded audit data could not be parsed: " + error.message;
    return;
  }

  var samples = data.samples || [];
  var rowRecords = [];
  var dialog = document.getElementById("sample-dialog");
  var dialogTitle = document.getElementById("dialog-title");
  var dialogContent = document.getElementById("dialog-content");
  var countNode = document.getElementById("result-count");
  var noResults = document.getElementById("no-results");

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function append(parent) {
    for (var i = 1; i < arguments.length; i += 1) parent.appendChild(arguments[i]);
    return parent;
  }

  function formatInt(value) {
    if (value === null || value === undefined || value === "") return "\\u2014";
    return Number(value).toLocaleString("en-US");
  }

  function formatFloat(value) {
    if (value === null || value === undefined || value === "") return "\\u2014";
    return Number(value).toFixed(2);
  }

  function pct(value) {
    if (value === null || value === undefined || value === "") return "\\u2014";
    return Number(value).toFixed(2) + "%";
  }

  function classificationBadge(status) {
    var cls = status === "PASS" ? "pass" : status === "WARN" ? "warn" : status === "FAIL" ? "fail" : "neutral";
    return el("span", "badge " + cls, status || "UNKNOWN");
  }

  function pairingBadge(value) {
    var cls = value === "PASS" ? "pass" : (value === "FAIL" || value === "MISSING_MATE" || value === "AMBIGUOUS") ? "fail" : "neutral";
    return el("span", "badge " + cls, String(value || "UNKNOWN").replace(/_/g, " "));
  }

  function moduleBadge(value) {
    var cls = value === "PASS" ? "pass" : value === "WARN" ? "warn" : value === "FAIL" ? "fail" : "neutral";
    return el("span", "badge " + cls, value || "UNKNOWN");
  }

  function availabilityLabel(value) {
    var labels = {
      available: "Available", missing: "Missing", invalid: "Invalid", ambiguous: "Ambiguous",
      not_requested: "Not requested", not_applicable: "Not applicable", not_assessed: "Not assessed"
    };
    return labels[value] || (value || "Unknown");
  }

  function availabilityBadge(value) {
    var cls = value === "available" ? "pass" : value === "missing" || value === "invalid" || value === "ambiguous" || value === "not_assessed" ? "warn" : "neutral";
    return el("span", "badge " + cls, availabilityLabel(value));
  }

  function sideLabel(sample, key) {
    var names = sample[key] || [];
    return names.length ? names.join("; ") : "\\u2014";
  }

  function fastqcSummary(sample) {
    if (!data.fastqc_requested) return "Not requested";
    var parts = [];
    [["R1", sample.fastqc.r1], ["R2", sample.fastqc.r2]].forEach(function (entry) {
      var label = entry[0], side = entry[1];
      if (!side) {
        parts.push(label + ": not assessed");
      } else if (side.availability === "available") {
        parts.push(label + ": " + (side.pass_count || 0) + "P/" + (side.warn_count || 0) + "W/" + (side.fail_count || 0) + "F");
      } else {
        parts.push(label + ": " + availabilityLabel(side.availability));
      }
    });
    return parts.join(" \\u00b7 ");
  }

  function fastqcIncomplete(sample) {
    if (!data.fastqc_requested) return true;
    return !sample.fastqc || !sample.fastqc.r1 || !sample.fastqc.r2 ||
      sample.fastqc.r1.availability !== "available" || sample.fastqc.r2.availability !== "available";
  }

  function problemsSummary(sample) {
    var reasons = (sample.classification && sample.classification.reasons) || [];
    if (!reasons.length) return "None detected";
    if (reasons.length === 1) return reasons[0];
    return reasons[0] + " (+" + (reasons.length - 1) + " more)";
  }

  function statsFor(sample, key) {
    var side = sample[key];
    return side && side.stats ? side.stats : null;
  }

  function buildCards() {
    var counts = data.counts || {};
    var definitions = [
      { label: "Samples", value: counts.discovered_samples, tone: "neutral", hint: "Discovered pairs or candidates" },
      { label: "PASS", value: counts.pass, tone: "pass", hint: "No detected integrity or FastQC concerns" },
      { label: "WARN", value: counts.warn, tone: "warn", hint: "Nonfatal evidence or FastQC concerns" },
      { label: "FAIL", value: counts.fail, tone: "fail", hint: "Structural or pairing failure" },
      { label: "Missing FastQC", value: counts.missing_fastqc_reports, tone: "warn", hint: data.fastqc_requested ? "Reports expected but absent" : "FastQC not requested" },
      { label: "Orphan reads", value: counts.orphaned_reads, tone: "neutral", hint: "Files without a mate" }
    ];
    var container = document.getElementById("summary-cards");
    definitions.forEach(function (definition) {
      var card = el("div", "card " + definition.tone);
      append(card,
        el("span", "label", definition.label),
        el("span", "value", formatInt(definition.value)),
        el("span", "hint", definition.hint)
      );
      container.appendChild(card);
    });
  }

  function buildBanner() {
    var counts = data.counts || {};
    var banner = document.getElementById("status-banner");
    if (counts.fail > 0) {
      banner.className = "banner fail";
      banner.textContent = counts.fail + " sample(s) failed structural or pairing checks. Investigate these files before downstream analysis; FastQC PASS cannot override integrity failures.";
    } else if (counts.warn > 0) {
      banner.className = "banner warn";
      banner.textContent = counts.warn + " sample(s) have nonfatal QC concerns or missing FastQC evidence. Review the WARN details before downstream analysis.";
    } else {
      banner.className = "banner pass";
      banner.textContent = data.fastqc_requested
        ? "All discovered samples passed the structural, pairing, and supplied FastQC checks."
        : "All discovered samples passed the structural and pairing checks. FastQC was not requested, so FastQC evidence was not assessed.";
    }
  }

  function buildSampleTable() {
    var body = document.getElementById("sample-body");
    body.replaceChildren();
    rowRecords = [];

    samples.forEach(function (sample, index) {
      var status = sample.classification ? sample.classification.status : "UNKNOWN";
      var r1 = statsFor(sample, "r1");
      var r2 = statsFor(sample, "r2");
      var row = el("tr", "clickable");

      var sampleCell = el("td", "sample-name");
      append(sampleCell, el("div", "", sample.sample_id), el("div", "small", "R1: " + sideLabel(sample, "r1_filenames")), el("div", "small", "R2: " + sideLabel(sample, "r2_filenames")));
      row.appendChild(sampleCell);

      row.appendChild(el("td", "", r1 || r2 ? formatInt(r1 ? r1.total_reads : null) + " / " + formatInt(r2 ? r2.total_reads : null) : "\\u2014"));
      row.appendChild(el("td", "", r1 || r2 ? formatFloat(r1 ? r1.mean_length : null) + " / " + formatFloat(r2 ? r2.mean_length : null) : "\\u2014"));
      row.appendChild(el("td", "", r1 || r2 ? pct(r1 ? r1.gc_percent : null) + " / " + pct(r2 ? r2.gc_percent : null) : "\\u2014"));

      var pairingCell = el("td");
      pairingCell.appendChild(pairingBadge(sample.pairing ? sample.pairing.result : "NOT_CHECKED"));
      row.appendChild(pairingCell);

      var fastqcCell = el("td");
      append(fastqcCell, el("div", "small", fastqcSummary(sample)));
      row.appendChild(fastqcCell);

      var statusCell = el("td");
      statusCell.appendChild(classificationBadge(status));
      row.appendChild(statusCell);

      var problemText = problemsSummary(sample);
      var problemCell = el("td", "problems-cell");
      var problemTextNode = el("div", "text", problemText);
      problemTextNode.title = problemText;
      problemCell.appendChild(problemTextNode);
      row.appendChild(problemCell);

      var actionCell = el("td");
      var detailsButton = el("button", "link-button", "View");
      detailsButton.type = "button";
      detailsButton.setAttribute("aria-label", "View details for " + sample.sample_id);
      detailsButton.addEventListener("click", function (event) {
        event.stopPropagation();
        openSample(index);
      });
      actionCell.appendChild(detailsButton);
      row.appendChild(actionCell);

      row.addEventListener("click", function () { openSample(index); });
      body.appendChild(row);

      var haystack = [
        sample.sample_id,
        (sample.r1_filenames || []).join(" "),
        (sample.r2_filenames || []).join(" "),
        ((sample.classification && sample.classification.reasons) || []).join(" "),
        fastqcSummary(sample)
      ].join(" ").toLowerCase();
      rowRecords.push({ element: row, status: status, haystack: haystack, incomplete: fastqcIncomplete(sample) });
    });
  }

  function applyFilters() {
    var query = document.getElementById("search-input").value.trim().toLowerCase();
    var status = document.getElementById("status-filter").value;
    var fastqcOnly = document.getElementById("fastqc-filter").checked;
    var visible = 0;
    rowRecords.forEach(function (record) {
      var matches = (!query || record.haystack.indexOf(query) !== -1) &&
        (status === "ALL" || record.status === status) &&
        (!fastqcOnly || record.incomplete);
      record.element.hidden = !matches;
      if (matches) visible += 1;
    });
    countNode.textContent = visible + " of " + rowRecords.length + " samples shown";
    noResults.hidden = visible !== 0;
  }

  function statGrid(entries) {
    var grid = el("dl", "stat-grid");
    entries.forEach(function (entry) {
      var stat = el("div", "stat");
      append(stat, el("dt", "", entry[0]), el("dd", "", entry[1]));
      grid.appendChild(stat);
    });
    return grid;
  }

  function listNode(items, emptyText, className) {
    if (!items || !items.length) return el("p", "empty-note", emptyText);
    var list = el("ul", className || "detail-list");
    items.forEach(function (item) { list.appendChild(el("li", "", item)); });
    return list;
  }

  function fileCard(sample, key, label) {
    var card = el("div", "mini-card");
    var scan = sample[key];
    var head = el("div", "mini-card-head");
    var heading = el("h4", "", label);
    head.appendChild(heading);
    if (scan) {
      head.appendChild(el("span", "badge " + (scan.valid ? "pass" : "fail"), scan.valid ? "VALID" : "INVALID"));
    } else {
      head.appendChild(el("span", "badge neutral", "NO FILE"));
    }
    card.appendChild(head);

    var names = sample[key + "_filenames"] || [];
    if (names.length) {
      names.forEach(function (name) { card.appendChild(el("p", "filename", name)); });
    } else {
      card.appendChild(el("p", "filename muted", "No file discovered for this read direction."));
    }

    if (!scan) {
      card.appendChild(el("p", "note-text", "No FASTQ statistics or identifier evidence are available."));
      return card;
    }
    var stats = scan.stats || {};
    card.appendChild(statGrid([
      ["Reads", formatInt(stats.total_reads)],
      ["Total bases", formatInt(stats.total_bases)],
      ["Mean length", formatFloat(stats.mean_length)],
      ["Min length", formatInt(stats.min_length)],
      ["Max length", formatInt(stats.max_length)],
      ["GC %", pct(stats.gc_percent)]
    ]));
    if (scan.errors && scan.errors.length) {
      card.appendChild(listNode(scan.errors, "", "detail-list"));
    }
    return card;
  }

  function pairingSection(sample) {
    var section = el("section", "detail-section");
    section.appendChild(el("h3", "", "Pairing and integrity"));
    var row = el("div", "detail-status-row");
    append(row, el("span", "small", "Result:"), pairingBadge(sample.pairing ? sample.pairing.result : "NOT_CHECKED"));
    if (sample.pairing && sample.pairing.mismatch_count !== null && sample.pairing.mismatch_count !== undefined) {
      row.appendChild(el("span", "small", "Identifier mismatches: " + formatInt(sample.pairing.mismatch_count)));
    }
    section.appendChild(row);
    if (sample.pairing && sample.pairing.details) {
      section.appendChild(el("p", "note-text", sample.pairing.details));
    }
    if (sample.pairing && sample.pairing.mismatches && sample.pairing.mismatches.length) {
      var table = el("table", "detail-table");
      var colgroup = el("colgroup");
      [18, 26, 26, 30].forEach(function (width) {
        var col = el("col");
        col.style.width = width + "%";
        colgroup.appendChild(col);
      });
      var thead = el("thead");
      var headerRow = el("tr");
      ["Record", "R1 identifier", "R2 identifier", "Reason"].forEach(function (heading) {
        headerRow.appendChild(el("th", "", heading));
      });
      thead.appendChild(headerRow);
      var tbody = el("tbody");
      sample.pairing.mismatches.forEach(function (mismatch) {
        var tr = el("tr");
        append(tr,
          el("td", "", formatInt(mismatch.record_number)),
          el("td", "", mismatch.r1_id),
          el("td", "", mismatch.r2_id),
          el("td", "", mismatch.reason)
        );
        tbody.appendChild(tr);
      });
      append(table, colgroup, thead, tbody);
      section.appendChild(table);
    }
    var errors = sample.pairing && sample.pairing.errors ? sample.pairing.errors : [];
    if (errors.length) section.appendChild(listNode(errors, "", "detail-list"));
    return section;
  }

  function fastqcSideBlock(label, side) {
    var card = el("div", "mini-card");
    var head = el("div", "mini-card-head");
    head.appendChild(el("h4", "", label + " FastQC"));
    if (side) head.appendChild(availabilityBadge(side.availability));
    card.appendChild(head);

    if (!side) {
      card.appendChild(el("p", "note-text", "No FastQC association result is available."));
      return card;
    }
    if (!data.fastqc_requested) {
      card.appendChild(el("p", "note-text", "FastQC was not requested for this audit. This is missing evidence, not a PASS."));
      return card;
    }
    if (side.report) {
      card.appendChild(el("p", "filename", side.report.report_name));
      if (side.report.available) {
        card.appendChild(el("p", "note-text", "Modules: " + formatInt(side.pass_count) + " PASS, " + formatInt(side.warn_count) + " WARN, " + formatInt(side.fail_count) + " FAIL. FastQC Total Sequences: " + formatInt(side.report.total_sequences) + "."));
        if (side.report.modules && side.report.modules.length) {
          var table = el("table", "detail-table");
          var colgroup = el("colgroup");
          [72, 28].forEach(function (width) {
            var col = el("col");
            col.style.width = width + "%";
            colgroup.appendChild(col);
          });
          var thead = el("thead");
          var headerRow = el("tr");
          append(headerRow, el("th", "", "Module"), el("th", "", "Status"));
          thead.appendChild(headerRow);
          var tbody = el("tbody");
          side.report.modules.forEach(function (module) {
            var tr = el("tr");
            append(tr, el("td", "", module.module), el("td", "", moduleBadge(module.status)));
            tbody.appendChild(tr);
          });
          append(table, colgroup, thead, tbody);
          card.appendChild(table);
        }
      } else {
        card.appendChild(el("p", "note-text", "The FastQC archive exists but is unusable; statuses are unavailable, not PASS."));
      }
    } else {
      card.appendChild(el("p", "note-text", "No matching FastQC archive was associated with this read direction."));
    }
    if (side.issues && side.issues.length) {
      card.appendChild(listNode(side.issues, "", "detail-list"));
    }
    return card;
  }

  function openSample(index) {
    var sample = samples[index];
    if (!sample) return;
    dialogTitle.textContent = sample.sample_id;
    dialogContent.replaceChildren();

    var statusRow = el("div", "detail-status-row");
    statusRow.appendChild(classificationBadge(sample.classification ? sample.classification.status : "UNKNOWN"));
    append(statusRow, el("span", "small", "Sample-level FASTQ FAIL is reserved for structural or pairing corruption; FastQC FAIL modules are reported as sample WARN."));
    dialogContent.appendChild(statusRow);

    var problemSection = el("section", "detail-section");
    problemSection.appendChild(el("h3", "", "Problems and classification evidence"));
    var reasons = (sample.classification && sample.classification.reasons) || [];
    problemSection.appendChild(listNode(reasons, "No problems were detected in the evidence audited.", "detail-list"));
    dialogContent.appendChild(problemSection);

    var fileSection = el("section", "detail-section");
    fileSection.appendChild(el("h3", "", "FASTQ files and statistics"));
    var columns = el("div", "detail-columns");
    append(columns, fileCard(sample, "r1", "R1"), fileCard(sample, "r2", "R2"));
    fileSection.appendChild(columns);
    fileSection.appendChild(el("p", "note-text", "GC denominator: A+C+G+T. N and other symbols are excluded. Means are rounded to two decimal places."));
    dialogContent.appendChild(fileSection);

    dialogContent.appendChild(pairingSection(sample));

    var fastqcSection = el("section", "detail-section");
    fastqcSection.appendChild(el("h3", "", "FastQC modules"));
    var fastqcColumns = el("div", "detail-columns");
    append(fastqcColumns, fastqcSideBlock("R1", sample.fastqc.r1), fastqcSideBlock("R2", sample.fastqc.r2));
    fastqcSection.appendChild(fastqcColumns);
    fastqcSection.appendChild(el("p", "dialog-close-hint", "Press Escape or use Close to return to the sample table."));
    dialogContent.appendChild(fastqcSection);

    dialog.showModal();
    dialogContent.scrollTop = 0;
  }

  function buildEvidence() {
    var missing = data.missing_fastqc_reports || [];
    var missingNode = document.getElementById("missing-reports");
    if (!data.fastqc_requested) {
      missingNode.appendChild(el("p", "empty-note", "FastQC was not requested (--fastqc-dir was omitted). FastQC evidence was not assessed."));
    } else {
      missingNode.replaceChildren();
      missingNode.appendChild(listNode(missing.map(function (item) {
        return item.sample_id + " " + item.read_direction + ": " + item.reason;
      }), "No expected FastQC reports were missing.", "plain-list"));
    }

    var orphans = data.orphaned_reads || [];
    var orphanNode = document.getElementById("orphan-reads");
    orphanNode.appendChild(listNode(orphans.map(function (item) {
      return item.filename + " (sample " + item.sample_id + ", " + item.read_direction + ")";
    }), "No orphaned read files were found.", "plain-list"));

    var ambiguous = data.ambiguous_samples || [];
    var ambiguousNode = document.getElementById("ambiguous-samples");
    ambiguousNode.appendChild(listNode(ambiguous.map(function (item) {
      return item.sample_id + " \\u2014 R1: " + ((item.r1_filenames || []).join(", ") || "none") + "; R2: " + ((item.r2_filenames || []).join(", ") || "none");
    }), "No ambiguous samples were found.", "plain-list"));

    var ignored = data.ignored_or_unrecognized_files || [];
    var ignoredNode = document.getElementById("ignored-files");
    ignoredNode.appendChild(listNode(ignored.map(function (item) {
      return item.message;
    }), "No ignored or unrecognized files were found.", "plain-list"));

    var warningsNode = document.getElementById("warnings-list");
    warningsNode.replaceChildren();
    var warnings = data.warnings || [];
    if (!warnings.length) {
      warningsNode.appendChild(el("li", "muted", "No global warnings."));
    } else {
      warnings.forEach(function (warning) { warningsNode.appendChild(el("li", "", warning)); });
    }

    var limitationsNode = document.getElementById("limitations-list");
    limitationsNode.replaceChildren();
    (data.limitations || []).forEach(function (limitation) {
      limitationsNode.appendChild(el("li", "", limitation));
    });

    document.getElementById("scope-callout").textContent = data.fastqc_requested
      ? "This audit verifies data integrity and copies FastQC statuses; it does not re-run FastQC, validate module calculations, align reads, or assess biological or clinical significance."
      : "This audit verifies data integrity only. FastQC was not run or supplied, so FastQC module evidence is absent and no sample is fully FastQC-validated.";
  }

  function buildHero() {
    var counts = data.counts || {};
    var meta = document.getElementById("hero-meta");
    append(meta,
      el("span", "", "Audit: " + (data.audit_timestamp || "unknown")),
      el("span", "", "Tool: " + (data.tool ? data.tool.name + " " + data.tool.version : "unknown")),
      el("span", "", "Samples: " + formatInt(counts.discovered_samples)),
      el("span", "", "FastQC: " + (data.fastqc_requested ? "requested" : "not requested"))
    );
    var paths = document.getElementById("hero-paths");
    paths.textContent = "FASTQ: " + (data.input_paths.fastq_dir || "") + "  |  FastQC: " + (data.input_paths.fastqc_dir || "not provided") + "  |  Output: " + (data.output_paths.output_dir || "");
    document.getElementById("footer-version").textContent = data.tool ? data.tool.version : "";
    document.getElementById("footer-time").textContent = "Audit timestamp: " + (data.audit_timestamp || "unknown");
  }

  document.getElementById("search-input").addEventListener("input", applyFilters);
  document.getElementById("status-filter").addEventListener("change", applyFilters);
  document.getElementById("fastqc-filter").addEventListener("change", applyFilters);
  document.getElementById("dialog-close").addEventListener("click", function () { dialog.close(); });
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) dialog.close();
  });

  buildHero();
  buildCards();
  buildBanner();
  buildSampleTable();
  buildEvidence();
  applyFilters();
})();
</script>
</body>
</html>
"""
