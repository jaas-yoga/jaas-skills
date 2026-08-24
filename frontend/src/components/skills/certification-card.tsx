import { ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CERTIFICATION_STATUS_META, LEVEL_META } from "@/lib/guardrail-level-meta";
import type { SkillMetadataResponse } from "@/lib/rune-api-types";

/** Sibling to the version detail page's Provenance card, same visual
 * pattern — a point-in-time guardrail attestation computed once at publish
 * (guardrails/certification.py), never recomputed. Renders nothing for a
 * version published before certification existed. */
export function CertificationCard({ entry }: { entry: SkillMetadataResponse }) {
  if (entry.guardrailCertifiedLevel === null) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="size-4 text-muted-foreground" />
          Guardrail Certification
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm text-muted-foreground">
        <div className="flex items-center justify-between">
          <span>Certified through</span>
          <Badge variant="outline" className="border-success/30 text-success">
            {entry.guardrailCertifiedLevel === 0
              ? "No level"
              : `Level ${entry.guardrailCertifiedLevel} — ${LEVEL_META[entry.guardrailCertifiedLevel as 1 | 2 | 3 | 4].name}`}
          </Badge>
        </div>

        <div className="divide-y divide-border rounded-md border border-border">
          {entry.guardrailLevelStatuses.map(([level, status]) => {
            const meta = LEVEL_META[level as 1 | 2 | 3 | 4];
            const statusMeta = CERTIFICATION_STATUS_META[status];
            return (
              <div key={level} className="flex items-center justify-between px-3 py-2">
                <span className="text-foreground">
                  L{level} {meta.name}
                </span>
                <span className={statusMeta.className}>{statusMeta.label}</span>
              </div>
            );
          })}
        </div>

        {entry.guardrailWarningCheckIds.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-foreground">Checks with findings</p>
            <div className="flex flex-wrap gap-1">
              {entry.guardrailWarningCheckIds.map((id) => (
                <Badge key={id} variant="outline" className="font-mono text-[10px]">
                  {id}
                </Badge>
              ))}
            </div>
          </div>
        )}

        <p className="text-xs">
          Reflects the tenant&apos;s guardrail policy at the time this version was published —
          not a live status.
        </p>
      </CardContent>
    </Card>
  );
}
