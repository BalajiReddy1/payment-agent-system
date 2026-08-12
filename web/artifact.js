/*
 * Shared-snapshot client.
 *
 * The live console streams; this one replays a captured session so the shared
 * page shows behaviour rather than a still frame. The interesting thing about
 * this system is a curve — success rate falling, the agent intervening, the
 * curve recovering — and a static screenshot cannot show that.
 *
 * Render functions are intentionally the same shape as app.js so the two stay
 * recognisably one product.
 */

const $ = (id) => document.getElementById(id);

const pct = (v, d = 1) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(d)}%`);
const ms = (v) => (v ? `${Math.round(v)}ms` : '—');
const int = (v) => (v ?? 0).toLocaleString('en-US');
const clock = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};
const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const title = (s) => String(s ?? '').replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());

const history = SNAPSHOT.history || [];

/* ── Sparkline ─────────────────────────────────────────────────────────────
 * A sparkline is a word, not a chart: which way is this going, nothing else.
 * An area fill under the line and an emphasised endpoint give it enough
 * weight to read at this size without becoming a figure in its own right. */
function sparkline(el, values, { invert = false } = {}) {
  if (!el || values.length < 2) return;
  const W = 240, H = 30, pad = 4;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;

  const xy = values.map((v, i) => [
    (i / (values.length - 1)) * W,
    pad + (1 - (v - lo) / span) * (H - pad * 2),
  ]);

  const line = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${xy[0][0]},${H} ${line} ${xy[xy.length - 1][0]},${H}`;

  const rising = values[values.length - 1] >= values[0];
  const good = invert ? !rising : rising;
  const stroke = span === 0 ? 'var(--ink-4)' : good ? 'var(--settled)' : 'var(--failing)';
  const [ex, ey] = xy[xy.length - 1];

  el.innerHTML = `
    <polygon points="${area}" fill="${stroke}" opacity="0.07" />
    <polyline points="${line}" fill="none" stroke="${stroke}" stroke-width="1.5"
      stroke-linejoin="round" stroke-linecap="round" />
    <circle cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="2" fill="${stroke}" />`;
}

/* ── Static panels ─────────────────────────────────────────────────────────*/

function renderIssuers() {
  const host = $('issuers');
  const rows = SNAPSHOT.issuers || [];
  if (!rows.length) { host.innerHTML = '<div class="empty">No traffic.</div>'; return; }

  host.innerHTML = rows.map((r) => {
    const level = r.success_rate < 0.80 ? 'bad' : r.success_rate < 0.90 ? 'warn' : 'ok';
    return `
      <div class="row row-issuer" data-level="${level}">
        <div class="row-name">
          ${esc(r.issuer.replace(/_/g, ' '))}
          ${r.broken ? '<span class="chip failing">broken</span>' : ''}
        </div>
        <div class="gauge"><i style="width:${(r.success_rate * 100).toFixed(1)}%" data-level="${level}"></i></div>
        <div class="val num">${pct(r.success_rate)}</div>
        <div class="val dim num">${int(r.volume)}</div>
      </div>`;
  }).join('');
}

/* An intervention that expires and is re-applied appends to the incident
 * again. Show distinct actions with a count; a repeated row of identical
 * chips reads as a rendering bug rather than as history. */
function actionChips(actions) {
  if (!actions || !actions.length) return '<span class="chip">no action yet</span>';
  const counts = actions.reduce((acc, a) => ((acc[a] = (acc[a] || 0) + 1), acc), {});
  return Object.entries(counts)
    .map(([a, n]) => `<span class="chip accent">${esc(title(a))}${n > 1 ? ` ×${n}` : ''}</span>`)
    .join(' ');
}

function renderIncidents() {
  const host = $('incidents');
  const rows = SNAPSHOT.incidents || [];
  if (!rows.length) { host.innerHTML = '<div class="empty">No incidents.</div>'; return; }

  host.innerHTML = rows.map((i) => {
    const level = !i.active ? 'ok' : i.peak_severity >= 0.7 ? 'bad' : i.peak_severity >= 0.4 ? 'warn' : '';
    const chip = level === 'bad' ? 'failing' : level === 'warn' ? 'watch' : '';
    return `
      <div class="incident" data-level="${level}">
        <div class="incident-head">
          <span class="incident-id">${esc(i.incident_id)}</span>
          <span class="incident-title">${esc(title(i.pattern_type))} · ${esc(i.target.replace(/_/g, ' '))}</span>
          <span class="chip ${i.active ? chip : 'settled'}">${i.active ? 'open' : 'resolved'}</span>
        </div>
        <div class="incident-meta">
          <span>peak severity <b class="num">${i.peak_severity.toFixed(2)}</b></span>
          <span>${int(i.detections)} detections</span>
          <span>${Math.round(i.duration_seconds)}s</span>
          ${actionChips(i.actions_taken)}
        </div>
        ${i.advice ? `<div class="incident-advice"><b>Agent assessment</b>${esc(i.advice)}</div>` : ''}
      </div>`;
  }).join('');
}

