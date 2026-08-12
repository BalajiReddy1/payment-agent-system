/*
 * Console client.
 *
 * No framework, no build step — the agent core has no third-party
 * dependencies and this keeps the same promise, so `python web/server.py` is
 * the whole setup. Rendering is a plain diff-free redraw at 2s intervals;
 * at this data volume that is cheaper than a virtual DOM and has no tearing.
 *
 * State arrives over server-sent events. The console is pushed to rather than
 * polling, because an operations view that is seconds stale is misleading in
 * exactly the moments it matters.
 */

const $ = (id) => document.getElementById(id);

const pct = (v, digits = 1) =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`;
const ms = (v) => (v ? `${Math.round(v)}ms` : '—');
const int = (v) => (v ?? 0).toLocaleString('en-US');
const clock = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};
const escape = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const title = (s) => String(s ?? '').replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());

let previous = null;

/* ── Sparklines ─────────────────────────────────────────────────────────────
 * Drawn as a plain polyline with no axis. A sparkline is a word, not a chart:
 * it answers "which way is this going" and nothing else.                     */
function sparkline(el, values, { invert = false } = {}) {
  if (!el || values.length < 2) return;
  const W = 240, H = 30, pad = 3;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * W;
    const norm = (v - lo) / span;
    const y = pad + (1 - norm) * (H - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = values[values.length - 1];
  const first = values[0];
  const rising = last >= first;
  const good = invert ? !rising : rising;
  const stroke = span === 0
    ? 'var(--ink-4)'
    : good ? 'var(--settled)' : 'var(--failing)';

  el.innerHTML = `
    <polyline fill="none" stroke="${stroke}" stroke-width="1.5"
      stroke-linejoin="round" stroke-linecap="round" points="${points.join(' ')}" />`;
}

/* ── Renderers ─────────────────────────────────────────────────────────────*/

const PHASE_NOTE = {
  observing:  'Watching the stream. No intervention in force.',
  monitoring: 'An intervention is live and being measured.',
  mitigating: 'Incident open. The agent is acting on it now.',
};

function renderRail(s) {
  $('phase').textContent = s.agent.phase;
  $('state').dataset.phase = s.agent.phase;
  $('phase-note').textContent = PHASE_NOTE[s.agent.phase] ?? '';
  $('cycle').textContent = int(s.agent.cycle);
  $('revision').textContent = `r${s.control_plane.revision}`;
  $('window').textContent = `${s.agent.window_minutes ?? '—'}m`;
  $('stat-actions').textContent = int(s.counters.actions_executed);
  $('stat-alerts').textContent = int(s.counters.alerts_raised);
  $('stat-rerouted').textContent = int(s.traffic.rerouted);
  $('stat-holdout').textContent = int(s.traffic.held_out);
}

function renderMetrics(s) {
  const history = s.history;
  $('m-success').textContent = pct(s.metrics.success_rate);
  $('m-latency').textContent = ms(s.metrics.latency?.p95);
  $('m-txns').textContent = int(s.metrics.transactions);
  $('m-retry').textContent = pct(s.metrics.retry_efficiency, 0);

  if (previous) {
    delta($('m-success-delta'), s.metrics.success_rate - previous.metrics.success_rate, 'pts', 1);
    delta($('m-latency-delta'), (previous.metrics.latency?.p95 ?? 0) - (s.metrics.latency?.p95 ?? 0), 'ms faster', 0);
  }

  $('m-window-note').textContent = `${s.agent.window_minutes ?? '—'} minute window`;
  $('m-retry-note').textContent = 'of retries that succeed';

  sparkline($('spark-success'), history.map((h) => h.success_rate));
  sparkline($('spark-latency'), history.map((h) => h.latency_p95), { invert: true });
}

function delta(el, value, unit, digits) {
  if (!el) return;
  const scaled = unit === 'pts' ? value * 100 : value;
  if (Math.abs(scaled) < (digits ? 0.05 : 5)) {
    el.textContent = 'steady';
    el.className = 'reading-delta';
    return;
  }
  el.textContent = `${scaled > 0 ? '+' : ''}${scaled.toFixed(digits)} ${unit}`;
  el.className = 'reading-delta ' + (scaled > 0 ? 'up' : 'down');
}

function renderIssuers(s) {
  const host = $('issuers');
  if (!s.issuers.length) return;

  host.innerHTML = s.issuers.map((row) => {
    const rate = row.success_rate;
    const level = rate < 0.80 ? 'bad' : rate < 0.90 ? 'warn' : 'ok';
    return `
      <div class="row row-issuer" data-level="${level}">
        <div class="row-name">
          ${escape(row.issuer.replace(/_/g, ' '))}
          ${row.broken ? '<span class="chip failing">broken</span>' : ''}
        </div>
        <div class="gauge"><i style="width:${(rate * 100).toFixed(1)}%" data-level="${level}"></i></div>
        <div class="val num">${pct(rate, 1)}</div>
        <div class="val dim num">${int(row.volume)}</div>
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
    .map(([a, n]) => `<span class="chip accent">${escape(title(a))}${n > 1 ? ` ×${n}` : ''}</span>`)
    .join(' ');
}

