import { AlertTriangle } from "lucide-react";

import type { ValidationResultResponse } from "@/lib/rune-api-types";

/** Sibling to ValidationResultsPanel, not an edit of it — warnings are
 * non-blocking (design.md §4.5) so they get their own, lower-urgency
 * visual treatment instead of a severity axis bolted onto the error panel. */
export function GuardrailWarningsPanel({ result }: { result: ValidationResultResponse }) {
  if (result.warnings.length === 0) return null;

  return (
    <div className="max-h-40 overflow-y-auto border-t border-warning/20 bg-warning/5">
      {result.warnings.map((warning, i) => (
        <div
          key={i}
          className="flex items-start gap-2 border-b border-warning/10 px-4 py-2 text-sm last:border-0"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          <div>
            <p className="font-medium text-warning">
              {warning.code}
              {warning.file ? ` — ${warning.file}` : ""}
            </p>
            <p className="text-muted-foreground">{warning.message}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
