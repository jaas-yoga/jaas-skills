"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const TABS = [
  { label: "Members", suffix: "members" },
  { label: "Guardrails", suffix: "guardrails" },
  { label: "Repositories", suffix: "repositories" },
];

/** ui-design.md §9.14 — Members | Guardrails | Repositories tab row under
 * a tenant's header. Real routes, not a client-side panel switch (Sharing
 * will slot in here the same way once §10.6 is built), so plain Links +
 * usePathname rather than the Tabs primitive. */
export function TenantNavTabs({ tenantId }: { tenantId: string }) {
  const pathname = usePathname();

  return (
    <div className="flex gap-1 border-b border-border">
      {TABS.map((tab) => {
        const href = `/tenants/${tenantId}/${tab.suffix}`;
        const active = pathname === href;
        return (
          <Link
            key={tab.suffix}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "border-brand text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
