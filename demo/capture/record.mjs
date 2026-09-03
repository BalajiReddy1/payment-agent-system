/*
  Records the silent product footage for the Flowstate pitch video.

  This drives the real product in a real browser. Nothing on screen is mocked:
  the desk shots run against the FastAPI runtime and its deterministic demo.

  Frames come from the Chrome DevTools screencast rather than Playwright's
  built-in video, because it lets us keep per-frame timestamps and hand ffmpeg
  a variable frame rate. Text stays crisp instead of being re-timed by a fixed
  25fps encoder.

  Close-ups are captured at a smaller CSS viewport with deviceScaleFactor 2, so
  a "zoom" is genuinely rendered at 1080p rather than upscaled after the fact.

  Usage:
    node record.mjs                 # every shot
    node record.mjs proof desk-run  # only the named shots
*/

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(HERE, "../out/footage");
const WORK = path.resolve(HERE, "../out/.frames");

const SITE = process.env.SITE_URL ?? "http://localhost:3100";
const WIDTH = 1920;
const HEIGHT = 1080;
const FPS = 30;

/* ------------------------------------------------------------ utilities */

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}\n${stderr.slice(-1500)}`))));
  });
}

/*
  Eased scroll inside the page. Exponential ease-out matches the motion the
  site itself uses, so a scroll shot feels like the product rather than like a
  robot dragging a scrollbar.
*/
async function glide(page, to, ms = 1800) {
  await page.evaluate(
    ([target, duration]) =>
      new Promise((done) => {
        const start = window.scrollY;
        const delta = target - start;
        const t0 = performance.now();
        const ease = (t) => 1 - Math.pow(1 - t, 4);
        const step = (now) => {
          const p = Math.min(1, (now - t0) / duration);
          window.scrollTo(0, start + delta * ease(p));
          window.dispatchEvent(new Event("scroll"));
          if (p < 1) requestAnimationFrame(step);
          else done();
        };
        requestAnimationFrame(step);
      }),
    [to, ms],
  );
}

async function topOf(page, selector, offset = 90) {
  return page.evaluate(
    ([sel, off]) => {
      const node = document.querySelector(sel);
      if (!node) throw new Error(`missing ${sel}`);
      return Math.max(0, node.getBoundingClientRect().top + window.scrollY - off);
    },
    [selector, offset],
  );
}

/* A very slow drift. Long holds need a little life without turning into a
   scroll the viewer has to follow. */
async function drift(page, pixels, ms) {
  await glide(page, (await page.evaluate(() => window.scrollY)) + pixels, ms);
}

/* Jump without animation, for the start of a shot. */
async function place(page, selector, offset = 90) {
  const y = await topOf(page, selector, offset);
  await page.evaluate((to) => {
    window.scrollTo({ top: to, behavior: "instant" });
    window.dispatchEvent(new Event("scroll"));
  }, y);
  await wait(700);
}

/* ------------------------------------------------------------ recording */

async function record(browser, shot) {
  const scale = shot.scale ?? 1;
  const context = await browser.newContext({
    viewport: { width: Math.round(WIDTH / scale), height: Math.round(HEIGHT / scale) },
    deviceScaleFactor: scale,
    colorScheme: "dark",
    reducedMotion: "no-preference",
  });
  const page = await context.newPage();
  const frames = [];
  const dir = path.join(WORK, shot.name);

  await rm(dir, { recursive: true, force: true });
  await mkdir(dir, { recursive: true });

  await page.goto(`${SITE}${shot.path}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  if (shot.setup) await shot.setup(page);
  await wait(shot.lead ?? 800);

  const cdp = await context.newCDPSession(page);
  let index = 0;
  const pending = [];

  cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
    const file = path.join(dir, `f-${String(index++).padStart(5, "0")}.jpg`);
    frames.push({ file, t: metadata.timestamp });
    pending.push(writeFile(file, Buffer.from(data, "base64")));
    cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
  });

  await cdp.send("Page.startScreencast", {
    format: "jpeg",
    quality: 92,
    maxWidth: WIDTH,
    maxHeight: HEIGHT,
    everyNthFrame: 1,
  });

  await shot.play(page);

  await cdp.send("Page.stopScreencast");
  await Promise.all(pending);
  await context.close();

  if (frames.length < 4) throw new Error(`${shot.name}: only ${frames.length} frames captured`);

  // Per-frame durations from the screencast timestamps, so motion keeps its
  // real pacing even when the compositor drops a frame.
  const lines = [];
  for (let i = 0; i < frames.length; i += 1) {
    const next = frames[i + 1];
    const duration = next ? Math.max(0.008, next.t - frames[i].t) : 1 / FPS;
    lines.push(`file '${frames[i].file.replaceAll("\\", "/")}'`);
    lines.push(`duration ${duration.toFixed(4)}`);
  }
  lines.push(`file '${frames.at(-1).file.replaceAll("\\", "/")}'`);

  const listFile = path.join(dir, "frames.txt");
  await writeFile(listFile, lines.join("\n"));

  const target = path.join(OUT, `${shot.name}.mp4`);
  await run("ffmpeg", [
    "-y", "-loglevel", "error",
    "-f", "concat", "-safe", "0", "-i", listFile,
    "-vf", `fps=${FPS},scale=${WIDTH}:${HEIGHT}:flags=lanczos,format=yuv420p`,
    "-c:v", "libx264", "-preset", "slow", "-crf", "17",
    "-movflags", "+faststart",
    target,
  ]);

  await rm(dir, { recursive: true, force: true });
  const seconds = (frames.at(-1).t - frames[0].t).toFixed(1);
  console.log(`  ${shot.name}.mp4  ${seconds}s  ${frames.length} frames`);
}