function renderIncidents(s) {
  const host = $('incidents');
  const open = s.incidents.filter((i) => i.active);
  const recent = s.incidents.filter((i) => !i.active).slice(0, 3);
  const shown = [...open, ...recent];

  if (!shown.length) {
    host.innerHTML = '<div class="empty">No incidents. The agent is observing.</div>';
    return;
  }

  host.innerHTML = shown.map((i) => {
    const level = !i.active ? 'ok' : i.peak_severity >= 0.7 ? 'bad' : i.peak_severity >= 0.4 ? 'warn' : '';
    const severity = level === 'bad' ? 'failing' : level === 'warn' ? 'watch' : '';
    return `
      <div class="incident" data-level="${level}">
        <div class="incident-head">
          <span class="incident-id">${escape(i.incident_id)}</span>
          <span class="incident-title">${escape(title(i.pattern_type))} · ${escape(i.target.replace(/_/g, ' '))}</span>
          <span class="chip ${i.active ? severity : 'settled'}">${i.active ? 'open' : 'resolved'}</span>
        </div>
        <div class="incident-meta">
          <span>peak severity <b class="num">${i.peak_severity.toFixed(2)}</b></span>
          <span>${int(i.detections)} detections</span>
          <span>${Math.round(i.duration_seconds)}s</span>
          ${actionChips(i.actions_taken)}
        </div>
        ${i.advice ? `<div class="incident-advice"><b>Agent assessment</b>${escape(i.advice)}</div>` : ''}
      </div>`;
  }).join('');
}

/* The decision trace is the screen that proves this is reasoning rather than
 * a rules engine, so it shows the alternatives that lost, not only the winner. */
/* Approvals are the one panel that asks something of the reader, so it sits
 * above the trace and hides itself entirely when the queue is empty rather
 * than showing a permanent "nothing to do" box. */
function renderApprovals(s) {
  const panel = $('approvals-panel');
  const host = $('approvals');
  const pending = (s.approvals || []).filter((a) => a.status === 'pending');

  panel.hidden = pending.length === 0;
  if (!pending.length) return;

  host.innerHTML = pending.map((a) => {
    const left = a.seconds_remaining;
    return `
      <div class="row approval" data-level="warn">
        <div>
          <div class="row-name">
            ${escape(title(a.action_type))} · ${escape(a.target.replace(/_/g, ' '))}
            <span class="chip watch">${escape(a.authorization.replace(/_/g, '-'))}</span>
          </div>
          <div class="approval-meta">
            <span class="incident-id">${escape(a.request_id)}</span>
            <span>risk ${escape(a.risk_level)}</span>
            <span>blast radius ${pct(a.blast_radius, 1)}</span>
            <span>expected ${a.expected_lift >= 0 ? '+' : ''}${(a.expected_lift * 100).toFixed(1)} pts</span>
            ${left !== null && left !== undefined ? `<span>lapses in ${Math.round(left)}s</span>` : ''}
          </div>
        </div>
        <div class="controls">
          <button class="primary" data-approve="${escape(a.request_id)}">Approve</button>
          <button data-deny="${escape(a.request_id)}">Deny</button>
        </div>
      </div>`;
  }).join('');
}

