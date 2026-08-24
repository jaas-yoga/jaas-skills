"use client";

import { Building2, Check, ChevronsUpDown, Loader2, Plus, Users } from "lucide-react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { CreateTenantDialog } from "@/components/tenants/create-tenant-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export type Tenant = { id: string; name: string; role: "admin" | "member" };

/**
 * ui-design.md §9 item 2, §6 (Phase 6). Switching calls
 * `useSession().update({ tenantId })`, which Auth.js routes into the `jwt`
 * callback with `trigger: "update"` (src/auth.ts) — that's what actually
 * re-mints the access token against the new tenant; `router.refresh()`
 * then re-renders the current Server Component tree against the updated
 * session.
 */
export function TenantSwitcher({
  tenants = [{ id: "personal", name: "Personal", role: "admin" }],
  activeTenantId = "personal",
}: {
  tenants?: Tenant[];
  activeTenantId?: string;
}) {
  const { update } = useSession();
  const router = useRouter();
  const [switching, startSwitching] = useTransition();
  const [createOpen, setCreateOpen] = useState(false);

  const activeTenant = tenants.find((t) => t.id === activeTenantId) ?? tenants[0];

  function handleSwitch(tenantId: string) {
    if (tenantId === activeTenantId) return;
    startSwitching(async () => {
      await update({ tenantId });
      router.refresh();
    });
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            disabled={switching}
            className="flex w-full items-center gap-2 rounded-md border border-sidebar-border bg-sidebar px-2.5 py-2 text-left text-sm hover:bg-sidebar-accent disabled:opacity-60"
          >
            <span className="flex size-6 shrink-0 items-center justify-center rounded bg-brand text-brand-foreground">
              <Building2 className="size-3.5" />
            </span>
            <span className="flex-1 truncate font-medium">{activeTenant.name}</span>
            {switching ? (
              <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" />
            ) : (
              <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
            )}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">
          <DropdownMenuLabel>Tenants</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {tenants.map((tenant) => (
            <DropdownMenuItem key={tenant.id} onSelect={() => handleSwitch(tenant.id)}>
              <span className={cn("flex-1", tenant.id === activeTenantId && "font-medium")}>
                {tenant.name}
              </span>
              {tenant.id === activeTenantId && <Check className="size-4" />}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem asChild>
            <Link href={`/tenants/${activeTenantId}/members`}>
              <Users className="size-4" /> Tenant Settings
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setCreateOpen(true)}>
            <Plus className="size-4" /> Create Tenant
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <CreateTenantDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}
