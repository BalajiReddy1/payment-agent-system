"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Icon } from "@/components/ui/icon";
import { Wordmark } from "@/components/ui/mark";
import { DEFAULT_SETUP, SOURCES, readSetup, writeSetup, type Setup } from "@/lib/setup";

const STEPS = [
  { id: "source", label: "Source", question: "Where should Flowstate read payments from?" },
  { id: "guardrails", label: "Guardrails", question: "How much traffic may one response touch?" },
  { id: "approver", label: "Approver", question: "Who decides when an action is disruptive?" },
  { id: "holdout", label: "Holdout", question: "How much traffic stays untreated, on purpose?" },
  { id: "review", label: "Review", question: "This is what Flowstate will run with." },
] as const;

const pct = (value: number) => `${Math.round(value * 100)}%`;

export function SetupFlow() {
  const router = useRouter();
  const [index, setIndex] = useState(0);
  const [setup, setSetup] = useState<Setup>(DEFAULT_SETUP);
  const [saved, setSaved] = useState(false);
  const [emailTouched, setEmailTouched] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const existing = readSetup();
    if (existing) setSetup(existing);
  }, []);

  const patch = (next: Partial<Setup>) => setSetup((current) => ({ ...current, ...next }));

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(setup.approver.trim());
  const canAdvance = STEPS[index].id !== "approver" || emailValid;
  const step = STEPS[index];

  // Move focus to the new question so the flow is usable from the keyboard.
  useEffect(() => {
    panelRef.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
  }, [index]);

  const holdoutNote = useMemo(() => {
    if (setup.holdout <= 0.08) return "A small holdout needs a longer incident before the comparison can be trusted.";
    if (setup.holdout >= 0.24) return "A large holdout proves the result quickly, but leaves more payments untreated.";
    return "A balanced split. Enough control traffic to reach significance inside a typical incident.";
  }, [setup.holdout]);

  const finish = () => {
    const complete = { ...setup, completedAt: new Date().toISOString() };
    writeSetup(complete);
    setSetup(complete);
    setSaved(true);
  };

  const next = () => {
    if (!canAdvance) {
      setEmailTouched(true);
      return;
    }
    if (index < STEPS.length - 1) setIndex(index + 1);
  };

  if (saved) {
    return (
      <div className="setup-done">
        <span className="tag" data-tone="proof">
          <Icon name="check" width={13} height={13} />
          configuration saved
        </span>
        <h1>Flowstate is set up.</h1>
        <p className="lead">
          The desk will observe {setup.source === "simulator" ? "simulated" : "connected"} traffic, hold anything above{" "}
          {pct(setup.blastRadius)} of a route for {setup.approver}, and keep {pct(setup.holdout)} of affected payments
          out of every response so recovery stays measurable.
        </p>
        <div className="setup-done-actions">
          <a className="btn" data-variant="solid" href="/desk">
            Open the recovery desk
            <Icon name="arrow" />
          </a>
          <button className="btn" data-variant="outline" type="button" onClick={() => setSaved(false)}>
            Change something
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="setup">
      <aside className="setup-rail">
        <Wordmark />
        <ol className="setup-steps">
          {STEPS.map((item, position) => (
            <li key={item.id} data-state={position === index ? "current" : position < index ? "done" : "todo"}>
              <button type="button" onClick={() => position < index && setIndex(position)} disabled={position > index}>
                <span className="setup-bullet" aria-hidden="true">
                  {position < index ? <Icon name="check" width={11} height={11} /> : String(position + 1)}
                </span>
                <span>{item.label}</span>
              </button>
            </li>
          ))}
        </ol>
        <a className="link setup-skip" href="/desk">
          Skip for now
          <Icon name="arrow" width={14} height={14} />
        </a>
      </aside>

      <div className="setup-main">
        <div className="setup-meter" aria-hidden="true">
          <i style={{ transform: `scaleX(${(index + 1) / STEPS.length})` }} />
        </div>

        <div className="setup-panel" ref={panelRef} key={step.id}>
          <p className="mono setup-count">
            Step {index + 1} of {STEPS.length}
          </p>
          <h1>{step.question}</h1>

          {step.id === "source" && (
            <fieldset className="setup-choices">
              <legend className="sr-only">Payment source</legend>
              {SOURCES.map((source, position) => (
                <label key={source.id} data-selected={setup.source === source.id}>
                  <input
                    type="radio"
                    name="source"
                    value={source.id}
                    checked={setup.source === source.id}
                    onChange={() => patch({ source: source.id })}
                    data-autofocus={position === 0 ? "" : undefined}
                  />
                  <span className="setup-choice-body">
                    <strong>{source.title}</strong>
                    <span>{source.body}</span>
                  </span>
                  <span className="mono setup-choice-note">{source.note}</span>
                </label>
              ))}
            </fieldset>
          )}

          {step.id === "guardrails" && (
            <div className="setup-field">
              <p className="setup-help">
                No single response may move more than this share of a route&apos;s traffic. Anything larger is held for
                a person, however confident the detector is.
              </p>
              <div className="setup-slider">
                <output className="num">{pct(setup.blastRadius)}</output>
                <input
                  type="range"
                  min={5}
                  max={50}
                  step={1}
                  value={Math.round(setup.blastRadius * 100)}
                  onChange={(event) => patch({ blastRadius: Number(event.target.value) / 100 })}
                  style={{ "--fill": `${((setup.blastRadius * 100 - 5) / 45) * 100}%` } as React.CSSProperties}
                  aria-label="Maximum share of route traffic one response may move"
                  data-autofocus=""
                />
                <div className="setup-scale mono">
                  <span>5% cautious</span>
                  <span>50% aggressive</span>
                </div>
              </div>

              <div className="setup-inline">
                <label className="setup-toggle" data-on={setup.autoTier === "automatic"}>
                  <input
                    type="checkbox"
                    checked={setup.autoTier === "automatic"}
                    onChange={(event) => patch({ autoTier: event.target.checked ? "automatic" : "none" })}
                  />
                  <span className="setup-switch" aria-hidden="true" />
                  <span>
                    <strong>Let low risk actions run on their own</strong>
                    <small>Retry tuning and alerts only. Routing changes always stop for a person.</small>
                  </span>
                </label>
              </div>

              <div className="setup-inline">
                <label className="setup-number">
                  <span>Action expires after</span>
                  <input
                    type="number"
                    min={1}
                    max={120}
                    value={setup.expiryMinutes}
                    onChange={(event) => patch({ expiryMinutes: Math.max(1, Number(event.target.value) || 1) })}
                  />
                  <span className="mono">minutes</span>
                </label>
              </div>
            </div>
          )}

          {step.id === "approver" && (
            <div className="setup-field">
              <p className="setup-help">
                Every held action is attributed to a named person, and that name is written into the policy revision. An
                approval nobody answers expires instead of applying itself.
              </p>
              <label className="setup-text">
                <span>Approver</span>
                <input
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  value={setup.approver}
                  placeholder="name@company.com"
                  onChange={(event) => patch({ approver: event.target.value })}
                  onBlur={() => setEmailTouched(true)}
                  aria-invalid={emailTouched && !emailValid}
                  aria-describedby="approver-error"
                  data-autofocus=""
                />
              </label>
              <p className="setup-error" id="approver-error" hidden={!emailTouched || emailValid}>
                Enter an address so approvals have somewhere to land.
              </p>
              <p className="setup-note mono">stored in this browser only · never sent to a payment provider</p>
            </div>
          )}

          {step.id === "holdout" && (
            <div className="setup-field">
              <p className="setup-help">
                A share of affected payments is deliberately kept out of every response. Without it, a recovery claim is
                just a chart that went up after somebody pressed a button.
              </p>
              <div className="setup-slider">
                <output className="num">{pct(setup.holdout)}</output>
                <input
                  type="range"
                  min={5}
                  max={30}
                  step={1}
                  value={Math.round(setup.holdout * 100)}
                  onChange={(event) => patch({ holdout: Number(event.target.value) / 100 })}
                  style={{ "--fill": `${((setup.holdout * 100 - 5) / 25) * 100}%` } as React.CSSProperties}
                  aria-label="Share of affected payments kept as an untreated control group"
                  data-autofocus=""
                />
                <div className="setup-scale mono">
                  <span>5% slow proof</span>
                  <span>30% fast proof</span>
                </div>
              </div>
              <p className="setup-tradeoff">{holdoutNote}</p>
            </div>
          )}

          {step.id === "review" && (
            <div className="setup-review">
              <dl>
                <div>
                  <dt>source</dt>
                  <dd>{SOURCES.find((source) => source.id === setup.source)?.title}</dd>
                </div>
                <div>
                  <dt>blast radius</dt>
                  <dd className="num">{pct(setup.blastRadius)} of route traffic</dd>
                </div>
                <div>
                  <dt>automatic tier</dt>
                  <dd>{setup.autoTier === "automatic" ? "Low risk actions only" : "Nothing runs unattended"}</dd>
                </div>
                <div>
                  <dt>expiry</dt>
                  <dd className="num">{setup.expiryMinutes} minutes</dd>
                </div>
                <div>
                  <dt>approver</dt>
                  <dd className="mono">{setup.approver}</dd>
                </div>
                <div>
                  <dt>holdout</dt>
                  <dd className="num">{pct(setup.holdout)} of affected payments</dd>
                </div>
              </dl>
              <p className="setup-note mono">
                <Icon name="shield" width={13} height={13} />
                Flowstate publishes policy. It never sends a payment action to a provider.
              </p>
            </div>
          )}
        </div>

        <div className="setup-actions">
          <button
            className="btn"
            data-variant="ghost"
            type="button"
            onClick={() => (index === 0 ? router.push("/") : setIndex(index - 1))}
          >
            {index === 0 ? "Back to site" : "Back"}
          </button>

          {step.id === "review" ? (
            <button className="btn" data-variant="solid" type="button" onClick={finish}>
              Activate Flowstate
              <Icon name="arrow" />
            </button>
          ) : (
            <button className="btn" data-variant="solid" type="button" onClick={next} disabled={!canAdvance}>
              Continue
              <Icon name="arrow" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
