import { CheckCircle2, XCircle } from "lucide-react";

import type { ValidationResultResponse } from "@/lib/rune-api-types";

/** ui-design.md §9 item 9. Maps a validation error to the file most likely
 * to fix it — a small static lookup, not a general error->location engine. */
const ERROR_CODE_FILE: Record<string, string> = {
  SCHEMA_VALIDATION_FAILED: "manifest.yaml",
  INVALID_ID_FORMAT: "manifest.yaml",
  INVALID_VERSION_FORMAT: "manifest.yaml",
  INVALID_RUNTIME_FORMAT: "manifest.yaml",
  INVALID_DEPENDENCY_CONSTRAINT: "dependencies.yaml",
  CIRCULAR_DEPENDENCY: "dependencies.yaml",
  MISSING_DEPENDENCY: "dependencies.yaml",
  MISSING_REQUIRED_FILE: "manifest.yaml",
};

export function ValidationResultsPanel({
  result,
  onJumpToFile,
}: {
  result: ValidationResultResponse;
  onJumpToFile?: (path: string) => void;
}) {
  if (result.valid) {
    return (
      <div className="flex items-center gap-2 border-t border-success/20 bg-success/10 px-4 py-2 text-sm text-success">
        <CheckCircle2 className="size-4" />
        Valid — ready to publish.
      </div>
    );
  }

  return (
    <div className="max-h-40 overflow-y-auto border-t border-danger/20 bg-danger/5">
      {result.errors.map((error, i) => {
        const file = error.file ?? ERROR_CODE_FILE[error.code];
        return (
          <div
            key={i}
            className="flex items-start justify-between gap-3 border-b border-danger/10 px-4 py-2 text-sm last:border-0"
          >
            <div className="flex items-start gap-2">
              <XCircle className="mt-0.5 size-4 shrink-0 text-danger" />
              <div>
                <p className="font-medium text-danger">{error.code}</p>
                <p className="text-muted-foreground">{error.message}</p>
              </div>
            </div>
            {file && onJumpToFile && (
              <button
                type="button"
                onClick={() => onJumpToFile(file)}
                className="shrink-0 text-xs font-medium text-brand hover:underline"
              >
                Jump to file
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