function renderDecisions(s) {
  const host = $('decisions');
  if (!s.decisions.length) {
    host.innerHTML = '<div class="empty">No interventions yet.</div>';
    return;
  }

  host.innerHTML = s.decisions.map((d, idx) => {
    const sections = parseReasoning(d.reasoning);
    return `
      <details class="trace" ${idx === 0 ? 'open' : ''}>
        <summary class="trace-summary">
          <svg class="caret" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M3 1.5 L7 5 L3 8.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="trace-action">${escape(title(d.type))}</span>
          <span class="trace-target">${escape(d.target.replace(/_/g, ' '))}</span>
          <span class="chip ${d.success ? 'settled' : 'failing'}">${d.success ? 'applied' : 'refused'}</span>
          <time class="trace-time">${clock(d.at)}</time>
        </summary>
        <div class="trace-detail">
          ${sections.length
            ? sections.map((sec) => `
                <h4 class="micro">${escape(sec.heading)}</h4>
                <ul>${sec.lines.map((l) => `<li>${escape(l)}</li>`).join('')}</ul>`).join('')
            : `<p>${escape(d.message)}</p>`}
          <h4 class="micro">Parameters</h4>
          <p><code>${escape(JSON.stringify(d.parameters))}</code></p>
        </div>
      </details>`;
  }).join('');
}

/* The agent writes reasoning as markdown-ish sections; parse them back so the
 * console can present structure rather than a wall of text. */
function parseReasoning(text) {
  if (!text) return [];
  const sections = [];
  let current = null;
  for (const raw of String(text).split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith('## ')) {
      current = { heading: line.slice(3).trim(), lines: [] };
      sections.push(current);
    } else if (current) {
      current.lines.push(line.replace(/^[-•]\s*/, ''));
    }
  }
  return sections.filter((s) => s.lines.length);
}

function renderExperiments(s) {
  const host = $('experiments');
  if (!s.experiments.length) {
    host.innerHTML = '<div class="empty">No experiments running.</div>';
    return;
  }

  host.innerHTML = s.experiments.map((e) => {
    const t = e.treatment, c = e.control;
    const tRate = t.total ? t.successes / t.total : 0;
    const cRate = c.total ? c.successes / c.total : 0;
    const ci = e.lift_ci;

    return `
      <div class="experiment">
        <div class="experiment-head">
          <span class="incident-id">${escape(e.experiment_id)}</span>
          <span class="incident-title">${escape(title(e.action_type))} · ${escape(e.target.replace(/_/g, ' '))}</span>
          <span class="chip ${e.significant ? 'settled' : ''}">${e.significant ? 'significant' : 'gathering'}</span>
        </div>

        <div class="arm">
          <span class="micro">Treated</span>
          <div class="gauge"><i style="width:${(tRate * 100).toFixed(1)}%"></i></div>
          <span class="arm-value">${pct(tRate, 1)} <span style="color:var(--ink-3)">${int(t.total)}</span></span>
        </div>
        <div class="arm">
          <span class="micro">Control</span>
          <div class="gauge"><i style="width:${(cRate * 100).toFixed(1)}%" data-level="${cRate < 0.80 ? 'bad' : cRate < 0.90 ? 'warn' : 'ok'}"></i></div>
          <span class="arm-value">${pct(cRate, 1)} <span style="color:var(--ink-3)">${int(c.total)}</span></span>
        </div>

        ${ci ? confidenceInterval(ci, e.lift) : ''}
        <div class="ci-caption">${escape(e.verdict)}</div>
      </div>`;
  }).join('');
}

/* Draw the interval, not the point estimate. A lift of +12% means something
 * different when the interval is [+10,+14] than when it is [-3,+27], and a
 * bare number hides exactly that. */
