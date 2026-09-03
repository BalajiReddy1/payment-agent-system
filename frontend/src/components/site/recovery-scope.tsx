"use client";

import { useEffect, useRef } from "react";

import { onScrollFrame } from "@/lib/in-view";

/*
  The hero image is the product, drawn honestly.

  Two traces of payment success run right to left: the live route, and the
  holdout that never receives the intervention. A route degrades, Flowstate
  publishes a bounded response, and the two traces separate. That separation is
  the entire pitch, so it is the picture. Individual declines are kept as raw
  ticks along the bottom, because the trace is a summary of them.

  Canvas cannot read CSS custom properties, so the palette is mirrored here
  from styles/tokens.css as sRGB.
*/
const PALETTE = {
  idle: "#899493", //  --ink-4
  proof: "#4ee9cc", //  --proof
  signal: "#fd6a31", //  --signal
  rule: "#2d3534",
  hold: "#7d8887", //  3.9:1 on --bg, subordinate but still readable
};

const CYCLE = 15_000;
const STEP = 80;
const COL_W = 4;
const WINDOW = 26;

/* The plot only covers 35% to 100%, so a real collapse is legible. */
const FLOOR = 0.35;

type Phase = "watch" | "degrade" | "act" | "recover";
type Column = { live: boolean; hold: boolean; marker: boolean; phase: Phase };

function phaseAt(t: number): Phase {
  if (t < 3_800) return "watch";
  if (t < 7_200) return "degrade";
  if (t < 8_100) return "act";
  return "recover";
}

function failRates(t: number, phase: Phase): [number, number] {
  if (phase === "watch") return [0.04, 0.04];
  if (phase === "degrade") return [0.55, 0.55];
  if (phase === "act") return [0.55 - ((t - 7_200) / 900) * 0.42, 0.55];
  return [0.11, 0.53];
}

const CAPTIONS: Record<Phase, { tone: string; text: string }> = {
  watch: { tone: "idle", text: "Watching five issuer routes across a rolling five minute window." },
  degrade: { tone: "signal", text: "ICICI_BANK declining. Sustained for 94 seconds, not a single error spike." },
  act: { tone: "signal", text: "Traffic to the failing route reduced. A holdout is deliberately kept back." },
  recover: { tone: "proof", text: "Treated payments recovered. The untreated holdout did not." },
};

