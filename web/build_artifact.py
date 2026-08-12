"""
Build the shareable console snapshot.

Produces a single self-contained HTML file from the live stylesheet and a
captured session, so the shared version cannot drift away from the real
console's design: both read the same styles.css.

Usage:
    python web/server.py 8098 &        # run the console
    curl -s localhost:8098/api/snapshot > session.json
    python web/build_artifact.py session.json out.html
"""

import json
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent

PAGE = """<title>Payment Operations Console</title>
<style>
{styles}

/* ── Shared-snapshot additions ─────────────────────────────────────────────
   The published version replays a captured session rather than streaming a
   live one, so it needs a transport control and an honest label. Everything
   else is the console's own stylesheet, unmodified. */

.replay {{ display: flex; align-items: center; gap: var(--s3); }}
.replay input[type="range"] {{
  flex: 1; min-width: 0; accent-color: var(--accent); cursor: pointer;
}}
.capture-note {{
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--ink-3);
}}
.controls button:disabled {{
  opacity: 0.45; cursor: not-allowed;
}}
.capture-note::before {{
  content: ""; width: 5px; height: 5px; border-radius: 50%;
  background: var(--ink-4);
}}
</style>

<div class="frame">
  <aside class="rail">
    <div class="rail-brand">
      <div class="name">Payment Operations</div>
      <div class="sub">Autonomous mitigation console</div>
    </div>

    <div class="state" id="state" data-phase="observing">
      <div class="state-phase" id="phase">observing</div>
      <div class="state-note" id="phase-note"></div>
    </div>

    <div class="rail-stats">
      <div class="rail-stat"><span class="k">Cycle</span><span class="v num" id="cycle">—</span></div>
      <div class="rail-stat"><span class="k">Policy</span><span class="v num" id="revision">r0</span></div>
      <div class="rail-stat"><span class="k">Interventions</span><span class="v num" id="stat-actions">—</span></div>
      <div class="rail-stat"><span class="k">Alerts</span><span class="v num" id="stat-alerts">—</span></div>
      <div class="rail-stat"><span class="k">Rerouted</span><span class="v num" id="stat-rerouted">—</span></div>
      <div class="rail-stat"><span class="k">Held out</span><span class="v num" id="stat-holdout">—</span></div>
    </div>

    <div class="panel">
      <div class="panel-head"><span class="capture-note">Captured session</span></div>
      <div class="panel-body">
        <div class="replay">
          <button id="play" class="primary">Pause</button>
          <input type="range" id="scrub" min="0" max="0" value="0" aria-label="Replay position">
        </div>
        <div class="state-note" id="replay-note"></div>
      </div>
    </div>
  </aside>

  <main class="grid">
    <section class="grid metrics-row">
      <div class="panel reading-block">
        <div class="micro">Success rate</div>
        <div class="reading-value" id="m-success">—</div>
        <div class="reading-delta" id="m-success-delta"></div>
        <svg class="spark" id="spark-success" viewBox="0 0 240 30" preserveAspectRatio="none" aria-hidden="true"></svg>
      </div>
      <div class="panel reading-block">
        <div class="micro">Latency p95</div>
        <div class="reading-value" id="m-latency">—</div>
        <div class="reading-delta" id="m-latency-delta"></div>
        <svg class="spark" id="spark-latency" viewBox="0 0 240 30" preserveAspectRatio="none" aria-hidden="true"></svg>
      </div>
      <div class="panel reading-block">
        <div class="micro">In window</div>
        <div class="reading-value" id="m-txns">—</div>
        <div class="reading-delta" id="m-window-note"></div>
      </div>
      <div class="panel reading-block">
        <div class="micro">Patterns detected</div>
        <div class="reading-value" id="m-patterns">—</div>
        <div class="reading-delta">this cycle</div>
      </div>
    </section>

    <section class="grid two">
      <div class="panel">
        <div class="panel-head"><span class="micro">Issuer health</span><span class="hint">Worst first</span></div>
        <div class="panel-body flush" id="issuers"></div>
      </div>
      <div class="panel">
        <div class="panel-head"><span class="micro">Incidents</span><span class="hint">Detections collapsed into events</span></div>
        <div class="panel-body flush scroll" id="incidents"></div>
      </div>
    </section>

    <section class="panel" id="approvals-panel" hidden>
      <div class="panel-head">
        <span class="micro">Awaiting authorization</span>
        <span class="hint">The agent decided these are needed but may not run them alone</span>
      </div>
      <div class="panel-body flush" id="approvals"></div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <span class="micro">Decision trace</span>
        <span class="hint">Every alternative that was scored, not only the one chosen</span>
      </div>
      <div class="panel-body scroll" id="decisions"></div>
    </section>

    <section class="grid two">
      <div class="panel">
        <div class="panel-head"><span class="micro">Measured effect</span><span class="hint">Treated vs held-out control</span></div>
        <div class="panel-body flush scroll" id="experiments"></div>
      </div>
      <div class="panel">
        <div class="panel-head"><span class="micro">Policy history</span><span class="hint">Append-only, attributed</span></div>
        <div class="panel-body flush scroll" id="revisions"></div>
      </div>
    </section>

    <p class="note">
      Traffic is synthetic; the control plane is real. Every intervention here was
      chosen by the agent, written to a versioned policy document that the traffic
      source reads, and measured against a concurrent holdout &mdash; a slice of
      traffic deliberately left unprotected so the effect can be attributed to the
      action rather than to the incident ending on its own.
    </p>
  </main>
</div>

<script>
const SNAPSHOT = {snapshot};
{script}
</script>
"""


def build(snapshot_path: Path, out_path: Path):
    styles = (WEB / 'styles.css').read_text()
    script = (WEB / 'artifact.js').read_text()
    snapshot = json.loads(snapshot_path.read_text())

    out_path.write_text(PAGE.format(
        styles=styles,
        script=script,
        snapshot=json.dumps(snapshot, separators=(',', ':')),
    ))
    size = out_path.stat().st_size
    print(f'wrote {out_path} ({size / 1024:.0f} KB)')


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]))