/* The trace shows the alternatives that lost, which is what distinguishes a
 * reasoning agent from a rules engine. */
function renderDecisions() {
  const host = $('decisions');
  const rows = SNAPSHOT.decisions || [];
  if (!rows.length) { host.innerHTML = '<div class="empty">No interventions.</div>'; return; }

  host.innerHTML = rows.map((d, idx) => {
    const sections = parseReasoning(d.reasoning);
    return `
      <details class="trace" ${idx === 0 ? 'open' : ''}>
        <summary class="trace-summary">
          <svg class="caret" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M3 1.5 L7 5 L3 8.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="trace-action">${esc(title(d.type))}</span>
          <span class="trace-target">${esc(d.target.replace(/_/g, ' '))}</span>
          <span class="chip ${d.success ? 'settled' : 'failing'}">${d.success ? 'applied' : 'refused'}</span>
          <time class="trace-time">${clock(d.at)}</time>
        </summary>
        <div class="trace-detail">
          ${sections.length
            ? sections.map((s) => `
                <h4 class="micro">${esc(s.heading)}</h4>
                <ul>${s.lines.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>`).join('')
            : `<p>${esc(d.message)}</p>`}
          <h4 class="micro">Parameters</h4>
          <p><code>${esc(JSON.stringify(d.parameters))}</code></p>
        </div>
      </details>`;
  }).join('');
}

function parseReasoning(text) {
  if (!text) return [];
  const out = [];
  let cur = null;
  for (const raw of String(text).split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith('## ')) { cur = { heading: line.slice(3).trim(), lines: [] }; out.push(cur); }
    else if (cur) cur.lines.push(line.replace(/^[-•]\s*/, ''));
  }
  return out.filter((s) => s.lines.length);
}

function renderExperiments() {
  const host = $('experiments');
  const rows = SNAPSHOT.experiments || [];
  if (!rows.length) { host.innerHTML = '<div class="empty">No experiments.</div>'; return; }

  host.innerHTML = rows.map((e) => {
    const t = e.treatment, c = e.control;
    const tRate = t.total ? t.successes / t.total : 0;
    const cRate = c.total ? c.successes / c.total : 0;
    return `
      <div class="experiment">
        <div class="experiment-head">
          <span class="incident-id">${esc(e.experiment_id)}</span>
          <span class="incident-title">${esc(title(e.action_type))} · ${esc(e.target.replace(/_/g, ' '))}</span>
          <span class="chip ${e.significant ? 'settled' : ''}">${e.significant ? 'significant' : 'gathering'}</span>
        </div>
        <div class="arm">
          <span class="micro">Treated</span>
          <div class="gauge"><i style="width:${(tRate * 100).toFixed(1)}%"></i></div>
          <span class="arm-value">${pct(tRate)} <span style="color:var(--ink-3)">${int(t.total)}</span></span>
        </div>
        <div class="arm">
          <span class="micro">Control</span>
          <div class="gauge"><i style="width:${(cRate * 100).toFixed(1)}%" data-level="${cRate < 0.80 ? 'bad' : cRate < 0.90 ? 'warn' : 'ok'}"></i></div>
          <span class="arm-value">${pct(cRate)} <span style="color:var(--ink-3)">${int(c.total)}</span></span>
        </div>
        ${e.lift_ci ? interval(e.lift_ci, e.lift) : ''}
        <div class="ci-caption">${esc(e.verdict)}</div>
      </div>`;
  }).join('');
}

/* Draw the interval, not the point. +12% means something very different when
 * the interval is [+10,+14] than when it is [-3,+27], and a bare number hides
 * exactly the thing that decides whether the result means anything. */
function interval(ci, point) {
  const [lo, hi] = ci;
  const bound = Math.max(Math.abs(lo), Math.abs(hi), 0.05) * 1.15;
  const at = (v) => (((v + bound) / (2 * bound)) * 100).toFixed(2);
  return `
    <div class="ci">
      <div class="ci-zero" style="left:${at(0)}%"></div>
      <div class="ci-range" style="left:${at(lo)}%;width:${(at(hi) - at(lo)).toFixed(2)}%"></div>
      <div class="ci-point" style="left:${at(point)}%"></div>
    </div>`;
}

