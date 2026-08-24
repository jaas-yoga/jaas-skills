"use client";

import { Loader2, Pencil, Plus, ShieldPlus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  deleteCustomGuardrailRuleAction,
  putCustomGuardrailRuleAction,
  validateCustomGuardrailRuleAction,
  type CustomGuardrailRuleInput,
} from "@/lib/actions";
import type { CustomGuardrailRuleResponse } from "@/lib/rune-api-types";

const CATEGORIES = [
  "SECRET",
  "SIZE",
  "CODE_SAFETY",
  "PROMPT_SAFETY",
  "PERMISSIONS",
  "LICENSING",
  "SUPPLY_CHAIN",
  "PRIVACY",
  "COMPLIANCE",
  "CONTENT_SAFETY",
] as const;

// Matches rune_guardrails/executors.py::EXECUTORS_BY_KIND exactly — a
// custom rule can only ever use one of these, never a new kind (see that
// service's README "Custom rules" section for why: no code-execution path).
const KINDS = [
  "regex_file_scan",
  "filename_pattern_scan",
  "package_size",
  "permission_pair_risk",
  "permission_count_threshold",
  "dependency_constraint",
  "dependency_count",
  "dependency_typosquat",
  "file_extension_scan",
  "wordlist_scan",
  "file_text_presence",
] as const;

const EMPTY_FORM: CustomGuardrailRuleInput = {
  slug: "",
  name: "",
  description: "",
  category: "CODE_SAFETY",
  severity: "WARN",
  standardRef: "",
  kind: "regex_file_scan",
  config: {},
};

function ruleToForm(rule: CustomGuardrailRuleResponse): CustomGuardrailRuleInput {
  return {
    slug: rule.slug,
    name: rule.name,
    description: rule.description,
    category: rule.category,
    severity: rule.severity,
    standardRef: rule.standardRef,
    kind: rule.kind,
    config: rule.config,
  };
}

