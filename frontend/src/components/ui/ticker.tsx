"use client";

import { useEffect, useRef, useState } from "react";

import { onEnterView } from "@/lib/in-view";

const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);

const whole = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const rupees = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

/*
  `format` is a named preset rather than a function so the component can be
  used directly from a server component.
*/
export type TickerFormat = "int" | "inr" | "pp";

function render(value: number, format: TickerFormat) {
  if (format === "inr") return rupees.format(value);
  if (format === "pp") return `${value >= 0 ? "+" : ""}${value.toFixed(1)}pp`;
  return whole.format(value);
}

/*
  Counts to `value` the first time it scrolls into view. The final value is the
  initial render, so the number is correct before and without JavaScript.
*/
export function Ticker({
  value,
  format = "int",
  duration = 1200,
}: {
  value: number;
  format?: TickerFormat;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [display, setDisplay] = useState(() => render(value, format));

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplay(render(value, format));
      return;
    }

    let frame = 0;
    const release = onEnterView(node, () => {
      const started = performance.now();
      const step = (now: number) => {
        const progress = Math.min(1, (now - started) / duration);
        setDisplay(render(value * easeOut(progress), format));
        if (progress < 1) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    });

    return () => {
      release();
      cancelAnimationFrame(frame);
    };
  }, [value, duration, format]);

  return (
    <span className="num" ref={ref}>
      {display}
    </span>
  );
}
