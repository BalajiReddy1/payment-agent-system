import type { Metadata } from "next";

import "@/styles/onboarding.css";

import { SetupFlow } from "@/components/onboarding/setup-flow";

export const metadata: Metadata = {
  title: "Setup",
  description: "Pick a payment source, set the blast radius, name an approver, and size the holdout.",
};

export default function Onboarding() {
  return <SetupFlow />;
}
