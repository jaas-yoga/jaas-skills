/** Shared copy for the guardrail catalog's 4 levels (guardrails/models.py's
 * GuardrailLevel) — the single source of truth for both the tenant policy
 * editor and anything certification-related, so the name/posture strings
 * never drift between the two. */
export const LEVEL_META = {
  1: { name: "Baseline", posture: "Every publish, no opt-out", badge: "Blocks publish" },
  2: {
    name: "Standard",
    posture: "On by default — disable individually if needed",
    badge: "Warns",
  },
  3: { name: "Advanced", posture: "Opt-in — defense in depth", badge: "Warns" },
  4: {
    name: "Regulatory",
    posture: "Opt-in — heavier, lower-confidence heuristics",
    badge: "Warns",
  },
} as const;

export const CERTIFICATION_STATUS_META = {
  certified: { label: "Certified", className: "text-success" },
  attempted_with_findings: { label: "Findings", className: "text-warning" },
  not_attempted: { label: "Not attempted", className: "text-muted-foreground" },
} as const;
