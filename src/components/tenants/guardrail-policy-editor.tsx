"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { updateGuardrailPolicyAction } from "@/lib/actions";
import { LEVEL_META } from "@/lib/guardrail-level-meta";
import type { GuardrailDefinitionResponse } from "@/lib/rune-api-types";

/** ui-design.md §9.15/§9.16/§10.7. Owns one unified enabled-set for every
 * configurable (non-mandatory) check across all levels, saved with a
 * single button — a policy change affects every future publish for the
 * whole tenant, which is deliberately not a per-row autosave field. */
export function GuardrailPolicyEditor({
  tenantId,
  catalog,
  initialEnabledIds,
  isAdmin,
}: {
  tenantId: string;
  catalog: GuardrailDefinitionResponse[];
  initialEnabledIds: string[];
  isAdmin: boolean;
}) {
  const [enabled, setEnabled] = useState(new Set(initialEnabledIds));
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  function toggle(checkId: string, next: boolean) {
    setEnabled((prev) => {
      const copy = new Set(prev);
      if (next) copy.add(checkId);
      else copy.delete(checkId);
      return copy;
    });
    setDirty(true);
    setSaved(false);
  }

  function handleSave() {
    setError(null);
    startTransition(async () => {
      const result = await updateGuardrailPolicyAction(tenantId, Array.from(enabled));
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setDirty(false);
      setSaved(true);
      router.refresh();
    });
  }

  return (
    <div className="space-y-4">
      {([1, 2, 3, 4] as const).map((level) => {
        const meta = LEVEL_META[level];
        const checks = catalog.filter((c) => c.level === level);
        const mandatory = level === 1;
        const enabledCount = checks.filter((c) => mandatory || enabled.has(c.id)).length;

        return (
          <div key={level} className="overflow-hidden rounded-lg border border-border">
            <div className="flex items-center gap-3 border-b border-border bg-muted/40 px-4 py-3">
              <div
                className={
                  "flex size-7 shrink-0 items-center justify-center rounded-md font-mono text-xs font-bold " +
                  (mandatory ? "bg-danger/10 text-danger" : "bg-warning/10 text-warning")
                }
              >
                L{level}
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">{meta.name}</p>
                <p className="text-xs text-muted-foreground">{meta.posture}</p>
              </div>
              <div className="ml-auto flex items-center gap-3">
                <Badge
                  variant="outline"
                  className={
                    mandatory ? "border-danger/30 text-danger" : "border-warning/30 text-warning"
                  }
                >
                  {meta.badge}
                </Badge>
                <span className="font-mono text-xs text-muted-foreground">
                  {enabledCount} of {checks.length} enabled
                </span>
              </div>
            </div>

            {level === 4 && (
              <div className="border-b border-border bg-warning/5 px-4 py-2 text-xs text-muted-foreground">
                Lower-confidence heuristics intended for tenants under specific compliance
                requirements — expect more advisory noise than Standard-tier checks.
              </div>
            )}

            <div className="divide-y divide-border">
              {checks.map((check) => (
                <div key={check.id} className="flex items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">{check.name}</p>
                    <p className="text-xs text-muted-foreground">{check.description}</p>
                  </div>
                  {mandatory ? (
                    <span className="shrink-0 text-xs font-medium text-muted-foreground">
                      Always enforced
                    </span>
                  ) : isAdmin ? (
                    <Switch
                      checked={enabled.has(check.id)}
                      onCheckedChange={(next) => toggle(check.id, next)}
                    />
                  ) : (
                    <Badge variant={enabled.has(check.id) ? "default" : "outline"}>
                      {enabled.has(check.id) ? "On" : "Off"}
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}

      {isAdmin && (
        <div className="sticky bottom-4 flex items-center gap-3 rounded-lg border border-border bg-background p-3 shadow-md">
          <p className="text-xs text-muted-foreground">
            Changes apply to every publish on this tenant going forward.
          </p>
          {error && <p className="text-xs text-danger">{error}</p>}
          {saved && !dirty && <p className="text-xs text-success">Saved.</p>}
          <Button onClick={handleSave} disabled={!dirty || pending} className="ml-auto">
            {pending ? <Loader2 className="size-4 animate-spin" /> : null}
            Save Changes
          </Button>
        </div>
      )}
    </div>
  );
}
