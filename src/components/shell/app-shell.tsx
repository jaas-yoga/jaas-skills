import type { ReactNode } from "react";

import type { AccountUser } from "@/components/shell/account-menu";
import { Sidebar } from "@/components/shell/sidebar";
import { TopBar } from "@/components/shell/top-bar";
import type { Tenant } from "@/components/shell/tenant-switcher";

/** ui-design.md §10.1 — global chrome for every authenticated route. */
export function AppShell({
  children,
  user,
  tenants,
  activeTenantId,
}: {
  children: ReactNode;
  user?: AccountUser;
  tenants?: Tenant[];
  activeTenantId?: string;
}) {
  return (
    <div className="flex h-dvh w-full">
      <Sidebar tenants={tenants} activeTenantId={activeTenantId} />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <TopBar user={user} />
        <main className="min-h-0 flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
