/*
  Cuts the pitch video.

    node assemble.mjs
      Builds out/flowstate-demo.mp4 - the finished silent film. Every second is
      real product, with no burned in captions, so a voice track can be laid
      over it and nothing on screen argues with what is being said.

    node assemble.mjs --voice ../in/voice.wav
      The same cut with a narration track muxed in.

    node assemble.mjs --voice ../in/take.mp4 --face ../in/take.mp4
      Adds a camera inset over the segments marked `face: "pip"`.

  Every segment is rendered to a uniform 1920x1080 / 30fps / yuv420p clip and
  then joined with the concat demuxer. That is slower than one enormous
  filter_complex and far easier to reason about when a shot needs changing.
*/

import { spawn } from "node:child_process";
import { access, mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FOOTAGE = path.resolve(HERE, "../out/footage");
const CARDS = path.resolve(HERE, "../out/cards");
const OUT = path.resolve(HERE, "../out");
const WORK = path.resolve(HERE, "../out/.segments");

const W = 1920;
const H = 1080;
const FPS = 30;

/* ------------------------------------------------------------- timeline */

/*
  `seconds` is what the segment occupies in the finished video, `from` is the in
  point inside the source clip, and `beat` names the line of narration this
  segment exists to carry. The durations are sized from the word counts in
  PRESENTATION.md at about 145 words a minute plus a breath, so the two files
  have to move together.

  `fade` marks the two deliberate breaths in the film: out of the idea and into
  the product, and out of the product at the end. Everything else is a straight
  cut.
*/
const TIMELINE = [
  { id: "scene", seconds: 19, clip: "00-tape", from: 1.0, fade: "in", beat: "A. The scene" },
  { id: "clock", seconds: 12, clip: "01-hero", from: 1.0, face: "pip", beat: "B. The decision" },
  { id: "name", seconds: 13, clip: "04-loop", from: 0.5, face: "pip", beat: "C. Name it" },
  { id: "thesis", seconds: 19, clip: "02-scope", from: 12.0, fade: "out", beat: "D. The thesis" },
  { id: "start", seconds: 11, clip: "10-desk-incident", from: 0.5, fade: "in", face: "pip", beat: "E. Start the demo" },
  { id: "detect", seconds: 13, clip: "10-desk-incident", from: 12.0, beat: "F. Detection and choice" },
  { id: "routes", seconds: 6, clip: "13-desk-routes", from: 1.0, beat: "F. Detection and choice" },
  { id: "approve", seconds: 20, clip: "11-desk-decision", from: 1.0, beat: "G. The human boundary" },
  { id: "measure", seconds: 20, clip: "12-desk-measure", from: 0.5, beat: "H. The proof" },
  { id: "claim", seconds: 10, clip: "06-proof", from: 3.0, beat: "H. The proof" },
  // The rendered policy revision, rather than the desk's receipt panel: this
  // beat is about the signed revision and this shot is only that.
  { id: "receipt", seconds: 7, clip: "07-revision", from: 1.0, beat: "I. Credibility" },
  { id: "planes", seconds: 6, clip: "08-planes", from: 4.0, beat: "I. Credibility" },
  { id: "close", seconds: 18, clip: "02-scope", from: 28.0, fade: "out", beat: "J. Close" },
];

/* Cards bookend the film. Durations must match those set in cards.mjs. */
const HEAD = ["title"];
const TAIL = ["end"];
const HEAD_SECONDS = 5;
const TAIL_SECONDS = 6;

/* ------------------------------------------------------------ utilities */

function run(args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn("ffmpeg", args, { cwd, stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg exited ${code}\n${stderr.slice(-2000)}`))));
  });
}

function probe(file) {
  return new Promise((resolve, reject) => {
    const child = spawn("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file], {
      stdio: ["ignore", "pipe", "ignore"],
    });
    let out = "";
    child.stdout.on("data", (chunk) => (out += chunk));
    child.on("error", reject);
    child.on("close", () => resolve(Number.parseFloat(out.trim()) || 0));
  });
}

const exists = (file) =>
  access(file)
    .then(() => true)
    .catch(() => false);

/* Common tail of every segment render: exact size, rate and a silent track. */
const NORMALISE = `scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:color=0x14191A,fps=${FPS},format=yuv420p`;

const SILENT = ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"];

const ENCODE = [
  "-c:v", "libx264", "-preset", "medium", "-crf", "18",
  "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
  "-video_track_timescale", "30000",
];

/* -------------------------------------------------------------- renders */

async function renderClip(segment, index, face) {
  const source = path.join(FOOTAGE, `${segment.clip}.mp4`);
  if (!(await exists(source))) throw new Error(`missing footage: ${segment.clip}.mp4 (run demo/capture/record.mjs)`);

  const available = (await probe(source)) - segment.from;
  const target = `seg-${String(index).padStart(2, "0")}.mp4`;
  if (available < segment.seconds - 0.05) {
    console.warn(`  ! ${segment.id}: clip has ${available.toFixed(1)}s from ${segment.from}s, needs ${segment.seconds}s. Holding the last frame.`);
  }

  // `crop` is [x, y, w, h] in source pixels. It enlarges, so prefer capturing
  // a tighter shot in record.mjs when you can.
  const punch = segment.crop ? `crop=${segment.crop[2]}:${segment.crop[3]}:${segment.crop[0]}:${segment.crop[1]},` : "";

  const fade = [
    segment.fade === "in" || segment.fade === "both" ? ",fade=in:st=0:d=0.45" : "",
    segment.fade === "out" || segment.fade === "both" ? `,fade=out:st=${(segment.seconds - 0.6).toFixed(2)}:d=0.6` : "",
  ].join("");

  const args = ["-y", "-loglevel", "error", "-ss", String(segment.from), "-i", source];
  let filter = `[0:v]${punch}${NORMALISE},tpad=stop_mode=clone:stop_duration=30${fade}[v]`;
  let map = ["-map", "[v]"];

  if (face && segment.face === "pip") {
    // Inset camera, bottom right, on a hairline so it separates from the page.
    args.push("-ss", String(offsetOf(segment)), "-i", face);
    filter =
      `[0:v]${punch}${NORMALISE},tpad=stop_mode=clone:stop_duration=30${fade}[bg];` +
      `[1:v]scale=440:-2,format=yuv420p[cam];` +
      `[bg][cam]overlay=W-w-56:H-h-56:shortest=0[v]`;
    map = ["-map", "[v]"];
  }

  args.push(...SILENT, "-filter_complex", filter, ...map, "-map", `${face && segment.face === "pip" ? 2 : 1}:a`, "-t", String(segment.seconds), ...ENCODE, "-shortest", target);
  await run(args, WORK);
  return target;
}

/* Where this segment starts in the finished film, which is also where it starts
   in a camera take recorded against that film. */
function offsetOf(segment) {
  let at = HEAD_SECONDS;
  for (const item of TIMELINE) {
    if (item.id === segment.id) return at;
    at += item.seconds;
  }
  return at;
}

async function renderCard(name, index) {
  const source = path.join(CARDS, `${name}.mp4`);
  if (!(await exists(source))) {
    console.warn(`  ! card ${name}.mp4 missing, skipping (run demo/capture/cards.mjs)`);
    return null;
  }
  const target = `card-${index}-${name}.mp4`;
  await run(["-y", "-loglevel", "error", "-i", source, ...SILENT, "-filter_complex", `[0:v]${NORMALISE}[v]`, "-map", "[v]", "-map", "1:a", ...ENCODE, "-shortest", target], WORK);
  return target;
}

/* ----------------------------------------------------------------- main */

const argv = process.argv.slice(2);
const flag = (name) => {
  const at = argv.indexOf(`--${name}`);
  return at === -1 ? null : argv[at + 1];
};

const voice = flag("voice") ? path.resolve(flag("voice")) : null;
const face = flag("face") ? path.resolve(flag("face")) : null;

for (const [label, file] of [["voice", voice], ["face", face]]) {
  if (file && !(await exists(file))) throw new Error(`--${label} not found: ${file}`);
}

await rm(WORK, { recursive: true, force: true });
await mkdir(WORK, { recursive: true });
await mkdir(OUT, { recursive: true });

const pieces = [];
const stamp = (t) => `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, "0")}`;
console.log(voice ? "Cutting the narrated film" : "Cutting the silent film");

for (const [i, name] of HEAD.entries()) {
  const rendered = await renderCard(name, `h${i}`);
  if (rendered) pieces.push(rendered);
}
if (HEAD.length) console.log(`  0:00  ${"title card".padEnd(16)} ${HEAD_SECONDS}s`);

let clock = HEAD_SECONDS;
for (const [index, segment] of TIMELINE.entries()) {
  pieces.push(await renderClip(segment, index, face));
  console.log(
    `  ${stamp(clock).padStart(4)}  ${segment.id.padEnd(16)} ${String(segment.seconds).padStart(2)}s  ${segment.clip.padEnd(18)} ${segment.beat}`,
  );
  clock += segment.seconds;
}
console.log(`  ${stamp(clock).padStart(4)}  ${"end card".padEnd(16)} ${TAIL_SECONDS}s`);

for (const [i, name] of TAIL.entries()) {
  const rendered = await renderCard(name, `t${i}`);
  if (rendered) pieces.push(rendered);
}

await writeFile(path.join(WORK, "list.txt"), pieces.map((file) => `file '${file}'`).join("\n"));

const silentCut = path.join(WORK, "cut.mp4");
await run(["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "-movflags", "+faststart", "cut.mp4"], WORK);

const target = path.join(OUT, voice ? "flowstate-pitch.mp4" : "flowstate-demo.mp4");
if (voice) {
  // apad plus shortest pins the result to the video length, so a voice track
  // that runs long does not leave a frozen tail, and one that runs short does
  // not truncate the end card.
  await run([
    "-y", "-loglevel", "error",
    "-i", silentCut, "-i", voice,
    "-map", "0:v", "-map", "1:a",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
    "-af", "apad", "-shortest",
    "-movflags", "+faststart", target,
  ]);
} else {
  await run(["-y", "-loglevel", "error", "-i", silentCut, "-c", "copy", "-movflags", "+faststart", target]);
}

await rm(WORK, { recursive: true, force: true });
const total = HEAD_SECONDS + TIMELINE.reduce((sum, item) => sum + item.seconds, 0) + TAIL_SECONDS;
console.log(`
${path.relative(process.cwd(), target)}  ${stamp(total)}  narration runs ${stamp(HEAD_SECONDS)} to ${stamp(total - TAIL_SECONDS)}`);
