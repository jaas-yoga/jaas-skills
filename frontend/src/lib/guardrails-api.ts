import "server-only";

import { runeFetch } from "./rune-api";
import type {
  CustomGuardrailRuleResponse,
  GuardrailDefinitionResponse,
  TenantGuardrailPolicyResponse,
} from "./rune-api-types";

export async function listGuardrailCatalog(): Promise<GuardrailDefinitionResponse[]> {
  return runeFetch<GuardrailDefinitionResponse[]>("/api/v1/guardrails");
}

export async function getTenantGuardrailPolicy(
  tenantId: string,
): Promise<TenantGuardrailPolicyResponse> {
  return runeFetch<TenantGuardrailPolicyResponse>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/guardrail-policy`,
  );
}

export async function listCustomGuardrailRules(
  tenantId: string,
): Promise<CustomGuardrailRuleResponse[]> {
  return runeFetch<CustomGuardrailRuleResponse[]>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/custom-guardrails`,
  );
}
