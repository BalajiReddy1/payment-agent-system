"use client";

import { useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "@/components/ui/icon";
import { onScrollFrame } from "@/lib/in-view";

type Step = {
  id: string;
  title: string;
  icon: IconName;
  body: string;
  note: string;
};

const STEPS: Step[] = [
  {
    id: "observe",
    title: "Observe",
    icon: "eye",
    body: "A sliding window tracks every outcome by issuer, method, region and decline code. Not an average across the account, where a single bad route disappears into a healthy overall number.",
    note: "5 minute window · per route",
  },
  {
    id: "reason",
    title: "Reason",
    icon: "spark",
    body: "Sequential detection and Bayesian rate estimates separate a sustained change from noise. One failed payment is not an incident. Forty in ninety seconds on one issuer is.",
    note: "sustained change, not a spike",
  },
  {
    id: "decide",
    title: "Decide",
    icon: "route",
    body: "Permitted responses are ranked on success rate, latency, cost and risk. Doing nothing is scored as an explicit candidate, so restraint is a decision the system can defend rather than an omission.",
    note: "wait is a ranked option",
  },
  {
    id: "guard",
    title: "Guard",
    icon: "shield",
    body: "Before anything reaches customer traffic: authorization tier, blast radius, rate limit, expiry, and a named approver for anything disruptive. An approval that is never answered expires. It never approves itself.",
    note: "expires closed, never open",
  },
  {
    id: "prove",
    title: "Prove",
    icon: "scale",
    body: "A concurrent holdout is assigned deterministically by transaction id. Treated traffic is compared against payments that never received the response, so recovery is measured rather than inferred from a chart that went up.",
    note: "treatment vs concurrent control",
  },
];

function Stage({ step }: { step: string }) {
  return (
    <div className="loop-stage" aria-hidden="true">
      <div className="loop-frame" data-active={step === "observe"}>
        <div className="stage-label mono">routes · 05:00</div>
        <ul className="stage-routes">
          {[
            ["HDFC_BANK", 0.97, false],
            ["SBIN", 0.95, false],
            ["ICICI_BANK", 0.41, true],
            ["AXIS_BANK", 0.96, false],
            ["KOTAK", 0.94, false],
          ].map(([name, rate, broken]) => (
            <li key={name as string} data-broken={broken as boolean}>
              <span className="mono">{name as string}</span>
              <span className="stage-bar">
                <i style={{ width: `${(rate as number) * 100}%` }} />
              </span>
              <span className="num">{((rate as number) * 100).toFixed(0)}%</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="loop-frame" data-active={step === "reason"}>
        <div className="stage-label mono">change detection</div>
        <svg className="stage-chart" viewBox="0 0 320 150" preserveAspectRatio="none">
          <rect x="0" y="16" width="320" height="46" fill="var(--proof-wash)" />
          <path d="M0 40 40 34 80 44 120 36 160 42 190 58 210 92 240 118 280 126 320 122" fill="none" stroke="var(--signal)" strokeWidth="2" />
          <path d="M0 40 40 34 80 44 120 36 160 42" fill="none" stroke="var(--ink-4)" strokeWidth="2" />
          <line x1="190" y1="6" x2="190" y2="144" stroke="var(--signal-edge)" strokeWidth="1" strokeDasharray="3 3" />
        </svg>
        <div className="stage-foot">
          <span className="tag" data-tone="signal">
            breach sustained 94s
          </span>
          <span className="mono">confidence 0.93</span>
        </div>
      </div>

      <div className="loop-frame" data-active={step === "decide"}>
        <div className="stage-label mono">ranked responses</div>
        <ol className="stage-rank">
          {[
            ["Reduce traffic to route", "0.81", true],
            ["Hold and keep watching", "0.64", false],
            ["Circuit breaker", "0.58", false],
            ["Suppress payment method", "0.22", false],
          ].map(([label, score, chosen]) => (
            <li key={label as string} data-chosen={chosen as boolean}>
              <span>{label as string}</span>
              <span className="num">{score as string}</span>
            </li>
          ))}
        </ol>
      </div>

      <div className="loop-frame" data-active={step === "guard"}>
        <div className="stage-label mono">approval required</div>
        <div className="stage-approval">
          <strong>Circuit breaker · ICICI_BANK</strong>
          <dl>
            <div>
              <dt>Authorization</dt>
              <dd>Semi automatic</dd>
            </div>
            <div>
              <dt>Blast radius</dt>
              <dd>
                <span className="stage-bar sm">
                  <i style={{ width: "18%" }} />
                </span>
                18% of traffic
              </dd>
            </div>
            <div>
              <dt>Expires</dt>
              <dd className="num">04:12</dd>
            </div>
          </dl>
          <div className="stage-actions">
            <span className="stage-pill" data-kind="approve">
              Approve
            </span>
            <span className="stage-pill">Deny</span>
          </div>
        </div>
      </div>

      <div className="loop-frame" data-active={step === "prove"}>
        <div className="stage-label mono">measured outcome</div>
        <div className="stage-proof">
          <div className="stage-rate">
            <span>Treated</span>
            <span className="stage-bar tall">
              <i data-tone="proof" style={{ width: "88%" }} />
            </span>
            <span className="num">88.4%</span>
          </div>
          <div className="stage-rate">
            <span>Holdout</span>
            <span className="stage-bar tall">
              <i style={{ width: "47%" }} />
            </span>
            <span className="num">47.1%</span>
          </div>
          <div className="stage-verdict">
            <span className="tag" data-tone="proof">
              significant p 0.004
            </span>
            <span className="num">+41.3pp</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function LoopNarrative() {
  const [active, setActive] = useState(STEPS[0].id);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const items = Array.from(list.querySelectorAll<HTMLElement>("[data-step]"));

    // The step whose block straddles the middle of the viewport wins.
    return onScrollFrame(() => {
      const line = window.innerHeight / 2;
      let current = items[0];
      for (const item of items) {
        if (item.getBoundingClientRect().top <= line) current = item;
      }
      const id = current?.getAttribute("data-step");
      if (id) setActive((existing) => (existing === id ? existing : id));
    });
  }, []);

  const index = STEPS.findIndex((step) => step.id === active);

  return (
    <div className="loop">
      <div className="loop-sticky">
        <Stage step={active} />
        <div className="loop-progress" aria-hidden="true">
          <i style={{ transform: `scaleY(${(index + 1) / STEPS.length})` }} />
        </div>
      </div>

      <ol className="loop-steps" ref={listRef}>
        {STEPS.map((step, position) => (
          <li key={step.id} data-step={step.id} data-active={step.id === active}>
            <div className="loop-step-head">
              <span className="num loop-index">{String(position + 1).padStart(2, "0")}</span>
              <Icon name={step.icon} width={18} height={18} />
              <h3>{step.title}</h3>
            </div>
            <p>{step.body}</p>
            <span className="mono loop-note">{step.note}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
