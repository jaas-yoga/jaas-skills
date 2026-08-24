import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { CustomGuardrailRulesEditor } from "@/components/tenants/custom-guardrail-rules-editor";
import { GuardrailPolicyEditor } from "@/components/tenants/guardrail-policy-editor";
import { Separator } from "@/components/ui/separator";
import {
  listCustomGuardrailRules,
  listGuardrailCatalog,
  getTenantGuardrailPolicy,
} from "@/lib/guardrails-api";
import { RuneApiRequestError } from "@/lib/rune-api";
import { listMembers } from "@/lib/tenants-api";

/** ui-design.md §10.7 — grouped-toggle pattern (GitHub Code security &
 * analysis / AWS Security Hub / Snyk project rules), not a bespoke layout.
 * GitHub connection + repo links live on the separate Repositories tab
 * (tenants/[id]/repositories/page.tsx) — connecting a repo isn't itself a
 * guardrail setting. */
export default async function TenantGuardrailsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let catalog, policy, members, customRules;
  try {
    [catalog, policy, members, customRules] = await Promise.all([
      listGuardrailCatalog(),
      getTenantGuardrailPolicy(id),
      listMembers(id),
      listCustomGuardrailRules(id),
    ]);
  } catch (err) {
    if (err instanceof RuneApiRequestError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  const session = await auth();
  const me = members.find((m) => m.userId === session?.runeUser?.id);
  const isAdmin = me?.role === "admin";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Publish Guardrails
        </h1>
        <p className="text-sm text-muted-foreground">
          Automated checks that run every time someone on this tenant publishes a skill — from
          the web UI, `runectl publish`, or a git-native CI release.
        </p>
      </div>

      <GuardrailPolicyEditor
        tenantId={id}
        catalog={catalog}
        initialEnabledIds={policy.enabledCheckIds}
        isAdmin={isAdmin}
      />

      <Separator />

      <CustomGuardrailRulesEditor tenantId={id} rules={customRules} isAdmin={isAdmin} />
    </div>
  );
}
