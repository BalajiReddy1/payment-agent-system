/*
  One shared, time-throttled scroll/resize pass that reports when an element
  first enters the viewport.

  Two deliberate choices here:

  - Not IntersectionObserver. Reveals gate whether content is painted, and IO
    callbacks are silently never delivered in some embedded and headless
    contexts, which would ship a blank page.
  - Not requestAnimationFrame for throttling. rAF is suspended entirely while a
    page is not being composited, which would leave a pending element hidden
    even after the reader scrolls back to it. A timestamp throttle degrades to
    slower, never to never.

  The watcher set empties itself, so the listeners detach once everything has
  been seen.
*/

const FRAME = 16;

type Watcher = {
  node: HTMLElement;
  enter: () => void;
  margin: number;
};

const watchers = new Set<Watcher>();
let last = 0;
let timer = 0;
let bound = false;

function pass() {
  timer = 0;
  last = performance.now();
  const viewport = window.innerHeight || document.documentElement.clientHeight;
  for (const watcher of [...watchers]) {
    if (!watcher.node.isConnected) {
      watchers.delete(watcher);
      continue;
    }
    const rect = watcher.node.getBoundingClientRect();
    if (rect.top < viewport - watcher.margin && rect.bottom > 0) {
      watchers.delete(watcher);
      watcher.enter();
    }
  }
  if (!watchers.size) unbind();
}

export function schedule() {
  const now = performance.now();
  if (now - last >= FRAME) {
    pass();
    return;
  }
  if (!timer) timer = window.setTimeout(pass, FRAME - (now - last));
}

function bind() {
  if (bound) return;
  bound = true;
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule, { passive: true });
}

function unbind() {
  if (!bound) return;
  bound = false;
  window.clearTimeout(timer);
  timer = 0;
  window.removeEventListener("scroll", schedule);
  window.removeEventListener("resize", schedule);
}

/** Calls `enter` once, as soon as `node` is inside the viewport. */
export function onEnterView(node: HTMLElement, enter: () => void, margin = 0) {
  const watcher: Watcher = { node, enter, margin };
  watchers.add(watcher);
  bind();
  schedule();
  return () => {
    watchers.delete(watcher);
    if (!watchers.size) unbind();
  };
}

/** Time-throttled scroll/resize subscription for continuous tracking. */
export function onScrollFrame(handler: () => void) {
  let own = 0;
  let ran = 0;
  const run = () => {
    own = 0;
    ran = performance.now();
    handler();
  };
  const tick = () => {
    const now = performance.now();
    if (now - ran >= FRAME) {
      run();
      return;
    }
    if (!own) own = window.setTimeout(run, FRAME - (now - ran));
  };
  window.addEventListener("scroll", tick, { passive: true });
  window.addEventListener("resize", tick, { passive: true });
  handler();
  return () => {
    window.clearTimeout(own);
    window.removeEventListener("scroll", tick);
    window.removeEventListener("resize", tick);
  };
}
