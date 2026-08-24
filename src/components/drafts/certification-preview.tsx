import { ShieldCheck } from "lucide-react";

import { LEVEL_META } from "@/lib/guardrail-level-meta";
import type { ValidationResultResponse } from "@/lib/rune-api-types";

/** Sibling to ValidationResultsPanel/GuardrailWarningsPanel — shown after a
 * successful Validate call to preview the certification a publish would
 * record right now. Always labeled "projected": nothing is persisted until
 * the draft is actually published (see CertificationCard for the real,
 * permanent record on a published version). */
export function CertificationPreview({ result }: { result: ValidationResultResponse }) {
  if (!result.valid || !result.certification) return null;
  const { highestCertifiedLevel } = result.certification;

  return (
    <div className="flex items-center gap-2 border-t border-border bg-muted/40 px-4 py-2 text-sm text-muted-foreground">
      <ShieldCheck className="size-4 shrink-0" />
      {highestCertifiedLevel ? (
        <span>
          Projected certification:{" "}
          <span className="font-medium text-foreground">
            Level {highestCertifiedLevel} — {LEVEL_META[highestCertifiedLevel as 1 | 2 | 3 | 4].name}
          </span>
        </span>
      ) : (
        <span>Projected certification: none of the baseline levels are fully clean yet.</span>
      )}
    </div>
  );
}
