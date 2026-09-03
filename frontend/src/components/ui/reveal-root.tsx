"use client";

import { useEffect } from "react";

import { onEnterView, schedule } from "@/lib/in-view";

/*
  Mounted once per page.

  Above-the-fold entrances are pure CSS (`data-enter`), so they play from the
  first paint and can never leave content stuck hidden. This handles the rest:
  it only hides an element that is currently *below* the fold, and reveals it
  from a scroll pass. Reduced motion, no JavaScript, and a headless render all
  ship the full page.
*/
export function RevealRoot() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const releases = new Map<HTMLElement, () => void>();

    /*
      Re-entrant on purpose: StrictMode runs this effect twice, and the second
      pass must re-arm anything the first pass already marked, or those elements
      stay hidden forever.
    */
    const consider = (node: HTMLElement) => {
      if (releases.has(node)) return;
      if (node.getBoundingClientRect().top < window.innerHeight) {
        delete node.dataset.pending;
        return;
      }
      node.dataset.pending = "";
      releases.set(
        node,
        onEnterView(
          node,
          () => {
            delete node.dataset.pending;
            releases.delete(node);
          },
          60,
        ),
      );
    };

    const scan = (scope: ParentNode) => {
      scope.querySelectorAll<HTMLElement>("[data-reveal]").forEach(consider);
    };

    scan(document);

    // The desk swaps panels in after each snapshot, so watch for new ones.
    const mutations = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (!(node instanceof HTMLElement)) continue;
          if (node.matches("[data-reveal]")) consider(node);
          scan(node);
        }
      }
      schedule();
    });
    mutations.observe(document.body, { childList: true, subtree: true });

    return () => {
      mutations.disconnect();
      releases.forEach((release) => release());
      releases.clear();
    };
  }, []);

  return null;
}
