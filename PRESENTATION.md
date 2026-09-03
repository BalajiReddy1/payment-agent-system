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

## A. 0:05 — The hook

*Payments scrolling past. A few of them turn orange.*

> **It's the middle of a big sale. People are at checkout, tapping pay. And one
> bank has quietly started saying no. Nothing breaks. No alarm goes off. You
> just lose a few hundred customers, one at a time.**

Slow. This is the only part of the video where you get to take your time. Land
on "one at a time" and stop for a beat.

## B. 0:24 — The clock

*The home page. The headline says "You have four minutes."*

> **By the time someone notices, you've got about four minutes to decide. Move
> the traffic? Wait it out? Or panic, and make a bad day worse.**

Three questions, three different tones. Don't rush them together.

## C. 0:36 — Who you are

*The five step loop scrolls past.*

> **I'm Balaji, and I built Flowstate for those four minutes. It spots the route
> that's failing, does one small thing about it, and then proves whether that
> actually helped.**

"Proves" is the promise the rest of the video keeps. Hit it.

## D. 0:49 — The whole idea

*The instrument. Two lines. Watch them split apart.*

> **This is the whole idea in one picture. The solid line is your live traffic.
> The dashed line is a small group we deliberately don't fix. The bank breaks,
> and both drop. We act, and only one comes back. That gap? That's the money
> you saved.**

Say "that gap" around **1:03**, when the two lines are furthest apart. Pause
before "that's the money you saved."

## E. 1:08 — Start it

*The desk. The demo is running.*

> **This is the desk. I'm starting the same simulated incident every time, so
> nothing you're about to see was cherry picked.**

Say "simulated" clearly. Volunteering it beats being asked.

## F. 1:19 — What it sees, and what it picks

*The incident fills in. At 1:32 it cuts to the route list.*

> **ICICI is declining. Not one bad minute. A real, sustained drop. Flowstate
> looks at what it's actually allowed to do, scores each option, including
> doing nothing, and picks the gentlest thing that should work. It moves
> traffic off that route.**

"Including doing nothing" is the bit people remember. Slow down on it.

## G. 1:38 — Where it stops

*The approval, waiting. Approve and deny buttons.*

> **Now the bigger hammer. A circuit breaker pulls a bank out completely, so
> Flowstate won't do that on its own. It stops, and it waits for a person. And
> if nobody answers, it expires. Silence is never a yes. That's the line I
> didn't want a machine crossing.**

Drop your voice on "silence is never a yes." It's the most quotable line you
have.

## H. 1:58 — Did it work

*The measurement. Treated against holdout, then the proof section.*

> **So here's the question nobody likes answering. Did it work? Remember that
> small group we left alone? Here they are, side by side. The fixed traffic
> came back to around ninety percent. The untreated group stayed near six. That
> number on the right is real money recovered, measured against a live control
> group. And if the sample's too small to be sure, Flowstate says nothing at
> all.**

Your longest beat and the one that wins it. Thirty seconds for sixty seven
words, so you can breathe. Pause after "did it work?" and let the bars fill
before you give the numbers.

## I. 2:28 — The receipt

*The signed policy revision, then the two planes.*

> **Every change leaves a receipt. Who did it, why, and when it expires.
> Flowstate never touches your payment provider. It writes a policy, and your
> router reads it.**

Short sentences. Businesslike. The cut at 2:35 falls before the last two.

**Once the advisor has quota**, swap `14-desk-receipt` back into the `receipt`
beat in `cut/assemble.mjs` and use this instead. Same thirteen seconds, and it
names the model while the assessment is on screen:

> **Every change leaves a receipt. Who did it, why, when it expires. And the
> plain English summary next to it? A model wrote that. It has no tools. It
> can't touch your routing.**

## J. 2:41 — Land it

*Back to the instrument. It breaks, and recovers, and holds on the gap.*

> **The traffic here is simulated, on purpose, so anyone can run this and get
> the same result. Point it at real routes and nothing changes. A safe
> decision, a human where it matters, and proof of the money you got back.**

Stop on "got back" around 2:58. The end card carries that line in text. No sign
off, no thank you.

---

## Delivering it

- 383 words over 2:54 is 132 words a minute, which is slower than you talk
  normally. If you finish a beat early, hold the silence rather than filling it.
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