function confidenceInterval(ci, point) {
  const [lo, hi] = ci;
  const bound = Math.max(Math.abs(lo), Math.abs(hi), 0.05) * 1.15;
  const toPct = (v) => ((v + bound) / (2 * bound)) * 100;
  return `
    <div class="ci">
      <div class="ci-zero" style="left:${toPct(0).toFixed(2)}%"></div>
      <div class="ci-range" style="left:${toPct(lo).toFixed(2)}%;width:${(toPct(hi) - toPct(lo)).toFixed(2)}%"></div>
      <div class="ci-point" style="left:${toPct(point).toFixed(2)}%"></div>
    </div>`;
}

function renderRevisions(s) {
  const host = $('revisions');
  const entries = s.control_plane.history;
  if (!entries.length) {
    host.innerHTML = '<div class="empty">No policy changes.</div>';
    return;
  }

  host.innerHTML = entries.map((r) => `
    <div class="revision">
      <div class="revision-no">r${r.revision}</div>
      <div>
        <div class="revision-reason">${escape(r.reason)}</div>
        <div class="revision-author">${escape(r.author)} · ${clock(r.at)}</div>
        ${r.changes.map((c) => {
          const cls = c.startsWith('+') ? 'add' : c.startsWith('-') ? 'remove' : '';
          return `<div class="revision-change ${cls}">${escape(c)}</div>`;
        }).join('')}
      </div>
    </div>`).join('');
}

function renderIssuerOptions(s) {
  const select = $('issuer-select');
  if (select.options.length || !s.issuers.length) return;
  select.innerHTML = s.issuers
    .map((r) => `<option value="${escape(r.issuer)}">${escape(r.issuer.replace(/_/g, ' '))}</option>`)
    .join('');
}

function render(snapshot) {
  renderRail(snapshot);
  renderMetrics(snapshot);
  renderIssuers(snapshot);
  renderIssuerOptions(snapshot);
  renderIncidents(snapshot);
  renderApprovals(snapshot);
  renderDecisions(snapshot);
  renderExperiments(snapshot);
  renderRevisions(snapshot);
  previous = snapshot;
}

/* ── Transport ──────────────────────────────────────────────────────────────*/

function connect() {
  const source = new EventSource('/api/stream');

  source.onmessage = (event) => {
    try {
      render(JSON.parse(event.data));
    } catch (err) {
      console.error('bad snapshot', err);
    }
  };

  source.onerror = () => {
    // EventSource reconnects on its own; fall back to a single fetch so the
    // console shows something rather than freezing on a stale frame.
    fetch('/api/snapshot').then((r) => r.json()).then(render).catch(() => {});
  };
}

document.addEventListener('click', async (event) => {
  const decision = event.target.closest('[data-approve], [data-deny]');
  if (decision) {
    const approve = decision.hasAttribute('data-approve');
    decision.disabled = true;
    await fetch('/api/approval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: decision.dataset.approve || decision.dataset.deny,
        verdict: approve ? 'approve' : 'deny',
        approver: 'console-operator',
      }),
    }).catch(() => {});
    fetch('/api/snapshot').then((r) => r.json()).then(render).catch(() => {});
    return;
  }

  const button = event.target.closest('[data-scenario]');
  if (!button) return;

  const type = button.dataset.scenario;
  const body = { type };
  if (type === 'issuer_degradation') {
    body.issuer = $('issuer-select').value;
    body.severity = 0.75;
  }

  $('scenario-status').textContent = 'injecting…';
  try {
    await fetch('/api/scenario', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    $('scenario-status').textContent =
      type === 'clear' ? 'cleared' : `${title(type)} injected — watch the agent find it`;
  } catch {
    $('scenario-status').textContent = 'could not reach the agent';
  }
  setTimeout(() => ($('scenario-status').textContent = ''), 6000);
});

fetch('/api/snapshot').then((r) => r.json()).then(render).catch(() => {});
connect();
