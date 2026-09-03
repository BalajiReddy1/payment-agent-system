"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Icon } from "@/components/ui/icon";
import { Mark } from "@/components/ui/mark";
import { onScrollFrame } from "@/lib/in-view";
import { readSetup } from "@/lib/setup";
import type { AgentSnapshot, Experiment } from "@/lib/types";

const number = new Intl.NumberFormat("en-IN");
const percent = new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 1 });
const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

const SECTIONS = ["overview", "decision", "evidence", "network", "record"] as const;
type SectionId = (typeof SECTIONS)[number];

function words(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

/* A real sparkline from the runtime history, not a decorative squiggle. */
function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const path = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * 100;
      const y = 28 - ((value - min) / span) * 24;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const falling = points[points.length - 1] < points[0];

  return (
    <svg className="spark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
      <path d={path} fill="none" stroke={falling ? "var(--signal)" : "var(--proof)"} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function RouteDiagram({ route, degraded, rate }: { route: string; degraded: boolean; rate: number }) {
  const nodes = ["Buyer", "Merchant", "Gateway", route];
  return (
    <div className="route" data-degraded={degraded}>
      <div className="route-line" aria-hidden="true">
        <span className="route-flow" />
      </div>
      <ol className="route-nodes">
        {nodes.map((node, index) => (
          <li key={node} data-terminal={index === nodes.length - 1}>
            <span className="route-dot" />
            <span className="mono">{node}</span>
          </li>
        ))}
      </ol>
      <div className="route-readout">
        <span className="mono">Route success</span>
        <strong className="num">{percent.format(rate)}</strong>
        <small className="mono">{degraded ? "outside expected range" : "inside expected range"}</small>
      </div>
    </div>
  );
}

/*
  The runtime emits its reasoning as small markdown sections. Rendering the raw
  string is a wall of text, and this is the part of the desk an operator is most
  likely to have to defend later, so it gets parsed into its actual structure.
*/
function Reasoning({ text }: { text: string }) {
  if (!text.includes("## ")) return <p>{text}</p>;

  const sections = text
    .split(/\n?##\s+/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => {
      const [title, ...rest] = chunk.split("\n");
      const lines = rest.map((line) => line.trim()).filter(Boolean);
      return {
        title,
        items: lines.filter((line) => line.startsWith("- ")).map((line) => line.slice(2)),
        pairs: lines
          .filter((line) => !line.startsWith("- ") && line.includes(": "))
          .map((line) => {
            const at = line.indexOf(": ");
            return [line.slice(0, at), line.slice(at + 2)] as const;
          }),
      };
    });

  return (
    <div className="reasoning">
      {sections.map((section) => (
        <section key={section.title}>
          <h4>{section.title}</h4>
          {section.pairs.length > 0 && (
            <dl>
              {section.pairs.map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          )}
          {section.items.length > 0 && (
            <ul>
              {section.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}

function Measurement({ experiment }: { experiment?: Experiment }) {
  if (!experiment) {
    return (
      <section className="panel" id="evidence">
        <header className="panel-head">
          <h2>Measurement</h2>
          <span className="tag">no sample yet</span>
        </header>
        <p className="panel-copy">
          Control traffic is being retained. Nothing is reported until the treated and untreated groups can actually be
          compared.
        </p>
      </section>
    );
  }

  const treated = experiment.treatment.total ? experiment.treatment.successes / experiment.treatment.total : 0;
  const control = experiment.control.total ? experiment.control.successes / experiment.control.total : 0;
  const recovery = experiment.recovery;

  return (
    <section className="panel" id="evidence" data-reveal="up">
      <header className="panel-head">
        <h2>Measurement</h2>
        <span className="tag" data-tone={experiment.significant ? "proof" : undefined}>
          {experiment.significant ? "significant" : "gathering"}
        </span>
      </header>

      <div className="bars">
        <div className="bar-row">
          <span>Treated</span>
          <span className="bar-track">
            <i data-tone="proof" style={{ width: `${treated * 100}%` }} />
          </span>
          <b className="num">{percent.format(treated)}</b>
        </div>
        <div className="bar-row">
          <span>Holdout</span>
          <span className="bar-track">
            <i style={{ width: `${control * 100}%` }} />
          </span>
          <b className="num">{percent.format(control)}</b>
        </div>
      </div>

      <div className="lift">
        <span>Lift over control</span>
        <strong className="num">{experiment.lift === null ? "not yet" : percent.format(experiment.lift)}</strong>
      </div>

      <p className="panel-fine mono">
        {number.format(experiment.treatment.total)} treated · {number.format(experiment.control.total)} control
        {experiment.p_value != null ? ` · p ${experiment.p_value.toFixed(3)}` : ""}
      </p>

      {recovery && (
        <dl className="money">
          <div>
            <dt>Value at risk</dt>
            <dd className="num">{money.format(recovery.at_risk)}</dd>
          </div>
          <div>
            <dt>{recovery.claimable ? "Recovered vs control" : "Estimate, not claimed"}</dt>
            <dd className="num" data-tone={recovery.claimable ? "proof" : undefined}>
              {money.format(recovery.recovered)}
            </dd>
          </div>
        </dl>
      )}
    </section>
  );
}

function Offline({ retry, loading }: { retry: () => void; loading: boolean }) {
  return (
    <main className="desk-offline">
      <div className="desk-offline-inner">
        <a className="wordmark" href="/">
          <Mark />
          Flowstate
        </a>
        <span className="tag" data-tone="signal">
          api unreachable
        </span>
        <h1>The desk is waiting for its runtime.</h1>
        <p className="lead">
          Start the FastAPI service on port 8000 and this view fills with live payment activity. No sample data is shown
          here, because a recovery desk that invents numbers is worse than an empty one.
        </p>
        <pre className="mono desk-cmd">uvicorn api.main:app --reload</pre>
        <div className="desk-offline-actions">
          <button className="btn" data-variant="solid" onClick={retry} disabled={loading}>
            Try again
            <Icon name="refresh" />
          </button>
          <a className="btn" data-variant="outline" href="/">
            Back to the site
          </a>
        </div>
      </div>
    </main>
  );
}

export function OperationsConsole() {
  const [snapshot, setSnapshot] = useState<AgentSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [active, setActive] = useState<SectionId>("overview");
  const [needsSetup, setNeedsSetup] = useState(false);
  const hasSnapshot = Boolean(snapshot);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/agent/snapshot", { cache: "no-store" });
      if (!response.ok) throw new Error();
      setSnapshot((await response.json()) as AgentSnapshot);
    } catch {
      setSnapshot(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    setNeedsSetup(readSetup() === null);
  }, []);

  useEffect(() => {
    const syncHash = () => {
      const id = window.location.hash.slice(1) as SectionId;
      setActive(SECTIONS.includes(id) ? id : "overview");
    };
    syncHash();
    window.addEventListener("hashchange", syncHash);
    window.addEventListener("popstate", syncHash);
    return () => {
      window.removeEventListener("hashchange", syncHash);
      window.removeEventListener("popstate", syncHash);
    };
  }, []);

  useEffect(() => {
    if (!hasSnapshot) return;

    const sections = SECTIONS.map((id) => document.getElementById(id)).filter(
      (section): section is HTMLElement => section !== null,
    );

    // The last section whose top has passed the reading line is the current one.
    return onScrollFrame(() => {
      const line = window.innerHeight * 0.32;
      let current = sections[0];
      for (const section of sections) {
        if (section.getBoundingClientRect().top <= line) current = section;
      }
      const id = current?.id as SectionId | undefined;
      if (!id || !SECTIONS.includes(id)) return;
      setActive((existing) => (existing === id ? existing : id));
      if (window.location.hash !== `#${id}`) window.history.replaceState(null, "", `#${id}`);
    });
  }, [hasSnapshot]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 5_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const issuers = useMemo(
    () => (snapshot ? [...snapshot.issuers].sort((a, b) => a.success_rate - b.success_rate) : []),
    [snapshot],
  );

  async function request(path: string, body: object, success: string) {
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch(`/api/agent/${path}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error();
      setNotice(success);
      await refresh();
    } catch {
      setNotice("The API did not complete this request. Check the service and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (!snapshot) return <Offline retry={() => void refresh()} loading={loading} />;

  // Worst active route first. Ordering by arrival can surface a decline-code
  // cluster ahead of the issuer that is actually down.
  const incident =
    [...snapshot.incidents].filter((item) => item.active).sort((a, b) => b.peak_severity - a.peak_severity)[0] ??
    snapshot.incidents[0];
  const approval = snapshot.approvals[0];
  const testScenario = snapshot.scenarios.find((scenario) => scenario.type === "issuer_degradation");
  const experiment = snapshot.experiments[0];
  const decision = snapshot.decisions[0];
  const routeName = incident ? words(incident.target) : "Payment network";
  // Prefer the route's measured success rate. Deriving it from peak severity
  // reports 0% for a fully degraded issuer that is still completing payments.
  const routeIssuer = incident ? snapshot.issuers.find((item) => item.issuer === incident.target) : undefined;
  const routeRate = routeIssuer
    ? routeIssuer.success_rate
    : incident
      ? Math.max(0, 1 - incident.peak_severity)
      : snapshot.metrics.success_rate;
  const approver = readSetup()?.approver ?? "ops@flowstate.local";
  const fromAdvisor = Boolean(incident?.advice);

  return (
    <div className="desk">
      <a className="skip" href="#overview">
        Skip to the incident
      </a>

      <aside className="desk-rail">
        <a className="wordmark" href="/">
          <Mark />
          Flowstate
        </a>

        <div className="desk-live">
          <span className="dot" data-tone={incident?.active ? "signal" : "proof"} />
          <span className="mono">
            {snapshot.agent.active ? words(snapshot.agent.phase) : "Idle"} · cycle {snapshot.agent.cycle}
          </span>
        </div>

        <div className="desk-lane" data-on={snapshot.agent.advisor}>
          <Icon name="spark" width={12} height={12} />
          <span className="mono">{snapshot.agent.advisor ? snapshot.agent.advisor_model : "advisor off"}</span>
        </div>

        <nav className="desk-nav" aria-label="Desk sections">
          {SECTIONS.map((id, index) => (
            <a
              key={id}
              href={`#${id}`}
              data-selected={active === id}
              aria-current={active === id ? "location" : undefined}
              onClick={() => setActive(id)}
            >
              <span className="num">{String(index + 1).padStart(2, "0")}</span>
              {words(id)}
            </a>
          ))}
        </nav>

        <div className="desk-rail-foot">
          <a className="link" href="/onboarding">
            Setup
            <Icon name="arrow" width={14} height={14} />
          </a>
          <a className="link" href="/">
            About Flowstate
            <Icon name="arrow" width={14} height={14} />
          </a>
        </div>
      </aside>

      <main className="desk-main">
        <header className="desk-head">
          <div className="desk-head-meta">
            <span className="mono">Payment operations · India</span>
            <strong>
              <span className="num">{number.format(snapshot.metrics.transactions)}</span> payments in the current{" "}
              {snapshot.agent.window_minutes} minute window
            </strong>
          </div>
          <div className="desk-head-actions">
            <button
              className="btn"
              data-variant="solid"
              data-size="sm"
              disabled={busy}
              onClick={() =>
                void request("demo/run", {}, "Demo complete. The decision receipt and measurement are below.")
              }
            >
              <Icon name="play" width={13} height={13} />
              Run demo
            </button>
            <button className="icon-btn" onClick={() => void refresh()} aria-label="Refresh payment data">
              <Icon name="refresh" />
            </button>
          </div>
        </header>

        {needsSetup && (
          <div className="desk-strip" role="note">
            <span>
              Running on defaults. Set the blast radius, approver and holdout so the desk matches how your team actually
              operates.
            </span>
            <a className="link" href="/onboarding">
              Open setup
              <Icon name="arrow" width={14} height={14} />
            </a>
            <button className="icon-btn" onClick={() => setNeedsSetup(false)} aria-label="Dismiss setup prompt">
              <Icon name="close" width={14} height={14} />
            </button>
          </div>
        )}

        {notice && (
          <div className="desk-notice" role="status">
            <span>{notice}</span>
            <button onClick={() => setNotice(null)} aria-label="Dismiss notification">
              <Icon name="close" width={14} height={14} />
            </button>
          </div>
        )}

        {/* -------------------------------------------------- overview */}
        <section className="desk-hero" id="overview">
          <div className="desk-hero-copy">
            <span className="tag" data-tone={incident?.active ? "signal" : "proof"}>
              <Icon name={incident?.active ? "warning" : "check"} width={13} height={13} />
              {incident?.active ? "Route degraded" : "All routes stable"}
            </span>
            <h1>{incident ? `${routeName} recovery` : "Payment routes are stable"}</h1>
            <p className="lead">
              {incident
                ? `${words(incident.pattern_type)} detected in the current window at ${percent.format(incident.latest_confidence)} confidence.`
                : "No payment route is outside its expected range. The desk is watching and holding."}
            </p>
            {incident && <span className="mono desk-case">{incident.incident_id}</span>}
          </div>

          <RouteDiagram route={routeName} degraded={Boolean(incident?.active)} rate={routeRate} />
        </section>

        <dl className="desk-metrics">
          <div>
            <dt>Success rate</dt>
            <dd className="num">{percent.format(snapshot.metrics.success_rate)}</dd>
            <Sparkline points={snapshot.history.map((entry) => entry.success_rate)} />
          </div>
          <div>
            <dt>Latency p95</dt>
            <dd className="num">{Math.round(snapshot.metrics.latency.p95)} ms</dd>
            <Sparkline points={snapshot.history.map((entry) => entry.latency_p95)} />
          </div>
          <div>
            <dt>Retry efficiency</dt>
            <dd className="num">{percent.format(snapshot.metrics.retry_efficiency)}</dd>
          </div>
          <div>
            <dt>Actions taken</dt>
            <dd className="num">{number.format(snapshot.counters.actions_executed)}</dd>
          </div>
          <div>
            <dt>Held out</dt>
            <dd className="num">{number.format(snapshot.traffic.held_out)}</dd>
          </div>
        </dl>

        {/* -------------------------------------------------- decision */}
        <div className="desk-split">
          <section className="panel" id="decision" data-reveal="up">
            <header className="panel-head">
              <h2>{approval ? "Proposed response" : "Decision record"}</h2>
              <span className="tag">revision {snapshot.control_plane.revision}</span>
            </header>

            <p className="panel-copy">
              {approval
                ? `${words(approval.action_type)} on ${words(approval.target)} sits inside the policy boundary and is waiting for an operator.`
                : testScenario
                  ? "An incident is open. The record fills in once the observation window closes."
                  : incident?.actions_taken.length
                    ? `${words(incident.actions_taken[0])} is active within the approved scope.`
                    : "No response has been published. Doing nothing was the ranked choice."}
            </p>

            {approval ? (
              <div className="approval">
                <dl>
                  <div>
                    <dt>Action</dt>
                    <dd>{words(approval.action_type)}</dd>
                  </div>
                  <div>
                    <dt>Authorization</dt>
                    <dd>{words(approval.authorization)}</dd>
                  </div>
                  <div>
                    <dt>Expected lift</dt>
                    <dd className="num">{percent.format(approval.expected_lift)}</dd>
                  </div>
                  <div>
                    <dt>Expires in</dt>
                    <dd className="num">
                      {Math.max(1, Math.ceil((approval.seconds_remaining ?? 0) / 60))} min
                    </dd>
                  </div>
                </dl>
                <div className="approval-buttons">
                  <button
                    className="btn"
                    data-variant="solid"
                    disabled={busy}
                    onClick={() =>
                      void request(
                        `approvals/${approval.request_id}/approve`,
                        { approver },
                        "Response approved and published as a new revision.",
                      )
                    }
                  >
                    Approve response
                    <Icon name="arrow" />
                  </button>
                  <button
                    className="btn"
                    data-variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void request(
                        `approvals/${approval.request_id}/deny`,
                        { approver },
                        "Response denied. Nothing was published.",
                      )
                    }
                  >
                    Deny
                  </button>
                </div>
                <p className="panel-fine mono">attributed to {approver}</p>
              </div>
            ) : (
              !testScenario && (
                <button
                  className="btn"
                  data-variant="outline"
                  disabled={busy}
                  onClick={() =>
                    void request(
                      "scenarios/inject",
                      { type: "issuer_degradation", issuer: "ICICI_BANK", severity: 0.82, duration_seconds: 300 },
                      "Incident created. The decision record updates when the observation window closes.",
                    )
                  }
                >
                  Create test incident
                  <Icon name="arrow" />
                </button>
              )
            )}
          </section>

          <Measurement experiment={experiment} />
        </div>

        {/* --------------------------------------------------- network */}
        <section className="panel wide" id="network" data-reveal="up">
          <header className="panel-head">
            <h2>Route health</h2>
            <span className="mono">worst first</span>
          </header>

          <table className="routes">
            <thead>
              <tr>
                <th scope="col">Route</th>
                <th scope="col">Success rate</th>
                <th scope="col">Volume</th>
                <th scope="col">p95</th>
                <th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {issuers.map((issuer) => (
                // `broken` is the routing state, not the health of the route, so
                // the rate colours itself and the state column stays separate.
                <tr key={issuer.issuer} data-failing={issuer.success_rate < 0.75}>
                  <th scope="row">{words(issuer.issuer)}</th>
                  <td>
                    <span className="route-rate">
                      <span className="bar-track sm">
                        <i
                          data-tone={issuer.success_rate < 0.75 ? undefined : "proof"}
                          style={{ width: `${issuer.success_rate * 100}%` }}
                        />
                      </span>
                      <b className="num">{percent.format(issuer.success_rate)}</b>
                    </span>
                  </td>
                  <td className="num">{number.format(issuer.volume)}</td>
                  <td className="num">{Math.round(issuer.p95)} ms</td>
                  <td>
                    <span className="tag" data-tone={issuer.broken ? "signal" : undefined}>
                      {issuer.broken ? "rerouted" : "normal"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* ---------------------------------------------------- record */}
        <section className="panel wide" id="record" data-reveal="up">
          <header className="panel-head">
            <h2>Decision receipt</h2>
            <span className="mono">what changed, and why</span>
          </header>

          <div className="receipt-cols">
            <article>
              <h3>Observed</h3>
              <strong>{incident ? `${words(incident.pattern_type)} on ${words(incident.target)}` : "No open incident"}</strong>
              <p>
                {incident
                  ? `${percent.format(incident.latest_confidence)} confidence, severity ${Math.round(incident.peak_severity * 100)} of 100.`
                  : "Every route is inside its expected range."}
              </p>
            </article>
            <article>
              <h3>Response</h3>
              <strong>
                {decision
                  ? `${words(decision.type)} on ${words(decision.target)}`
                  : approval
                    ? `${words(approval.action_type)} requested`
                    : "No action proposed"}
              </strong>
              <p>
                {approval
                  ? `Held for ${words(approval.authorization)} approval.`
                  : decision?.message || "No policy change has been published."}
              </p>
            </article>
            <article>
              <h3>Measured outcome</h3>
              <strong>
                {experiment?.recovery
                  ? experiment.recovery.claimable
                    ? `${money.format(experiment.recovery.recovered)} recovered against control`
                    : experiment.verdict
                  : "Measurement has not started"}
              </strong>
              <p>
                {experiment
                  ? `${number.format(experiment.treatment.total)} treated and ${number.format(experiment.control.total)} control payments.`
                  : "A holdout is retained as soon as a response goes live."}
              </p>
            </article>
          </div>

          <div className="assessment">
            <div className="assessment-source">
              <h3>Assessment</h3>
              {fromAdvisor ? (
                <>
                  <span className="tag" data-tone="proof">
                    <Icon name="spark" width={12} height={12} />
                    {snapshot.agent.advisor_model ?? "model"}
                  </span>
                  <small>Written by the advisor. It has no tools and cannot change routing.</small>
                </>
              ) : (
                <>
                  <span className="tag" data-tone={incident?.advice_unavailable ? "signal" : undefined}>
                    detector
                  </span>
                  <small>
                    {incident?.advice_unavailable ??
                      (snapshot.agent.advisor
                        ? "The advisor has not written on this incident yet."
                        : "No advisor is configured, so the deterministic lane speaks for itself.")}
                  </small>
                </>
              )}
            </div>
            <Reasoning
              text={
                incident?.advice ||
                decision?.reasoning ||
                "The deterministic detector and policy engine completed this response. No model assessment was attached."
              }
            />
          </div>

          <ol className="revisions">
            {snapshot.control_plane.history.slice(0, 4).map((item) => (
              <li key={item.revision}>
                <span className="num">r{item.revision}</span>
                <div>
                  <strong>{item.reason}</strong>
                  <p>{item.changes.join(" · ") || "Recorded for measurement"}</p>
                </div>
                <small className="mono">{item.author}</small>
              </li>
            ))}
          </ol>
        </section>
      </main>
    </div>
  );
}
