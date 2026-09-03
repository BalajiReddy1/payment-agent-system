/*
  First-run configuration. It lives in the browser only: nothing here is a
  credential, and the runtime keeps its own authoritative policy. The desk
  reads it to know whether to show the setup prompt.
*/

export const SETUP_KEY = "flowstate.setup.v1";

export type SourceId = "simulator" | "razorpay_test" | "replay";

export type Setup = {
  source: SourceId;
  blastRadius: number;
  autoTier: "automatic" | "none";
  expiryMinutes: number;
  approver: string;
  holdout: number;
  completedAt: string;
};

export const DEFAULT_SETUP: Setup = {
  source: "simulator",
  blastRadius: 0.18,
  autoTier: "automatic",
  expiryMinutes: 15,
  approver: "ops@flowstate.local",
  holdout: 0.15,
  completedAt: "",
};

export function readSetup(): Setup | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SETUP_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Setup>;
    if (!parsed.completedAt) return null;
    return { ...DEFAULT_SETUP, ...parsed } as Setup;
  } catch {
    return null;
  }
}

export function writeSetup(setup: Setup) {
  try {
    window.localStorage.setItem(SETUP_KEY, JSON.stringify(setup));
  } catch {
    // A blocked storage API must not break the flow; the runtime holds the
    // real configuration either way.
  }
}

export const SOURCES: Array<{ id: SourceId; title: string; body: string; note: string }> = [
  {
    id: "simulator",
    title: "Deterministic simulator",
    body: "Synthetic payment traffic that reproduces the same incident every run. The whole decision and measurement path is repeatable.",
    note: "recommended for a first pass",
  },
  {
    id: "razorpay_test",
    title: "Razorpay test mode",
    body: "Read only intake of test mode payment records. Status, issuer and decline codes are ingested. No payment action is ever sent back.",
    note: "keys stay on the API service",
  },
  {
    id: "replay",
    title: "Journal replay",
    body: "Replay a recorded incident against a changed agent version, to see whether a detector or policy change would have behaved differently.",
    note: "needs a recorded journal",
  },
];
