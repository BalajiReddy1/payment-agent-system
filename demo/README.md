# Pitch video

Everything needed to produce the submission video. The spoken script is
[`../PRESENTATION.md`](../PRESENTATION.md); this covers the mechanics.

You record one thing: your voice. The picture is generated from the real running
product, so there is no screen recording, no scrolling on camera, and no fumbled
clicks.

```text
capture/record.mjs   drives the real site and desk, writes out/footage/*.mp4
capture/cards.mjs    renders the title and end cards from the live design system
cut/assemble.mjs   cuts the rough edit, then the final video
out/                 generated, not committed
```

## Requirements

- ffmpeg and ffprobe on PATH
- Node 20 or newer
- One-time: `cd capture && npm install && npx playwright install chromium`

## 1. Generate the footage

Both servers must be running, and the frontend must be the production build so
the dev indicator stays out of frame.

```bash
uvicorn api.main:app --port 8000
```

```bash
cd frontend && npm run build && npx next start -p 3100
```

```bash
cd demo/capture && node record.mjs && node cards.mjs
```

Fifteen clips land in `out/footage`. Re-record a single shot by name:

```bash
node record.mjs 12-desk-measure
```

The desk shots run the deterministic demo against the live runtime, so the
incident, the approval and the measurement on screen are real. The rupee figure
moves a little between runs, which is why the script never says it out loud.

## 2. Cut the film

```bash
cd demo/cut && node assemble.mjs
```

Writes `out/flowstate-demo.mp4`: 3:05, silent, every second real product. There
are no captions or slates in it, so nothing on screen argues with what you say
over the top. It prints the timing table as it goes, and that table is the one
in `../PRESENTATION.md`.

## 3. Record the narration

Play the film and read `../PRESENTATION.md` against it, in one continuous pass.
Narration runs 0:05 to 2:59; the cards at either end are silent.

- Use a wired headset or any dedicated mic. Laptop mics make a good pitch sound
  like a support call.
- Sit down, look at the lens if you are also filming yourself, and let the cuts
  pace you rather than watching a clock.
- Fluffed a line? Pause two full seconds and start that sentence again. The
  silence makes the bad take trivial to cut.

Save it as `demo/in/voice.wav`.

## 4. Mux it

```bash
cd demo/cut && node assemble.mjs --voice ../in/voice.wav
```

Writes `out/flowstate-pitch.mp4`. The output is always exactly the length of the
film: a track that runs long is trimmed rather than left playing over a frozen
frame, and one that runs short is padded rather than clipping the end card.

To add your face, record camera and voice together and pass the same file twice:

```bash
node assemble.mjs --voice ../in/take.mp4 --face ../in/take.mp4
```

It insets bottom right over the segments marked `face: "pip"` in the timeline
(the ticker, the home page and the demo start) and stays off every panel that
has numbers on it.

## Adjusting the edit

`TIMELINE` in `cut/assemble.mjs` is the edit decision list. Each entry has:

| Field | Meaning |
| --- | --- |
| `seconds` | How long the segment runs in the finished video |
| `clip` | Which file in `out/footage` to use, or omit for camera |
| `from` | In point inside that clip |
| `face` | `pip` to allow a camera inset over this segment |
| `fade` | `in` or `out` for the two deliberate section breaks |
| `crop` | `[x, y, w, h]` to punch in. Enlarges, so prefer a tighter capture |
| `beat` | Which narration beat this segment carries |

Keep it in step with the table in `PRESENTATION.md`. If a clip is too short for
its beat the assembler warns and holds the last frame, which is a signal to
raise the wait in `capture/record.mjs` and re-record that shot.

## Unused footage

`03-problem`, `05-guardrails`, `09-onboarding` and `14-desk-receipt` are not in
the three minute cut. They are there if you want a longer version, and for
stills.

`14-desk-receipt` is the desk's own receipt panel, including the assessment.
It is worth swapping back in for the `receipt` beat once the advisor has quota,
because it shows a model-written assessment attributed on screen. Until then
the beat uses `07-revision`, the rendered policy revision on the home page,
which carries the same line without a quota notice in frame.

## The advisor in the footage

The desk names the model that wrote each assessment. Set `GEMINI_API_KEY` in
`.env` before recording, or the desk will correctly say the advisor is off and
the footage will show the deterministic lane speaking for itself.

`gemini-3.6-flash` is the configured primary and returns 503 under load often
enough that the desk may name the fallback instead. That is the system working:
the assessment is attributed to whichever model actually answered.

**Mind the quota.** The Gemini free tier allows 20 generate requests per day per
model, and one `Run demo` consults the advisor once per open incident, so about
ten runs exhausts a model for the day. Rehearse against the desk without
clicking Run demo, and check the quota is intact before you record. When it is
gone the desk says so on the incident rather than looking broken.

If you want the primary named in the footage, check the snapshot reports it
before recording the desk shots:

```bash
curl -s http://localhost:8000/snapshot | python -c "import json,sys; print(json.load(sys.stdin)['agent']['advisor_model'])"
```

Record `10-desk-incident` first: it clicks Run demo and resets the runtime, so
recording it after the others would leave them showing a different incident.

## Notes on the footage

- The hero shots wait for the instrument's fifteen second loop to roll over
  before recording starts, so `01-hero` and `02-scope` always open on a healthy
  route and contain the full arc. In points in the edit stay valid when you
  re-record.
- Close-ups (`02-scope`, `05-guardrails`, `07-revision`, `11-desk-decision`)
  are captured at a smaller CSS viewport with a doubled device pixel ratio.
  They are rendered at that size, not enlarged afterwards, so they stay sharp.
- Long holds carry a slow drift rather than sitting still. The desk also polls
  every four seconds, so its numbers move on their own.