function renderRevisions() {
  const host = $('revisions');
  const rows = SNAPSHOT.control_plane?.history || [];
  if (!rows.length) { host.innerHTML = '<div class="empty">No policy changes.</div>'; return; }

  host.innerHTML = rows.map((r) => `
    <div class="revision">
      <div class="revision-no">r${r.revision}</div>
      <div>
        <div class="revision-reason">${esc(r.reason)}</div>
        <div class="revision-author">${esc(r.author)} · ${clock(r.at)}</div>
        ${r.changes.map((c) => {
          const cls = c.startsWith('+') ? 'add' : c.startsWith('-') ? 'remove' : '';
          return `<div class="revision-change ${cls}">${esc(c)}</div>`;
        }).join('')}
      </div>
    </div>`).join('');
}

/* ── Replay ────────────────────────────────────────────────────────────────*/

const PHASE_NOTE = {
  observing: 'Watching the stream. No intervention in force.',
  monitoring: 'An intervention is live and being measured.',
  mitigating: 'Incident open. The agent is acting on it now.',
};

/* Phase is derived from the captured timeline: before the first intervention
 * the agent was observing, during an open incident it was mitigating. */
function phaseAt(index) {
  const point = history[index];
  if (!point) return 'observing';
  if (point.actions > 0 || point.patterns > 2) return 'mitigating';
  const acted = history.slice(0, index + 1).some((h) => h.actions > 0);
  return acted ? 'monitoring' : 'observing';
}

function paintFrame(index) {
  const point = history[index];
  if (!point) return;

  const window = history.slice(0, index + 1);
  const phase = phaseAt(index);

  $('phase').textContent = phase;
  $('state').dataset.phase = phase;
  $('phase-note').textContent = PHASE_NOTE[phase];

  $('cycle').textContent = int(point.cycle);
  $('m-success').textContent = pct(point.success_rate);
  $('m-latency').textContent = ms(point.latency_p95);
  $('m-txns').textContent = int(point.transactions);
  $('m-patterns').textContent = int(point.patterns);
  $('m-window-note').textContent = '5 minute window';

  const prior = history[index - 1];
  if (prior) {
    setDelta($('m-success-delta'), (point.success_rate - prior.success_rate) * 100, 'pts', 1);
    setDelta($('m-latency-delta'), prior.latency_p95 - point.latency_p95, 'ms faster', 0);
  } else {
    $('m-success-delta').textContent = '';
    $('m-latency-delta').textContent = '';
  }

  sparkline($('spark-success'), window.map((h) => h.success_rate));
  sparkline($('spark-latency'), window.map((h) => h.latency_p95), { invert: true });

  // Counters accumulate, so scale them to how far through the replay we are
  const share = (index + 1) / history.length;
  const c = SNAPSHOT.counters || {};
  const traffic = SNAPSHOT.traffic || {};
  $('revision').textContent = `r${Math.round((SNAPSHOT.control_plane?.revision || 0) * share)}`;
  $('stat-actions').textContent = int(Math.round((c.actions_executed || 0) * share));
  $('stat-alerts').textContent = int(Math.round((c.alerts_raised || 0) * share));
  $('stat-rerouted').textContent = int(Math.round((traffic.rerouted || 0) * share));
  $('stat-holdout').textContent = int(Math.round((traffic.held_out || 0) * share));

  $('scrub').value = String(index);
  $('replay-note').textContent =
    `Cycle ${point.cycle} of ${history[history.length - 1].cycle} · recorded run`;
}

function setDelta(el, value, unit, digits) {
  if (!el) return;
  if (Math.abs(value) < (digits ? 0.05 : 5)) {
    el.textContent = 'steady';
    el.className = 'reading-delta';
    return;
  }
  el.textContent = `${value > 0 ? '+' : ''}${value.toFixed(digits)} ${unit}`;
  el.className = 'reading-delta ' + (value > 0 ? 'up' : 'down');
}

let cursor = 0;
let timer = null;

function play() {
  stop();
  timer = setInterval(() => {
    cursor = (cursor + 1) % history.length;
    paintFrame(cursor);
  }, 700);
  $('play').textContent = 'Pause';
}

function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  $('play').textContent = 'Play';
}

function init() {
  renderIssuers();
  renderIncidents();
  renderDecisions();
  renderExperiments();
  renderRevisions();

  if (!history.length) return;

  $('scrub').max = String(history.length - 1);
  $('scrub').addEventListener('input', (event) => {
    stop();
    cursor = Number(event.target.value);
    paintFrame(cursor);
  });
  $('play').addEventListener('click', () => (timer ? stop() : play()));

  paintFrame(0);

  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (still) {
    cursor = history.length - 1;
    paintFrame(cursor);
    stop();
  } else {
    play();
  }
}

init();