/*
  The hero instrument runs a fifteen second loop. Waiting for it to roll over
  means a shot always starts on a healthy route and contains the whole arc, so
  the in points in the edit stay stable across re-records.
*/
async function syncToCycle(page) {
  const tone = (want) =>
    page.waitForFunction(
      (value) => document.querySelector(".scope-caption")?.dataset.tone === value,
      want,
      { timeout: 25_000 },
    );
  await tone("proof");
  await tone("idle");
}

/* Desk shots run as a configured operator, so the first-run prompt stays out
   of the frame. */
async function asConfigured(page, then) {
  await page.evaluate(() =>
    localStorage.setItem(
      "flowstate.setup.v1",
      JSON.stringify({
        source: "simulator",
        blastRadius: 0.18,
        autoTier: "automatic",
        expiryMinutes: 15,
        approver: "ops@flowstate.local",
        holdout: 0.15,
        completedAt: new Date().toISOString(),
      }),
    ),
  );
  await page.reload({ waitUntil: "networkidle" });
  await wait(2500);
  if (then) await then(page);
}

/* ---------------------------------------------------------------- shots */

const SHOTS = [
  {
    // Opening ticker. Everything but the tape is hidden so the shot is a strip
    // of individual payments, a few of them declining, on near black.
    name: "00-tape",
    path: "/",
    scale: 2.2,
    lead: 600,
    setup: async (page) => {
      await page.evaluate(() => {
        document.querySelector(".nav").style.display = "none";
        document.querySelector(".hero-grid").style.display = "none";
        document.querySelectorAll(".band, .site-foot").forEach((node) => {
          node.style.display = "none";
        });
        const hero = document.querySelector(".hero");
        hero.style.cssText = "min-height:100svh;display:grid;align-content:center;padding:0";
        window.dispatchEvent(new Event("resize"));
      });
    },
    play: async (page) => wait(21_000),
  },
  {
    // A full pass of the hero instrument: healthy, degrading, decision, split.
    name: "01-hero",
    path: "/",
    lead: 0,
    setup: syncToCycle,
    play: async (page) => wait(17_000),
  },
  {
    // The same instrument, framed close, so the two traces separating reads on
    // a phone. This is the single most important image in the video.
    name: "02-scope",
    path: "/",
    scale: 2,
    lead: 0,
    setup: async (page) => {
      await page.evaluate(() => {
        document.querySelector(".nav").style.display = "none";
        const hero = document.querySelector(".hero-grid");
        hero.style.gridTemplateColumns = "minmax(0, 1fr)";
        document.querySelector(".hero-copy").style.display = "none";
        window.dispatchEvent(new Event("resize"));
      });
      await syncToCycle(page);
    },
    play: async (page) => wait(47_000),
  },
  {
    name: "03-problem",
    path: "/",
    setup: (page) => place(page, ".problem", 140),
    play: async (page) => {
      await wait(1600);
      await glide(page, await topOf(page, ".problem", -120), 3200);
      await wait(1200);
    },
  },
  {
    // The five step loop, paced so each stage is legible.
    name: "04-loop",
    path: "/",
    setup: (page) => place(page, ".loop-band", 120),
    play: async (page) => {
      await wait(1200);
      for (const step of ["reason", "decide", "guard", "prove"]) {
        await glide(page, await topOf(page, `[data-step="${step}"]`, 380), 1500);
        await wait(1700);
      }
    },
  },
  {
    name: "05-guardrails",
    path: "/",
    scale: 1.5,
    setup: (page) => place(page, ".approval-card", 200),
    play: async (page) => wait(4500),
  },
  {
    // The proof section, entered from below so the bars animate on reveal.
    name: "06-proof",
    path: "/",
    setup: (page) => place(page, ".proof", 900),
    play: async (page) => {
      await wait(900);
      await glide(page, await topOf(page, ".proof", 90), 2400);
      await wait(12_500);
    },
  },
  {
    name: "07-revision",
    path: "/",
    scale: 1.4,
    setup: (page) => place(page, ".revision", 180),
    play: async (page) => wait(4500),
  },
  {
    name: "08-planes",
    path: "/",
    setup: (page) => place(page, ".build", 120),
    play: async (page) => {
      await wait(1400);
      await glide(page, await topOf(page, ".plane", 260), 1800);
      await wait(9000);
    },
  },
  {
    // First run. Clicks through the real flow rather than cutting stills.
    name: "09-onboarding",
    path: "/onboarding",
    setup: async (page) => {
      await page.evaluate(() => localStorage.removeItem("flowstate.setup.v1"));
      await page.reload({ waitUntil: "networkidle" });
    },
    play: async (page) => {
      await wait(2200);
      await page.getByRole("button", { name: "Continue" }).click();
      await wait(2600);
      await page.locator('input[type="range"]').first().focus();
      for (let i = 0; i < 7; i += 1) {
        await page.keyboard.press("ArrowRight");
        await wait(110);
      }
      await wait(1500);
      await page.getByRole("button", { name: "Continue" }).click();
      await wait(2400);
      await page.getByRole("button", { name: "Continue" }).click();
      await wait(2400);
      await page.getByRole("button", { name: "Continue" }).click();
      await wait(3000);
      await page.getByRole("button", { name: "Activate Flowstate" }).click();
      await wait(3200);
    },
  },
  {
    // The desk taking the incident. Run demo, then let the record fill in.
    name: "10-desk-incident",
    path: "/desk",
    lead: 1200,
    setup: (page) => asConfigured(page),
    play: async (page) => {
      await wait(1200);
      await page.getByRole("button", { name: "Run demo" }).click();
      await wait(13_000);
      await drift(page, 220, 4000);
      await wait(9000);
    },
  },
  {
    name: "11-desk-decision",
    path: "/desk",
    scale: 1.35,
    lead: 1200,
    setup: (page) => asConfigured(page, (p) => place(p, "#decision", 150)),
    play: async (page) => {
      await wait(9000);
      await drift(page, 90, 6000);
      await wait(9000);
    },
  },
  {
    // The measurement. Entered from below so the bars grow on screen.
    name: "12-desk-measure",
    path: "/desk",
    lead: 1200,
    setup: (page) => asConfigured(page, (p) => place(p, "#evidence", 780)),
    play: async (page) => {
      await wait(900);
      await glide(page, await topOf(page, "#evidence", 95), 2200);
      await wait(14_000);
      await drift(page, 120, 5000);
      await wait(4000);
    },
  },
  {
    name: "13-desk-routes",
    path: "/desk",
    lead: 1200,
    setup: (page) => asConfigured(page, (p) => place(p, "#network", 120)),
    play: async (page) => {
      await wait(6000);
      await drift(page, 130, 4000);
      await wait(3000);
    },
  },
  {
    name: "14-desk-receipt",
    path: "/desk",
    lead: 1200,
    setup: (page) => asConfigured(page, (p) => place(p, "#record", 120)),
    play: async (page) => {
      await wait(2000);
      await glide(page, await topOf(page, ".revisions", 260), 2200);
      await wait(8000);
    },
  },
];

/* ----------------------------------------------------------------- main */

const only = process.argv.slice(2);
const queue = only.length ? SHOTS.filter((shot) => only.some((name) => shot.name.includes(name))) : SHOTS;

if (!queue.length) {
  console.error(`No shots matched. Available:\n${SHOTS.map((s) => `  ${s.name}`).join("\n")}`);
  process.exit(1);
}

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ args: ["--force-color-profile=srgb", "--hide-scrollbars"] });

console.log(`Recording ${queue.length} shot(s) from ${SITE}`);
try {
  for (const shot of queue) {
    await record(browser, shot);
  }
} finally {
  await browser.close();
  await rm(WORK, { recursive: true, force: true });
}
console.log(`\nFootage written to ${OUT}`);
