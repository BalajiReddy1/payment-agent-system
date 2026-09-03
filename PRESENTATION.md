# Flowstate — narration script

For `demo/out/flowstate-demo.mp4`. The film runs **3:05** and is silent. Nothing
is burned into the picture, so your voice is the only thing carrying words.

Narration starts at **0:05**, when the title card clears, and ends at **2:59**,
when the end card comes up. That is **2:54 of speaking**.

Read this with the film playing. Every beat has three to four words of headroom
at a normal pace, so you are not being rushed anywhere.

---

## The beats

| In | Out | Length | On screen | Beat |
| --- | --- | --- | --- | --- |
| 0:00 | 0:05 | 5s | Title card | silent |
| 0:05 | 0:24 | 19s | Payment ticker | A. The scene |
| 0:24 | 0:36 | 12s | Home page, "You have four minutes" | B. The decision |
| 0:36 | 0:49 | 13s | The five step loop | C. Name it |
| 0:49 | 1:08 | 19s | The instrument, close | D. The thesis |
| 1:08 | 1:19 | 11s | Desk, demo starting | E. Start the demo |
| 1:19 | 1:38 | 19s | Desk incident, then route health | F. Detection and choice |
| 1:38 | 1:58 | 20s | Approval waiting, close | G. The human boundary |
| 1:58 | 2:28 | 30s | Measurement, then the proof section | H. The proof |
| 2:28 | 2:41 | 13s | Decision receipt, then the two planes | I. Credibility |
| 2:41 | 2:59 | 18s | The instrument recovering | J. Close |
| 2:59 | 3:05 | 6s | End card | silent |

---

## A. 0:05 — The scene

*Payments scroll past. A few of them are orange.*

> **It is the middle of a sale. Customers are reaching checkout, tapping pay,
> and one bank has quietly started declining them. There is no single big
> alarm. There are just a few hundred small losses.**

Slow. This is the only place in the film you are allowed to be unhurried. Land
on "a few hundred small losses" and stop for a beat before the cut.

## B. 0:24 — The decision

*Cut to the home page. The headline says "You have four minutes."*

> **And now somebody has about four minutes to decide. Move traffic off that
> bank, wait it out, or overreact and make a bad day worse.**

Three options, three slightly different intonations. Do not rush the list.

## C. 0:36 — Name it

*The five step loop scrolls: observe, reason, decide, guard, prove.*

> **I am Balaji. I built Flowstate for that four minutes. It finds the route
> that is failing, takes one bounded action, and then proves whether the action
> recovered anything.**

"Proves" is the word the rest of the film pays off. Lean on it.

## D. 0:49 — The thesis

*The instrument, close. Two traces. Watch them separate.*

> **This is the whole idea in one picture. The solid line is live traffic. The
> dashed line is a holdout that never receives the fix. When the bank breaks,
> both fall. After the response, only one comes back. That gap is the
> recovery.**

Time it so "that gap is the recovery" lands around **1:03**, when the two lines
are furthest apart. The picture fades out under your last word.

## E. 1:08 — Start the demo

*Fade in on the desk. The demo is running.*

> **Here is the desk. I am starting the same simulated incident every time, so
> nothing you are about to see is hand picked.**

Say "simulated" clearly. Volunteering it is worth more than being asked.

## F. 1:19 — Detection and choice

*The incident fills in. At 1:32 it cuts to route health, ICICI at the top.*

> **ICICI Bank is declining. Sustained, not one bad minute. Flowstate ranks
> only the responses it is allowed to take, and it scores doing nothing as a
> real option. It picks the least disruptive thing that should work, and moves
> traffic off the route.**

Reach "ranks only the responses it is allowed to take" by about 1:30 so the cut
to the route table lands under "least disruptive thing that should work".

## G. 1:38 — The human boundary

*The approval, waiting. Authorization, expiry, an approve and a deny button.*