function RuleFormDialog({
  tenantId,
  initial,
  open,
  onOpenChange,
}: {
  tenantId: string;
  initial: CustomGuardrailRuleInput | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const isEdit = initial !== null;
  const [form, setForm] = useState<CustomGuardrailRuleInput>(initial ?? EMPTY_FORM);
  const [configText, setConfigText] = useState(JSON.stringify(form.config, null, 2));
  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  function reset() {
    const next = initial ?? EMPTY_FORM;
    setForm(next);
    setConfigText(JSON.stringify(next.config, null, 2));
    setError(null);
    setValidation(null);
  }

  function parsedConfig(): { ok: true; config: Record<string, unknown> } | { ok: false } {
    try {
      return { ok: true, config: JSON.parse(configText || "{}") };
    } catch {
      setError("Config must be valid JSON.");
      return { ok: false };
    }
  }

  function handleValidate() {
    const parsed = parsedConfig();
    if (!parsed.ok) return;
    setError(null);
    startTransition(async () => {
      const result = await validateCustomGuardrailRuleAction(tenantId, {
        ...form,
        config: parsed.config,
      });
      setValidation(result.valid ? "Looks good." : (result.error ?? "Invalid rule."));
    });
  }

  function handleSave() {
    const parsed = parsedConfig();
    if (!parsed.ok) return;
    if (!form.slug.trim() || !form.name.trim()) {
      setError("Slug and name are required.");
      return;
    }
    setError(null);
    startTransition(async () => {
      const result = await putCustomGuardrailRuleAction(tenantId, {
        ...form,
        config: parsed.config,
      });
      if (!result.ok) {
        setError(result.error);
        return;
      }
      onOpenChange(false);
      router.refresh();
    });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) reset();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${initial.slug}` : "New custom rule"}</DialogTitle>
          <DialogDescription>
            Restricted to the platform&apos;s executor kinds — a custom rule can never run
            arbitrary code, only a declarative check like the built-in catalog uses.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Slug</label>
            <Input
              value={form.slug}
              disabled={isEdit}
              onChange={(e) => setForm({ ...form, slug: e.target.value })}
              placeholder="no-internal-hostnames"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Name</label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="No internal hostnames"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Description</label>
          <Input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="What this rule flags and why"
          />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Category</label>
            <Select
              value={form.category}
              onValueChange={(v) => setForm({ ...form, category: v })}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CATEGORIES.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Severity</label>
            <Select
              value={form.severity}
              onValueChange={(v) => setForm({ ...form, severity: v as "BLOCK" | "WARN" })}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="WARN">WARN</SelectItem>
                <SelectItem value="BLOCK">BLOCK</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Kind</label>
            <Select value={form.kind} onValueChange={(v) => setForm({ ...form, kind: v })}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {KINDS.map((k) => (
                  <SelectItem key={k} value={k}>
                    {k}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            Config (JSON — shape depends on kind, see the guardrails service README)
          </label>
          <Textarea
            value={configText}
            onChange={(e) => setConfigText(e.target.value)}
            rows={6}
          />
        </div>

        {validation && (
          <p className={validation === "Looks good." ? "text-sm text-success" : "text-sm text-danger"}>
            {validation}
          </p>
        )}
        {error && <p className="text-sm text-danger">{error}</p>}

        <DialogFooter className="justify-between sm:justify-between">
          <Button variant="outline" onClick={handleValidate} disabled={pending}>
            {pending ? <Loader2 className="size-4 animate-spin" /> : null}
            Validate
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={pending}>
              {pending ? <Loader2 className="size-4 animate-spin" /> : null}
              Save
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** design.md §4.5's "user can define guardrails" — a tenant-owned library
 * of reusable custom rules, applied tenant-wide or per-skill via a
 * .rune/guardrails.yaml `apply:` list (guardrails/skill_config.py in the
 * backend). This library never runs anything itself; the standalone
 * guardrails service validates+executes whatever gets sent to it. */
export function CustomGuardrailRulesEditor({
  tenantId,
  rules,
  isAdmin,
}: {
  tenantId: string;
  rules: CustomGuardrailRuleResponse[];
  isAdmin: boolean;
}) {
  const [editing, setEditing] = useState<CustomGuardrailRuleResponse | "new" | null>(null);
  const [deletingSlug, setDeletingSlug] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  function handleDelete(slug: string) {
    setDeletingSlug(slug);
    startTransition(async () => {
      await deleteCustomGuardrailRuleAction(tenantId, slug);
      setDeletingSlug(null);
      router.refresh();
    });
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Custom Rules</h2>
          <p className="text-xs text-muted-foreground">
            Rules this tenant defines itself, on top of the platform catalog above. Apply them
            tenant-wide here, or per-skill via that skill&apos;s own{" "}
            <code className="rounded bg-muted px-1 py-0.5">.rune/guardrails.yaml</code>.
          </p>
        </div>
        {isAdmin && (
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus className="size-4" />
            New rule
          </Button>
        )}
      </div>

      {rules.length === 0 ? (
        <EmptyState
          icon={ShieldPlus}
          title="No custom rules yet"
          description={
            isAdmin
              ? "Define a rule here, or push one from git with `runectl guardrails push`."
              : "This tenant hasn't defined any custom guardrail rules."
          }
        />
      ) : (
        <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
          {rules.map((rule) => (
            <div key={rule.id} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-foreground">{rule.name}</p>
                  <Badge
                    variant="outline"
                    className={
                      rule.severity === "BLOCK"
                        ? "border-danger/30 text-danger"
                        : "border-warning/30 text-warning"
                    }
                  >
                    {rule.severity}
                  </Badge>
                </div>
                <p className="truncate text-xs text-muted-foreground">
                  <code>{rule.id}</code> · {rule.category} · {rule.kind}
                </p>
              </div>
              {isAdmin && (
                <div className="flex shrink-0 items-center gap-1">
                  <Button variant="ghost" size="icon" onClick={() => setEditing(rule)}>
                    <Pencil className="size-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleDelete(rule.slug)}
                    disabled={pending && deletingSlug === rule.slug}
                  >
                    {pending && deletingSlug === rule.slug ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Trash2 className="size-4" />
                    )}
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <RuleFormDialog
        tenantId={tenantId}
        initial={editing === "new" || editing === null ? null : ruleToForm(editing)}
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
      />
    </div>
  );
}
