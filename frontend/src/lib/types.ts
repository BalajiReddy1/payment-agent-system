export type Experiment = {
  experiment_id: string;
  action_id: string;
  action_type: string;
  target: string;
  holdout_fraction: number;
  treatment: { successes: number; total: number };
  control: { successes: number; total: number };
  lift: number | null;
  lift_ci?: [number, number] | null;
  p_value?: number | null;
  significant?: boolean;
  verdict: string;
  recovery?: {
    currency: string;
    treatment: { successful: number; total: number };
    control: { successful: number; total: number };
    at_risk: number;
    recovered: number;
    claimable: boolean;
  };
};

export type AgentSnapshot = {
  agent: { active: boolean; cycle: number; phase: string; window_minutes: number };
  metrics: {
    success_rate: number;
    latency: { p50: number; p95: number; p99: number; mean: number; max: number };
    transactions: number;
    retry_efficiency: number;
  };
  counters: { patterns_detected: number; actions_executed: number; alerts_raised: number };
  issuers: Array<{ issuer: string; success_rate: number; volume: number; p95: number; broken: boolean }>;
  incidents: Array<{
    incident_id: string;
    pattern_type: string;
    target: string;
    active: boolean;
    peak_severity: number;
    latest_confidence: number;
    actions_taken: string[];
    advice?: string | null;
  }>;
  approvals: Array<{
    request_id: string;
    action_type: string;
    target: string;
    risk_level: string;
    authorization: string;
    seconds_remaining: number | null;
    expected_lift: number;
  }>;
  experiments: Experiment[];
  control_plane: {
    revision: number;
    history: Array<{ revision: number; author: string; reason: string; changes: string[] }>;
  };
  decisions: Array<{
    action_id: string;
    type: string;
    target: string;
    at: string;
    success: boolean;
    message: string;
    parameters: Record<string, unknown>;
    reasoning: string;
  }>;
  events: Array<{ seq: number; kind: string; at: string; payload: Record<string, unknown> }>;
  demo: { active: boolean; seed: number | null; stage: string; scenario?: string; message?: string };
  history: Array<{ cycle: number; success_rate: number; latency_p95: number; transactions: number }>;
  scenarios: Array<{ type: string; expires_at: string }>;
  traffic: { rerouted: number; held_out: number; method_switched: number };
};