export function RecoveryScope() {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const captionRef = useRef<HTMLParagraphElement>(null);
  const liveRef = useRef<HTMLSpanElement>(null);
  const holdRef = useRef<HTMLSpanElement>(null);
  const deltaRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const columns: Column[] = [];
    let width = 0;
    let height = 0;
    let capacity = 0;
    let frame = 0;
    let timer = 0;
    let elapsed = 0;
    let lastPhase: Phase | null = null;
    let lastReadout = 0;

    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(280, Math.round(rect.width));
      height = Math.max(180, Math.round(rect.height));
      capacity = Math.ceil(width / COL_W) + WINDOW + 2;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const push = (t: number) => {
      const phase = phaseAt(t);
      const [liveRate, holdRate] = failRates(t, phase);
      const marker = lastPhase !== "act" && phase === "act";
      lastPhase = phase;
      columns.push({ live: Math.random() < liveRate, hold: Math.random() < holdRate, marker, phase });
      while (columns.length > capacity) columns.shift();
    };

    /* Rolling success rate ending at `index`, the same summary an operator sees. */
    const rateAt = (index: number, key: "live" | "hold") => {
      const start = Math.max(0, index - WINDOW + 1);
      let ok = 0;
      let total = 0;
      for (let i = start; i <= index; i += 1) {
        total += 1;
        if (!columns[i][key]) ok += 1;
      }
      return total ? ok / total : 1;
    };

    const readout = (phase: Phase) => {
      if (columns.length < 2) return;
      const last = columns.length - 1;
      const live = rateAt(last, "live");
      const hold = rateAt(last, "hold");
      const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
      if (liveRef.current) liveRef.current.textContent = pct(live);
      if (holdRef.current) holdRef.current.textContent = pct(hold);
      if (deltaRef.current) {
        const delta = (live - hold) * 100;
        deltaRef.current.textContent = `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}pp`;
        deltaRef.current.dataset.tone = phase === "recover" && delta > 8 ? "proof" : "idle";
      }
      if (captionRef.current) {
        const caption = CAPTIONS[phase];
        if (captionRef.current.textContent !== caption.text) {
          captionRef.current.dataset.tone = caption.tone;
          captionRef.current.textContent = caption.text;
        }
      }
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      const padTop = 14;
      const tickBand = 30;
      const plot = Math.max(40, height - padTop - tickBand);
      const y = (rate: number) => padTop + (1 - (Math.max(FLOOR, rate) - FLOOR) / (1 - FLOOR)) * plot;
      const phase = phaseAt(elapsed);
      const toneOf = (p: Phase) => (p === "recover" ? PALETTE.proof : p === "watch" ? PALETTE.idle : PALETTE.signal);
      const liveColor = toneOf(phase);

      // Reference lines at 100, 75 and 50 percent.
      ctx.strokeStyle = PALETTE.rule;
      ctx.lineWidth = 1;
      for (const level of [1, 0.75, 0.5]) {
        ctx.beginPath();
        ctx.setLineDash(level === 1 ? [] : [2, 5]);
        ctx.moveTo(0, Math.round(y(level)) + 0.5);
        ctx.lineTo(width, Math.round(y(level)) + 0.5);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      const visibleFrom = Math.max(WINDOW - 1, columns.length - Math.ceil(width / COL_W));
      const xAt = (index: number) => width - (columns.length - 1 - index) * COL_W;

      // Decision marker, drawn behind the traces.
      for (let i = visibleFrom; i < columns.length; i += 1) {
        if (!columns[i].marker) continue;
        ctx.strokeStyle = PALETTE.signal;
        ctx.globalAlpha = 0.55;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(Math.round(xAt(i)) + 0.5, 0);
        ctx.lineTo(Math.round(xAt(i)) + 0.5, padTop + plot);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      }

      const trace = (key: "live" | "hold") => {
        ctx.beginPath();
        for (let i = visibleFrom; i < columns.length; i += 1) {
          const px = xAt(i);
          const py = y(rateAt(i, key));
          if (i === visibleFrom) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
      };

      // Live trace with a flat translucent fill beneath it.
      trace("live");
      ctx.lineTo(width, padTop + plot);
      ctx.lineTo(xAt(visibleFrom), padTop + plot);
      ctx.closePath();
      ctx.fillStyle = liveColor;
      ctx.globalAlpha = 0.13;
      ctx.fill();
      ctx.globalAlpha = 1;

      ctx.strokeStyle = PALETTE.hold;
      ctx.lineWidth = 1.25;
      ctx.setLineDash([4, 4]);
      trace("hold");
      ctx.stroke();
      ctx.setLineDash([]);

      // Coloured per segment, so the healthy stretch never gets recoloured by
      // whatever is happening now.
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      for (let i = visibleFrom + 1; i < columns.length; i += 1) {
        ctx.strokeStyle = toneOf(columns[i].phase);
        ctx.beginPath();
        ctx.moveTo(xAt(i - 1), y(rateAt(i - 1, "live")));
        ctx.lineTo(xAt(i), y(rateAt(i, "live")));
        ctx.stroke();
      }

      // Leading marker on the live trace.
      const head = y(rateAt(columns.length - 1, "live"));
      ctx.fillStyle = liveColor;
      ctx.beginPath();
      ctx.arc(width - 1, head, 3, 0, Math.PI * 2);
      ctx.fill();

      // Raw declines, the evidence the trace summarises.
      const tickTop = padTop + plot + 12;
      for (let i = visibleFrom; i < columns.length; i += 1) {
        const px = Math.round(xAt(i));
        if (columns[i].live) {
          ctx.fillStyle = PALETTE.signal;
          ctx.globalAlpha = 0.95;
          ctx.fillRect(px, tickTop, 2, 7);
        }
        if (columns[i].hold) {
          ctx.fillStyle = PALETTE.signal;
          ctx.globalAlpha = 0.4;
          ctx.fillRect(px, tickTop + 10, 2, 7);
        }
      }
      ctx.globalAlpha = 1;
    };

    const seed = () => {
      columns.length = 0;
      lastPhase = null;
      for (let i = capacity; i > 0; i -= 1) push(Math.max(0, elapsed - i * STEP));
    };

    resize();
    elapsed = reduced.matches ? 12_500 : 0;
    seed();
    draw();
    readout(phaseAt(elapsed));

    const loop = (now: number) => {
      draw();
      if (now - lastReadout > 200) {
        lastReadout = now;
        readout(phaseAt(elapsed));
      }
      frame = requestAnimationFrame(loop);
    };

    let running = false;

    const start = () => {
      if (running || reduced.matches) return;
      running = true;
      timer = window.setInterval(() => {
        elapsed = (elapsed + STEP) % CYCLE;
        if (elapsed < STEP) seed();
        push(elapsed);
      }, STEP);
      frame = requestAnimationFrame(loop);
    };

    const stop = () => {
      if (!running) return;
      running = false;
      window.clearInterval(timer);
      cancelAnimationFrame(frame);
    };

    // Nothing runs while the instrument is scrolled away or the tab is hidden.
    const sync = () => {
      const rect = wrap.getBoundingClientRect();
      const onScreen = rect.bottom > 0 && rect.top < window.innerHeight;
      if (onScreen && !document.hidden) start();
      else stop();
    };
    const unwatch = onScrollFrame(sync);
    document.addEventListener("visibilitychange", sync);

    const sizing = new ResizeObserver(() => {
      resize();
      seed();
      draw();
      // A layout change can move the instrument into or out of view without a
      // scroll, so re-check here rather than waiting for an event that may
      // never come.
      sync();
    });
    sizing.observe(wrap);

    return () => {
      stop();
      unwatch();
      sizing.disconnect();
      document.removeEventListener("visibilitychange", sync);
    };
  }, []);

  return (
    <figure className="scope">
      <figcaption className="scope-head">
        <span className="kicker">
          <span className="dot" data-tone="signal" />
          Live simulation
        </span>
        <span className="mono scope-window">rolling 05:00</span>
      </figcaption>

      <div className="scope-canvas" ref={wrapRef}>
        <canvas
          ref={canvasRef}
          role="img"
          aria-label="Payment success rate for the live route and the untreated holdout. The live route recovers after a bounded response; the holdout does not."
        />
      </div>

      <div className="scope-legend" aria-hidden="true">
        <span data-kind="live">Live traffic</span>
        <span data-kind="hold">Holdout, untreated</span>
      </div>

      <p className="scope-caption" ref={captionRef} data-tone="idle" aria-live="polite">
        Watching five issuer routes across a rolling five minute window.
      </p>

      <dl className="scope-readout">
        <div>
          <dt>Live</dt>
          <dd>
            <span className="num" ref={liveRef}>
              96.0%
            </span>
          </dd>
        </div>
        <div>
          <dt>Holdout</dt>
          <dd>
            <span className="num" ref={holdRef}>
              96.0%
            </span>
          </dd>
        </div>
        <div>
          <dt>Difference</dt>
          <dd>
            <span className="num scope-delta" ref={deltaRef} data-tone="idle">
              +0.0pp
            </span>
          </dd>
        </div>
      </dl>
    </figure>
  );
}
