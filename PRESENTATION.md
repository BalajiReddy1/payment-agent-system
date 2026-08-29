# Flowstate — five-minute pitch

This is a spoken script, not slide copy. Keep the Flowstate homepage open at
the start, then move to the recovery desk. Speak calmly; the proof on screen
does the heavy lifting.

## Recording run-sheet

| Time | Keep on screen | Action | Purpose |
| --- | --- | --- | --- |
| 0:00–0:30 | Homepage hero | Do not click yet | Set up the payment-loss moment. |
| 0:30–0:45 | Homepage hero | Introduce yourself and Flowstate. | Reveal the product as the answer. |
| 0:45–1:20 | Recovery desk | Click **Open recovery desk**; pause. | Explain why this is more than monitoring. |
| 1:20–1:35 | Recovery desk | Click **Run demo** once. | Start the reproducible incident. |
| 1:35–2:15 | Incident and Decision record | Point, do not scroll fast. | Show the affected route and chosen low-risk action. |
| 2:15–3:05 | Decision record | Click **Approve response** once, if shown. | Show the human boundary on high-impact action. |
| 3:05–4:05 | Measurement | Scroll down and pause. | Show treatment, control, and recovered value. |
| 4:05–4:40 | Decision receipt and Policy record | Scroll down. | Establish traceability and reversibility. |
| 4:40–5:00 | Policy record or Measurement | Hold still for the close. | Finish on proof, not a new screen. |

Before recording: open `http://localhost:3000`, use 100% browser zoom, and
keep the desk in the default simulated source. Do not open the Razorpay
dashboard during the recording.

## 0:00–0:45 — Open with a scene

> “Imagine it is the middle of a sale. Customers are reaching checkout, tapping
> ‘Pay’—and one bank has quietly started declining them. Nothing looks dramatic
> at first. The merchant does not get a single big alarm; they get hundreds of
> small lost moments.”

> “Now the operations team has a decision to make. Do they move traffic away
> from that bank? Do they wait? Or do they overreact and make a bad payment day
> even worse?”

> “I’m Balaji Thukuntala. I built Flowstate for that decision: a system that
> detects payment revenue at risk, takes only a bounded action, and then proves
> whether it recovered anything.”

Hold the homepage while telling the scene. Click **Open the desk** only after
you say “I built Flowstate”.

## 0:40–1:20 — Define the difference

> “This is not another payment dashboard. A dashboard tells an operator that
> something has broken. Flowstate answers the next question: what can we safely
> do about it—and did it make a difference?”

> “The operator can see the affected route, the response being considered, the
> control that prevents overreach, and the evidence after the response runs.”

Pause on the recovery desk. Do not read every number.

## 1:20–2:15 — Create the moment

> “Let me show this against a repeatable incident. I am starting a simulated
> ICICI Bank degradation—the same scenario every time, so the result is not a
> hand-picked screen.”

Click **Run demo**.

> “Flowstate sees a sustained decline on this route. It first chooses the
> lower-risk response: reduce traffic to the affected route. A more disruptive
> circuit breaker is not silently applied; it stays with an operator.”

Point to the incident and **Decision record**. If the approval button appears,
do not click it yet.

## 2:15–3:05 — Make safety tangible

> “This is the part that matters in payments. Automation cannot be allowed to
> turn every anomaly into an uncontrolled routing change. Each action has a
> policy boundary, an approval requirement, and a time limit.”

> “Here, the circuit breaker is proposed but held. The operator still has the
> final decision. That gives the team speed without pretending risk has gone
> away.”

Click **Approve response** once, if it is visible, to show the controlled
handoff. Do not dwell on the button.

## 3:05–4:05 — Deliver proof, not activity

> “Now comes the question most systems avoid: did the response actually recover
> anything?”

Scroll to **Measurement**.

> “Flowstate deliberately keeps a small concurrent holdout. That gives us a
> fair comparison: treated payments against payments that did not receive the
> intervention. We are not claiming success because a chart went up after an
> incident.”

> “In this simulated incident, the desk shows value at risk and recovered value
> relative to that control group. It only makes the recovery claim after there
> is enough data and the comparison is statistically supported.”

Pause long enough for the treatment, control, and recovered-value figures to
be readable.

## 4:05–4:40 — Establish credibility

> “Every response becomes a policy revision with its reason and author. The
> checkout or routing service reads that versioned policy; Flowstate does not
> directly alter a provider payment. That keeps changes reviewable and
> reversible.”

Scroll to **Decision receipt** and **Policy record**.

> “The same runtime also has a read-only Razorpay test-mode connector. It can
> ingest payment records without exposing credentials to the browser or taking
> payment actions on its own.”

## 4:40–5:00 — Close with one clear promise

> “When payment revenue starts slipping away, teams need more than an alert.
> They need a safe decision, a human boundary where it matters, and evidence of
> the money recovered. That is Flowstate.”

## Recording notes

- Keep the recording to one uninterrupted journey: homepage → desk → demo →
  evidence → record.
- Do not show an empty Razorpay account in the recording.
- Say “simulated incident” whenever you reference the financial result.
- Record at 1080p or 1440p with browser zoom at 100%.
