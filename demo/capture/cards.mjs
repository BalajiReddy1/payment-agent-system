/*
  Renders the title, end and lower-third cards for the pitch video.

  The cards are drawn inside the running site so they inherit the real tokens
  and the real self-hosted fonts. Nothing here re-implements the brand, which
  means the cards cannot drift away from the product.

  Usage: node cards.mjs
*/

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(HERE, "../out/cards");
const SITE = process.env.SITE_URL ?? "http://localhost:3100";

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} ${code}\n${stderr.slice(-1200)}`))));
  });
}

const MARK = `
  <svg viewBox="0 0 20 20" style="width:56px;height:56px">
    <rect x="0" y="4" width="9" height="3.4" rx="0.6" fill="var(--signal)"></rect>
    <rect x="0" y="12.6" width="20" height="3.4" rx="0.6" fill="var(--proof)"></rect>
  </svg>`;

const CARDS = {
  title: {
    transparent: false,
    html: `
      <div style="display:grid;place-content:center;justify-items:start;gap:2rem;height:100%;padding:0 12rem">
        ${MARK}
        <h1 style="margin:0;font-size:7rem;font-weight:500;letter-spacing:-0.035em;line-height:1">Flowstate</h1>
        <p style="margin:0;font-size:2rem;color:var(--ink-3);letter-spacing:-0.02em">Payment recovery with evidence.</p>
      </div>`,
  },
  end: {
    transparent: false,
    html: `
      <div style="display:grid;place-content:center;justify-items:start;gap:2.5rem;height:100%;padding:0 12rem">
        ${MARK}
        <h1 style="margin:0;max-width:22ch;font-size:4.2rem;font-weight:500;letter-spacing:-0.03em;line-height:1.05">
          A safe decision, a person where it matters,<br>and proof of the money you got back.
        </h1>
        <div style="display:flex;gap:3rem;align-items:baseline;padding-top:1.5rem;border-top:1px solid var(--line);width:100%">
          <span style="font-size:1.6rem">Balaji Thukuntala</span>
          <span class="mono" style="font-size:1.15rem;color:var(--ink-4);letter-spacing:0.04em">
            simulated traffic · no live payment action
          </span>
        </div>
      </div>`,
  },
  "lower-third": {
    transparent: true,
    html: `
      <div style="position:absolute;left:6rem;bottom:6rem;display:grid;gap:0.7rem;
                  padding:1.5rem 2rem;background:var(--bg);border-left:none;border:1px solid var(--line)">
        <span style="font-size:2rem;letter-spacing:-0.025em">Balaji Thukuntala</span>
        <span class="mono" style="font-size:1.05rem;color:var(--signal-hi);letter-spacing:0.06em;text-transform:uppercase">
          Built Flowstate
        </span>
      </div>`,
  },
};

await mkdir(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 2,
  colorScheme: "dark",
});
const page = await context.newPage();
await page.goto(SITE, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);

for (const [name, card] of Object.entries(CARDS)) {
  await page.evaluate(
    ([markup, transparent]) => {
      document.querySelectorAll(".video-card").forEach((node) => node.remove());
      const layer = document.createElement("div");
      layer.className = "video-card";
      layer.style.cssText = `position:fixed;inset:0;z-index:99999;background:${transparent ? "transparent" : "var(--bg)"}`;
      layer.innerHTML = markup;
      document.body.append(layer);
      document.documentElement.style.background = transparent ? "transparent" : "var(--bg)";
      document.body.style.background = transparent ? "transparent" : "var(--bg)";
    },
    [card.html, card.transparent],
  );
  await page.waitForTimeout(350);

  const png = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: png, omitBackground: card.transparent, scale: "css" });
  console.log(`  ${name}.png`);

  if (card.transparent) continue;

  // Cards enter and leave on a soft fade, and hold long enough to be read
  // without stalling a three minute video.
  const seconds = name === "title" ? 5 : 6;
  const mp4 = path.join(OUT, `${name}.mp4`);
  await run("ffmpeg", [
    "-y", "-loglevel", "error",
    "-loop", "1", "-t", String(seconds), "-i", png,
    "-f", "lavfi", "-t", String(seconds), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    "-vf", `scale=1920:1080,fade=in:st=0:d=0.5,fade=out:st=${seconds - 0.7}:d=0.7,format=yuv420p`,
    "-r", "30", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
    "-c:a", "aac", "-shortest", "-movflags", "+faststart",
    mp4,
  ]);
  console.log(`  ${name}.mp4`);
}

await browser.close();
console.log(`\nCards written to ${OUT}`);
