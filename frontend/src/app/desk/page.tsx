import type { Metadata } from "next";

import "@/styles/desk.css";

import { OperationsConsole } from "@/components/operations-console";
import { RevealRoot } from "@/components/ui/reveal-root";

export const metadata: Metadata = {
  title: "Recovery desk",
  description: "Live payment routes, the response under consideration, and the measured outcome against a holdout.",
};

export default function RecoveryDesk() {
  return (
    <>
      <OperationsConsole />
      <RevealRoot />
    </>
  );
}
