import "@/styles/site.css";

import { LoopNarrative } from "@/components/site/loop-narrative";
import { PaymentTape } from "@/components/site/payment-tape";
import { RecoveryScope } from "@/components/site/recovery-scope";
import { SiteNav } from "@/components/site/site-nav";
import { Icon } from "@/components/ui/icon";
import { Wordmark } from "@/components/ui/mark";
import { RevealRoot } from "@/components/ui/reveal-root";
import { Ticker } from "@/components/ui/ticker";

const QUESTIONS: Array<[string, string]> = [
  ["Which route is failing, right now?", "A dashboard, if somebody happens to be looking at it."],
  ["What am I actually allowed to change?", "Tribal knowledge, a Slack thread, and a nervous guess."],
  ["Did the change recover anything?", "Nobody knows. The chart went back up, eventually."],
];

const AUTHORIZATION: Array<[string, string, string]> = [
  ["Automatic", "Retry tuning, alerts", "Runs inside safety limits once confidence clears the threshold"],
  ["Semi automatic", "Circuit breaker, routing change", "Named operator approval unless the action is explicitly low risk"],
  ["Manual", "Payment method suppression", "Named operator approval, always"],
];

export default function Home() {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <SiteNav />

      <main className="site" id="main">
        {/* ---------------------------------------------------- hero */}
        <section className="hero">
          <div className="shell hero-grid">
            <div className="hero-copy">
              <span className="kicker" data-enter="in">
                <span className="dot" data-tone="signal" />
                Payment recovery, with evidence
              </span>
              <h1 data-enter="up" style={{ "--reveal-delay": "60ms" } as React.CSSProperties}>
                A bank starts declining. You have four minutes.
              </h1>
              <p className="lead" data-enter="up" style={{ "--reveal-delay": "140ms" } as React.CSSProperties}>
                Flowstate watches every payment route, takes one bounded action when a route breaks, and proves what it
                recovered against a control group that never got the fix. A decision with a receipt, not another chart.
              </p>
              <div className="hero-actions" data-enter="up" style={{ "--reveal-delay": "220ms" } as React.CSSProperties}>
                <a className="btn" data-variant="solid" href="/desk">
                  Open the recovery desk
                  <Icon name="arrow" />
                </a>
                <a className="btn" data-variant="outline" href="/onboarding">
                  Walk through setup
                </a>
              </div>
              <p className="hero-fine mono" data-enter="in" style={{ "--reveal-delay": "300ms" } as React.CSSProperties}>
                Runs locally · deterministic demo · no payment action is ever sent to a provider
              </p>
            </div>

            <div className="hero-scope" data-enter="in" style={{ "--reveal-delay": "180ms" } as React.CSSProperties}>
              <RecoveryScope />
            </div>
          </div>

          <PaymentTape />
        </section>

        {/* ------------------------------------------------- problem */}
        <section className="band problem">
          <div className="shell problem-grid">
            <div>
              <h2 data-reveal="up">
                Monitoring tells you a number moved. It never tells you what you are allowed to do about it.
              </h2>
              <div className="prose problem-prose" data-reveal="up" style={{ "--reveal-delay": "80ms" } as React.CSSProperties}>
                <p>
                  A single issuer starts failing during a sale. There is no alarm loud enough to be obvious and no
                  failure large enough to be safe to ignore. Revenue leaves in small pieces while a team argues about
                  whether to touch routing at all.
                </p>
                <p>
                  The hard part was never detection. It is the ninety seconds after detection, when somebody has to
                  choose an action they can defend afterwards.
                </p>
              </div>
            </div>

            <dl className="questions" data-reveal="up" style={{ "--reveal-delay": "120ms" } as React.CSSProperties}>
              {QUESTIONS.map(([question, answer], index) => (
                <div key={question} style={{ "--reveal-delay": `${index * 70}ms` } as React.CSSProperties}>
                  <dt>{question}</dt>
                  <dd>{answer}</dd>
                </div>
              ))}
              <p className="questions-close">Flowstate answers all three, in one record, every time.</p>
            </dl>
          </div>
        </section>

        {/* ---------------------------------------------------- loop */}
        <section className="band loop-band" id="loop">
          <div className="shell">
            <div className="loop-head">
              <h2 data-reveal="up">Five moves, in order, every time.</h2>
              <p className="lead" data-reveal="up" style={{ "--reveal-delay": "80ms" } as React.CSSProperties}>
                The loop is fixed. That is what makes an incident reviewable a week later instead of a story somebody
                reconstructs from memory.
              </p>
            </div>
          </div>
          <div className="shell">
            <LoopNarrative />
          </div>
        </section>

        {/* ---------------------------------------------- guardrails */}
        <section className="band guardrails" id="guardrails">
          <div className="shell">
            <div className="guard-head">
              <h2 data-reveal="up">Automation with a hand on the lever.</h2>
              <p className="lead" data-reveal="up" style={{ "--reveal-delay": "80ms" } as React.CSSProperties}>
                Every action type carries one authorization classification, used identically by the runtime, the tool
                layer and the API. There is no side door.
              </p>
            </div>

            <div className="guard-grid">
              <table className="auth-table" data-reveal="up">
                <thead>
                  <tr>
                    <th scope="col">Tier</th>
                    <th scope="col">Actions</th>
                    <th scope="col">Requirement</th>
                  </tr>
                </thead>
                <tbody>
                  {AUTHORIZATION.map(([tier, actions, requirement]) => (
                    <tr key={tier}>
                      <th scope="row">{tier}</th>
                      <td className="mono">{actions}</td>
                      <td>{requirement}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <aside className="approval-card" data-reveal="up" style={{ "--reveal-delay": "120ms" } as React.CSSProperties}>
                <div className="approval-top">
                  <span className="tag" data-tone="signal">
                    awaiting operator
                  </span>
                  <span className="num approval-clock">04:12</span>
                </div>
                <strong>Circuit breaker · ICICI_BANK</strong>
                <p>
                  Ranked first on expected recovery. Held anyway, because it removes a route from customer traffic.
                </p>
                <dl>
                  <div>
                    <dt>Blast radius</dt>
                    <dd>18% of live traffic</dd>
                  </div>
                  <div>
                    <dt>Expected lift</dt>
                    <dd className="num">+37.0pp</dd>
                  </div>
                  <div>
                    <dt>On timeout</dt>
                    <dd>Expires unapproved</dd>
                  </div>
                </dl>
                <div className="approval-actions">
                  <span className="btn" data-variant="solid" data-size="sm">
                    Approve response
                  </span>
                  <span className="btn" data-variant="outline" data-size="sm">
                    Deny
                  </span>
                </div>
              </aside>
            </div>

            <ul className="guard-facts">
              {[
                ["Bounded", "Every action carries a maximum share of traffic it may touch."],
                ["Timed", "An approval nobody answers expires. Silence is never consent."],
                ["Reversible", "Responses are policy revisions, so rolling back is a revision too."],
              ].map(([title, body], index) => (
                <li key={title} data-reveal="up" style={{ "--reveal-delay": `${index * 70}ms` } as React.CSSProperties}>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* --------------------------------------------------- proof */}
        <section className="band proof" id="proof">
          <div className="shell-tight proof-inner">
            <h2 data-reveal="up">
              Everyone claims recovery.
              <br />
              We keep a control group.
            </h2>
            <p className="lead proof-lead" data-reveal="up" style={{ "--reveal-delay": "80ms" } as React.CSSProperties}>
              Affected payments are split deterministically by transaction id. Most receive the response. A small share
              deliberately does not. Both halves run at the same moment, through the same incident, so the comparison
              survives an incident that was going to resolve on its own.
            </p>

            <div className="proof-bars" data-reveal="up" style={{ "--reveal-delay": "140ms" } as React.CSSProperties}>
              <div className="proof-row" data-reveal="bar">
                <span className="proof-name">Treated</span>
                <span className="proof-track">
                  <i data-tone="proof" style={{ width: "88.4%" }} />
                </span>
                <span className="num proof-value">88.4%</span>
              </div>
              <div className="proof-row" data-reveal="bar" style={{ "--reveal-delay": "140ms" } as React.CSSProperties}>
                <span className="proof-name">Holdout</span>
                <span className="proof-track">
                  <i style={{ width: "47.1%" }} />
                </span>
                <span className="num proof-value">47.1%</span>
              </div>
            </div>

            <dl className="proof-figures" data-reveal="up" style={{ "--reveal-delay": "200ms" } as React.CSSProperties}>
              <div>
                <dt>Value at risk</dt>
                <dd>
                  <Ticker value={1_284_500} format="inr" />
                </dd>
              </div>
              <div>
                <dt>Recovered against control</dt>
                <dd data-tone="proof">
                  <Ticker value={531_200} format="inr" />
                </dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>
                  <span className="num">p 0.004</span>
                </dd>
              </div>
            </dl>

            <p className="proof-honest" data-reveal="up">
              When the sample is too small or the difference is not significant, Flowstate reports no recovery at all.
              Refusing to claim a number is the feature, not a gap.
            </p>
          </div>
        </section>

        {/* ------------------------------------------------- receipt */}
        <section className="band receipt">
          <div className="shell receipt-grid">
            <div className="receipt-copy">
              <h2 data-reveal="up">Every change leaves a signed revision.</h2>
              <div className="prose" data-reveal="up" style={{ "--reveal-delay": "80ms" } as React.CSSProperties}>
                <p>
                  Flowstate does not reach into your payment provider and alter a transaction. It publishes a versioned
                  policy document, atomically, with the author, the reason and the expiry attached. Your checkout or
                  routing service reads that policy.
                </p>
                <p>
                  That split is what makes an action reviewable and reversible. If a read fails, the client keeps the
                  last valid policy. If the runtime restarts, an active policy is adopted as a new revision rather than
                  quietly forgotten.
                </p>
              </div>
              <a className="link" href="/desk">
                See a live revision on the desk
                <Icon name="arrow" width={15} height={15} />
              </a>
            </div>

            <figure className="revision" data-reveal="up" style={{ "--reveal-delay": "120ms" } as React.CSSProperties}>
              <figcaption>
                <span className="mono">policy revision</span>
                <span className="num">r14</span>
              </figcaption>
              <dl>
                <div>
                  <dt>action</dt>
                  <dd className="mono">reduce_traffic · ICICI_BANK</dd>
                </div>
                <div>
                  <dt>author</dt>
                  <dd className="mono">ops@flowstate.local</dd>
                </div>
                <div>
                  <dt>reason</dt>
                  <dd>Sustained issuer decline, 94s, confidence 0.93</dd>
                </div>
                <div>
                  <dt>share</dt>
                  <dd className="mono">0.18 of route traffic</dd>
                </div>
                <div>
                  <dt>holdout</dt>
                  <dd className="mono">0.15 retained, deterministic by txn id</dd>
                </div>
                <div>
                  <dt>expires</dt>
                  <dd className="mono">2026-08-29T19:41:00Z</dd>
                </div>
              </dl>
              <span className="revision-seal">
                <Icon name="stamp" width={14} height={14} />
                written atomically to the journal
              </span>
            </figure>
          </div>
        </section>

        {/* --------------------------------------------------- build */}
        <section className="band build" id="build">
          <div className="shell">
            <div className="build-head">
              <h2 data-reveal="up">The decision plane never touches your provider.</h2>
              <p className="lead" data-reveal="up" style={{ "--reveal-delay": "80ms" } as React.CSSProperties}>
                Flowstate decides and publishes. Your router consumes. Outcomes come back and close the loop.
              </p>
            </div>

            <ol className="plane" data-reveal="up">
              <li>
                <span className="plane-tag mono">source</span>
                <strong>Payment outcomes</strong>
                <p>Deterministic simulator, journal replay, or read only Razorpay test mode intake.</p>
              </li>
              <li data-accent="signal">
                <span className="plane-tag mono">decision plane</span>
                <strong>Flowstate runtime</strong>
                <p>Observe, reason, decide, guard. One lifecycle, one consistent read model.</p>
              </li>
              <li>
                <span className="plane-tag mono">contract</span>
                <strong>Versioned policy</strong>
                <p>An attributed, expiring document written atomically. The only thing that crosses the boundary.</p>
              </li>
              <li data-accent="proof">
                <span className="plane-tag mono">routing plane</span>
                <strong>Your checkout or router</strong>
                <p>Reads the current policy. Keeps the last valid one if a read fails.</p>
              </li>
            </ol>

            <div className="build-notes">
              <div data-reveal="up">
                <h3>What is running</h3>
                <ul className="mono">
                  <li>FastAPI runtime, one agent lifecycle, one snapshot</li>
                  <li>Next.js recovery desk behind a server side API proxy</li>
                  <li>Journal of transactions, decisions, outcomes and revisions</li>
                  <li>Read only Razorpay test mode connector, keys never reach the browser</li>
                </ul>
              </div>
              <div data-reveal="up" style={{ "--reveal-delay": "90ms" } as React.CSSProperties}>
                <h3>The boundary, stated plainly</h3>
                <p>
                  The shipped demonstration runs on synthetic traffic. That is deliberate: it makes the whole decision
                  and measurement path reproducible on any machine, in the same order, with the same result. It is not a
                  claim about performance on live merchant traffic, and it is not presented as one.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ----------------------------------------------------- cta */}
        <section className="band cta">
          <div className="shell-tight">
            <h2 data-reveal="up">Three ways in.</h2>
            <ul className="cta-list">
              {[
                {
                  href: "/desk",
                  title: "Run the demo",
                  body: "The same ICICI degradation every time. Watch detection, approval and measurement in one pass.",
                  cta: "Open the recovery desk",
                },
                {
                  href: "/onboarding",
                  title: "Walk the setup",
                  body: "Pick a source, set the blast radius, name an approver, size the holdout. Around ninety seconds.",
                  cta: "Start setup",
                },
                {
                  href: "http://localhost:8000/docs",
                  title: "Call the runtime",
                  body: "The read model and every operator action, documented and callable. Nothing the desk does is hidden from you.",
                  cta: "Open the API reference",
                },
              ].map((item, index) => (
                <li key={item.title} data-reveal="up" style={{ "--reveal-delay": `${index * 80}ms` } as React.CSSProperties}>
                  <a href={item.href}>
                    <span className="num cta-index">{String(index + 1).padStart(2, "0")}</span>
                    <h3>{item.title}</h3>
                    <p>{item.body}</p>
                    <span className="cta-go">
                      {item.cta}
                      <Icon name="arrow" width={15} height={15} />
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>

      <footer className="site-foot">
        <div className="shell site-foot-grid">
          <div>
            <Wordmark />
            <p>Payment recovery with a clear record.</p>
          </div>
          <nav aria-label="Footer">
            <a href="/desk">Recovery desk</a>
            <a href="/onboarding">Setup</a>
            <a href="#loop">The loop</a>
            <a href="#proof">Proof</a>
          </nav>
          <p className="mono site-foot-fine">
            Built by Balaji Thukuntala.
            <br />
            Simulated traffic. No live payment action.
          </p>
        </div>
      </footer>

      <RevealRoot />
    </>
  );
}
