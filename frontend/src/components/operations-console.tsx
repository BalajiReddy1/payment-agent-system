"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { AgentSnapshot, Experiment } from "@/lib/types";

const number = new Intl.NumberFormat("en-IN");
const percent = new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 1 });
const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const links = ["overview", "decision", "evidence", "network", "record"] as const;

type IconName = "arrow" | "check" | "close" | "refresh" | "shield" | "warning";

function words(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function Icon({ name }: { name: IconName }) {
  const paths = {
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    check: <path d="m5 12 4.2 4.2L19.5 6" />,
    close: <path d="m7 7 10 10M17 7 7 17" />,
    refresh: <><path d="M20 11a8.1 8.1 0 0 0-14.2-4.6L4 8.2" /><path d="M4 4.2v4h4" /><path d="M4 13a8.1 8.1 0 0 0 14.2 4.6l1.8-1.8" /><path d="M20 19.8v-4h-4" /></>,
    shield: <><path d="M12 3.5 19 6v5.3c0 4.1-2.8 7.5-7 9.2-4.2-1.7-7-5.1-7-9.2V6z" /><path d="m9 12 2 2 4-4" /></>,
    warning: <><path d="M12 4 21 20H3z" /><path d="M12 9v4.5M12 17h.01" /></>,
  };
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function Measurement({ experiment }: { experiment?: Experiment }) {
  if (!experiment) return <article className="measure-panel" id="evidence"><p className="eyebrow">Measurement</p><h2>No completed sample yet.</h2><p>Control traffic is retained until the recovery effect can be calculated.</p></article>;
  const treatment = experiment.treatment.total ? experiment.treatment.successes / experiment.treatment.total : 0;
  const control = experiment.control.total ? experiment.control.successes / experiment.control.total : 0;
  const recovery = experiment.recovery;
  return <article className="measure-panel" id="evidence">
    <div className="panel-heading"><div><p className="eyebrow">Measurement</p><h2>Observed effect</h2></div><span className="proof"><Icon name="check" />Verified</span></div>
    <div className="rate-row"><span>Treatment</span><div className="rate-track"><i style={{ width: `${treatment * 100}%` }} /></div><b>{percent.format(treatment)}</b></div>
    <div className="rate-row"><span>Control</span><div className="rate-track control"><i style={{ width: `${control * 100}%` }} /></div><b>{percent.format(control)}</b></div>
    <div className="lift"><span>Lift over control</span><strong>{experiment.lift === null ? "—" : percent.format(experiment.lift)}</strong></div>
    <p className="measure-note">{number.format(experiment.treatment.total)} treated payments · {number.format(experiment.control.total)} control payments</p>
    {recovery && <div className="money-outcome"><div><span>Value at risk</span><strong>{money.format(recovery.at_risk)}</strong></div><div><span>{recovery.claimable ? "Recovered vs control" : "Recovery estimate"}</span><strong>{money.format(recovery.recovered)}</strong></div></div>}
  </article>;
}

function DecisionReceipt({
  incident,
  approval,
  decision,
  experiment,
  revision,
}: {
  incident?: AgentSnapshot["incidents"][number];
  approval?: AgentSnapshot["approvals"][number];
  decision?: AgentSnapshot["decisions"][number];
  experiment?: Experiment;
  revision: number;
}) {
  const recovery = experiment?.recovery;
  const result = recovery ? (recovery.claimable ? `${money.format(recovery.recovered)} recovered against concurrent control.` : experiment?.verdict) : "Outcome measurement has not started.";
  const assessment = incident?.advice || decision?.reasoning || "The deterministic detector and policy engine completed this response. No model assessment was available.";
  return <section className="receipt-section" id="record"><div className="section-head"><div><p className="eyebrow">Decision receipt</p><h2>What changed, and why.</h2></div><span>Revision {revision}</span></div><div className="receipt-grid"><article><span>Observed</span><strong>{incident ? `${words(incident.pattern_type)} on ${words(incident.target)}` : "No open incident"}</strong><p>{incident ? `${percent.format(incident.latest_confidence)} confidence · severity ${Math.round(incident.peak_severity * 100)}/100` : "The desk is waiting for a route to move outside its expected range."}</p></article><article><span>Response</span><strong>{decision ? `${words(decision.type)} for ${words(decision.target)}` : approval ? `${words(approval.action_type)} requested` : "No action proposed"}</strong><p>{approval ? `Held for ${words(approval.authorization)} approval.` : decision?.message || "No policy change has been published."}</p></article><article><span>Measured outcome</span><strong>{result}</strong><p>{experiment ? `${number.format(experiment.treatment.total)} treated and ${number.format(experiment.control.total)} control payments.` : "A holdout will be retained once a response is active."}</p></article></div><article className="assessment"><span>Assessment</span><p>{assessment}</p></article></section>;
}

function Offline({ retry, loading }: { retry: () => void; loading: boolean }) {
  return <main className="desk offline-view"><div className="offline-panel"><a className="brand" href="#overview"><i>F</i>flowstate</a><p className="eyebrow">Connection required</p><h1>The recovery desk is waiting for its API.</h1><p>Start the FastAPI service to view live payment activity. No sample data is displayed here.</p><button className="solid-button" onClick={retry} disabled={loading}>Try again <Icon name="refresh" /></button></div></main>;
}

export function OperationsConsole() {
  const [snapshot, setSnapshot] = useState<AgentSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [active, setActive] = useState<(typeof links)[number]>("overview");
  const hasSnapshot = Boolean(snapshot);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/agent/snapshot", { cache: "no-store" });
      if (!response.ok) throw new Error();
      setSnapshot(await response.json() as AgentSnapshot);
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
    const syncHash = () => {
      const id = window.location.hash.slice(1);
      setActive(links.includes(id as (typeof links)[number]) ? id as (typeof links)[number] : "overview");
    };
    syncHash();
    window.addEventListener("hashchange", syncHash);
    window.addEventListener("popstate", syncHash);
    return () => { window.removeEventListener("hashchange", syncHash); window.removeEventListener("popstate", syncHash); };
  }, []);

  useEffect(() => {
    if (!hasSnapshot) return;

    const sections = links
      .map((id) => document.getElementById(id))
      .filter((section): section is HTMLElement => section !== null);

    const setCurrentSection = (id: (typeof links)[number]) => {
      setActive((current) => current === id ? current : id);
      if (window.location.hash !== `#${id}`) {
        window.history.replaceState(null, "", `#${id}`);
      }
    };

    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      const current = visible[0]?.target.id as (typeof links)[number] | undefined;
      if (current && links.includes(current)) setCurrentSection(current);
    }, { rootMargin: "-12% 0px -72% 0px", threshold: 0 });

    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [hasSnapshot]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const issuers = useMemo(() => snapshot ? [...snapshot.issuers].sort((a, b) => a.success_rate - b.success_rate) : [], [snapshot]);

  async function request(path: string, body: object, success: string) {
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch(`/api/agent/${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
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

  const incident = snapshot.incidents.find((item) => item.active) ?? snapshot.incidents[0];
  const approval = snapshot.approvals[0];
  const testScenario = snapshot.scenarios.find((scenario) => scenario.type === "issuer_degradation");
  const experiment = snapshot.experiments[0];
  const decision = snapshot.decisions[0];
  const routeName = incident ? words(incident.target) : "Payment network";

  return <main className="desk">
    <aside className="rail">
      <a className="brand" href="#overview"><i>F</i>flowstate</a>
      <div className="rail-label">Recovery desk</div>
      <nav aria-label="Desk sections">{links.map((id, index) => <a key={id} href={`#${id}`} className={active === id ? "selected" : undefined} onClick={() => setActive(id)} aria-current={active === id ? "location" : undefined}><span>0{index + 1}</span>{words(id)}</a>)}</nav>
      <a className="rail-footer" href="/">About Flowstate <Icon name="arrow" /></a>
    </aside>

    <section className="workspace">
      <header className="workspace-header"><div><p className="eyebrow">Payment operations / India</p><strong>{number.format(snapshot.metrics.transactions)} payments in current window</strong></div><div className="header-actions"><button className="demo-button" disabled={busy} onClick={() => void request("demo/run", {}, "Demo completed. Review the decision receipt and measurement below.")}>Run demo</button><button className="icon-button" onClick={() => void refresh()} aria-label="Refresh payment data"><Icon name="refresh" /></button></div></header>
      {notice && <div className="notice" role="status"><span>{notice}</span><button onClick={() => setNotice(null)} aria-label="Dismiss notification"><Icon name="close" /></button></div>}

      <section className="incident-canvas" id="overview">
        <div className="case-title"><p className="eyebrow">{incident?.incident_id ?? "No active incident"}</p><div className={incident?.active ? "state-alert" : "state-stable"}>{incident?.active ? <Icon name="warning" /> : <Icon name="check" />}{incident?.active ? "Route degraded" : "Stable"}</div><h1>{incident ? `${routeName} payment recovery` : "Payment routes are stable"}</h1><p>{incident ? `${words(incident.pattern_type)} detected in the active five-minute window.` : "No payment route is outside its expected range."}</p></div>
        <div className="route-map" aria-label={`Payment route status for ${routeName}`}>
          <span className="node buyer">Buyer</span><span className="node merchant">Merchant</span><span className="node gateway">Gateway</span><span className="node issuer">{routeName}</span>
          <svg viewBox="0 0 700 220" preserveAspectRatio="none" aria-hidden="true"><path className="route-base" d="M48 110H650" /><path className="route-active" d="M48 110H650" /></svg>
          <div className="route-stat"><span>Route success</span><strong>{percent.format(incident ? Math.max(0, 1 - incident.peak_severity) : snapshot.metrics.success_rate)}</strong><small>Expected range exceeded</small></div>
        </div>
      </section>

      <section className="decision-grid" id="decision">
        <article className="decision-panel"><p className="eyebrow">Decision record</p><h2>{approval ? "Proposed response" : testScenario ? "Active incident" : "Recovery decision"}</h2><p className="decision-copy">{approval ? `${words(approval.action_type)} for ${words(approval.target)} is within the policy boundary and awaits an operator decision.` : testScenario ? "ICICI Bank is the affected route. The record will show the selected response once the observation window is complete." : incident?.actions_taken.length ? `${words(incident.actions_taken[0])} is active within the approved scope.` : "No response has been published."}</p>{approval ? <div className="approval"><div><span>Requested action</span><strong>{words(approval.action_type)}</strong><small>{percent.format(approval.expected_lift)} expected lift · {Math.max(1, Math.ceil((approval.seconds_remaining ?? 0) / 60))} min remaining</small></div><button className="solid-button" disabled={busy} onClick={() => void request(`approvals/${approval.request_id}/approve`, { approver: "ops@flowstate.local" }, "Response approved and applied.")}>Approve response <Icon name="arrow" /></button></div> : !testScenario && <button className="outline-button" disabled={busy} onClick={() => void request("scenarios/inject", { type: "issuer_degradation", issuer: "ICICI_BANK", severity: 0.82, duration_seconds: 300 }, "Incident created. The decision record will update when the observation window is complete.")}>Create test incident <Icon name="arrow" /></button>}</article>
        <Measurement experiment={experiment} />
      </section>

      <section className="network-section" id="network"><div className="section-head"><div><p className="eyebrow">Payment network</p><h2>Route health</h2></div><span>Worst route first</span></div><div className="issuer-list" role="table" aria-label="Issuer route health"><div className="issuer-head" role="row"><span>Route</span><span>Success rate</span><span>p95</span><span>State</span></div>{issuers.map((issuer) => <div className="issuer-line" role="row" key={issuer.issuer}><strong>{words(issuer.issuer)}</strong><span className="route-rate"><i style={{ width: `${issuer.success_rate * 100}%` }} />{percent.format(issuer.success_rate)}</span><span>{Math.round(issuer.p95)} ms</span><span className={issuer.broken ? "route-alert" : "route-normal"}>{issuer.broken ? "Rerouted" : "Normal"}</span></div>)}</div></section>

      <DecisionReceipt incident={incident} approval={approval} decision={decision} experiment={experiment} revision={snapshot.control_plane.revision} />
      <section className="record-section"><div className="section-head"><div><p className="eyebrow">Policy record</p><h2>Revision {snapshot.control_plane.revision}</h2></div><span>Immutable history</span></div><ol>{snapshot.control_plane.history.slice(0, 3).map((item) => <li key={item.revision}><span>r{item.revision}</span><div><strong>{item.reason}</strong><p>{item.changes.join(" · ") || "Recorded for measurement"}</p></div><small>{item.author}</small></li>)}</ol></section>
    </section>
  </main>;
}