> **The circuit breaker is a different matter. It pulls a route out of customer
> traffic, so it stops here and waits for a named person. If nobody answers, it
> expires. Silence is never consent. That is the one line I did not want
> automation to cross.**

Drop your pace on "silence is never consent". It is the most quotable sentence
in the pitch.

## H. 1:58 — The proof

*The measurement. Treated against holdout, the lift, the money. At 2:18 it cuts
to the proof section on the home page.*

> **Now the question most tools avoid. Did it actually work? Flowstate
> deliberately kept part of the affected traffic out of the fix. Treated
> payments recovered to about ninety percent. The untreated control stayed near
> six. That is the number on the right, recovered against a live control group,
> and it only appears because the comparison is statistically significant. If
> the sample is thin, it reports nothing at all.**

The longest beat, and the one that wins it. Do not speed up because it is long.
Pause after "did it actually work?" and let the bars finish before you give the
numbers. You have thirty seconds for sixty eight words, which is slow on
purpose.

If you want to say the rupee figure out loud, read it off the screen. It moves
between runs, which is why the script does not fix it.

## I. 2:28 — Credibility

*The decision receipt, then the decision plane and the routing plane.*

> **Every change is a signed policy revision, with an author and an expiry.
> Flowstate publishes policy. Your router reads it. It never touches a payment
> at the provider.**

Four short sentences, businesslike. The cut at 2:35 falls between the second and
the third.

**If the advisor is live**, use this instead. It fits the same 13 seconds and
names the model lane, which is worth doing while the assessment is on screen:

> **Every change is a signed policy revision. The assessment beside it is
> written by a model that holds no tools and cannot change routing. Flowstate
> publishes policy; your router reads it.**

That only works if the footage shows it. Set `GEMINI_API_KEY`, restart the API,
then re-record the one shot and re-cut:

```bash
cd demo/capture && node record.mjs 14-desk-receipt 11-desk-decision 12-desk-measure 13-desk-routes 10-desk
```

## J. 2:41 — Close

*Back to the instrument. It breaks, then recovers, and holds on the gap.*

> **The traffic here is simulated on purpose, so the entire decision path is
> reproducible. Point it at real routes and the loop does not change. A safe
> decision, a person where it matters, and proof of the money you got back.**

Stop talking on "got back" at about 2:58. The picture fades and the end card
carries the last line in text. Do not add a sign off.

---

## Delivering it

- 390 words over 2:54 is 134 words a minute. That is deliberately slower than
  conversation. If you finish a beat early, hold the silence rather than filling
  it.
- Record in one continuous pass with the film playing. Sit down, look at the
  lens, and let the cuts pace you.
- The three numbers you need are **ninety**, **six**, and **four minutes**.
  Everything else is on screen.
- If you fluff a line, pause for two full seconds and start that sentence again.
  The silence makes the bad take trivial to cut.
- Say "simulated" every time you reference the money. It costs nothing and it is
  the difference between a credible demo and an overclaim.

## Putting it together

Save the take as `demo/in/voice.wav` (or .mp4, the audio is taken from it):

```bash
cd demo/cut && node assemble.mjs --voice ../in/voice.wav
```

That writes `demo/out/flowstate-pitch.mp4`. The result is always exactly the
length of the film, so a take that runs a little long or short will not leave a
frozen tail or clip the end card.

If you want your face in it, record camera and voice in the same take and pass
it to both flags. It goes bottom right over the ticker, the home page and the
demo start, and stays out of the way of every panel with numbers on it:

```bash
node assemble.mjs --voice ../in/take.mp4 --face ../in/take.mp4
```

## What not to do

- Do not read the architecture out loud. It is on screen at 2:35 and is doing
  its own work.
- Do not narrate the interface. The film shows it; you explain why it matters.
- Do not open the Razorpay dashboard. The connector is read only and test mode,
  and an empty account on camera raises a question you do not need.
- Do not apologise for the simulator. It is a deliberate engineering choice and
  the close says so.
